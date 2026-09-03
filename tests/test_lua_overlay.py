from __future__ import annotations

import re
import unittest
from pathlib import Path


class LuaOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = Path(__file__).parents[1] / "lua" / "3ds" / "platform.lua"
        cls.text = cls.path.read_text(encoding="utf-8")

    def test_platform_exposes_runtime_entrypoints(self) -> None:
        for name in ("attach", "syncBottomState", "handleAction", "installAtomicSaves"):
            self.assertRegex(self.text, rf"function\s+[\w.:]*{name}\s*\(")

    def test_all_native_action_families_are_handled(self) -> None:
        required = {
            "pan_camera", "cursor_step", "confirm", "cancel", "open_quick_menu",
            "rotate_object", "toggle_walls", "zoom_in", "zoom_out",
            "pause_toggle", "speed_cycle", "open_build", "open_staff",
            "open_patients", "open_finance", "open_messages", "open_town_map",
            "open_casebook", "open_research", "quick_save", "quick_load",
            "build_room_rectangle", "place_item", "lifecycle_suspend",
            "lifecycle_resume", "lifecycle_exit",
        }
        handled = set(re.findall(r'kind\s*==\s*"([a-z_]+)"', self.text))
        self.assertFalse(required - handled, f"missing actions: {sorted(required - handled)}")

    def test_atomic_save_uses_temporary_file_then_commit(self) -> None:
        self.assertIn('filename .. ".tmp"', self.text)
        self.assertIn("native.atomic_commit", self.text)
        self.assertLess(self.text.index('filename .. ".tmp"'), self.text.index("native.atomic_commit"))

    def test_game_toolbar_is_never_hidden(self) -> None:
        # The lower screen mirrors the real frame, so CorsixTH's own toolbar is
        # what the player touches. Hiding it would empty the lower screen.
        self.assertNotIn("bottom_panel.visible = false", self.text)
        self.assertIn("bottom_panel.visible = true", self.text)

    def test_zoom_is_pinned(self) -> None:
        # Any zoom other than 1.0 makes CorsixTH scale every sprite through the
        # software renderer, which an Old 3DS cannot afford.
        self.assertNotIn("setZoom", self.text)

    def test_file_has_no_unresolved_template_tokens(self) -> None:
        self.assertNotRegex(self.text, r"\{\{[^}]+\}\}|TODO_PORT|PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
