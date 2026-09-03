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
    def make_upstream(self, root: Path) -> Path:
        (root / "CorsixTH/Lua").mkdir(parents=True)
        (root / "CorsixTH/Src").mkdir(parents=True)
        (root / "CorsixTH/SrcUnshared").mkdir(parents=True)
        (root / "CMakeLists.txt").write_text(
            'option(BUILD_CORSIXTH "Builds the main game" ON)\n', encoding="utf-8"
        )
        (root / "CorsixTH/CMakeLists.txt").write_text(
            "set(CORSIX_TH_INTERPRETER_NAME CorsixTH.lua)\n"
            "if(USE_SOURCE_DATADIRS)\n"
            "  set(CORSIX_TH_DATADIR ${CMAKE_CURRENT_SOURCE_DIR})\n"
            "endif()\n"
            "# Find SDL\n"
            "if(VCPKG_TARGET_TRIPLET)\n"
            "  find_package(SDL2 CONFIG REQUIRED)\n"
            "  target_link_libraries(CorsixTH_lib\n"
            "    PUBLIC\n"
            "      $<IF:$<TARGET_EXISTS:SDL2::SDL2>,SDL2::SDL2,SDL2::SDL2-static>)\n"
            "  target_link_libraries(CorsixTH PRIVATE SDL2::SDL2main)\n"
            "else()\n"
            "  find_package(SDL2 REQUIRED)\n"
            "  if(SDL_FOUND)\n"
            "    include_directories(${SDL_INCLUDE_DIR})\n"
            "    if(SDLMAIN_LIBRARY STREQUAL \"\")\n"
            "      message(FATAL_ERROR \"Error: SDL2 was found but SDL2main was not\")\n"
            "      message(\"Make sure the path is correctly defined or set the environment variable SDLDIR to the correct location\")\n"
            "    endif()\n"
            "    # No need to specify sdl2main separately, the FindSDL.cmake file will take care of that. If not we get an error about it\n"
            "    target_link_libraries(CorsixTH_lib PUBLIC ${SDL_LIBRARY})\n"
            "    message(\"  SDL2 found\")\n"
            "  else()\n"
            "    message(FATAL_ERROR \"Error: SDL2 library not found, it is required to build. Make sure the path is correctly defined or set the environment variable SDLDIR to the correct location\")\n"
            "  endif()\n"
            "endif()\n"
            "# Find SDL_mixer\n"
            "if(VCPKG_TARGET_TRIPLET)\n"
            "  find_package(SDL2_mixer CONFIG REQUIRED)\n"
            "  target_link_libraries(\n"
            "    CorsixTH_lib\n"
            "    PUBLIC\n"
            "      $<IF:$<TARGET_EXISTS:SDL2_mixer::SDL2_mixer>,SDL2_mixer::SDL2_mixer,SDL2_mixer::SDL2_mixer-static>)\n"
            "else()\n"
            "  find_package(SDL2_mixer REQUIRED)\n"
            "  if(SDLMIXER_FOUND)\n"
            "    target_link_libraries(CorsixTH_lib PUBLIC ${SDLMIXER_LIBRARY})\n"
            "    include_directories(${SDLMIXER_INCLUDE_DIR})\n"
            "    message(\"  SDL_mixer found\")\n"
            "  else()\n"
            "    message(FATAL_ERROR \"Error: SDL_mixer library not found, it is required to build\")\n"
            "  endif()\n"
            "endif()\n",
            encoding="utf-8",
        )
        (root / "CorsixTH/Src/CMakeLists.txt").write_text(
            "target_sources(CorsixTH_lib PRIVATE sample.cpp)\n", encoding="utf-8"
        )
        (root / "CorsixTH/SrcUnshared/main.cpp").write_text(
            '#include "../Src/sdl_core.h"\n'
            "void sample() {\n"
            "    luaL_openlibs(L.get());\n"
            "    lua_settop(L.get(), 0);\n"
            "    if (lua_pcall(L.get(), argc, 0, 1) != 0) {\n"
            "      const char* err = lua_tostring(L.get(), -1);\n"
            "      if (err != nullptr) {\n"
            "        std::fprintf(stderr, \"%s\\n\", err);\n"
            "      } else {\n"
            "        std::fprintf(stderr,\n"
            "                     \"An error has occurred in CorsixTH:\\n\"\n"
            "                     \"Uncaught non-string Lua error\\n\");\n"
            "      }\n"
            "      lua_pushcfunction(L.get(), bootstrap_lua_error_report);\n"
            "      lua_insert(L.get(), -2);\n"
            "      if (lua_pcall(L.get(), 1, 0, 0) != 0) {\n"
            "        std::fprintf(stderr, \"%s\\n\", lua_tostring(L.get(), -1));\n"
            "      }\n"
            "    }\n"
            "    mainloop(L.get());\n\n"
            "    lua_getfield(L.get(), LUA_REGISTRYINDEX, \"_RESTART\");\n"
            "    bRun = lua_toboolean(L.get(), -1) != 0;\n"
            "}\n",
            encoding="utf-8",
        )
        (root / "CorsixTH/Src/sdl_core.cpp").write_text(
            '#include "th_lua.h"\n'
            "void mainloop(lua_State* L) {\n"
            "  SDL_TimerID timer = SDL_AddTimer(18, nullptr, nullptr);\n"
            "  SDL_Event e;\n\n"
            "#ifndef TRACY_ENABLE\n"
            "  setup();\n"
            "#endif\n"
            "  while ((wait_error = SDL_WaitEvent(&e)) != 0) {\n"
            "    bool do_frame = false;\n"
            "    do {\n"
            "      int nargs;\n"
            "      switch (e.type) {\n"
            "      default: nargs = 0; break;\n"
            "      }\n"
            "    } while (SDL_PollEvent(&e) != 0);\n"
            "  }\n"
            "leave_loop:\n"
            "  SDL_RemoveTimer(timer);\n"
            "  push_app_dispatch(L, last_dispatch);\n"
            "  int res = lua_pcall(L, 2, 1, -4);\n"
            "        if (res != LUA_OK) {\n"
            "          std::fprintf(stderr, \"Error in frame callback: %s\\n\",\n"
            "                       lua_tostring(L, -1));\n"
            "        } else {\n"
            "          do_frame = do_frame || (lua_toboolean(L, -1) != 0);\n"
            "          lua_pop(L, 2);\n"
            "        }\n"
            "}\n",
            encoding="utf-8",
        )
        (root / "CorsixTH/Src/bootstrap.cpp").write_text(
            '     "local video = TheApp and TheApp.video or TH.surface(w, h)",\n',
            encoding="utf-8",
        )
        (root / "CorsixTH/Src/th_gfx_sdl.cpp").write_text(
            '#include "th_gfx_font.h"\n'
            'void render_target() {\n'
            '  SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");\n'
            '  pixel_format = SDL_AllocFormat(SDL_PIXELFORMAT_ABGR8888);\n'
            '  window = SDL_CreateWindow("CorsixTH", SDL_WINDOWPOS_UNDEFINED,\n'
            '                            SDL_WINDOWPOS_UNDEFINED, width, height,\n'
            '                            SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE);\n'
            '  Uint32 iRendererFlags =\n'
            '      (params.present_immediate ? 0 : SDL_RENDERER_PRESENTVSYNC);\n'
            '  SDL_SetWindowMinimumSize(window, params.min_width, params.min_height);\n'
            '  SDL_RenderSetLogicalSize(renderer, width, height);\n'
            '  if (eWhatToScale == scaled_items::all && direct_zoom) {\n'
            '    if ((SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP) ==\n'
            '        SDL_WINDOW_FULLSCREEN_DESKTOP) {\n'
            '      // Drawing to an intermediate screen sized buffer when fullscreen results\n'
            '      // in noticeably better text rendering quality.\n'
            '      zoom_buffer =\n'
            '          std::make_unique<scoped_target_texture>(this, 0, 0, width, height,\n'
            '                                                  /* bScale = */ true);\n'
            '    }\n'
            '  }\n'
            '}\n'
            'void create_texture_from_pixels() {\n'
            '  SDL_Texture* pTexture = create_texture(iWidth, iHeight, pARGBPixels);\n'
            '  if (iSpriteFlags & thdf_nearest)\n'
            '    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");\n'
            '}\n',
            encoding="utf-8",
        )
        (root / "CorsixTH/Lua/app.lua").write_text(
            'local SDL = require("sdl")\n'
            "local SAVEGAME_VERSION = 254 -- 0.70.1\n"
            "App.MIN_WINDOW_WIDTH = 640\n"
            "App.MIN_WINDOW_HEIGHT = 480\n"
            "function App:init()\n"
            "  -- App initialisation 1st goal: Get the loading screen up\n"
            "  self:fixConfig()\n"
            '  corsixth.require("filesystem")\n'
            "  self:initScreenshotsDir()\n\n"
            "  -- Create the window\n"
            "  self.video = assert(TH.surface(\n"
            "      self.config.width, self.config.height, 640, 480,\n"
            "      unpack(modes)))\n"
            "  self.video:setBlueFilterActive(false)\n"
            "  self.gfx = Graphics(self, gfx_set, charset)\n"
            "    self.video:endFrame()\n"
            "    -- Add some notices to the loading screen\n"
            "  -- Load audio\n"
            '  corsixth.require("audio")\n'
            "  self.audio:init()\n"
            "  local language_load_success, language_error = self:initLanguage()\n"
            '    self.anims = self.gfx:loadAnimations("Data", "V")\n'
            "  -- Load UI\n"
            '  corsixth.require("ui")\n'
            "  if good_install_folder then\n"
            "    self.ui = UI(self, true)\n"
            "  else\n"
            "    self.ui = UI(self, true)\n"
            "  end\n"
            "end\n"
            "function App:_loadLevel()\n"
            '  self.world.gfx_set = self.using_demo_files and "demo" or "full"\n'
            "end\n"
            "function App:fixConfig()\n"
            "      value = value:match('^%s*(.*%S)') or \"\"\n"
            "      if value:len() == 0 then -- unless that is also empty\n"
            "end\n"
            "function App:trimLogs()\n"
            "  local log_table = {}\n"
            "  table.sort(log_table,\n"
            "      function(a, b) return lfs.attributes(a, \"modification\") > lfs.attributes(b, \"modification\") end)\n"
            "end\n",
            encoding="utf-8",
        )
        return root

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
            self.assertEqual(app_text.count(APP_ATTACH_MARKER), 2)
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
                "cth3ds::runtime_after_frame()",
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
            self.assertIn('th3ds_stage("S120", "LEVEL READY")', app_text)
            self.assertIn('TH3DS.probe_regular_heap("LEVEL READY")', app_text)
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
