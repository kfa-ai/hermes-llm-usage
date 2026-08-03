import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "desktop-plugins" / "llm-usage" / "plugin.js"
INSTALLER = ROOT / "install.sh"


class DesktopPluginCompatibilityTests(unittest.TestCase):
    def test_usage_state_palette_uses_live_theme_tokens(self):
        source = PLUGIN.read_text(encoding="utf-8")

        self.assertIn("var(--ui-text-primary)", source)
        self.assertIn("var(--ui-accent)", source)
        self.assertIn("var(--dt-destructive)", source)
        self.assertIn(
            "color-mix(in srgb, var(--ui-accent) 40%, var(--dt-destructive))",
            source,
        )
        self.assertNotRegex(
            source,
            r"#[0-9a-fA-F]{3,8}\b",
            "Desktop plugin chrome and quota meters must resolve from live theme variables",
        )

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
        self.assertIn("function CodexResetPill", source)
        self.assertIn("usage_resets", source)
        self.assertIn("reset", source)

    def test_plugin_source_and_installer_parse(self):
        subprocess.run(["node", "--check", str(PLUGIN)], check=True, cwd=ROOT)
        subprocess.run(["bash", "-n", str(INSTALLER)], check=True, cwd=ROOT)

    def test_installer_stages_desktop_plugin_byte_for_byte(self):
        with tempfile.TemporaryDirectory(prefix="llm-usage-stage-") as hermes_home:
            env = os.environ.copy()
            env["HERMES_HOME"] = hermes_home
            result = subprocess.run(
                ["bash", str(INSTALLER)],
                check=False,
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            staged = Path(hermes_home) / "desktop-plugins" / "llm-usage" / "plugin.js"
            self.assertTrue(staged.is_file(), "installer did not stage the Desktop plugin")
            self.assertEqual(PLUGIN.read_bytes(), staged.read_bytes())


if __name__ == "__main__":
    unittest.main()
