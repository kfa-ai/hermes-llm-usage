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

    def test_panel_can_persistently_switch_between_float_and_docked_modes(self):
        source = PLUGIN.read_text(encoding="utf-8")

        self.assertIn("const MODE_STORAGE_KEY = 'panelMode.v1'", source)
        self.assertIn("const DEFAULT_PANEL_MODE = 'float'", source)
        self.assertIn("const $panelMode = atom(DEFAULT_PANEL_MODE)", source)
        self.assertIn(
            "const storedMode = ctx.storage.get(MODE_STORAGE_KEY, DEFAULT_PANEL_MODE)",
            source,
        )
        self.assertIn("$panelMode.set(storedMode === 'docked' ? 'docked' : DEFAULT_PANEL_MODE)", source)
        self.assertIn("const OPEN_STORAGE_KEY = 'floatingOpen.v2'", source)
        self.assertIn("id: 'pane-v2'", source)
        self.assertIn(
            "function UsageBoard({ rest, mode, onClose, onFloat, onModeChange, storage, onResize })",
            source,
        )
        self.assertIn(
            "placement: mode === 'float' ? 'floating' : 'right'",
            source,
        )
        self.assertIn("headerActions:", source)
        self.assertIn("id: 'dock'", source)
        self.assertIn("label: 'Dock LLM Usage panel'", source)
        self.assertIn("codicon: 'layout-sidebar-right'", source)
        self.assertIn("onClick: () => setPanelMode('docked')", source)
        self.assertNotIn("onDock", source)
        self.assertIn("const isDocked = mode === 'docked'", source)
        self.assertIn("onFloat: mode === 'docked' ? () => setPanelMode('float') : undefined", source)
        # Both mode switches are in-panel icon buttons: the host's floating
        # header ignores headerActions, so the dock control must render inside
        # the panel, and the docked panel returns to floating via an icon too.
        self.assertIn("'aria-label': 'Dock LLM Usage panel'", source)
        self.assertIn("name: 'layout-sidebar-right'", source)
        self.assertIn("onModeChange('docked')", source)
        self.assertIn("'aria-label': 'Float LLM Usage panel'", source)
        self.assertIn("name: 'multiple-windows'", source)
        self.assertIn("ctx.storage.set(MODE_STORAGE_KEY, mode)", source)
        self.assertIn("disposePane()", source)
        self.assertIn("registerPane()", source)
        self.assertIn("const PROVIDERS_STORAGE_KEY = 'visibleProviders.v1'", source)
        self.assertIn("function SettingsMenu({ storage })", source)
        self.assertIn("Nous Research", source)
        self.assertIn("const SIZE_STORAGE_KEY = 'floatingSize.v1'", source)
        self.assertIn("width: mode === 'float' ? `${size.width}px` : undefined", source)
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
