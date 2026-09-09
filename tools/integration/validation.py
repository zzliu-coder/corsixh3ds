"""Validate assembled upstream hooks and copied overlay contents."""

from __future__ import annotations

from dual_screen_canvas import patch_dual_screen, check_dual_screen
from handheld_ui import patch_handheld_ui, check_handheld_ui
from load_recovery import patch_load_recovery, check_load_recovery
from pathlib import Path
from sound_callbacks import patch_sound_callbacks, check_sound_callbacks
from sound_lifetime import (sound_transaction, patch_sound_lifetime,
                            check_sound_lifetime, SoundPatchError)
from sprite_residency import patch_sprite_residency, check_sprite_residency
from .render_fast import check_render_fast
from .render_gpu import check_render_gpu
from .cpu_hotspots import check_cpu_hotspots
from .media import check_media
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
    read_text,
    sha256_file,
)
from .overlay import (
    iter_overlay_files,
)
from .sound_init import (
    SOUND_INIT_R41_TRANSACTION,
    SOUND_INIT_TRANSACTION,
)
from .clock import (
    SIMULATION_CLOCK_SITES,
)


def check_integrated(root: Path, overlay: Path, profile: str = 'loose') -> list[str]:
    errors: list[str] = check_sound_lifetime(root, SOUND_INIT_R41_TRANSACTION)
    errors.extend(check_dual_screen(root))
    errors.extend(check_render_fast(root))
    errors.extend(check_render_gpu(root))
    errors.extend(check_cpu_hotspots(root, overlay))
    errors.extend(check_media(root))
    errors.extend(check_sound_callbacks(root))
    errors.extend(check_sprite_residency(root))
    errors.extend(check_handheld_ui(root))
    errors.extend(check_load_recovery(root))
    clock_source = read_text(root / "CorsixTH/Src/sdl_core.cpp")
    if any(clock_source.count(new) != 1 for _, new in SIMULATION_CLOCK_SITES):
        errors.append("simulation clock observation sites missing or changed")
    if SOUND_INIT_TRANSACTION not in read_text(root / "CorsixTH/Src/th_sound.cpp"):
        errors.append("sound initialization transaction missing or changed")
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
    from .build_profile import common_sources, cmake_contract
    selected = common_sources(overlay, profile)
    actual = {p.name for p in (root / "CorsixTH/Src/3ds/common").glob("*.cpp")}
    if actual != set(selected):
        errors.append("generated common sources differ from build profile")
    for source, relative in iter_overlay_files(overlay, profile):
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
        if cmake_contract(profile, selected) not in generated_text:
            errors.append("generated CMake build-profile contract differs")
        for required in ("liblfs.a", "liblpeg.a", "ctr_generate_smdh", "ctr_create_3dsx"):
            if required not in generated_text:
                errors.append(f"generated 3DS CMake is missing {required}")
    return errors
