#!/usr/bin/env bash
# Install Hermes LLM Usage into the active Hermes home (default ~/.hermes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

DESKTOP_SRC="$ROOT/desktop-plugins/llm-usage"
AGENT_SRC="$ROOT/plugins/llm-usage"
DESKTOP_DST="$HERMES_HOME/desktop-plugins/llm-usage"
AGENT_DST="$HERMES_HOME/plugins/llm-usage"

if [[ ! -f "$DESKTOP_SRC/plugin.js" ]]; then
  echo "error: missing $DESKTOP_SRC/plugin.js" >&2
  exit 1
fi
if [[ ! -f "$AGENT_SRC/dashboard/plugin_api.py" ]]; then
  echo "error: missing $AGENT_SRC/dashboard/plugin_api.py" >&2
  exit 1
fi

mkdir -p "$HERMES_HOME/desktop-plugins" "$HERMES_HOME/plugins"
rm -rf "$DESKTOP_DST" "$AGENT_DST"
mkdir -p "$DESKTOP_DST" "$AGENT_DST"
cp -R "$DESKTOP_SRC/." "$DESKTOP_DST/"
cp -R "$AGENT_SRC/." "$AGENT_DST/"
# never ship bytecode
find "$AGENT_DST" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$AGENT_DST" -type f -name '*.pyc' -delete 2>/dev/null || true

echo "Installed desktop plugin → $DESKTOP_DST"
echo "Installed agent/backend  → $AGENT_DST"

if command -v hermes >/dev/null 2>&1; then
  if hermes plugins enable llm-usage 2>/dev/null; then
    echo "Enabled llm-usage in plugins.enabled"
  else
    echo "note: run: hermes plugins enable llm-usage"
    echo "      (or add 'llm-usage' under plugins.enabled in config.yaml)"
  fi
else
  echo "note: hermes CLI not on PATH — enable manually:"
  echo "      plugins.enabled: [..., llm-usage]"
fi

cat <<EOF

Next:
  1. Restart Hermes dashboard/gateway so /api/plugins/llm-usage mounts
  2. Desktop: ⌘K → Reload desktop plugins
  3. Look for floating "LLM Usage" + status-bar chip

Venice: Admin key in \$HERMES_HOME/.env as VENICE_API_KEY or HERMES_CUSTOM_VENICE_API_KEY
EOF
