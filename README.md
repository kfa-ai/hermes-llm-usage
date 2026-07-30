# Hermes LLM Usage

Floating capacity HUD for **Hermes Desktop** — account plan windows and balances, not API-key caps.

| Provider | What it shows |
|---|---|
| **Claude Code** | Session · All models · Fable (CLI `/usage`) |
| **Grok** | Weekly (CLI `/usage`) |
| **Codex** | 5-hour / weekly (app-server rate limits) |
| **Venice** | USD / DIEM balance (Admin billing API) |

Successor to the macOS menubar app [`llm-usage-bar`](https://github.com/kfa-ai/llm-usage-bar) for day-to-day use inside Hermes. That Tauri app stays available as a standalone reference; this repo is the Hermes-native plugin.

**Status:** private while we polish. Not public yet.

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
| Floating card | Drag header · resize SE corner · collapse chevron |
| Header **↻** | Force refresh (CLI + API; can take ~15s) |
| Header **✕** | Hide card |
| Status-bar **LLM …** chip | Toggle card open/closed |
| ⌘K | Show / Hide / Refresh / Open full page |

Preferences (open/closed) persist per plugin storage.

---

## Requirements

| Provider | Needs |
|---|---|
| Claude Code | `claude` + `tmux` on PATH |
| Grok | `grok` (xAI CLI) + `tmux` |
| Codex | `codex` CLI (app-server) |
| Venice | Admin API key in `~/.hermes/.env` as `VENICE_API_KEY` or `HERMES_CUSTOM_VENICE_API_KEY` |

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

Results cache ~5 minutes in memory + `~/.hermes/cache/llm-usage.json`.

---

## Design rules

- **Account-level** plan windows / balances only — never treat API-key rate caps as “balance”
- Desktop plugin is uncompiled ESM — **no JSX**; only `@hermes/plugin-sdk` + `react` / `react/jsx-runtime`
- Theme via `var(--ui-*)` tokens

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
