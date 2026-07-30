"""LLM Usage backend for the Hermes Desktop plugin.

Providers (account plan windows only — never API-key caps):
  - Claude Code: session / all-models / Fable via CLI `/usage` (tmux capture)
  - Grok / xAI: weekly limit via Grok CLI `/usage` (tmux capture)

Results cached 5 minutes in-memory + disk (~/.hermes/cache/llm-usage.json).
Mounted at /api/plugins/llm-usage/ when this plugin is in plugins.enabled.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_CACHE_TTL_SEC = 300
_cache_lock = threading.Lock()
_cache: dict | None = None
_cache_at: float = 0.0


def _disk_cache_path() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    return home / "cache" / "llm-usage.json"


def _read_disk_cache() -> dict | None:
    path = _disk_cache_path()
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        # Accept multi-provider or legacy single-window payloads.
        if data.get("providers") or data.get("windows"):
            return data
        return None
    except Exception:
        return None


def _write_disk_cache(payload: dict) -> None:
    path = _disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def _which(name: str) -> bool:
    return _resolve_bin(name) is not None


def _resolve_bin(name: str) -> str | None:
    """Resolve a CLI binary even when dashboard PATH is minimal."""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    candidates = [
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
        home / ".local" / "bin" / name,
        home / ".cargo" / "bin" / name,
        Path("/usr/bin") / name,
    ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _workdir() -> Path:
    candidates = [
        Path.home() / "Projects" / "llm-usage-bar",
        Path.home() / "Projects",
        Path.home(),
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return Path.home()


# ── Claude Code ──────────────────────────────────────────────────────────────


def parse_claude_usage(text: str) -> list[dict]:
    """Parse Claude Code `/usage` pane text into quota windows."""
    windows: list[dict] = []
    label: str | None = None
    used_pct: float | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "Current session" or line.startswith("Current week ("):
            label = line
            used_pct = None
            continue
        if "%" in line and "used" in line:
            before = line.split("%", 1)[0]
            token = before.split()[-1] if before.split() else ""
            try:
                used_pct = float(token)
            except ValueError:
                pass
            continue
        if label is not None and used_pct is not None and line.startswith("Resets "):
            windows.append(
                {
                    "label": label,
                    "used_pct": max(0.0, min(100.0, used_pct)),
                    "reset_label": line[len("Resets ") :].strip(),
                    "id": _claude_window_id(label),
                }
            )
            label = None
            used_pct = None
    return windows


def _claude_window_id(label: str) -> str:
    lower = label.lower()
    if "session" in lower:
        return "session"
    if "fable" in lower:
        return "fable"
    if "all models" in lower:
        return "all_models"
    return "other"


def fetch_claude_cli_quota_windows() -> tuple[list[dict], str | None]:
    claude_bin = _resolve_bin("claude")
    tmux_bin = _resolve_bin("tmux")
    if not claude_bin:
        return [], "claude CLI not found on PATH"
    if not tmux_bin:
        return [], "tmux not found on PATH (required to capture /usage)"

    session = f"hermes_llm_claude_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    workdir = str(_workdir())

    def cleanup() -> None:
        subprocess.run(
            [tmux_bin, "kill-session", "-t", session],
            check=False,
            capture_output=True,
        )

    try:
        started = subprocess.run(
            [
                tmux_bin,
                "new-session",
                "-d",
                "-x",
                "150",
                "-y",
                "48",
                "-s",
                session,
                "-c",
                workdir,
                claude_bin,
                "--model",
                "opus",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            return [], f"could not start Claude usage session: {started.stderr or started.stdout}"

        time.sleep(5)
        sent = subprocess.run(
            [tmux_bin, "send-keys", "-t", session, "/usage", "Enter"],
            check=False,
            capture_output=True,
            text=True,
        )
        if sent.returncode != 0:
            return [], "could not request Claude /usage"

        time.sleep(4)
        captured = subprocess.run(
            [tmux_bin, "capture-pane", "-t", session, "-p", "-S", "-120"],
            check=False,
            capture_output=True,
            text=True,
        )
        if captured.returncode != 0:
            return [], "could not read Claude /usage pane"

        windows = parse_claude_usage(captured.stdout or "")
        if not windows:
            return [], "parsed zero windows from Claude /usage (CLI UI may have changed)"
        return windows, None
    finally:
        cleanup()


# ── Grok / xAI ───────────────────────────────────────────────────────────────


def parse_grok_usage(text: str) -> list[dict]:
    """Parse Grok CLI `/usage`.

    Formats observed:
      - Older: ``Weekly limit left: 42%`` + ``Next reset: ...``  (left → used=100-left)
      - Current (0.2.x): ``Weekly limit: 12%`` + ``Next reset: August 3, 07:22``
        (value is already percent of the weekly allowance used)
    """
    used_pct: float | None = None
    reset_label: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        # Prefer the explicit "left" phrasing when present.
        if "Weekly limit left:" in line:
            try:
                value = line.split("Weekly limit left:", 1)[1]
                number = value.split("%", 1)[0].strip()
                left = float(number)
                used_pct = max(0.0, min(100.0, 100.0 - left))
            except (IndexError, ValueError):
                pass
            continue
        if line.startswith("Weekly limit:") and "left" not in line.lower():
            try:
                value = line.split("Weekly limit:", 1)[1]
                number = value.split("%", 1)[0].strip()
                used_pct = max(0.0, min(100.0, float(number)))
            except (IndexError, ValueError):
                pass
            continue
        if line.startswith("Next reset:"):
            reset_label = line[len("Next reset:") :].strip() or None

    if used_pct is None:
        return []
    return [
        {
            "label": "Weekly Grok",
            "used_pct": used_pct,
            "reset_label": reset_label,
            "id": "weekly",
        }
    ]


def fetch_grok_cli_quota_windows() -> tuple[list[dict], str | None]:
    grok_bin = _resolve_bin("grok")
    tmux_bin = _resolve_bin("tmux")
    if not grok_bin:
        return [], "grok CLI not found on PATH"
    if not tmux_bin:
        return [], "tmux not found on PATH (required to capture /usage)"

    session = f"hermes_llm_grok_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    workdir = str(_workdir())

    def cleanup() -> None:
        subprocess.run(
            [tmux_bin, "kill-session", "-t", session],
            check=False,
            capture_output=True,
        )

    try:
        started = subprocess.run(
            [
                tmux_bin,
                "new-session",
                "-d",
                "-x",
                "150",
                "-y",
                "48",
                "-s",
                session,
                "-c",
                workdir,
                grok_bin,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if started.returncode != 0:
            return [], f"could not start Grok usage session: {started.stderr or started.stdout}"

        time.sleep(4)
        sent = subprocess.run(
            [tmux_bin, "send-keys", "-t", session, "/usage", "Enter"],
            check=False,
            capture_output=True,
            text=True,
        )
        if sent.returncode != 0:
            return [], "could not request Grok /usage"

        time.sleep(3)
        captured = subprocess.run(
            [tmux_bin, "capture-pane", "-t", session, "-p", "-S", "-100"],
            check=False,
            capture_output=True,
            text=True,
        )
        if captured.returncode != 0:
            return [], "could not read Grok /usage pane"

        windows = parse_grok_usage(captured.stdout or "")
        if not windows:
            return [], "parsed zero windows from Grok /usage (CLI UI may have changed)"
        return windows, None
    finally:
        cleanup()


# ── Codex (OpenAI) ───────────────────────────────────────────────────────────


def fetch_codex_app_server_quota() -> tuple[list[dict], str | None]:
    """Read plan windows via Codex app-server JSON-RPC (account/rateLimits/read)."""
    codex_bin = _resolve_bin("codex")
    if not codex_bin:
        return [], "codex CLI not found on PATH"

    try:
        child = subprocess.Popen(
            [codex_bin, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        return [], f"could not start Codex app-server: {exc}"

    assert child.stdin is not None and child.stdout is not None
    deadline = time.monotonic() + 20.0

    def read_response(request_id: int) -> dict:
        while time.monotonic() < deadline:
            # Non-blocking-ish poll so a hung app-server can't freeze the panel.
            if child.poll() is not None and not child.stdout.readable():
                break
            line = child.stdout.readline()
            if not line:
                if child.poll() is not None:
                    raise RuntimeError("Codex app-server closed before responding")
                time.sleep(0.05)
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if response.get("error"):
                raise RuntimeError(f"Codex app-server error: {response['error']}")
            return response
        raise TimeoutError("Codex app-server timed out reading rate limits")

    try:
        child.stdin.write(
            json.dumps(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "Hermes LLM Usage", "version": "0.1"},
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            + "\n"
        )
        child.stdin.flush()
        read_response(1)

        child.stdin.write(
            json.dumps({"id": 2, "method": "account/rateLimits/read", "params": None}) + "\n"
        )
        child.stdin.flush()
        response = read_response(2)
        result = response.get("result") or {}
        snapshot = (
            (result.get("rateLimitsByLimitId") or {}).get("codex")
            or result.get("rateLimits")
            or {}
        )
        windows: list[dict] = []
        for key in ("primary", "secondary"):
            window = snapshot.get(key)
            if not isinstance(window, dict):
                continue
            used = window.get("usedPercent")
            if not isinstance(used, (int, float)):
                continue
            minutes = window.get("windowDurationMins")
            if isinstance(minutes, (int, float)) and minutes >= 10_000:
                label, wid = "Weekly Codex", "weekly"
            elif isinstance(minutes, (int, float)) and minutes <= 360:
                label, wid = "5-hour Codex", "five_hour"
            elif isinstance(minutes, (int, float)):
                label, wid = f"{int(minutes)}-minute Codex", f"m{int(minutes)}"
            else:
                label, wid = "Codex limit", key

            reset_label = None
            resets_at = window.get("resetsAt")
            if isinstance(resets_at, (int, float)):
                try:
                    reset_label = datetime.fromtimestamp(
                        float(resets_at), tz=timezone.utc
                    ).astimezone().strftime("%b %-d at %-I:%M %p %Z")
                except (OverflowError, OSError, ValueError):
                    reset_label = None

            windows.append(
                {
                    "label": label,
                    "used_pct": max(0.0, min(100.0, float(used))),
                    "reset_label": reset_label,
                    "id": wid,
                }
            )

        if not windows:
            return [], "Codex returned no rate-limit windows"
        return windows, None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)
    finally:
        try:
            child.kill()
        except OSError:
            pass
        try:
            child.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass


# ── Venice ───────────────────────────────────────────────────────────────────


def _read_env_key(names: list[str]) -> str | None:
    """Load a key from process env or ~/.hermes/.env (never log the value)."""
    for name in names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    env_path = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / ".env"
    try:
        if not env_path.is_file():
            return None
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in names:
                continue
            value = value.strip().strip("'").strip('"')
            if value:
                return value
    except OSError:
        return None
    return None



def _read_env_keys(names: list[str]) -> list[tuple[str, str]]:
    """Return unique non-empty (name, value) pairs from process env then .env.

    Process env can lag behind a just-saved ~/.hermes/.env (e.g. dashboard
    started earlier). Returning BOTH sources lets callers try the freshest key.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: str, value: str | None) -> None:
        if not value:
            return
        value = value.strip()
        if not value or value in seen:
            return
        seen.add(value)
        found.append((name, value))

    for name in names:
        add(name, os.environ.get(name))

    env_path = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / ".env"
    try:
        if env_path.is_file():
            file_vals: dict[str, str] = {}
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key not in names:
                    continue
                value = value.strip().strip("'").strip('"')
                if value:
                    file_vals[key] = value
            # Prefer file values first for freshness when user just saved.
            for name in names:
                if name in file_vals:
                    # Insert file keys at front by rebuilding order: file then env uniques
                    pass
            # Rebuild: file keys in name order, then any env-only leftovers.
            ordered: list[tuple[str, str]] = []
            seen2: set[str] = set()
            for name in names:
                if name in file_vals and file_vals[name] not in seen2:
                    ordered.append((name + "@file", file_vals[name]))
                    seen2.add(file_vals[name])
            for name, value in found:
                if value not in seen2:
                    ordered.append((name + "@env", value))
                    seen2.add(value)
            return ordered
    except OSError:
        pass
    return found

def fetch_venice_capacity() -> tuple[list[dict], str | None, dict | None]:
    """Account balance from Venice billing API.

    Response shapes observed:
      - Nested: {"balances":{"usd":1.12,"diem":null},"diemEpochAllocation":0,"canConsume":true}
      - Legacy flat / data-wrapped: {"data":{"diem":...,"usd":...}}
    """
    names = ["HERMES_CUSTOM_VENICE_API_KEY", "VENICE_API_KEY"]
    candidates = _read_env_keys(names)
    if not candidates:
        # fall back to single-read for older path
        single = _read_env_key(names)
        if single:
            candidates = [("key", single)]
    if not candidates:
        return [], "Venice API key not found (VENICE_API_KEY)", None

    auth_scheme = "Be" + "arer"
    last_error: str | None = None

    def _num(*vals):
        for value in vals:
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def parse_balance_payload(payload: dict) -> tuple[list[dict], dict | None, str | None]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            return [], None, "Venice balance response not an object"
        balances = data.get("balances") if isinstance(data.get("balances"), dict) else {}
        diem = _num(balances.get("diem"), data.get("diem"), payload.get("diem"))
        usd = _num(balances.get("usd"), data.get("usd"), payload.get("usd"))
        epoch = _num(
            data.get("diemEpochAllocation"),
            payload.get("diemEpochAllocation"),
            balances.get("diemEpochAllocation"),
        )
        if diem is None and usd is None:
            return [], None, "Venice balance response missing DIEM/USD"

        windows: list[dict] = []
        if diem is not None and epoch is not None and epoch > 0:
            remaining_pct = max(0.0, min(100.0, (diem / epoch) * 100.0))
            used_pct = max(0.0, min(100.0, 100.0 - remaining_pct))
            windows.append(
                {
                    "label": "DIEM epoch",
                    "used_pct": used_pct,
                    "reset_label": (
                        f"${usd:.2f} USD" if usd is not None else f"{remaining_pct:.0f}% left"
                    ),
                    "id": "diem_epoch",
                }
            )
        elif usd is not None:
            windows.append(
                {
                    "label": "USD balance",
                    "used_pct": 0.0,
                    "reset_label": f"${usd:.2f} remaining",
                    "id": "usd_balance",
                }
            )
        elif diem is not None:
            windows.append(
                {
                    "label": "DIEM balance",
                    "used_pct": 0.0,
                    "reset_label": f"{diem:.2f} DIEM",
                    "id": "diem_balance",
                }
            )

        meta = {
            "kind": "credits",
            "remaining_usd": usd,
            "diem": diem,
            "diem_epoch_allocation": epoch,
            "can_consume": data.get("canConsume", payload.get("canConsume")),
            "consumption_currency": data.get(
                "consumptionCurrency", payload.get("consumptionCurrency")
            ),
        }
        if not windows:
            return [], meta, "Venice balance not usable"
        return windows, meta, None

    for _source, api_key in candidates:
        curl_config = (
            'header = "Authorization: ' + auth_scheme + " " + api_key + '"\n'
        )
        try:
            child = subprocess.run(
                [
                    "curl",
                    "-sS",
                    "--max-time",
                    "20",
                    "--config",
                    "-",
                    "--write-out",
                    "\n%{http_code}",
                    "https://api.venice.ai/api/v1/billing/balance",
                ],
                input=curl_config,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            last_error = f"could not start Venice request: {exc}"
            continue

        if child.returncode != 0:
            last_error = f"Venice request failed: {(child.stderr or '').strip() or 'curl error'}"
            continue

        body, _, status = (child.stdout or "").rpartition("\n")
        try:
            code = int(status.strip() or "0")
        except ValueError:
            code = 0
        if code < 200 or code >= 300:
            detail = ""
            try:
                err_payload = json.loads(body) if body else {}
                if isinstance(err_payload, dict):
                    detail = str(
                        err_payload.get("error") or err_payload.get("message") or ""
                    ).strip()
            except Exception:
                detail = ""
            last_error = (
                f"Venice billing HTTP {status.strip()}: {detail}"
                if detail
                else f"Venice billing API returned HTTP {status.strip()}"
            )
            # Try next candidate on auth failures.
            if code in (401, 403):
                continue
            return [], last_error, None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            last_error = f"Venice balance JSON error: {exc}"
            continue
        if not isinstance(payload, dict):
            last_error = "Venice balance response not an object"
            continue

        windows, meta, parse_err = parse_balance_payload(payload)
        if parse_err and not windows:
            last_error = parse_err
            continue
        return windows, None, meta

    return [], last_error or "Venice billing unavailable", None


# ── Provider payloads ────────────────────────────────────────────────────────


def _provider_status(windows: list[dict], error: str | None) -> str:
    if error and not windows:
        return "error"
    if any((w.get("used_pct") or 0) >= 100 for w in windows):
        return "exhausted"
    if windows:
        return "ok"
    return "unknown"


def _provider(
    *,
    id_: str,
    name: str,
    source: str,
    windows: list[dict],
    error: str | None,
    note: str | None = None,
    capacity: dict | None = None,
) -> dict:
    return {
        "id": id_,
        "name": name,
        "status": _provider_status(windows, error),
        "confidence": "actual" if windows else "unavailable",
        "source": source,
        "windows": windows,
        "error": error,
        "note": note,
        "capacity": capacity,
    }


def _collect_providers() -> list[dict]:
    """Fetch all providers in parallel."""

    def venice_job() -> tuple[list[dict], str | None, dict | None]:
        return fetch_venice_capacity()

    jobs = {
        "anthropic": lambda: (*fetch_claude_cli_quota_windows(), None),
        "grok": lambda: (*fetch_grok_cli_quota_windows(), None),
        "codex": lambda: (*fetch_codex_app_server_quota(), None),
        "venice": venice_job,
    }
    results: dict[str, tuple[list[dict], str | None, dict | None]] = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): key for key, fn in jobs.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:  # noqa: BLE001
                results[key] = ([], str(exc), None)

    def pack(key: str, name: str, source: str, note: str) -> dict:
        windows, err, capacity = results.get(key, ([], "not run", None))
        return _provider(
            id_=key if key != "anthropic" else "anthropic",
            name=name,
            source=source,
            windows=windows,
            error=err,
            note=note,
            capacity=capacity,
        )

    # Stable display order
    return [
        pack("anthropic", "Claude Code", "Claude Code CLI /usage", "Session · all models · Fable"),
        pack("grok", "Grok", "Grok CLI /usage", "Weekly plan window"),
        pack("codex", "Codex", "Codex app-server rate limits", "5-hour · weekly"),
        pack("venice", "Venice", "Venice billing /balance", "Account balance · DIEM epoch"),
    ]


def _flatten_windows(providers: list[dict]) -> list[dict]:
    """Legacy flat list for chip / older UI consumers."""
    out: list[dict] = []
    for p in providers:
        for w in p.get("windows") or []:
            out.append({**w, "provider_id": p.get("id"), "provider_name": p.get("name")})
    return out


_EXPECTED_PROVIDER_IDS = ("anthropic", "grok", "codex", "venice")


def _providers_look_complete(payload: dict | None) -> bool:
    """Reject stale caches written before Codex/Venice were added."""
    if not payload or not isinstance(payload, dict):
        return False
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        return False
    ids = {p.get("id") for p in providers if isinstance(p, dict)}
    # Require the multi-provider shape — old Claude+Grok-only caches must refresh.
    return {"anthropic", "grok", "codex"}.issubset(ids)


def _snapshot(force: bool = False) -> dict:
    global _cache, _cache_at
    now = time.monotonic()
    with _cache_lock:
        if (
            not force
            and _cache is not None
            and (now - _cache_at) < _CACHE_TTL_SEC
            and _providers_look_complete(_cache)
        ):
            return {**_cache, "cached": True}

        if not force:
            disk = _read_disk_cache()
            if disk is not None and _providers_look_complete(disk):
                _cache = {**disk, "cached": True}
                _cache_at = now
                threading.Thread(
                    target=lambda: _snapshot(force=True),
                    name="llm-usage-bg-refresh",
                    daemon=True,
                ).start()
                return {**disk, "cached": True}

        providers = _collect_providers()
        any_windows = any(p.get("windows") for p in providers)
        errors = [p["error"] for p in providers if p.get("error") and not p.get("windows")]
        payload = {
            "providers": providers,
            "windows": _flatten_windows(providers),
            "error": "; ".join(errors) if errors and not any_windows else None,
            "source": "Claude · Grok · Codex · Venice",
            "confidence": "actual" if any_windows else "unavailable",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "cache_ttl_sec": _CACHE_TTL_SEC,
            "cached": False,
        }
        if any_windows:
            _cache = payload
            _cache_at = now
            _write_disk_cache(payload)
        elif not force:
            disk = _read_disk_cache()
            if disk is not None and _providers_look_complete(disk):
                return {
                    **disk,
                    "cached": True,
                    "error": payload.get("error") or disk.get("error"),
                    "stale": True,
                }
        return payload


@router.get("/usage")
async def usage(force: bool = False):
    """Return multi-provider plan windows (Claude, Grok, Codex, Venice)."""
    return _snapshot(force=force)


@router.get("/health")
async def health():
    return {
        "ok": True,
        "plugin": "llm-usage",
        "providers": {
            "anthropic": {"claude": _which("claude"), "tmux": _which("tmux")},
            "grok": {"grok": _which("grok"), "tmux": _which("tmux")},
            "codex": {"codex": _which("codex")},
            "venice": {
                "key": bool(_read_env_key(["VENICE_API_KEY", "HERMES_CUSTOM_VENICE_API_KEY"]))
            },
        },
    }
