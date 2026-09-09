"""Upstream identity, copied files, build configuration and provenance."""

from __future__ import annotations

from pathlib import Path
from .platform_sources import platform_files
from .build_profile import common_sources, cmake_contract, validate_profile
from typing import Iterable, Sequence
import shutil
import subprocess
import sys
from .common import (
    Change,
    IntegrationError,
    OVERLAY_VERSION,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    read_text,
    sha256_file,
    write_text,
)


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


def iter_overlay_files(overlay: Path, profile: str = 'loose', *, all_sources=False) -> Iterable[tuple[Path, Path]]:
    include_root = overlay / "include" / "cth3ds"
    for source in sorted(include_root.glob("*.hpp")):
        yield source, Path("CorsixTH/Src/3ds/include/cth3ds") / source.name
    for name in common_sources(overlay, profile, all_sources=all_sources):
        yield overlay / "src/common" / name, Path("CorsixTH/Src/3ds/common") / name
    sources, headers = platform_files(overlay / "src/3ds")
    for name in [*sources, *headers, "sources.cmake"]:
        source = overlay / "src" / "3ds" / name
        yield source, Path("CorsixTH/Src/3ds") / name
    # This directory is the authoritative set of shipped platform modules.
    # Enumerating it keeps newly required Lua dependencies in the assembly and
    # its provenance manifest without a second, manually maintained file list.
    for source in sorted((overlay / "lua" / "3ds").glob("*.lua")):
        yield source, Path("CorsixTH/Lua/3ds") / source.name
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


def copy_overlay(root: Path, overlay: Path, dry_run: bool, profile: str = 'loose') -> list[Change]:
    changes: list[Change] = []
    if not dry_run:
        refresh_embedded_adapter(overlay)
    for source, relative in iter_overlay_files(overlay, profile):
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

@COMMON_PROFILE_CONTRACT@

target_sources(CorsixTH_lib PRIVATE
  ${CTH3DS_COMMON_SOURCES})
include("${CTH3DS_PLATFORM_ROOT}/sources.cmake")
foreach(CTH3DS_PLATFORM_FILE IN LISTS CTH3DS_PLATFORM_SOURCES CTH3DS_PLATFORM_HEADERS)
  target_sources(CorsixTH_lib PRIVATE "${CTH3DS_PLATFORM_ROOT}/${CTH3DS_PLATFORM_FILE}")
endforeach()

target_include_directories(CorsixTH_lib PUBLIC
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
target_compile_definitions(CorsixTH_lib PUBLIC CORSIXTH_3DS_GPU=1)
# R51: retain size optimisation globally, favour speed at measured CPU sites.
# OFF provides the same-source -Oz comparison; never enable fast-math.
option(CORSIXTH_3DS_HOTSPOT_O2 "Optimise measured drawing/map hot paths for speed" ON)
if(CORSIXTH_3DS_HOTSPOT_O2)
  if(CMAKE_VERSION VERSION_LESS 3.18)
    message(FATAL_ERROR "3DS hotspot source scope requires CMake 3.18 or newer")
  endif()
  set_source_files_properties(
    "${CTH3DS_PLATFORM_ROOT}/../th_gfx_sdl.cpp"
    "${CTH3DS_PLATFORM_ROOT}/../th_map.cpp"
    "${CTH3DS_PLATFORM_ROOT}/../th_pathfind.cpp"
    "${CTH3DS_PLATFORM_ROOT}/../persist_lua.cpp"
    "${CTH3DS_PLATFORM_ROOT}/common/framebuffer_scaler.cpp"
    "${CTH3DS_PLATFORM_ROOT}/runtime/gpu_renderer.cpp"
    TARGET_DIRECTORY CorsixTH_lib
    PROPERTIES COMPILE_OPTIONS "-O2")
endif()
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
target_link_libraries(CorsixTH_lib PUBLIC citro2d citro3d ctru m PRIVATE cth3ds_lfs cth3ds_lpeg)

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
    generated_text = generated_text.replace("@COMMON_PROFILE_CONTRACT@", cmake_contract(profile, common_sources(overlay, profile)))
    if not generated.is_file() or read_text(generated) != generated_text:
        write_text(generated, generated_text, dry_run)
        changes.append(Change(generated.relative_to(root).as_posix(), "generate"))
    return changes


def manifest(root: Path, overlay: Path, provenance: str, profile: str = 'loose') -> dict[str, object]:
    files = []
    for source, relative in iter_overlay_files(overlay, profile):
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
        "build_profile": validate_profile(profile),
        "files": files,
    }
