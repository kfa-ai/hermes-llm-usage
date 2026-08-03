# Contributing

## Working on the plugin

Install into your Hermes profile from a clone:

```bash
./install.sh
```

That copies:

- `desktop-plugins/llm-usage/` → `$HERMES_HOME/desktop-plugins/llm-usage/`
- `plugins/llm-usage/` → `$HERMES_HOME/plugins/llm-usage/`

and enables `llm-usage` when the Hermes CLI is available.

| What changed | How to pick it up |
| --- | --- |
| Desktop UI (`plugin.js`) | Disk watch, or ⌘K → **Reload desktop plugins** |
| Backend (`plugin_api.py`) | Restart dashboard / Desktop-owned `hermes serve` — Reload does **not** remount Python |
| Both | `./install.sh`, restart backend, reload UI |

Set `HERMES_HOME` to target a non-default profile.

## Before opening a PR

```bash
node --check desktop-plugins/llm-usage/plugin.js
bash -n install.sh
shellcheck install.sh
node .github/scripts/check-imports.mjs
python3 -m unittest discover -s tests -v
```

CI runs the same checks (shellcheck when available). `main` is protected — land changes through a pull request.

## Two constraints that will bite you

**Never write the word `from` followed by a quoted token anywhere in
`plugin.js` — not even in a comment.** Hermes resolves a plugin's imports by
regex-scanning raw source with no comment awareness, so prose that looks like a
specifier is read as a bare import and the plugin is refused at load time.
`check-imports.mjs` runs the loader's own regex to catch this.

**Desktop imports are limited to `@hermes/plugin-sdk`, `react`, and
`react/jsx-runtime`.** There is no build step; the UI ships as uncompiled ESM
and uses `react/jsx-runtime` rather than JSX. Styles stay inline (or use live
theme CSS variables) because Tailwind does not scan runtime plugin directories.

## Scope

This plugin reports **account-level** plan windows and balances only. PRs that
treat API-key rate caps as “balance”, scrape browser cookies/dashboards for
quota, or invent undocumented provider billing routes will be declined.
