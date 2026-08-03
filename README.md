<h1 align="center">hermes-llm-usage</h1>

<p align="center">
  Floating multi-provider capacity HUD for Hermes Desktop —
  account plan windows and balances, not API-key caps.
</p>

<p align="center">
  <img alt="Hermes Desktop plugin" src="https://img.shields.io/badge/Hermes-Desktop%20Plugin-2f81f7?style=flat-square">
  <img alt="JavaScript ESM" src="https://img.shields.io/badge/JavaScript-ESM-f7df1e?style=flat-square&logo=javascript&logoColor=111111">
  <img alt="Python FastAPI backend" src="https://img.shields.io/badge/Python-FastAPI-3776ab?style=flat-square&logo=python&logoColor=white">
  <img alt="Providers" src="https://img.shields.io/badge/Providers-Claude%20%7C%20Grok%20%7C%20Codex%20%7C%20Nous%20%7C%20Venice-111827?style=flat-square">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square">
  <a href="https://github.com/kfa-ai/hermes-llm-usage/actions/workflows/check.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/kfa-ai/hermes-llm-usage/check.yml?branch=main&style=flat-square&label=check"></a>
  <a href="https://github.com/kfa-ai/hermes-llm-usage/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/kfa-ai/hermes-llm-usage?style=flat-square&label=release"></a>
</p>

At-a-glance plan windows for the providers you actually use inside Hermes:

| Provider | What it shows |
| --- | --- |
| **Claude Code** | Session · All models · Fable (CLI `/usage`) |
| **Grok** | Weekly (CLI `/usage`) |
| **Codex** | Weekly (+ 5-hour when present); banked usage-reset pill |
| **Nous Research** | Monthly subscription allowance, renewal, top-up |
| **Venice** | USD / DIEM balance (Admin billing API) |

Successor to the macOS menubar app [`llm-usage-bar`](https://github.com/kfa-ai/llm-usage-bar) for day-to-day use inside Hermes. That Tauri app stays as a standalone reference; this repo is the Hermes-native plugin.

## Features

- Floating HUD + status-bar chip + full page + ⌘K commands.
- Multi-provider sections with quiet-until-it-matters meters (theme-live accent → destructive).
- Provider visibility toggles and a corner resize grip (sizes persist).
- Codex banked **usage-limit resets** as a header pill with expiry on hover.
- Disk + memory cache (~5 min) so polls never block on a full provider sweep.
- Stock Hermes only — no core patches; `placement: 'floating'` public surface.

## Install

```bash
git clone git@github.com:kfa-ai/hermes-llm-usage.git
cd hermes-llm-usage
./install.sh
```

What it does:

1. Copies `desktop-plugins/llm-usage/` → `~/.hermes/desktop-plugins/llm-usage/`
2. Copies `plugins/llm-usage/` → `~/.hermes/plugins/llm-usage/`
3. Enables `llm-usage` in `plugins.enabled` when the Hermes CLI is available

Then:

1. **Restart dashboard / Desktop-owned `hermes serve`** so `/api/plugins/llm-usage` mounts  
   (⌘K → Reload desktop plugins alone does **not** remount Python)
2. In Desktop: **⌘K → Reload desktop plugins**
3. Look for the floating **LLM Usage** card and the status-bar chip

Profile-specific install:

```bash
HERMES_HOME=/path/to/profile ./install.sh
```

## Controls

| Control | Action |
| --- | --- |
| Floating card | Drag header · collapse chevron |
| In-panel **↻** | Force refresh (CLI + API; can take ~15s) |
| In-panel **✕** | Hide card |
| In-panel **⚙** | Toggle visible providers |
| Bottom-right grip | Resize floating card (persisted) |
| Status-bar **LLM …** chip | Toggle card open/closed |
| Codex **N reset** pill | Hover for Full reset expiry |
| ⌘K | Show / Hide / Refresh / Open full page |

## Requirements

| Provider | Needs |
| --- | --- |
| Claude Code | `claude` + `tmux` on PATH |
| Grok | `grok` (xAI CLI) + `tmux` |
| Codex | `codex` CLI (app-server) |
| Nous Research | Hermes Portal login (`hermes portal` / `hermes model`) |
| Venice | **Admin** API key in `$HERMES_HOME/.env` as `VENICE_API_KEY` or `HERMES_CUSTOM_VENICE_API_KEY` |

Inference-only Venice keys can call models but **not** `/billing/balance`.

## Layout

```text
desktop-plugins/llm-usage/plugin.js   # Desktop UI (@hermes/plugin-sdk)
plugins/llm-usage/
  plugin.yaml
  __init__.py                         # no agent tools; API-only
  dashboard/
    manifest.json
    plugin_api.py                     # FastAPI /api/plugins/llm-usage/*
tests/                                # stdlib unittest
install.sh
```

Backend routes (when enabled):

- `GET /api/plugins/llm-usage/usage` — multi-provider snapshot (`?force=true` bypasses cache)
- `GET /api/plugins/llm-usage/health` — CLI / key presence

Each quota window carries `used_pct`, `reset_label`, and `resets_at` (epoch seconds).  
Codex also attaches `capacity.usage_resets` when banked full-limit resets are available.

Results cache ~5 minutes in memory + `$HERMES_HOME/cache/llm-usage.json`. Expiry serves the last good snapshot and refreshes behind it.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `HERMES_LLM_USAGE_TTL_SEC` | `300` | Seconds between provider refreshes (min 30) |
| `HERMES_LLM_USAGE_WORKDIR` | `$HOME` | cwd for throwaway CLI sessions (folder trust) |

## Design rules

- **Account-level** plan windows / balances only — never treat API-key rate caps as “balance”.
- Desktop plugin is uncompiled ESM — **no JSX**; only `@hermes/plugin-sdk` + `react` / `react/jsx-runtime`.
- Theme via live `var(--ui-*)` and `var(--dt-*)` tokens. Hermes does **not** define `--ui-warning` / `--ui-danger`; attention states use accent → mix toward `--dt-destructive` → `--dt-destructive`.
- Tailwind does not scan `$HERMES_HOME/desktop-plugins` — prefer inline styles / theme vars.
- Quiet until it matters: low usage stays near-monochrome; length is primary, colour secondary.

## Development

```bash
node --check desktop-plugins/llm-usage/plugin.js
bash -n install.sh
shellcheck install.sh
node .github/scripts/check-imports.mjs
python3 -m unittest discover -s tests -v
./install.sh   # then restart backend; ⌘K → Reload desktop plugins
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Troubleshooting

### Reload desktop plugins did nothing after a backend change

Reload only hot-swaps `plugin.js`. Changes under `plugins/llm-usage/dashboard/` need a **dashboard / Desktop `serve` restart**, then a force refresh in the panel.

### Settings → Plugins shows “0 installed” on a remote backend

Known Hermes Desktop issue when the client derives the plugin root from a remote `hermes_home` ([#66899](https://github.com/NousResearch/hermes-agent/issues/66899)). Local sessions are fine; install into the remote profile or run Desktop locally.

## License

[MIT](LICENSE)
