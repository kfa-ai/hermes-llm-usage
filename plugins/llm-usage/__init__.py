"""llm-usage — backend API for the Hermes Desktop LLM Usage pane.

Providers: Claude Code, Grok, Codex, Venice (account plan windows / balances).
No agent tools or hooks — dashboard/plugin_api.py is the payload surface.
"""


def register(ctx):
    """No agent-side registration; API lives under dashboard/plugin_api.py."""
    return None
