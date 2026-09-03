#!/usr/bin/env python3
"""Inject the CorsixTH 3DS overlay into a pinned CorsixTH 0.70.1 checkout.

The operation is deterministic and idempotent. It copies the platform sources,
adds guarded build hooks, registers the native Lua module, and loads the 3DS
Lua adapter. Original Theme Hospital data is never copied by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

UPSTREAM_TAG = "v0.70.1"
UPSTREAM_COMMIT = "56bd5d00f76331c7f76d7b696726a7926303ca0c"
OVERLAY_VERSION = "0.6.1"

ROOT_CMAKE_MARKER = "# CORSIXTH_3DS_BEGIN: root-option"
SRC_CMAKE_MARKER = "# CORSIXTH_3DS_BEGIN: platform-sources"
MAIN_INCLUDE_MARKER = "// CORSIXTH_3DS_BEGIN: main-include"
MAIN_REGISTER_MARKER = "// CORSIXTH_3DS_BEGIN: lua-preload"
MAIN_INIT_GUARD_MARKER = "// CORSIXTH_3DS_BEGIN: init-failure-guard"
SDL_INCLUDE_MARKER = "// CORSIXTH_3DS_BEGIN: sdl-core-include"
SDL_INIT_MARKER = "// CORSIXTH_3DS_BEGIN: runtime-init"
SDL_TICK_MARKER = "// CORSIXTH_3DS_BEGIN: runtime-tick"
SDL_FILTER_MARKER = "// CORSIXTH_3DS_BEGIN: bottom-event-filter"
SDL_SHUTDOWN_MARKER = "// CORSIXTH_3DS_BEGIN: runtime-shutdown"
SDL_FRAME_STACK_MARKER = "// CORSIXTH_3DS_BEGIN: frame-stack-balance"
GFX_WINDOW_MARKER = "// CORSIXTH_3DS_BEGIN: window-flags"
GFX_RENDERER_MARKER = "// CORSIXTH_3DS_BEGIN: renderer-flags"
GFX_QUALITY_MARKER = "// CORSIXTH_3DS_BEGIN: render-quality"
GFX_REGISTER_MARKER = "// CORSIXTH_3DS_BEGIN: register-game-window"
GFX_ZOOM_BUFFER_MARKER = "// CORSIXTH_3DS_BEGIN: no-fullscreen-zoom-buffer"
SDL_AFTER_FRAME_MARKER = "// CORSIXTH_3DS_BEGIN: after-frame"
APP_BOOT_MARKER = "-- CORSIXTH_3DS_BEGIN: native-bootstrap"
APP_STAGE_HELPER_MARKER = "-- CORSIXTH_3DS_BEGIN: startup-stage-helper"
APP_STAGE_INIT_MARKER = "  -- CORSIXTH_3DS_STAGE: S20"
APP_STAGE_VIDEO_MARKER = "  -- CORSIXTH_3DS_STAGE: S35"
APP_STAGE_LOADING_MARKER = "    -- CORSIXTH_3DS_STAGE: S40"
APP_STAGE_GFX_MARKER = "  -- CORSIXTH_3DS_STAGE: S45"
APP_STAGE_AUDIO_MARKER = "  -- CORSIXTH_3DS_STAGE: S50"
APP_STAGE_LANGUAGE_MARKER = "  -- CORSIXTH_3DS_STAGE: S60"
APP_STAGE_DATA_MARKER = "    -- CORSIXTH_3DS_STAGE: S70"
APP_STAGE_UI_MARKER = "  -- CORSIXTH_3DS_STAGE: S80"
APP_LEVEL_READY_MARKER = "  -- CORSIXTH_3DS_STAGE: S120"
APP_CONFIG_MARKER = "  -- CORSIXTH_3DS_BEGIN: handheld-config"
APP_ATTACH_MARKER = "    -- CORSIXTH_3DS_BEGIN: platform-attach"
APP_PLAYER_NAME_MARKER = "      -- CORSIXTH_3DS_BEGIN: nil-safe-player-name"
APP_LOG_SORT_MARKER = "  -- CORSIXTH_3DS_BEGIN: nil-safe-log-sort"
BOOTSTRAP_SURFACE_MARKER = "-- CORSIXTH_3DS: four-argument-surface"
CMAKE_DATA_MARKER = "# CORSIXTH_3DS_BEGIN: data-path"
SDL_CMAKE_MARKER = "# CORSIXTH_3DS_BEGIN: sdl-targets"
SDL_MIXER_CMAKE_MARKER = "# CORSIXTH_3DS_BEGIN: sdl-mixer-targets"
BZIP2_CMAKE_MARKER = "# CORSIXTH_3DS_BEGIN: bzip2-freetype"


class IntegrationError(RuntimeError):
    """Raised when the upstream tree does not match the pinned integration."""


@dataclass(frozen=True)
class Change:
    path: str
    operation: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IntegrationError(f"cannot read {path}: {exc}") from exc


def write_text(path: Path, text: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".cth3ds.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def replace_once(
    path: Path,
    old: str,
    new: str,
    marker: str,
    *,
    dry_run: bool,
) -> bool:
    text = read_text(path)
    if marker in text:
        return False
    count = text.count(old)
    if count != 1:
        raise IntegrationError(
            f"expected exactly one integration anchor in {path}, found {count}: {old[:80]!r}"
        )
    write_text(path, text.replace(old, new, 1), dry_run)
    return True


def replace_many(
    path: Path,
    old: str,
    new: str,
    marker: str,
    expected_count: int,
    *,
    dry_run: bool,
) -> bool:
    text = read_text(path)
    if text.count(marker) == expected_count:
        return False
    count = text.count(old)
    if count != expected_count:
        raise IntegrationError(
            f"expected {expected_count} integration anchors in {path}, found {count}: {old!r}"
        )
    write_text(path, text.replace(old, new), dry_run)
    return True


def append_block(path: Path, block: str, marker: str, *, dry_run: bool) -> bool:
    text = read_text(path)
    if marker in text:
        return False
    if not text.endswith("\n"):
        text += "\n"
    write_text(path, text + "\n" + block.rstrip() + "\n", dry_run)
    return True


def git_head(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def validate_upstream(root: Path, allow_unverified: bool) -> str:
    required = [
        root / "CMakeLists.txt",
        root / "CorsixTH" / "CMakeLists.txt",
        root / "CorsixTH" / "Lua" / "app.lua",
        root / "CorsixTH" / "Src" / "CMakeLists.txt",
        root / "CorsixTH" / "Src" / "sdl_core.cpp",
        root / "CorsixTH" / "Src" / "bootstrap.cpp",
        root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        root / "CorsixTH" / "SrcUnshared" / "main.cpp",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise IntegrationError("not a CorsixTH source tree; missing: " + ", ".join(missing))

    head = git_head(root)
    if head is not None:
        if head != UPSTREAM_COMMIT and not allow_unverified:
            raise IntegrationError(
                f"upstream commit is {head}; expected {UPSTREAM_COMMIT} ({UPSTREAM_TAG}). "
                "Checkout the pinned tag or pass --allow-unverified."
            )
        return f"git:{head}"

    app = read_text(root / "CorsixTH" / "Lua" / "app.lua")
    base_signatures = (
        "local SAVEGAME_VERSION = 254 -- 0.70.1",
        "function App:fixConfig()",
    )
    layout_signature = (
        "App.MIN_WINDOW_WIDTH = 640" in app
        or "App.MIN_WINDOW_WIDTH = IS_3DS and 400 or 640" in app
    )
    signature_ok = all(signature in app for signature in base_signatures) and layout_signature
    if not signature_ok and not allow_unverified:
        raise IntegrationError(
            "release archive has no .git directory and does not match the 0.70.1 source signature; "
            "pass --allow-unverified only if you intentionally maintain a compatible fork"
        )
    return "source-signature:v0.70.1" if signature_ok else "unverified"


def iter_overlay_files(overlay: Path) -> Iterable[tuple[Path, Path]]:
    include_root = overlay / "include" / "cth3ds"
    for source in sorted(include_root.glob("*.hpp")):
        yield source, Path("CorsixTH/Src/3ds/include/cth3ds") / source.name
    for source in sorted((overlay / "src" / "common").glob("*.cpp")):
        yield source, Path("CorsixTH/Src/3ds/common") / source.name
    for name in ("runtime_3ds.cpp", "runtime_3ds.hpp", "embedded_platform_lua.hpp"):
        source = overlay / "src" / "3ds" / name
        yield source, Path("CorsixTH/Src/3ds") / name
    yield overlay / "lua" / "3ds" / "platform.lua", Path("CorsixTH/Lua/3ds/platform.lua")
    yield overlay / "assets" / "3ds" / "icon.png", Path("CorsixTH/Src/3ds/icon.png")


def refresh_embedded_adapter(overlay: Path) -> None:
    """Regenerate src/3ds/embedded_platform_lua.hpp from lua/3ds/platform.lua.

    The runtime falls back to this compiled-in copy when the SD card's adapter
    cannot be loaded, so it must always describe the adapter in this tree.
    """
    generator = overlay / "tools" / "embed_platform_lua.py"
    if not generator.is_file():
        raise IntegrationError(f"missing generator: {generator}")
    result = subprocess.run(
        [sys.executable, str(generator)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise IntegrationError(
            f"failed to regenerate the embedded adapter: {result.stderr.strip()}"
        )


def copy_overlay(root: Path, overlay: Path, dry_run: bool) -> list[Change]:
    changes: list[Change] = []
    if not dry_run:
        refresh_embedded_adapter(overlay)
    for source, relative in iter_overlay_files(overlay):
        if not source.is_file():
            raise IntegrationError(f"overlay file is missing: {source}")
        destination = root / relative
        same = destination.is_file() and sha256_file(source) == sha256_file(destination)
        if same:
            continue
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        changes.append(Change(relative.as_posix(), "copy"))

    generated = root / "CorsixTH" / "Src" / "3ds" / "corsixth_3ds_sources.cmake"
    generated_text = """# Generated by corsixth-3ds-port/tools/integrate_corsixth.py.
set(CTH3DS_PLATFORM_ROOT "${CMAKE_CURRENT_LIST_DIR}")
if(NOT CORSIXTH_3DS_DEPS_PREFIX)
  message(FATAL_ERROR "CORSIXTH_3DS_DEPS_PREFIX must point to the staged 3DS dependencies")
endif()

file(GLOB CTH3DS_COMMON_SOURCES CONFIGURE_DEPENDS
  "${CTH3DS_PLATFORM_ROOT}/common/*.cpp")

target_sources(CorsixTH_lib PRIVATE
  ${CTH3DS_COMMON_SOURCES}
  "${CTH3DS_PLATFORM_ROOT}/runtime_3ds.cpp"
  "${CTH3DS_PLATFORM_ROOT}/runtime_3ds.hpp")

target_include_directories(CorsixTH_lib PRIVATE
  "${CTH3DS_PLATFORM_ROOT}"
  "${CTH3DS_PLATFORM_ROOT}/include")

# devkitARM/newlib exposes the C spellings LONG_LONG_* to C++ while Lua's
# luaconf.h checks the C99 spellings LLONG_*. Alias the equivalent limits so
# C and C++ select the same default 64-bit lua_Integer ABI.
set(CTH3DS_LUA_INTEGER_LIMITS
  LLONG_MAX=LONG_LONG_MAX
  LLONG_MIN=LONG_LONG_MIN
  ULLONG_MAX=ULONG_LONG_MAX)
target_compile_definitions(CorsixTH_lib PUBLIC CORSIXTH_3DS=1 ${CTH3DS_LUA_INTEGER_LIMITS})
target_compile_definitions(CorsixTH PRIVATE CORSIXTH_3DS=1 ${CTH3DS_LUA_INTEGER_LIMITS})
target_link_options(CorsixTH PRIVATE
  "-Wl,-Map,${CMAKE_CURRENT_BINARY_DIR}/CorsixTH-3DS.map")

set(CTH3DS_LFS_LIBRARY "${CORSIXTH_3DS_DEPS_PREFIX}/lib/liblfs.a")
set(CTH3DS_LPEG_LIBRARY "${CORSIXTH_3DS_DEPS_PREFIX}/lib/liblpeg.a")
foreach(CTH3DS_REQUIRED_LIBRARY IN ITEMS "${CTH3DS_LFS_LIBRARY}" "${CTH3DS_LPEG_LIBRARY}")
  if(NOT EXISTS "${CTH3DS_REQUIRED_LIBRARY}")
    message(FATAL_ERROR "Missing staged 3DS dependency: ${CTH3DS_REQUIRED_LIBRARY}")
  endif()
endforeach()

add_library(cth3ds_lfs STATIC IMPORTED GLOBAL)
set_target_properties(cth3ds_lfs PROPERTIES IMPORTED_LOCATION "${CTH3DS_LFS_LIBRARY}")
add_library(cth3ds_lpeg STATIC IMPORTED GLOBAL)
set_target_properties(cth3ds_lpeg PROPERTIES IMPORTED_LOCATION "${CTH3DS_LPEG_LIBRARY}")
target_link_libraries(CorsixTH_lib PUBLIC ctru m PRIVATE cth3ds_lfs cth3ds_lpeg)

if(NOT COMMAND ctr_generate_smdh OR NOT COMMAND ctr_create_3dsx)
  message(FATAL_ERROR "Nintendo 3DS CMake helpers are unavailable; use the devkitPro 3DS toolchain")
endif()
set_target_properties(CorsixTH PROPERTIES OUTPUT_NAME "CorsixTH-3DS")
set(CTH3DS_SMDH "${CMAKE_CURRENT_BINARY_DIR}/CorsixTH-3DS.smdh")
ctr_generate_smdh(
  OUTPUT "${CTH3DS_SMDH}"
  NAME "CorsixTH"
  DESCRIPTION "Theme Hospital engine for Nintendo 3DS"
  AUTHOR "CorsixTH contributors / cth3ds port"
  ICON "${CTH3DS_PLATFORM_ROOT}/icon.png")
ctr_create_3dsx(corsixth_3dsx
  TARGET CorsixTH
  OUTPUT "${CMAKE_BINARY_DIR}/CorsixTH-3DS.3dsx"
  SMDH "${CTH3DS_SMDH}")
"""
    if not generated.is_file() or read_text(generated) != generated_text:
        write_text(generated, generated_text, dry_run)
        changes.append(Change(generated.relative_to(root).as_posix(), "generate"))
    return changes


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


def manifest(root: Path, overlay: Path, provenance: str) -> dict[str, object]:
    files = []
    for source, relative in iter_overlay_files(overlay):
        destination = root / relative
        if not destination.is_file():
            raise IntegrationError(f"integrated file is missing: {relative}")
        files.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(destination),
                "size": destination.stat().st_size,
            }
        )
    return {
        "format": 1,
        "overlay_version": OVERLAY_VERSION,
        "upstream_tag": UPSTREAM_TAG,
        "upstream_commit": UPSTREAM_COMMIT,
        "provenance": provenance,
        "files": files,
    }


def check_integrated(root: Path, overlay: Path) -> list[str]:
    errors: list[str] = []
    marker_files = {
        ROOT_CMAKE_MARKER: root / "CMakeLists.txt",
        CMAKE_DATA_MARKER: root / "CorsixTH" / "CMakeLists.txt",
        SDL_CMAKE_MARKER: root / "CorsixTH" / "CMakeLists.txt",
        SDL_MIXER_CMAKE_MARKER: root / "CorsixTH" / "CMakeLists.txt",
        BZIP2_CMAKE_MARKER: root / "CorsixTH" / "CMakeLists.txt",
        SRC_CMAKE_MARKER: root / "CorsixTH" / "Src" / "CMakeLists.txt",
        MAIN_INCLUDE_MARKER: root / "CorsixTH" / "SrcUnshared" / "main.cpp",
        MAIN_REGISTER_MARKER: root / "CorsixTH" / "SrcUnshared" / "main.cpp",
        MAIN_INIT_GUARD_MARKER: root / "CorsixTH" / "SrcUnshared" / "main.cpp",
        SDL_INCLUDE_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        SDL_INIT_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        SDL_TICK_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        SDL_FILTER_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        SDL_SHUTDOWN_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        SDL_FRAME_STACK_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        BOOTSTRAP_SURFACE_MARKER: root / "CorsixTH" / "Src" / "bootstrap.cpp",
        GFX_WINDOW_MARKER: root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        GFX_RENDERER_MARKER: root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        GFX_QUALITY_MARKER: root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        GFX_REGISTER_MARKER: root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        GFX_ZOOM_BUFFER_MARKER: root / "CorsixTH" / "Src" / "th_gfx_sdl.cpp",
        SDL_AFTER_FRAME_MARKER: root / "CorsixTH" / "Src" / "sdl_core.cpp",
        APP_BOOT_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_HELPER_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_INIT_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_VIDEO_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_LOADING_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_GFX_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_AUDIO_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_LANGUAGE_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_DATA_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_STAGE_UI_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_LEVEL_READY_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_CONFIG_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_PLAYER_NAME_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
        APP_LOG_SORT_MARKER: root / "CorsixTH" / "Lua" / "app.lua",
    }
    for marker, path in marker_files.items():
        if marker not in read_text(path):
            errors.append(f"missing marker {marker} in {path.relative_to(root)}")
    app_text = read_text(root / "CorsixTH" / "Lua" / "app.lua")
    if app_text.count(APP_ATTACH_MARKER) != 2:
        errors.append("platform adapter must be attached in both app initialization branches")
    if "self.config.width = 640" not in app_text or "self.config.height = 480" not in app_text:
        errors.append("3DS logical canvas must remain 640x480")
    if "self.config.ui_scale = 0.5" in app_text:
        errors.append("fractional ui_scale is invalid because CorsixTH sprite scaling is integral")
    generated_text_path = root / "CorsixTH" / "Src" / "3ds" / "corsixth_3ds_sources.cmake"
    if generated_text_path.is_file():
        generated_platform_text = read_text(generated_text_path)
        if "LUA_USE_C89" in generated_platform_text:
            errors.append("3DS Lua must retain its default 64-bit integer ABI for packed ARGB colours")
        for limit_alias in (
            "LLONG_MAX=LONG_LONG_MAX",
            "LLONG_MIN=LONG_LONG_MIN",
            "ULLONG_MAX=ULONG_LONG_MAX",
        ):
            if limit_alias not in generated_platform_text:
                errors.append(f"3DS C++ Lua ABI is missing limit alias {limit_alias}")
    for source, relative in iter_overlay_files(overlay):
        destination = root / relative
        if not destination.is_file():
            errors.append(f"missing copied file {relative}")
        elif sha256_file(source) != sha256_file(destination):
            errors.append(f"copied file differs from overlay {relative}")
    generated = root / "CorsixTH" / "Src" / "3ds" / "corsixth_3ds_sources.cmake"
    if not generated.is_file():
        errors.append("missing generated 3DS CMake source list")
    else:
        generated_text = read_text(generated)
        for required in ("liblfs.a", "liblpeg.a", "ctr_generate_smdh", "ctr_create_3dsx"):
            if required not in generated_text:
                errors.append(f"generated 3DS CMake is missing {required}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path, help="CorsixTH source checkout or release archive")
    parser.add_argument(
        "--overlay-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="corsixth-3ds-port root (normally inferred)",
    )
    parser.add_argument("--check", action="store_true", help="verify an already integrated tree")
    parser.add_argument("--dry-run", action="store_true", help="validate and list changes without writing")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="allow a non-pinned compatible fork; integration anchors still must match",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.upstream.expanduser().resolve()
    overlay = args.overlay_root.expanduser().resolve()
    try:
        provenance = validate_upstream(root, args.allow_unverified)
        if args.check:
            errors = check_integrated(root, overlay)
            payload = {
                "ok": not errors,
                "mode": "check",
                "upstream": str(root),
                "provenance": provenance,
                "errors": errors,
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif errors:
                for error in errors:
                    print(f"error: {error}", file=sys.stderr)
            else:
                print(f"CorsixTH 3DS integration verified: {root}")
            return 0 if not errors else 2

        changes = copy_overlay(root, overlay, args.dry_run)
        changes.extend(patch_sources(root, args.dry_run))
        if not args.dry_run:
            integrated_manifest = manifest(root, overlay, provenance)
            manifest_path = root / "CorsixTH" / "Src" / "3ds" / "integration-manifest.json"
            manifest_text = json.dumps(integrated_manifest, indent=2, sort_keys=True) + "\n"
            if not manifest_path.is_file() or read_text(manifest_path) != manifest_text:
                write_text(manifest_path, manifest_text, False)
                changes.append(Change(manifest_path.relative_to(root).as_posix(), "generate"))
            errors = check_integrated(root, overlay)
            if errors:
                raise IntegrationError("post-integration verification failed: " + "; ".join(errors))

        payload = {
            "ok": True,
            "mode": "dry-run" if args.dry_run else "integrate",
            "upstream": str(root),
            "provenance": provenance,
            "changes": [change.__dict__ for change in changes],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            action = "Would apply" if args.dry_run else "Applied"
            print(f"{action} {len(changes)} changes to {root}")
            for change in changes:
                print(f"  {change.operation:8s} {change.path}")
        return 0
    except IntegrationError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
