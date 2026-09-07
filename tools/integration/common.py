"""Pinned identity, patch markers and exact atomic text operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


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
