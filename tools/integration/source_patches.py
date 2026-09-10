"""Pinned upstream startup, SDL and base build hooks."""

from __future__ import annotations

from pathlib import Path
from .common import (
    APP_ATTACH_MARKER,
    APP_BOOT_MARKER,
    APP_CONFIG_MARKER,
    APP_LEVEL_READY_MARKER,
    APP_LOG_SORT_MARKER,
    APP_PLAYER_NAME_MARKER,
    APP_STAGE_AUDIO_MARKER,
    APP_STAGE_DATA_MARKER,
    APP_STAGE_GFX_MARKER,
    APP_STAGE_HELPER_MARKER,
    APP_STAGE_INIT_MARKER,
    APP_STAGE_LANGUAGE_MARKER,
    APP_STAGE_LOADING_MARKER,
    APP_STAGE_UI_MARKER,
    APP_STAGE_VIDEO_MARKER,
    BOOTSTRAP_SURFACE_MARKER,
    BZIP2_CMAKE_MARKER,
    CMAKE_DATA_MARKER,
    Change,
    GFX_QUALITY_MARKER,
    GFX_REGISTER_MARKER,
    GFX_RENDERER_MARKER,
    GFX_WINDOW_MARKER,
    GFX_ZOOM_BUFFER_MARKER,
    MAIN_INCLUDE_MARKER,
    MAIN_INIT_GUARD_MARKER,
    MAIN_REGISTER_MARKER,
    ROOT_CMAKE_MARKER,
    SDL_AFTER_FRAME_MARKER,
    SDL_CMAKE_MARKER,
    SDL_FILTER_MARKER,
    SDL_FRAME_STACK_MARKER,
    SDL_INCLUDE_MARKER,
    SDL_INIT_MARKER,
    SDL_MIXER_CMAKE_MARKER,
    SDL_SHUTDOWN_MARKER,
    SDL_TICK_MARKER,
    SRC_CMAKE_MARKER,
    append_block,
    read_text,
    replace_many,
    replace_once,
    write_text,
)


def patch_sources(root: Path, dry_run: bool) -> list[Change]:
    changes: list[Change] = []

    root_cmake = root / "CMakeLists.txt"
    if replace_once(
        root_cmake,
        'option(BUILD_CORSIXTH "Builds the main game" ON)\n',
        'option(BUILD_CORSIXTH "Builds the main game" ON)\n'
        f'{ROOT_CMAKE_MARKER}\n'
        'option(CORSIXTH_3DS "Build the Nintendo 3DS platform integration" OFF)\n'
        'set(CORSIXTH_3DS_DEPS_PREFIX "" CACHE PATH "Staged static 3DS dependencies")\n'
        'if(CORSIXTH_3DS)\n'
        '  set(CORSIX_TH_LINK_LUA_MODULES OFF CACHE BOOL "3DS preloads lfs/lpeg directly" FORCE)\n'
        'endif()\n'
        '# CORSIXTH_3DS_END: root-option\n',
        ROOT_CMAKE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CMakeLists.txt", "patch"))

    corsix_cmake = root / "CorsixTH" / "CMakeLists.txt"
    if replace_once(
        corsix_cmake,
        'set(CORSIX_TH_INTERPRETER_NAME CorsixTH.lua)\nif(USE_SOURCE_DATADIRS)\n',
        'set(CORSIX_TH_INTERPRETER_NAME CorsixTH.lua)\n'
        f'{CMAKE_DATA_MARKER}\n'
        'if(CORSIXTH_3DS)\n'
        '  set(CORSIX_TH_DATADIR "sdmc:/3ds/corsixth")\n'
        '  set(CORSIX_TH_INTERPRETER_PATH "sdmc:/3ds/corsixth/CorsixTH.lua")\n'
        'elseif(USE_SOURCE_DATADIRS)\n'
        '# CORSIXTH_3DS_END: data-path\n',
        CMAKE_DATA_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/CMakeLists.txt", "patch"))

    # The 3DS dependency bootstrap installs SDL2 and SDL2_mixer CMake package
    # files next to the static archives. The desktop fallback uses the old
    # FindSDL2 modules, which check SDL_FOUND/SDLMIXER_FOUND and cannot consume
    # those package targets. Select the package targets explicitly for 3DS
    # while preserving both upstream desktop paths.
    if replace_once(
        corsix_cmake,
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
        "endif()\n",
        "# Find SDL\n"
        f"{SDL_CMAKE_MARKER}\n"
        "if(CORSIXTH_3DS)\n"
        "  find_package(SDL2 CONFIG REQUIRED)\n"
        "  target_include_directories(CorsixTH_lib PUBLIC\n"
        "    $<TARGET_PROPERTY:SDL2::SDL2-static,INTERFACE_INCLUDE_DIRECTORIES>)\n"
        "  if(TARGET SDL2::SDL2main)\n"
        "    target_link_libraries(CorsixTH PRIVATE SDL2::SDL2main)\n"
        "  endif()\n"
        "elseif(VCPKG_TARGET_TRIPLET)\n"
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
        "endif()\n",
        SDL_CMAKE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/CorsixTH/CMakeLists.txt", "patch"))

    if replace_once(
        corsix_cmake,
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
        "# Find SDL_mixer\n"
        f"{SDL_MIXER_CMAKE_MARKER}\n"
        "if(CORSIXTH_3DS)\n"
        "  find_package(SDL2_mixer CONFIG REQUIRED)\n"
        "  # Keep SDL2 after SDL2_mixer in the static link line. The mixer\n"
        "  # package does not encode this dependency in its exported target.\n"
        "  target_link_libraries(CorsixTH_lib PUBLIC\n"
        "    SDL2_mixer::SDL2_mixer-static SDL2::SDL2-static)\n"
        "elseif(VCPKG_TARGET_TRIPLET)\n"
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
        SDL_MIXER_CMAKE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/CorsixTH/CMakeLists.txt", "patch"))

    bzip2_block = (
        f"{BZIP2_CMAKE_MARKER}\n"
        "if(CORSIXTH_3DS)\n"
        "  # The devkitPro FreeType archive is built with bzip2 support, but\n"
        "  # its exported target does not carry that static dependency.\n"
        "  find_package(BZip2 REQUIRED)\n"
        "  target_link_libraries(CorsixTH_lib PRIVATE BZip2::BZip2)\n"
        "endif()\n"
        "# CORSIXTH_3DS_END: bzip2-freetype"
    )
    if append_block(corsix_cmake, bzip2_block, BZIP2_CMAKE_MARKER, dry_run=dry_run):
        changes.append(Change("CorsixTH/CorsixTH/CMakeLists.txt", "patch"))

    src_cmake = root / "CorsixTH" / "Src" / "CMakeLists.txt"
    cmake_block = f"""{SRC_CMAKE_MARKER}
if(CORSIXTH_3DS)
  include(${{CMAKE_CURRENT_SOURCE_DIR}}/3ds/corsixth_3ds_sources.cmake)
endif()
# CORSIXTH_3DS_END: platform-sources"""
    if append_block(src_cmake, cmake_block, SRC_CMAKE_MARKER, dry_run=dry_run):
        changes.append(Change("CorsixTH/Src/CMakeLists.txt", "patch"))

    main_cpp = root / "CorsixTH" / "SrcUnshared" / "main.cpp"
    if replace_once(
        main_cpp,
        '#include "../Src/sdl_core.h"\n',
        '#include "../Src/sdl_core.h"\n'
        f'{MAIN_INCLUDE_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '#include <new>\n'
        '#include <stdexcept>\n'
        '#include "../Src/3ds/runtime_3ds.hpp"\n'
        '#endif\n'
        '// CORSIXTH_3DS_END: main-include\n',
        MAIN_INCLUDE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/SrcUnshared/main.cpp", "patch"))
    # Upgrade an already-integrated 0.6.0 tree. Marker-only idempotence would
    # otherwise retain the Lua bootstrap reporter that calls nil SDL.mainloop.
    main_text = read_text(main_cpp)
    old_3ds_reporter = (
        '      lua_pushcfunction(L.get(), bootstrap_lua_error_report);\n'
        '      lua_insert(L.get(), -2);\n'
        '      if (lua_pcall(L.get(), 1, 0, 0) != LUA_OK) {\n'
        '        const char* report_error = lua_tostring(L.get(), -1);\n'
        '        std::fprintf(stderr, "%s\\n",\n'
        '                     report_error != nullptr ? report_error\n'
        '                                             : "Startup error reporter failed");\n'
        '      }\n'
    )
    guarded_reporter = (
        '#ifdef CORSIXTH_3DS\n'
        '      // App:init failed before SDL.mainloop exists. Preserve the\n'
        '      // original error and show it with the native lower-screen page.\n'
        '      cth3ds::report_fatal(err != nullptr ? err\n'
        '                                           : "uncaught non-string Lua error");\n'
        '#else\n'
        + old_3ds_reporter +
        '#endif\n'
    )
    if (MAIN_INIT_GUARD_MARKER in main_text and old_3ds_reporter in main_text
            and guarded_reporter not in main_text):
        write_text(main_cpp, main_text.replace(old_3ds_reporter, guarded_reporter, 1), dry_run)
        changes.append(Change("CorsixTH/SrcUnshared/main.cpp", "migrate"))
    if replace_once(
        main_cpp,
        '    if (lua_pcall(L.get(), argc, 0, 1) != 0) {\n'
        '      const char* err = lua_tostring(L.get(), -1);\n'
        '      if (err != nullptr) {\n'
        '        std::fprintf(stderr, "%s\\n", err);\n'
        '      } else {\n'
        '        std::fprintf(stderr,\n'
        '                     "An error has occurred in CorsixTH:\\n"\n'
        '                     "Uncaught non-string Lua error\\n");\n'
        '      }\n'
        '      lua_pushcfunction(L.get(), bootstrap_lua_error_report);\n'
        '      lua_insert(L.get(), -2);\n'
        '      if (lua_pcall(L.get(), 1, 0, 0) != 0) {\n'
        '        std::fprintf(stderr, "%s\\n", lua_tostring(L.get(), -1));\n'
        '      }\n'
        '    }\n'
        '    mainloop(L.get());\n\n'
        '    lua_getfield(L.get(), LUA_REGISTRYINDEX, "_RESTART");\n'
        '    bRun = lua_toboolean(L.get(), -1) != 0;\n',
        f'    {MAIN_INIT_GUARD_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '    // An Old 3DS runs out of application memory long before a desktop\n'
        '    // does, and CorsixTH allocates raw arrays while decoding sprites.\n'
        '    // An uncaught std::bad_alloc there reaches std::terminate, which on\n'
        '    // this hardware is indistinguishable from a freeze: both screens\n'
        '    // simply stop. Catching it turns that into a message on the lower\n'
        '    // screen and a line in sdmc:/3ds/corsixth/boot.log.\n'
        '    try {\n'
        '#endif\n'
        '    const int init_status = lua_pcall(L.get(), argc, 0, 1);\n'
        '    if (init_status != LUA_OK) {\n'
        '      const char* err = lua_tostring(L.get(), -1);\n'
        '      if (err != nullptr) {\n'
        '        std::fprintf(stderr, "%s\\n", err);\n'
        '      } else {\n'
        '        std::fprintf(stderr,\n'
        '                     "An error has occurred in CorsixTH:\\n"\n'
        '                     "Uncaught non-string Lua error\\n");\n'
        '      }\n'
        '#ifdef CORSIXTH_3DS\n'
        '      // App:init failed before SDL.mainloop exists. Preserve the\n'
        '      // original error and show it with the native lower-screen page.\n'
        '      cth3ds::report_fatal(err != nullptr ? err\n'
        '                                           : "uncaught non-string Lua error");\n'
        '#else\n'
        '      lua_pushcfunction(L.get(), bootstrap_lua_error_report);\n'
        '      lua_insert(L.get(), -2);\n'
        '      if (lua_pcall(L.get(), 1, 0, 0) != LUA_OK) {\n'
        '        const char* report_error = lua_tostring(L.get(), -1);\n'
        '        std::fprintf(stderr, "%s\\n",\n'
        '                     report_error != nullptr ? report_error\n'
        '                                             : "Startup error reporter failed");\n'
        '      }\n'
        '#endif\n'
        '      bRun = false;\n'
        '    } else {\n'
        '      mainloop(L.get());\n'
        '      lua_getfield(L.get(), LUA_REGISTRYINDEX, "_RESTART");\n'
        '      bRun = lua_toboolean(L.get(), -1) != 0;\n'
        '    }\n'
        '#ifdef CORSIXTH_3DS\n'
        '    } catch (const std::bad_alloc&) {\n'
        '      cth3ds::report_fatal("out of memory");\n'
        '      bRun = false;\n'
        '    } catch (const std::exception& fatal) {\n'
        '      cth3ds::report_fatal(fatal.what());\n'
        '      bRun = false;\n'
        '    } catch (...) {\n'
        '      cth3ds::report_fatal("unknown fatal error");\n'
        '      bRun = false;\n'
        '    }\n'
        '#endif\n'
        '    // CORSIXTH_3DS_END: init-failure-guard\n',
        MAIN_INIT_GUARD_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/SrcUnshared/main.cpp", "patch"))
    if replace_once(
        main_cpp,
        '    luaL_openlibs(L.get());\n    lua_settop(L.get(), 0);\n',
        '    luaL_openlibs(L.get());\n'
        f'    {MAIN_REGISTER_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '    cth3ds::register_lua_module(L.get());\n'
        '#endif\n'
        '    // CORSIXTH_3DS_END: lua-preload\n'
        '    lua_settop(L.get(), 0);\n',
        MAIN_REGISTER_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/SrcUnshared/main.cpp", "patch"))

    sdl_cpp = root / "CorsixTH" / "Src" / "sdl_core.cpp"
    if replace_once(
        sdl_cpp,
        '#include "th_lua.h"\n',
        '#include "th_lua.h"\n'
        f'{SDL_INCLUDE_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '#include "3ds/runtime_3ds.hpp"\n'
        '#endif\n'
        '// CORSIXTH_3DS_END: sdl-core-include\n',
        SDL_INCLUDE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))
    if replace_once(
        sdl_cpp,
        '        if (res != LUA_OK) {\n'
        '          std::fprintf(stderr, "Error in frame callback: %s\\n",\n'
        '                       lua_tostring(L, -1));\n'
        '        } else {\n'
        '          do_frame = do_frame || (lua_toboolean(L, -1) != 0);\n'
        '          lua_pop(L, 2);\n'
        '        }\n',
        f'        {SDL_FRAME_STACK_MARKER}\n'
        '        if (res != LUA_OK) {\n'
        '          std::fprintf(stderr, "Error in frame callback: %s\\n",\n'
        '                       lua_tostring(L, -1));\n'
        '        } else {\n'
        '          do_frame = do_frame || (lua_toboolean(L, -1) != 0);\n'
        '        }\n'
        '        // lua_pcall leaves one result or one error object above the\n'
        '        // message handler. Remove both on every path.\n'
        '        lua_pop(L, 2);\n'
        f'        {SDL_AFTER_FRAME_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '        // CorsixTH has just presented. Mirror that frame onto the\n'
        '        // lower screen while its pixels are still current.\n'
        '        cth3ds::runtime_after_frame();\n'
        '#endif\n'
        '        // CORSIXTH_3DS_END: after-frame\n'
        '        // CORSIXTH_3DS_END: frame-stack-balance\n',
        SDL_FRAME_STACK_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))

    bootstrap_cpp = root / "CorsixTH" / "Src" / "bootstrap.cpp"
    if replace_once(
        bootstrap_cpp,
        '     "local video = TheApp and TheApp.video or TH.surface(w, h)",\n',
        '     "local video = TheApp and TheApp.video or TH.surface(w, h, w, h) '
        f'{BOOTSTRAP_SURFACE_MARKER}",\n',
        BOOTSTRAP_SURFACE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/bootstrap.cpp", "patch"))
    if replace_once(
        sdl_cpp,
        '  SDL_Event e;\n\n#ifndef TRACY_ENABLE\n',
        '  SDL_Event e;\n\n'
        f'  {SDL_INIT_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '  if (!cth3ds::runtime_initialize(L)) {\n'
        '    std::fprintf(stderr, "CorsixTH 3DS: platform runtime initialization failed\\n");\n'
        '  }\n'
        '#endif\n'
        '  // CORSIXTH_3DS_END: runtime-init\n\n'
        '#ifndef TRACY_ENABLE\n',
        SDL_INIT_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))
    if replace_once(
        sdl_cpp,
        '  while ((wait_error = SDL_WaitEvent(&e)) != 0) {\n    bool do_frame = false;\n',
        '  while ((wait_error = SDL_WaitEvent(&e)) != 0) {\n'
        f'    {SDL_TICK_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '    cth3ds::runtime_tick(L);\n'
        '#endif\n'
        '    // CORSIXTH_3DS_END: runtime-tick\n'
        '    bool do_frame = false;\n',
        SDL_TICK_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))
    if replace_once(
        sdl_cpp,
        '    do {\n      int nargs;\n      switch (e.type) {\n',
        '    do {\n'
        f'      {SDL_FILTER_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '      if (cth3ds::runtime_consume_sdl_event(e)) {\n'
        '        continue;\n'
        '      }\n'
        '#endif\n'
        '      // CORSIXTH_3DS_END: bottom-event-filter\n'
        '      int nargs;\n'
        '      switch (e.type) {\n',
        SDL_FILTER_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))
    if replace_once(
        sdl_cpp,
        'leave_loop:\n  SDL_RemoveTimer(timer);\n',
        'leave_loop:\n'
        f'  {SDL_SHUTDOWN_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '  cth3ds::runtime_shutdown(L);\n'
        '#endif\n'
        '  // CORSIXTH_3DS_END: runtime-shutdown\n'
        '  SDL_RemoveTimer(timer);\n',
        SDL_SHUTDOWN_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/sdl_core.cpp", "patch"))

    gfx_cpp = root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp"
    if replace_once(
        gfx_cpp,
        '  window = SDL_CreateWindow("CorsixTH", SDL_WINDOWPOS_UNDEFINED,\n'
        '                            SDL_WINDOWPOS_UNDEFINED, width, height,\n'
        '                            SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE);\n',
        f'  {GFX_WINDOW_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '  const Uint32 window_flags = SDL_WINDOW_SHOWN | SDL_WINDOW_FULLSCREEN;\n'
        '#else\n'
        '  const Uint32 window_flags = SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE;\n'
        '#endif\n'
        '  // CORSIXTH_3DS_END: window-flags\n'
        '  window = SDL_CreateWindow("CorsixTH", SDL_WINDOWPOS_UNDEFINED,\n'
        '                            SDL_WINDOWPOS_UNDEFINED, width, height,\n'
        '                            window_flags);\n',
        GFX_WINDOW_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    # Two call sites set this hint: the render target constructor picks the
    # default, and create_texture_from_pixels restores it after temporarily
    # switching to nearest. Both have to agree, otherwise the very first
    # nearest sprite flips every later texture back to bilinear.
    if replace_once(
        gfx_cpp,
        '  SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");\n'
        '  pixel_format = SDL_AllocFormat(SDL_PIXELFORMAT_ABGR8888);\n',
        f'  {GFX_QUALITY_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '// Linear filtering routes every scaled blit through SDL\'s bilinear\n'
        '// software stretch. An Old 3DS cannot afford that, and the only\n'
        '// resize that matters (640x480 -> 320x240 for the top screen) is done\n'
        '// once in the N3DS framebuffer copy instead.\n'
        '#define CORSIXTH_3DS_SCALE_QUALITY "nearest"\n'
        '#else\n'
        '#define CORSIXTH_3DS_SCALE_QUALITY "linear"\n'
        '#endif\n'
        '  SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, CORSIXTH_3DS_SCALE_QUALITY);\n'
        '  // CORSIXTH_3DS_END: render-quality\n'
        '  pixel_format = SDL_AllocFormat(SDL_PIXELFORMAT_ABGR8888);\n',
        GFX_QUALITY_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    if replace_once(
        gfx_cpp,
        '  SDL_SetWindowMinimumSize(window, params.min_width, params.min_height);\n'
        '  SDL_RenderSetLogicalSize(renderer, width, height);\n',
        f'  {GFX_REGISTER_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '  // The lower screen mirrors this window\'s surface, and SDL2 has no\n'
        '  // way to enumerate windows, so hand it over explicitly.\n'
        '  cth3ds::runtime_set_game_window(window);\n'
        '#endif\n'
        '  // CORSIXTH_3DS_END: register-game-window\n'
        '  SDL_SetWindowMinimumSize(window, params.min_width, params.min_height);\n'
        '  SDL_RenderSetLogicalSize(renderer, width, height);\n',
        GFX_REGISTER_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    if replace_once(
        gfx_cpp,
        '#include "th_gfx_font.h"\n',
        '#include "th_gfx_font.h"\n'
        '#ifdef CORSIXTH_3DS\n'
        '#include "3ds/runtime_3ds.hpp"\n'
        '#endif\n',
        '#include "3ds/runtime_3ds.hpp"',
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    if replace_once(
        gfx_cpp,
        '  SDL_Texture* pTexture = create_texture(iWidth, iHeight, pARGBPixels);\n'
        '  if (iSpriteFlags & thdf_nearest)\n'
        '    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");\n',
        '  SDL_Texture* pTexture = create_texture(iWidth, iHeight, pARGBPixels);\n'
        '  if (iSpriteFlags & thdf_nearest)\n'
        '    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, CORSIXTH_3DS_SCALE_QUALITY);\n',
        # Four-space indent: distinct from the constructor's two-space call,
        # so idempotence checks do not confuse the two sites.
        '    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, CORSIXTH_3DS_SCALE_QUALITY);\n',
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    if replace_once(
        gfx_cpp,
        '  Uint32 iRendererFlags =\n'
        '      (params.present_immediate ? 0 : SDL_RENDERER_PRESENTVSYNC);\n',
        '  Uint32 iRendererFlags =\n'
        '      (params.present_immediate ? 0 : SDL_RENDERER_PRESENTVSYNC);\n'
        f'  {GFX_RENDERER_MARKER}\n'
        '#ifdef CORSIXTH_3DS\n'
        '  iRendererFlags |= SDL_RENDERER_SOFTWARE;\n'
        '#endif\n'
        '  // CORSIXTH_3DS_END: renderer-flags\n',
        GFX_RENDERER_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))
    if replace_once(
        gfx_cpp,
        '    if ((SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP) ==\n'
        '        SDL_WINDOW_FULLSCREEN_DESKTOP) {\n'
        '      // Drawing to an intermediate screen sized buffer when fullscreen results\n'
        '      // in noticeably better text rendering quality.\n'
        '      zoom_buffer =\n'
        '          std::make_unique<scoped_target_texture>(this, 0, 0, width, height,\n'
        '                                                  /* bScale = */ true);\n'
        '    }\n',
        f'    {GFX_ZOOM_BUFFER_MARKER}\n'
        '#ifndef CORSIXTH_3DS\n'
        '    if ((SDL_GetWindowFlags(window) & SDL_WINDOW_FULLSCREEN_DESKTOP) ==\n'
        '        SDL_WINDOW_FULLSCREEN_DESKTOP) {\n'
        '      // Desktop-only quality buffer. At 640x480 RGBA it costs another\n'
        '      // 1.2 MiB and duplicates the 3DS software framebuffer.\n'
        '      zoom_buffer =\n'
        '          std::make_unique<scoped_target_texture>(this, 0, 0, width, height,\n'
        '                                                  /* bScale = */ true);\n'
        '    }\n'
        '#endif\n'
        '    // CORSIXTH_3DS_END: no-fullscreen-zoom-buffer\n',
        GFX_ZOOM_BUFFER_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Src/th_gfx_sdl.cpp", "patch"))

    app_lua = root / "CorsixTH" / "Lua" / "app.lua"
    if replace_once(
        app_lua,
        'local SDL = require("sdl")\n',
        'local SDL = require("sdl")\n'
        f'{APP_BOOT_MARKER}\n'
        'local th3ds_ok, TH3DS = pcall(require, "th3ds")\n'
        'local IS_3DS = th3ds_ok and TH3DS.is_platform()\n'
        '-- CORSIXTH_3DS_END: native-bootstrap\n',
        APP_BOOT_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    # In a dry run the previous insertion is intentionally not written, so its
    # end marker cannot be used as the next anchor. A real run, or an existing
    # integrated tree, has the anchor on disk.
    if replace_once(
        app_lua,
        '  -- Put up the loading screen\n',
        '  -- CORSIXTH_3DS_PRESENTATION_R74: explicit startup-only projection\n'
        '  if IS_3DS and good_install_folder then TH3DS.presentation("boot-artwork") end\n'
        '  -- Put up the loading screen\n',
        'CORSIXTH_3DS_PRESENTATION_R74', dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  -- Load UI\n  corsixth.require("ui")\n  if good_install_folder then\n',
        '  -- CORSIXTH_3DS_PRESENTATION_GAME_R74: before UI, intro or menu can render\n'
        '  if IS_3DS then TH3DS.presentation("game") end\n'
        '  -- Load UI\n  corsixth.require("ui")\n  if good_install_folder then\n',
        'CORSIXTH_3DS_PRESENTATION_GAME_R74', dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if not dry_run or APP_BOOT_MARKER in read_text(app_lua):
        if replace_once(
            app_lua,
            '-- CORSIXTH_3DS_END: native-bootstrap\n',
            '-- CORSIXTH_3DS_END: native-bootstrap\n'
            f'{APP_STAGE_HELPER_MARKER}\n'
            'local function th3ds_stage(code, label)\n'
            '  if IS_3DS and TH3DS.stage then TH3DS.stage(code, label) end\n'
            'end\n'
            '-- CORSIXTH_3DS_END: startup-stage-helper\n',
            APP_STAGE_HELPER_MARKER,
            dry_run=dry_run,
        ):
            changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  self:initScreenshotsDir()\n\n  -- Create the window\n',
        '  self:initScreenshotsDir()\n'
        f'{APP_STAGE_INIT_MARKER}\n'
        '  th3ds_stage("S20", "CONFIG AND GAME PATH READY")\n\n'
        '  -- Create the window\n',
        APP_STAGE_INIT_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '      unpack(modes)))\n  self.video:setBlueFilterActive(false)\n',
        '      unpack(modes)))\n'
        f'{APP_STAGE_VIDEO_MARKER}\n'
        '  th3ds_stage("S35", "VIDEO READY")\n'
        '  self.video:setBlueFilterActive(false)\n',
        APP_STAGE_VIDEO_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '    self.video:endFrame()\n    -- Add some notices to the loading screen\n',
        '    self.video:endFrame()\n'
        f'{APP_STAGE_LOADING_MARKER}\n'
        '    th3ds_stage("S40", "LOADING IMAGE DRAWN")\n'
        '    -- Add some notices to the loading screen\n',
        APP_STAGE_LOADING_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  self.gfx = Graphics(self, gfx_set, charset)\n',
        '  self.gfx = Graphics(self, gfx_set, charset)\n'
        f'{APP_STAGE_GFX_MARKER}\n'
        '  th3ds_stage("S45", "GRAPHICS READY")\n',
        APP_STAGE_GFX_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  self.audio:init()\n',
        '  self.audio:init()\n'
        f'{APP_STAGE_AUDIO_MARKER}\n'
        '  th3ds_stage("S50", "AUDIO READY")\n',
        APP_STAGE_AUDIO_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  local language_load_success, language_error = self:initLanguage()\n',
        f'{APP_STAGE_LANGUAGE_MARKER}\n'
        '  th3ds_stage("S60", "LOADING LANGUAGE")\n'
        '  local language_load_success, language_error = self:initLanguage()\n',
        APP_STAGE_LANGUAGE_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '    self.anims = self.gfx:loadAnimations("Data", "V")\n',
        f'{APP_STAGE_DATA_MARKER}\n'
        '    th3ds_stage("S70", "LOADING GAME DATA")\n'
        '    self.anims = self.gfx:loadAnimations("Data", "V")\n',
        APP_STAGE_DATA_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  -- Load UI\n  corsixth.require("ui")\n',
        f'{APP_STAGE_UI_MARKER}\n'
        '  th3ds_stage("S80", "BUILDING UI")\n'
        '  -- Load UI\n  corsixth.require("ui")\n',
        APP_STAGE_UI_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        '  self.world.gfx_set = self.using_demo_files and "demo" or "full"\nend\n',
        '  self.world.gfx_set = self.using_demo_files and "demo" or "full"\n'
        f'{APP_LEVEL_READY_MARKER}\n'
        '  th3ds_stage("S120", "LEVEL READY")\n'
        '  if IS_3DS and not TH3DS.probe_regular_heap("LEVEL READY") then\n'
        '    error("E-HEAP-PROBE: level has less than 2 MiB contiguous heap")\n'
        '  end\n'
        'end\n',
        APP_LEVEL_READY_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    app_text = read_text(app_lua)
    old_start_stage = (
        'function App:init()\n'
        f'{APP_STAGE_INIT_MARKER}\n'
        '  th3ds_stage("S20", "READING CONFIG")\n'
    )
    if old_start_stage in app_text:
        migrated = app_text.replace(old_start_stage, 'function App:init()\n', 1)
        migrated = migrated.replace(
            '  self:initScreenshotsDir()\n',
            '  self:initScreenshotsDir()\n'
            f'{APP_STAGE_INIT_MARKER}\n'
            '  th3ds_stage("S20", "CONFIG AND GAME PATH READY")\n',
            1,
        )
        write_text(app_lua, migrated, dry_run)
        changes.append(Change("CorsixTH/Lua/app.lua", "migrate"))
        app_text = migrated
    old_video_stage = (
        '  -- CORSIXTH_3DS_STAGE: S40\n'
        '  th3ds_stage("S40", "VIDEO READY")\n'
    )
    if old_video_stage in app_text:
        migrated = app_text.replace(
            old_video_stage,
            f'{APP_STAGE_VIDEO_MARKER}\n  th3ds_stage("S35", "VIDEO READY")\n',
            1,
        )
        write_text(app_lua, migrated, dry_run)
        changes.append(Change("CorsixTH/Lua/app.lua", "migrate"))
        app_text = migrated
    old_audio_stage = (
        f'{APP_STAGE_AUDIO_MARKER}\n'
        '  th3ds_stage("S50", "STARTING AUDIO")\n'
        '  -- Load audio\n'
    )
    if old_audio_stage in app_text:
        migrated = app_text.replace(old_audio_stage, '  -- Load audio\n', 1)
        migrated = migrated.replace(
            '  self.audio:init()\n',
            '  self.audio:init()\n'
            f'{APP_STAGE_AUDIO_MARKER}\n'
            '  th3ds_stage("S50", "AUDIO READY")\n',
            1,
        )
        write_text(app_lua, migrated, dry_run)
        changes.append(Change("CorsixTH/Lua/app.lua", "migrate"))
    if replace_once(
        app_lua,
        '  table.sort(log_table,\n'
        '      function(a, b) return lfs.attributes(a, "modification") > lfs.attributes(b, "modification") end)\n',
        f'{APP_LOG_SORT_MARKER}\n'
        '  table.sort(log_table, function(a, b)\n'
        '    local a_modified = lfs.attributes(a, "modification")\n'
        '    local b_modified = lfs.attributes(b, "modification")\n'
        '    if type(a_modified) == "number" and type(b_modified) == "number"\n'
        '        and a_modified ~= b_modified then\n'
        '      return a_modified > b_modified\n'
        '    end\n'
        '    -- Some 3DS filesystems do not expose modification timestamps.\n'
        '    -- Gamelog names begin with a sortable launch timestamp, so the\n'
        '    -- filename is a deterministic and safe fallback.\n'
        '    return a > b\n'
        '  end)\n'
        '  -- CORSIXTH_3DS_END: nil-safe-log-sort\n',
        APP_LOG_SORT_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    if replace_once(
        app_lua,
        "      value = value:match('^%s*(.*%S)') or \"\"\n"
        "      if value:len() == 0 then -- unless that is also empty\n",
        f'{APP_PLAYER_NAME_MARKER}\n'
        "      value = (value or \"\"):match('^%s*(.*%S)') or \"\"\n"
        "      -- CORSIXTH_3DS_END: nil-safe-player-name\n"
        "      if value:len() == 0 then -- unless that is also empty\n",
        APP_PLAYER_NAME_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    # Migration from overlay 0.1: keep the CorsixTH logical canvas at 640x480.
    # SDL2 performs the physical top-screen letterboxing.
    app_text = read_text(app_lua)
    old_minimums = (
        'App.MIN_WINDOW_WIDTH = IS_3DS and 400 or 640\n'
        'App.MIN_WINDOW_HEIGHT = IS_3DS and 240 or 480\n'
    )
    if old_minimums in app_text:
        write_text(
            app_lua,
            app_text.replace(
                old_minimums,
                'App.MIN_WINDOW_WIDTH = 640\nApp.MIN_WINDOW_HEIGHT = 480\n',
                1,
            ),
            dry_run,
        )
        changes.append(Change("CorsixTH/Lua/app.lua", "migrate"))

    if replace_once(
        app_lua,
        '  self:fixConfig()\n  corsixth.require("filesystem")\n',
        '  self:fixConfig()\n'
        f'{APP_CONFIG_MARKER}\n'
        '  if IS_3DS then\n'
        '    self.config.width = 640\n'
        '    self.config.height = 480\n'
        '    self.config.fullscreen = true\n'
        '    self.config.ui_scale = 1\n'
        '    -- direct_zoom must stay true on 3DS. With it false, CorsixTH\n'
        '    -- allocates a 640x480 render-target texture every frame, clears\n'
        '    -- it, and composites it back with a full-screen alpha blend;\n'
        '    -- through the software renderer that alone costs an Old 3DS\n'
        '    -- more than 30 ms per frame. The lower-screen adapter pins the\n'
        '    -- zoom factor at 1.0 so the direct path never scales sprites.\n'
        '    self.config.direct_zoom = true\n'
        '    self.config.play_intro = false\n'
        '    self.config.play_demo = false\n'
        '    self.config.track_fps = false\n'
        '    self.config.scrolling_momentum = false\n'
        '    self.config.movies = false\n'
        '    self.config.prevent_edge_scrolling = true\n'
        '    -- Sound effects stay on; music does not. The original music is\n'
        '    -- XMI/MIDI and this build has no MIDI synthesiser, so every track\n'
        '    -- would fail to load - after spawning a loader thread each. Off is\n'
        '    -- both the honest state and a faster boot.\n'
        '    self.config.audio = true\n'
        '    self.config.play_sounds = true\n'
        '    self.config.play_announcements = true\n'
        '    self.config.play_music = false\n'
        '  end\n'
        '  -- CORSIXTH_3DS_END: handheld-config\n'
        '  corsixth.require("filesystem")\n',
        APP_CONFIG_MARKER,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))
    attach_block = (
        '    self.ui = UI(self, true)\n'
        f'{APP_ATTACH_MARKER}\n'
        '    if IS_3DS then\n'
        '      self.is_3ds = true\n'
        '      self._3ds = require("3ds.platform").attach(self, TH3DS)\n'
        '    end\n'
        '    -- CORSIXTH_3DS_END: platform-attach\n'
    )
    if replace_many(
        app_lua,
        '    self.ui = UI(self, true)\n',
        attach_block,
        APP_ATTACH_MARKER,
        2,
        dry_run=dry_run,
    ):
        changes.append(Change("CorsixTH/Lua/app.lua", "patch"))

    return changes
