# Hermes LLM Usage

Floating capacity HUD for **Hermes Desktop** — account plan windows and balances, not API-key caps.

| Provider | What it shows |
|---|---|
| **Claude Code** | Session · All models · Fable (CLI `/usage`) |
| **Grok** | Weekly (CLI `/usage`) |
| **Codex** | 5-hour / weekly (app-server rate limits) |
| **Nous Research** | Monthly subscription allowance, renewal, and top-up balance (Portal account API) |
| **Venice** | USD / DIEM balance (Admin billing API) |

Successor to the macOS menubar app [`llm-usage-bar`](https://github.com/kfa-ai/llm-usage-bar) for day-to-day use inside Hermes. That Tauri app stays available as a standalone reference; this repo is the Hermes-native plugin.

**Status:** private while we polish. Not public yet.

**Planned rename:** this will be published as **`hermes-llm-usage-bar`**;
`hermes-llm-usage` is an internal working name. The repo name is cosmetic, but
decide deliberately whether the *plugin id* (`llm-usage`) changes with it — that
id is load-bearing:

- install paths — `$HERMES_HOME/{plugins,desktop-plugins}/llm-usage/`
- the backend route — `/api/plugins/llm-usage/*`
- persisted open/closed state in the plugin-storage namespace

Changing the id resets saved pane geometry and orphans the old install
directories, so a rename wants an uninstall step rather than a second `install.sh`.

---

## Install

```bash
# from a clone of this repo
./install.sh
```

What it does:

1. Copies `desktop-plugins/llm-usage/` → `~/.hermes/desktop-plugins/llm-usage/`
2. Copies `plugins/llm-usage/` → `~/.hermes/plugins/llm-usage/`
3. Enables `llm-usage` in `plugins.enabled` (via `hermes plugins enable` when available)

Then:

1. **Restart the Hermes dashboard / gateway** so `/api/plugins/llm-usage` mounts  
   (or restart Desktop if it owns that process)
2. In Desktop: **⌘K → Reload desktop plugins**
3. Look for the floating **LLM Usage** card (top-right) and the status-bar chip

Manual install (same paths):

```bash
mkdir -p ~/.hermes/desktop-plugins ~/.hermes/plugins
cp -R desktop-plugins/llm-usage ~/.hermes/desktop-plugins/
cp -R plugins/llm-usage ~/.hermes/plugins/
hermes plugins enable llm-usage   # if CLI supports it
```

Profile-specific: use `$HERMES_HOME` instead of `~/.hermes`.

---

## Use

| Control | Action |
|---|---|
| Floating card | Drag header · collapse chevron |
| In-panel **↻** | Force refresh (CLI + API; can take ~15s) |
| In-panel **✕** | Hide card |
| In-panel **⚙** | Toggle providers |
| Bottom-right corner grip | Drag to resize the floating card |
| Status-bar **LLM …** chip | Toggle card open/closed |
| ⌘K | Show / Hide / Refresh / Open full page |

Preferences (open/closed, visible providers, and floating size) persist per plugin storage.

The floating card has a small bottom-right resize grip. Drag it to grow or
shrink the card; size is persisted automatically and is not part of settings.

The HUD uses Hermes' public `placement: 'floating'` plugin surface only. Its
refresh/close controls live inside the plugin, so it does not require a patched
Hermes core. The pane contribution id is versioned when necessary to discard
stale off-screen geometry saved by an older window layout.

---

## Requirements

| Provider | Needs |
|---|---|
| Claude Code | `claude` + `tmux` on PATH |
| Grok | `grok` (xAI CLI) + `tmux` |
| Codex | `codex` CLI (app-server) |
| Venice | Admin API key in `~/.hermes/.env` as `VENICE_API_KEY` or `HERMES_CUSTOM_VENICE_API_KEY` |
| Nous Research | Hermes Portal login (`hermes portal` / `hermes model`) |

Inference-only Venice keys can call models but **not** `/billing/balance` (needs Admin).

---

## Layout

```text
desktop-plugins/llm-usage/plugin.js     # Desktop UI (@hermes/plugin-sdk)
plugins/llm-usage/
  plugin.yaml
  __init__.py                           # no agent tools; API-only
  dashboard/
    manifest.json
    plugin_api.py                       # FastAPI /api/plugins/llm-usage/*
```

Backend routes (when enabled):

- `GET /api/plugins/llm-usage/usage` — multi-provider snapshot (`?force=true` bypasses cache)
- `GET /api/plugins/llm-usage/health` — CLI/key presence

Each quota window carries `used_pct`, `reset_label` (raw provider wording) and
`resets_at` (epoch seconds, `null` when unparseable). Codex supplies a real
timestamp; Claude and Grok are scraped text run through `parse_reset_to_epoch`.

Nous usage uses Hermes' authenticated `/api/oauth/account` client. The public
Nous inference OpenAPI documents completions only; it does not document a stable
usage endpoint, so the plugin does not scrape the billing page or invent a
`/v1/usage` contract. Results cache ~5 minutes in memory + `~/.hermes/cache/llm-usage.json`. Expiry
serves the last good snapshot and refreshes behind it, so a poll never waits on
the provider sweep (~15s).

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `HERMES_LLM_USAGE_TTL_SEC` | `300` | Seconds between provider refreshes (min 30). Each sweep spawns tmux, the Claude/Grok CLIs, a Codex app-server and a Venice request — lower values mean real process churn. |
| `HERMES_LLM_USAGE_WORKDIR` | `$HOME` | cwd for the throwaway CLI sessions. Only needed if the CLIs must run in a directory they've already been trusted in. |

---

## Design rules

- **Account-level** plan windows / balances only — never treat API-key rate caps as “balance”
- Desktop plugin is uncompiled ESM — **no JSX**; only `@hermes/plugin-sdk` + `react` / `react/jsx-runtime`
- Theme via live `var(--ui-*)` and `var(--dt-*)` tokens — with two traps:
  - **`--ui-warning` and `--ui-danger` do not exist.** The usage palette uses the
    supported `--ui-accent` at watch, blends it toward the active theme's
    `--dt-destructive` at risk, and uses `--dt-destructive` when maxed. Hermes
    rewrites those semantic variables as its light/dark/custom theme changes, so
    the panel and status chip repaint without a plugin reload.
  - **Tailwind can't see this file.** `apps/desktop/styles.css` does a bare
    `@import 'tailwindcss'`, so Tailwind 4 only scans `apps/desktop` — never
    `$HERMES_HOME/desktop-plugins`. Arbitrary classes work *only* if the host
    happens to use the same value somewhere. Verify against the host's compiled
    CSS before relying on one, or use an inline `style` — which is what all the
    palette and gauge geometry does.
- **Quiet until it matters.** A quota with headroom stays near-monochrome; rows
  ramp from the theme accent toward its destructive colour as they approach their
  ceiling, so the row needing attention is found without reading the others. Tick *count* is the primary
  encoding and colour is secondary, and maxed swaps to a hatch — the panel stays
  readable with no colour at all.
- **One time format.** Providers each state resets in their own wording, so the
  backend resolves all of them to a `resets_at` epoch and the client formats once
  (`3h`, `23h`, `Mon 7 am`). Unparseable text keeps its raw `reset_label`.

---

## Dev loop

```bash
# edit local install in place, or rsync from this repo:
./install.sh && # then ⌘K → Reload desktop plugins
# backend changes need a dashboard restart
```

---

## License

Private for now. All rights reserved until published.
