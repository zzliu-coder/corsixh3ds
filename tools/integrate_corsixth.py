#!/usr/bin/env python3
"""Inject the CorsixTH 3DS overlay into a pinned CorsixTH 0.70.1 checkout.

The operation is deterministic and idempotent. It copies the platform sources,
adds guarded build hooks, registers the native Lua module, and loads the 3DS
Lua adapter. Original Theme Hospital data is never copied by this command."""

from __future__ import annotations

from dual_screen_canvas import patch_dual_screen, check_dual_screen
from handheld_ui import patch_handheld_ui, check_handheld_ui
from load_recovery import patch_load_recovery, check_load_recovery
from pathlib import Path
from sound_callbacks import patch_sound_callbacks, check_sound_callbacks
from sound_lifetime import (sound_transaction, patch_sound_lifetime,
                            check_sound_lifetime, SoundPatchError)
from sprite_residency import patch_sprite_residency, check_sprite_residency
from typing import Iterable, Sequence
import argparse
import json
import sys
from integration.common import (
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
    IntegrationError,
    MAIN_INCLUDE_MARKER,
    MAIN_INIT_GUARD_MARKER,
    MAIN_REGISTER_MARKER,
    OVERLAY_VERSION,
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
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    append_block,
    read_text,
    replace_many,
    replace_once,
    sha256_file,
    write_text,
)
from integration.overlay import (
    copy_overlay,
    git_head,
    iter_overlay_files,
    manifest,
    refresh_embedded_adapter,
    validate_upstream,
)
from integration.source_patches import (
    patch_sources,
)
from integration.product_patches import (
    patch_product_sources,
)
from integration.sound_init import (
    SOUND_INIT_LEGACY,
    SOUND_INIT_MARKER,
    SOUND_INIT_R41_TRANSACTION,
    SOUND_INIT_TRANSACTION,
    patch_sound_initialization,
)
from integration.clock import (
    SIMULATION_CLOCK_SITES,
    patch_simulation_clock,
)
from integration.observations import (
    patch_u3_observations,
)
from integration.validation import (
    check_integrated,
)
from integration.render_fast import patch_render_fast
from integration.render_gpu import patch_render_gpu
from integration.cpu_hotspots import patch_cpu_hotspots


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
            changes.extend(patch_sound_initialization(root))
            changes.extend(Change(path, "sound-lifetime") for path in
                           patch_sound_lifetime(root, SOUND_INIT_R41_TRANSACTION))
            changes.extend(Change(path, "load-recovery") for path in
                           patch_load_recovery(root))
        changes.extend(patch_u3_observations(root, args.dry_run))
        if not args.dry_run:
            changes.extend(patch_simulation_clock(root))
            changes.extend(Change(path, "sound-callbacks") for path in
                           patch_sound_callbacks(root))
            changes.extend(Change(path, "sprite-residency") for path in
                           patch_sprite_residency(root))
            changes.extend(Change(path, "dual-screen-canvas") for path in
                           patch_dual_screen(root))
            changes.extend(Change(path, "handheld-ui") for path in patch_handheld_ui(root))
            changes.extend(Change(path, "render-fast") for path in patch_render_fast(root))
            changes.extend(Change(path, "render-gpu") for path in patch_render_gpu(root))
            changes.extend(Change(path, "cpu-hotspots") for path in patch_cpu_hotspots(root))
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
    except (IntegrationError, SoundPatchError, ValueError, OSError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
