from __future__ import annotations

import sys
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from integrate_corsixth import (
    APP_ATTACH_MARKER,
    APP_LOG_SORT_MARKER,
    APP_PLAYER_NAME_MARKER,
    APP_STAGE_HELPER_MARKER,
    BOOTSTRAP_SURFACE_MARKER,
    MAIN_INIT_GUARD_MARKER,
    SDL_FRAME_STACK_MARKER,
    SDL_TICK_MARKER,
    UPSTREAM_COMMIT,
    main,
)


OVERLAY = ROOT


class IntegratorTests(unittest.TestCase):
    def test_writer_uses_python39_exact_lf_atomic_publish(self) -> None:
        source = (ROOT / "tools/integrate_corsixth.py").read_text(encoding="utf-8")
        self.assertIn('temporary.open("w", encoding="utf-8", newline="\\n")', source)
        self.assertIn("temporary.replace(path)", source)
        self.assertNotIn("temporary.write_text(text", source)

    def make_upstream(self, root: Path) -> Path:
        from test_playable_path import original_sources
        return original_sources(root)

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([*arguments, "--overlay-root", str(OVERLAY)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_integrates_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream = self.make_upstream(Path(temporary) / "upstream")
            code, output, error = self.run_main(str(upstream))
            self.assertEqual(code, 0, error)
            self.assertIn("Applied", output)
            app_text = (upstream / "CorsixTH/Lua/app.lua").read_text(encoding="utf-8")
            self.assertEqual(app_text.count(APP_ATTACH_MARKER), 1)
            self.assertIn(SDL_TICK_MARKER, (upstream / "CorsixTH/Src/sdl_core.cpp").read_text())
            self.assertTrue((upstream / "CorsixTH/Src/3ds/runtime_3ds.cpp").is_file())
            generated = (upstream / "CorsixTH/Src/3ds/corsixth_3ds_sources.cmake").read_text()
            self.assertIn("liblfs.a", generated)
            self.assertIn("liblpeg.a", generated)
            self.assertIn("ctr_create_3dsx", generated)
            self.assertTrue((upstream / "CorsixTH/Src/3ds/icon.png").is_file())
            gfx_text = (upstream / "CorsixTH/Src/th_gfx_sdl.cpp").read_text()
            self.assertIn("SDL_RENDERER_SOFTWARE", gfx_text)
            self.assertIn("SDL_WINDOW_FULLSCREEN", gfx_text)
            # Linear filtering forces SDL's bilinear software stretch on every
            # scaled blit, which an Old 3DS cannot afford.
            self.assertIn('#define CORSIXTH_3DS_SCALE_QUALITY "nearest"', gfx_text)
            self.assertEqual(
                gfx_text.count(
                    "SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, CORSIXTH_3DS_SCALE_QUALITY)"
                ),
                2,
            )
            # direct_zoom false makes CorsixTH allocate and alpha-composite a
            # full-screen render target every frame.
            self.assertIn("self.config.direct_zoom = true", app_text)
            self.assertNotIn("self.config.direct_zoom = false", app_text)
            self.assertIn("std::bad_alloc", (upstream / "CorsixTH/SrcUnshared/main.cpp").read_text())
            # The lower screen mirrors the game window, so the platform layer
            # must be handed that window and told when a frame has been shown.
            self.assertIn("cth3ds::runtime_set_game_window(window)", gfx_text)
            self.assertIn(
                "cth3ds::runtime_after_frame(res == LUA_OK)",
                (upstream / "CorsixTH/Src/sdl_core.cpp").read_text(),
            )
            self.assertIn("self.config.width = 640", app_text)
            self.assertIn("self.config.height = 480", app_text)
            self.assertIn(APP_PLAYER_NAME_MARKER, app_text)
            self.assertIn("(value or \"\")", app_text)
            self.assertIn(APP_LOG_SORT_MARKER, app_text)
            self.assertIn('type(a_modified) == "number"', app_text)
            self.assertIn("return a > b", app_text)
            self.assertNotIn("self.config.ui_scale = 0.5", app_text)
            main_text = (upstream / "CorsixTH/SrcUnshared/main.cpp").read_text()
            self.assertIn(MAIN_INIT_GUARD_MARKER, main_text)
            self.assertIn("cth3ds::report_fatal(err != nullptr ? err", main_text)
            self.assertIn("#else\n      lua_pushcfunction", main_text)
            self.assertIn("} else {\n      mainloop(L.get());", main_text)
            self.assertIn(APP_STAGE_HELPER_MARKER, app_text)
            for stage in ("S20", "S35", "S40", "S45", "S50", "S60", "S70", "S80"):
                self.assertIn(f'th3ds_stage("{stage}"', app_text)
            self.assertIn('th3ds_stage("S120", "LEVEL VALIDATING")', app_text)
            self.assertIn('TH3DS.probe_regular_heap("LEVEL READY", "level")', app_text)
            self.assertIn("no-fullscreen-zoom-buffer", gfx_text)
            sdl_text = (upstream / "CorsixTH/Src/sdl_core.cpp").read_text()
            self.assertIn(SDL_FRAME_STACK_MARKER, sdl_text)
            self.assertIn("Remove both on every path", sdl_text)
            bootstrap_text = (upstream / "CorsixTH/Src/bootstrap.cpp").read_text()
            self.assertIn(BOOTSTRAP_SURFACE_MARKER, bootstrap_text)
            self.assertIn("TH.surface(w, h, w, h)", bootstrap_text)
            self.assertNotIn("LUA_USE_C89", generated)
            self.assertIn("LLONG_MAX=LONG_LONG_MAX", generated)
            self.assertIn("LLONG_MIN=LONG_LONG_MIN", generated)
            self.assertIn("ULLONG_MAX=ULONG_LONG_MAX", generated)
            manifest = json.loads(
                (upstream / "CorsixTH/Src/3ds/integration-manifest.json").read_text()
            )
            self.assertEqual(manifest["upstream_commit"], UPSTREAM_COMMIT)

            code, output, error = self.run_main(str(upstream))
            self.assertEqual(code, 0, error)
            self.assertIn("Applied 0 changes", output)

            code, output, error = self.run_main(str(upstream), "--check")
            self.assertEqual(code, 0, error)
            self.assertIn("verified", output)

    def test_dry_run_does_not_modify_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream = self.make_upstream(Path(temporary) / "upstream")
            before = (upstream / "CMakeLists.txt").read_bytes()
            code, output, error = self.run_main(str(upstream), "--dry-run")
            self.assertEqual(code, 0, error)
            self.assertIn("Would apply", output)
            self.assertEqual((upstream / "CMakeLists.txt").read_bytes(), before)
            self.assertFalse((upstream / "CorsixTH/Src/3ds").exists())

    def test_check_detects_overlay_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream = self.make_upstream(Path(temporary) / "upstream")
            self.assertEqual(self.run_main(str(upstream))[0], 0)
            runtime = upstream / "CorsixTH/Src/3ds/runtime_3ds.cpp"
            runtime.write_text(runtime.read_text() + "\n// drift\n", encoding="utf-8")
            code, _output, error = self.run_main(str(upstream), "--check")
            self.assertEqual(code, 2)
            self.assertIn("differs from overlay", error)

    def test_rejects_unknown_release_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream = self.make_upstream(Path(temporary) / "upstream")
            app = upstream / "CorsixTH/Lua/app.lua"
            app.write_text(app.read_text().replace("254 -- 0.70.1", "999 -- fork"))
            code, _output, error = self.run_main(str(upstream))
            self.assertEqual(code, 2)
            self.assertIn("does not match the 0.70.1 source signature", error)


if __name__ == "__main__":
    unittest.main()
