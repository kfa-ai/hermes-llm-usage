from pathlib import Path
import unittest


PLUGIN = Path(__file__).parents[1] / "desktop-plugins" / "llm-usage" / "plugin.js"


class DesktopPluginCompatibilityTests(unittest.TestCase):
    def test_floating_panel_uses_only_public_plugin_surface(self):
        source = PLUGIN.read_text(encoding="utf-8")

        self.assertNotIn(
            "headerActions:",
            source,
            "standard Hermes floating panes do not render plugin headerActions",
        )
        self.assertIn("const OPEN_STORAGE_KEY = 'floatingOpen.v2'", source)
        self.assertIn("id: 'pane-v2'", source)
        self.assertIn("function UsageBoard({ rest, mode, onClose })", source)
        self.assertIn(
            "render: () =>\n              jsx(UsageBoard, { rest: ctx.rest, mode: 'float', onClose: () => setOpen(false) })",
            source,
        )


if __name__ == "__main__":
    unittest.main()
