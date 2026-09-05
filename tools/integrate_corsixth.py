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
import tempfile
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
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
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
    if marker == APP_ATTACH_MARKER and "CORSIXTH_3DS_PRODUCT_U1" in text:
        return False
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


def patch_product_sources(root: Path, dry_run: bool) -> list[Change]:
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="cth3ds-product-preview-") as temp:
            preview=Path(temp)/"upstream"
            shutil.copytree(root,preview,ignore=shutil.ignore_patterns(".git"))
            patch_sources(preview,False)
            return patch_product_sources(preview,False)
    changes = []
    def patch(relative, replacements):
        path = root / relative
        if not path.exists():
            raise IntegrationError(f"missing product target: {relative}")
        text = read_text(path)
        marker = "CORSIXTH_3DS_PRODUCT_U1"
        if marker in text:
            return
        for old, new in replacements:
            if old not in text:
                raise IntegrationError(f"product anchor missing in {relative}: {old[:80]}")
            text = text.replace(old, new)
        if relative in ("CorsixTH/Lua/audio.lua", "CorsixTH/Lua/game_ui.lua", "CorsixTH/Lua/persistance.lua"):
            text = 'local native_ok, TH3DS = pcall(require,"th3ds")\nlocal IS_3DS = native_ok and TH3DS.is_platform()\n' + text
        prefix = "-- " if relative.endswith(".lua") else "// "
        write_text(path, prefix + marker + "\n" + text, dry_run)
        changes.append(Change(relative, "product-u1"))
    patch('CorsixTH/Src/th_sound.h', [
        ('#include <array>',
         r'''#include <array>
#ifdef CORSIXTH_3DS
#include <atomic>
#include <string>
#endif'''),
        ('  bool load_from_th_file',
         r'''#ifdef CORSIXTH_3DS
  bool load_from_file(const char* path);
  bool pcm_requirement(size_t index, size_t& converted, size_t& scratch);
  size_t metadata_bytes() const;
#endif
  bool load_from_th_file'''),
        ('  std::vector<uint8_t> data;',
         r'''#ifdef CORSIXTH_3DS
  std::string file_path;
#endif
  std::vector<uint8_t> data;'''),
        ('  Mix_Chunk** sounds;',
         r'''#ifdef CORSIXTH_3DS
 public:
  size_t cached_bytes() const {return cache_bytes;}
  size_t decoded_clip_count() const {size_t n=0;for(size_t i=0;i<sound_count;++i)if(sounds[i])++n;return n;}
 private:
  sound_archive* archive{nullptr}; // Lua soundEffects environment retains archive.
  std::array<std::atomic<bool>, number_of_channels> finished{};
  std::array<size_t, number_of_channels> channel_sound{};
  std::vector<uint64_t> used_at;
  std::vector<size_t> allocated_bytes;
  size_t cache_bytes{0};
  uint64_t cache_clock{0};
  void drain_finished();
  bool ensure_sound(size_t index);
#endif
  Mix_Chunk** sounds;'''),
    ])
    patch('CorsixTH/Src/th_sound.cpp', [
        ('#include "th.h"',
         r'''#include "th.h"
#ifdef CORSIXTH_3DS
#include "3ds/runtime_3ds.hpp"
#include <cstdio>
#include <memory>
#include <climits>
#endif
#ifdef CORSIXTH_3DS
namespace {
struct SoundSlice { FILE* file; Sint64 start, length, cursor; };
Sint64 slice_size(SDL_RWops* rw) { return static_cast<SoundSlice*>(rw->hidden.unknown.data1)->length; }
Sint64 slice_seek(SDL_RWops* rw, Sint64 offset, int whence) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  Sint64 base = whence == RW_SEEK_SET ? 0 : whence == RW_SEEK_CUR ? s->cursor : whence == RW_SEEK_END ? s->length : -1;
  if (base < 0 || offset < -base || offset > s->length-base) return -1;
  if (std::fseek(s->file, static_cast<long>(s->start+base+offset), SEEK_SET)) return -1;
  return s->cursor = base+offset;
}
size_t slice_read(SDL_RWops* rw, void* ptr, size_t size, size_t count) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  if (!size) return 0;
  count = std::min(count, static_cast<size_t>(s->length-s->cursor)/size);
  size_t n = std::fread(ptr,size,count,s->file); s->cursor += n*size; return n;
}
size_t slice_write(SDL_RWops*, const void*, size_t, size_t) { return 0; }
int slice_close(SDL_RWops* rw) {
  auto* s = static_cast<SoundSlice*>(rw->hidden.unknown.data1);
  int result = std::fclose(s->file); delete s; SDL_FreeRW(rw); return result;
}
SDL_RWops* open_slice(const std::string& path, uint32_t start, uint32_t length) {
  FILE* f=std::fopen(path.c_str(),"rb"); if (!f) return nullptr;
  if (std::fseek(f,0,SEEK_END) || std::ftell(f)<static_cast<int64_t>(start)+length || std::fseek(f,start,SEEK_SET)) { std::fclose(f); return nullptr; }
  SDL_RWops* rw=SDL_AllocRW(); if (!rw) {std::fclose(f); return nullptr;}
  auto* s=new(std::nothrow) SoundSlice{f,start,length,0};
  if (!s) {std::fclose(f);SDL_FreeRW(rw);return nullptr;}
  rw->size=slice_size;rw->seek=slice_seek;rw->read=slice_read;rw->write=slice_write;rw->close=slice_close;
  rw->type=SDL_RWOPS_UNKNOWN;rw->hidden.unknown.data1=s;return rw;
}
struct WaveInfo { uint32_t rate=0, bytes=0; uint16_t channels=0,bits=0; };
bool wave_info(SDL_RWops* rw, WaveInfo& info) {
  uint8_t h[16]; const auto length=SDL_RWsize(rw);
  if (length<12 || SDL_RWread(rw,h,1,12)!=12 || std::memcmp(h,"RIFF",4) || std::memcmp(h+8,"WAVE",4)) return false;
  uint64_t end=uint64_t(bytes_to_uint32_le(h+4))+8;
  if (end>static_cast<uint64_t>(length)) return false;
  bool fmt=false,pcm=false;
  while (SDL_RWtell(rw)<static_cast<Sint64>(end)) {
    if (end-SDL_RWtell(rw)<8 || SDL_RWread(rw,h,1,8)!=8) return false;
    uint32_t n=bytes_to_uint32_le(h+4); uint64_t next=uint64_t(SDL_RWtell(rw))+n;
    if (next>end) return false;
    if (!std::memcmp(h,"fmt ",4)) {
      if (fmt || n<16 || SDL_RWread(rw,h,1,16)!=16) return false;
      info.channels=h[2]|h[3]<<8;info.rate=bytes_to_uint32_le(h+4);info.bits=h[14]|h[15]<<8;
      uint16_t align=h[12]|h[13]<<8;
      if ((h[0]|h[1]<<8)!=1 || (info.channels!=1&&info.channels!=2) || (info.bits!=8&&info.bits!=16) || info.rate<4000 || info.rate>192000 || align!=info.channels*(info.bits/8)) return false;
      fmt=true;
    } else if (!std::memcmp(h,"data",4)) { if(pcm) return false;info.bytes=n;pcm=true; }
    if (SDL_RWseek(rw,next+(n&1),RW_SEEK_SET)<0) return false;
  }
  return fmt&&pcm&&info.bytes&&info.bytes%(info.channels*(info.bits/8))==0;
}
}

bool sound_archive::load_from_file(const char* path) {
  if (!file_path.empty() || !path || !*path || std::strlen(path)>1024) return false;
  std::unique_ptr<FILE,decltype(&std::fclose)> f(std::fopen(path,"rb"),std::fclose);
  if (!f || std::fseek(f.get(),0,SEEK_END)) return false;
  long length=std::ftell(f.get());if(length<238 || length>INT32_MAX) return false;
  auto read=[&](uint32_t offset,void* dst,size_t n){return uint64_t(offset)+n<=uint64_t(length)&&!std::fseek(f.get(),offset,SEEK_SET)&&std::fread(dst,1,n,f.get())==n;};
  uint8_t h[234];if(!read(length-4,h,4)) return false;
  uint32_t hp=bytes_to_uint32_le(h);if(uint64_t(hp)+234>uint64_t(length)-4 || !read(hp,h,234))return false;
  uint32_t tp=bytes_to_uint32_le(h+50),tl=bytes_to_uint32_le(h+58);
  if(!tl || tl%32 || tl/32>4096 || uint64_t(tp)+tl>uint64_t(length)-4 || (tp<uint64_t(hp)+234 && hp<uint64_t(tp)+tl))return false;
  std::vector<sound_dat_sound_info> index(tl/32);
  for(size_t i=0;i<index.size();++i) {
    uint8_t e[32];if(!read(tp+i*32,e,32))return false;
    auto& v=index[i];std::copy_n(e,18,v.sound_name.begin());
    v.position=bytes_to_uint32_le(e+18);v.length=bytes_to_uint32_le(e+26);
    // The original format reserves slot zero; animation sound index zero
    // means no sound. Retain its index and never open it as a WAV.
    if(i==0 && std::all_of(e,e+18,[](uint8_t c){return c==0;})) {v.length=0;continue;}
    if(!e[0] || !std::memchr(e,0,18) || !v.length || uint64_t(v.position)+v.length>uint64_t(length)-4 || (v.position<uint64_t(tp)+tl && tp<uint64_t(v.position)+v.length) || (v.position<uint64_t(hp)+234 && hp<uint64_t(v.position)+v.length))return false;
    for(size_t k=0;k<18&&e[k];++k)if(e[k]<32||e[k]>=127)return false;
    for(size_t j=0;j<i;++j) {
      const auto& other=index[j];if(!other.length)continue;
      bool same_name=!SDL_strcasecmp(v.sound_name.data(),other.sound_name.data());
      if(same_name && v.position==other.position && v.length==other.length)continue; // exact original alias
      if(same_name || (v.position<uint64_t(other.position)+other.length && other.position<uint64_t(v.position)+v.length))return false;
    }
  }
  data.clear();data.shrink_to_fit();file_path=path;sound_files.swap(index);
  cth3ds::report_memory_checkpoint("sound_index","ready",path,metadata_bytes(),0);
  return true;
}
size_t sound_archive::metadata_bytes() const {return sound_files.capacity()*sizeof(sound_dat_sound_info)+file_path.capacity()+sizeof(*this);}
bool sound_archive::pcm_requirement(size_t index,size_t& converted,size_t& scratch) {
  SDL_RWops* rw=load_sound(index);if(!rw)return false;
  WaveInfo w;bool valid=wave_info(rw,w);SDL_RWclose(rw);if(!valid)return false;
  int rate,channels;Uint16 format;if(!Mix_QuerySpec(&rate,&format,&channels))return false;
  SDL_AudioCVT cvt{};
  int result=SDL_BuildAudioCVT(&cvt,w.bits==8?AUDIO_U8:AUDIO_S16LSB,w.channels,w.rate,format,channels,rate);
  if(result<0 || cvt.len_mult<1)return false;
  uint64_t reserve=uint64_t(w.bytes)*cvt.len_mult;
  uint64_t output=(uint64_t(w.bytes)/(w.channels*(w.bits/8))*rate+w.rate-1)/w.rate;
  output=(output+64)*channels*(SDL_AUDIO_BITSIZE(format)/8);
  if(reserve>SIZE_MAX || output>SIZE_MAX)return false;
  converted=static_cast<size_t>(std::max<uint64_t>(reserve,output));
  scratch=static_cast<size_t>(reserve)+w.bytes+65536;
  return true;
}
#endif
'''),
        ('  if (iDataLength < sizeof(uint32_t)',
         r'''#ifdef CORSIXTH_3DS
  // Device callers must supply a file path; never allocate an archive copy.
  (void)pData; (void)iDataLength; return false;
#endif
  if (iDataLength < sizeof(uint32_t)'''),
        ('  sound_dat_sound_info pFile = sound_files[iIndex];',
         r'''  sound_dat_sound_info pFile = sound_files[iIndex];
#ifdef CORSIXTH_3DS
  if (!pFile.length) return nullptr;
  return open_slice(file_path, pFile.position, pFile.length);
#endif'''),
        ('sound_player::~sound_player() {', '''sound_player::~sound_player() {
#ifdef CORSIXTH_3DS
  Mix_ChannelFinished(nullptr); // synchronizes with mixer callbacks before destruction
#endif'''),
        ('  pThis->release_channel(iChannel);',
         r'''#ifdef CORSIXTH_3DS
  if (iChannel>=0 && iChannel<number_of_channels)
    pThis->finished[iChannel].store(true,std::memory_order_release);
#else
  pThis->release_channel(iChannel);
#endif'''),
        ('void sound_player::populate_from(sound_archive* pArchive) {',
         r'''void sound_player::populate_from(sound_archive* pArchive) {
#ifdef CORSIXTH_3DS
  Mix_HaltChannel(-1); // synchronous: no callback can access the freed bank
  for(int c=0;c<number_of_channels;++c) {finished[c].store(false);release_channel(c);}
  archive=pArchive;cache_bytes=0;used_at.clear();
#endif'''),
        ('  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];',
         r'''#ifdef CORSIXTH_3DS
  sound_count=pArchive->get_number_of_sounds();
  sounds=new Mix_Chunk*[sound_count]();used_at.resize(sound_count);allocated_bytes.resize(sound_count);
  cth3ds::report_memory_checkpoint("sound_cache","metadata-only",nullptr,pArchive->metadata_bytes()+sound_count*(sizeof(Mix_Chunk*)+sizeof(uint64_t)+sizeof(size_t)),0);
  return;
#endif
  sounds = new Mix_Chunk*[pArchive->get_number_of_sounds()];'''),
        ('iIndex >= sound_count || !sounds[iIndex]',
         'iIndex >= sound_count'),
        (r'''  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {''',
         r'''#ifdef CORSIXTH_3DS
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);
  for (size_t i = 0; i < channels.size(); ++i) {'''),
        ('  channels[iChannel] = null_handle;',
         r'''  if(iChannel<0 || iChannel>=number_of_channels)return;
  channels[iChannel] = null_handle;
#ifdef CORSIXTH_3DS
  channel_sound[iChannel]=SIZE_MAX;
#endif'''),
        ('  int iChannel = reserve_channel();',
         r'''#ifdef CORSIXTH_3DS
  if (!ensure_sound(iIndex)) {
    cth3ds::report_allocation_failure("sound",archive ? archive->get_sound_name(iIndex) : "no-archive",0,"mixer",SDL_GetError());
    cth3ds::report_fatal(SDL_GetError());
    return null_handle;
  }
#endif
  int iChannel = reserve_channel();'''),
        (r'''  Mix_Volume(iChannel, iVolume);
  Mix_PlayChannel(iChannel, sounds[iIndex], loops);''',
         r'''#ifdef CORSIXTH_3DS
  finished[iChannel].store(false,std::memory_order_release);
  channel_sound[iChannel]=iIndex;
#endif
  Mix_Volume(iChannel, iVolume);
  if (Mix_PlayChannel(iChannel, sounds[iIndex], loops)<0) {
    release_channel(iChannel);return null_handle;
  }'''),
        (r'''  std::scoped_lock lock(channel_mutex);

  if (handle == null_handle)''',
         r'''#ifdef CORSIXTH_3DS
  drain_finished();
#endif
  std::scoped_lock lock(channel_mutex);

  if (handle == null_handle)'''),
        ('sound_player* sound_player::singleton = nullptr;',
         r'''#ifdef CORSIXTH_3DS
void sound_player::drain_finished() {
  for (int i=0;i<number_of_channels;++i) {
    if (finished[i].exchange(false,std::memory_order_acquire)) {
      // Completion is delivered while the mixer lock is held. Mix_Playing
      // acquires that lock before a channel can be reused on this thread.
      if (!Mix_Playing(i)) release_channel(i);
    }
  }
}
bool sound_player::ensure_sound(size_t index) {
  drain_finished();
  if(index>=sound_count || !archive)return false;
  if(sounds[index]) {used_at[index]=++cache_clock;return true;}
  size_t pcm=0,scratch=0;
  if(!archive->pcm_requirement(index,pcm,scratch)) {SDL_SetError("invalid required sound slice/WAV/mixer");return false;}
  constexpr size_t limit=3*1024*1024;
  size_t metadata=archive->metadata_bytes()+sound_count*(sizeof(Mix_Chunk*)+sizeof(uint64_t)+sizeof(size_t))+sizeof(*this);
  if(pcm+sizeof(Mix_Chunk)>limit || metadata>limit-pcm-sizeof(Mix_Chunk)) {SDL_SetError("required sound exceeds 3MiB PCM+metadata");return false;}
  while(cache_bytes+metadata+pcm+sizeof(Mix_Chunk)>limit) {
    size_t victim=sound_count;uint64_t oldest=UINT64_MAX;
    for(size_t j=0;j<sound_count;++j) {
      bool pinned=false;for(int c=0;c<number_of_channels;++c)if(channels[c]!=null_handle&&channel_sound[c]==j)pinned=true;
      if(sounds[j]&&!pinned&&used_at[j]<oldest){oldest=used_at[j];victim=j;}
    }
    if(victim==sound_count){SDL_SetError("audio cache pinned: required clip rejected");return false;}
    cache_bytes-=allocated_bytes[victim]+sizeof(Mix_Chunk);Mix_FreeChunk(sounds[victim]);sounds[victim]=nullptr;
  }
  // Actual conversion scratch plus operation reserve must coexist with cache.
  if(!cth3ds::runtime_audio_reserve(scratch+pcm+sizeof(Mix_Chunk),archive->get_sound_name(index)))return false;
  cth3ds::report_memory_checkpoint("sound_decode","begin",archive->get_sound_name(index),cache_bytes+metadata,scratch+pcm);
  SDL_RWops* rw=archive->load_sound(index);if(!rw)return false;
  Mix_Chunk* chunk=Mix_LoadWAV_RW(rw,1);if(!chunk)return false;
  if(chunk->alen>pcm || cache_bytes+metadata+chunk->alen+sizeof(Mix_Chunk)>limit){Mix_FreeChunk(chunk);SDL_SetError("mixer output exceeded preflight");return false;}
  sounds[index]=chunk;allocated_bytes[index]=pcm;cache_bytes+=pcm+sizeof(Mix_Chunk);used_at[index]=++cache_clock;
  Mix_VolumeChunk(chunk,MIX_MAX_VOLUME);
  cth3ds::report_memory_checkpoint("sound_decode","complete",archive->get_sound_name(index),cache_bytes+metadata,0);
  return true;
}
#endif

sound_player* sound_player::singleton = nullptr;'''),
    ])
    patch('CorsixTH/Src/th_lua_sound.cpp', [
        ('int l_soundarc_count(lua_State* L) {',
         r'''#ifdef CORSIXTH_3DS
int l_soundarc_load_file(lua_State* L) {
  sound_archive* archive=luaT_testuserdata<sound_archive>(L);
  lua_pushboolean(L,archive->load_from_file(luaL_checkstring(L,2)));
  return 1;
}
#endif
int l_soundarc_count(lua_State* L) {'''),
        ('    lcb.add_function(l_soundarc_load, "load");',
         r'''    lcb.add_function(l_soundarc_load, "load");
#ifdef CORSIXTH_3DS
    lcb.add_function(l_soundarc_load_file, "loadFromFile");
#endif'''),
    ])
    patch('CorsixTH/Lua/audio.lua', [
        (r'''    self.not_loaded = true
    self.has_bg_music = false''',
         r'''    if IS_3DS then error("audio initialize: " .. tostring(err)) end
    self.not_loaded = true
    self.has_bg_music = false'''),
        (r'''function Audio:initSpeech(speech_file)
''',
         r'''function Audio:initSpeech(speech_file)
  if IS_3DS then
    speech_file=speech_file or "Sound-0.dat"
    if self.speech_file_name==speech_file then return true end
    assert(not self.not_loaded,"audio device unavailable")
    assert(not self.app.fs.provider,"loose sound requires physical files")
    local path,err=self.app.fs:_getFilePath("Sound"..pathsep.."Data"..pathsep..speech_file)
    assert(path,"sound path: "..tostring(err))
    local archive=TH.soundArchive()
    assert(archive:loadFromFile(path),"sound index invalid: "..path)
    if self.sound_fx then self.sound_fx:setSoundArchive(archive) else
      self.sound_fx=TH.soundEffects()
      self.sound_fx:setSoundArchive(archive)
    end
    self.sound_archive=archive
    self.speech_file_name=speech_file
    self:setSoundStage()
    return true
  end
'''),
    ])
    patch('CorsixTH/Lua/config_finder.lua', [
        ('    language = [[English]],',
         r'''    asset_mode = [[loose]],
    language = [[English]],'''),
        ("param(config_values, 'language')",
         "param(config_values, 'asset_mode') .. param(config_values, 'language')"),
    ])
    patch('CorsixTH/Lua/app.lua', [
        (r'''    -- CORSIXTH_3DS_BEGIN: platform-attach
    if IS_3DS then
      self.is_3ds = true
      self._3ds = require("3ds.platform").attach(self, TH3DS)
    end
    -- CORSIXTH_3DS_END: platform-attach
''',
         ''),
        ('    self.config.width = 640',
         r'''    self.config.asset_mode=self.config.asset_mode or "loose"
    assert(self.config.asset_mode=="loose", "Player entry requires loose; th3ds is an unsupported resource experiment")
    self.config.language="English"
    self.config.use_new_graphics=false
    self.config.audio_frequency=22050
    self.config.audio_channels=2
    self.config.width = 640'''),
        ('  self.good_install_folder = good_install_folder',
         r'''  if IS_3DS then assert(good_install_folder,"game filesystem prerequisites failed") end
  self.good_install_folder = good_install_folder'''),
        ('  self:initSavegameDir()',
         r'''  local saves_ok=self:initSavegameDir()
  if IS_3DS then assert(saves_ok,"save directory initialization failed") end'''),
        ('  th3ds_stage("S35", "VIDEO READY")',
         r'''  th3ds_stage("S35", "VIDEO READY")
  if IS_3DS then
    local ok,caps=TH3DS.initialize(self.config.asset_mode)
    assert(ok==true,tostring(caps))
    self._3ds_capabilities=caps
  end'''),
        ('  local language_load_success, language_error = self:initLanguage()',
         r'''  local language_load_success, language_error = self:initLanguage()
  if IS_3DS then assert(language_load_success,language_error) end'''),
        (r'''    self:loadMainMenu()
    self.audio:playRandomBackgroundTrack()''',
         r'''    self:loadMainMenu()
    -- CORSIXTH_3DS_BEGIN: platform-attach
    if IS_3DS then
      local module=TH3DS.adapter_module()
      module.attach(self,TH3DS,self._3ds_capabilities)
      self.is_3ds=true
      assert(TH3DS.mark_ready())
    end
    -- CORSIXTH_3DS_END: platform-attach
    self.audio:playRandomBackgroundTrack()'''),
        ('  if IS_3DS and not TH3DS.probe_regular_heap("LEVEL READY") then',
         '  if IS_3DS and not TH3DS.probe_regular_heap("LEVEL READY", "level") then'),
        ('    error("E-HEAP-PROBE: level has less than 2 MiB contiguous heap")',
         '    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")'),
        ('  th3ds_stage("S120", "LEVEL READY")',
         '  th3ds_stage("S120", "LEVEL VALIDATING")'),
        ('  return SaveGameFile(self.savegame_dir .. filename)',
         '  return self:save(self.savegame_dir .. filename)'),
        (r'''  if self.world then
    self:worldExited()
  end
  return LoadGameFile(filepath)''',
         r'''  if not IS_3DS and self.world then self:worldExited() end
  return LoadGameFile(filepath)'''),
        (r'''      local status, err = pcall(self.load, self, self.savegame_dir .. self.command_line.load)
      if not status then''',
         r'''      local status, accepted, err = pcall(self.load, self, self.savegame_dir .. self.command_line.load)
      if not status or accepted ~= true then
        err = tostring(err or accepted)'''),
        (r'''function App:reset()
''',
         r'''function App:reset()
  if IS_3DS and self.world then
    local ok,result=pcall(self.save,self,self.savegame_dir.."recovery-before-reset.sav")
    if not ok or result~=true then return false,result end
  end
'''),
        ('  tracy.Message("Loading level: " .. (level_name or level or "map editor"))',
         r'''  if IS_3DS and err ~= true then status=false;err=err or "map loader rejected level" end
  tracy.Message("Loading level: " .. (level_name or level or "map editor"))'''),
        (r'''    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")
  end
end''',
         r'''    error("E-HEAP-PROBE: LevelStable policy failed; see requested probe and reserve in boot.log")
  end
  th3ds_stage("S120", "LEVEL READY")
  return true
end'''),
    ])
    patch('CorsixTH/Lua/persistance.lua', [
        (r'''  local result, err, obj = persist.dump(state, MakePermanentObjectsTable(false))
  state.map:afterSave()''',
         r'''  local dumped, result, err, obj = pcall(function()
    return persist.dump(state, MakePermanentObjectsTable(false))
  end)
  local cleaned, cleanup_error = pcall(state.map.afterSave,state.map)
  if not dumped then error("save dump: "..tostring(result)) end
  if not cleaned then error("save afterSave: "..tostring(cleanup_error)) end'''),
        (r'''  local f = TheApp:writeToFileOrTmp(filename, "wb")
  f:write(data)
  f:close()''',
         r'''  local f,err
  if IS_3DS then f,err=io.open(filename,"wb") else f=TheApp:writeToFileOrTmp(filename,"wb") end
  assert(f,"save open: "..tostring(err))
  local wrote,result,write_error=pcall(f.write,f,data)
  local closed,close_result,close_error=pcall(f.close,f)
  if not wrote or not result then error("save write: "..tostring(write_error or result)) end
  if not closed or not close_result then error("save close: "..tostring(close_error or close_result)) end
  return true'''),
        (r'''function LoadGame(data)
''',
         r'''local function decodeGame(data)
'''),
        (r'''  if not TheApp:checkCompatibility(state.world.savegame_version, state.world.gfx_set) then return end
  state.ui:resync(TheApp.ui)''',
         r'''  if not TheApp:checkCompatibility(state.world.savegame_version, state.world.gfx_set) then
    return false,"incompatible savegame"
  end
  return state
end

local function publishGame(state)
  state.ui:resync(TheApp.ui)
  if TheApp.world then TheApp:worldExited() end'''),
        (r'''  TheApp.world:updateScreenBlueFilter()
end''',
         r'''  TheApp.world:updateScreenBlueFilter()
  return true
end

local function checkedPublish(state)
  local ok,result=pcall(publishGame,state)
  if ok and result==true then return true end
  local detail="load publication/afterLoad failed: "..tostring(result).."; prior progress: recovery-before-load.sav"
  local menu_ok=pcall(TheApp.loadMainMenu,TheApp)
  if not menu_ok then
    if IS_3DS then TH3DS.shutdown() end
    error("fatal recovery: "..detail)
  end
  return false,detail
end

function LoadGame(data)
  local ok,state,err=pcall(decodeGame,data)
  if not ok then return false,tostring(state) end
  if not state then return false,err end
  return checkedPublish(state)
end'''),
        (r'''  local f = assert(io.open(filename, "rb"))
  local data = f:read("*a")
  f:close()
  LoadGame(data)''',
         r'''  local failures={}
  -- Validate committed final then backup. Never promote an uncommitted tmp.
  local paths=IS_3DS and {filename,filename..".bak"} or {filename}
  for _,path in ipairs(paths) do
    local f,err=io.open(path,"rb")
    if f then
      local read_ok,data=pcall(f.read,f,"*a")
      local close_ok,closed=pcall(f.close,f)
      if read_ok and data and close_ok and closed then
        local decoded,state,reason=pcall(decodeGame,data)
        if decoded and state then return checkedPublish(state) end
        err=decoded and reason or state
      else err="save read/close failed" end
    end
    failures[#failures+1]=path..": "..tostring(err)
  end
  return false,table.concat(failures,"; ")'''),
    ])
    patch('CorsixTH/Lua/game_ui.lua', [
        ('  local msg = mapeditor and _S.confirmation.quit_mapeditor or _S.confirmation.quit',
         '  local msg = IS_3DS and "Save and exit?" or (mapeditor and _S.confirmation.quit_mapeditor or _S.confirmation.quit)'),
        (r'''    self.app:loadMainMenu()
    -- Release the mouse regardless of setting''',
         r'''    if IS_3DS then return self.app._3ds:saveAndExit() end
    self.app:loadMainMenu()
    -- Release the mouse regardless of setting'''),
    ])
    patch('CorsixTH/Src/sdl_core.cpp', [
        (r'''  if (!cth3ds::runtime_initialize(L)) {
    std::fprintf(stderr, "CorsixTH 3DS: platform runtime initialization failed\n");
  }''',
         r'''  if (!cth3ds::runtime_assert_ready(L)) {
    cth3ds::runtime_shutdown(L);
    cth3ds::report_fatal("CorsixTH 3DS: mainloop requires completed ready state");
    return;
  }'''),
    ])
    patch('CorsixTH/SrcUnshared/main.cpp', [
        ('    // CORSIXTH_3DS_END: init-failure-guard',
         r'''#ifdef CORSIXTH_3DS
    cth3ds::runtime_shutdown(L.get());
#endif
    // CORSIXTH_3DS_END: init-failure-guard'''),
    ])
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
    if app_text.count(APP_ATTACH_MARKER) != 1:
        errors.append("platform adapter must attach once after the real main menu")
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
        changes.extend(patch_product_sources(root, args.dry_run))
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
