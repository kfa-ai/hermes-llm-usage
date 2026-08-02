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
        self.assertIn("function UsageBoard({ rest, mode, onClose, storage, onResize })", source)
        self.assertIn(
            "mode: 'float',\n            storage: ctx.storage,",
            source,
        )
        self.assertIn("const PROVIDERS_STORAGE_KEY = 'visibleProviders.v1'", source)
        self.assertIn("function SettingsMenu({ storage })", source)
        self.assertIn("Nous Research", source)
        self.assertIn("const SIZE_STORAGE_KEY = 'floatingSize.v1'", source)
        self.assertIn("width: `${size.width}px`", source)
        self.assertIn("function ResizeHandle({ size, onResize, paneRef })", source)
        self.assertIn("'aria-label': 'Resize LLM Usage window'", source)
        self.assertIn("closest?.('[data-floating-pane]')", source)
        self.assertIn("floatingPane.style.width", source)
        self.assertNotIn("children: 'Floating window size'", source)


if __name__ == "__main__":
    unittest.main()
