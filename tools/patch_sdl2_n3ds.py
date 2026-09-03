#!/usr/bin/env python3
"""Patch SDL2's Nintendo 3DS software framebuffer for aspect-fit scaling.

CorsixTH renders its desktop UI at a 640x480 logical resolution. SDL2's N3DS
backend normally copies/crops the surface into the physical framebuffer. This
patch adds deterministic nearest-neighbour letterboxing, so 640x480 becomes a
320x240 viewport centered on the 400x240 top screen while a 320x240 lower
window remains pixel-for-pixel.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SDL2_COMMIT = "5882a4f13d3bf374d2345280c679173f4ff324da"
SDL2_FILE_BLOB = "591c5859bd8be05e18df47a93419f7dff7d3d791"
RELATIVE_PATH = Path("src/video/n3ds/SDL_n3dsframebuffer.c")
MARKER = "/* CORSIXTH_3DS_LETTERBOX_BEGIN */"
END_MARKER = "/* CORSIXTH_3DS_LETTERBOX_END */"
HINT_INCLUDE = '#include "SDL_hints.h"'
INCLUDE_ANCHOR = '#include "../../SDL_internal.h"\n'
START_ANCHOR = "SDL_FORCE_INLINE void\nCopyFramebuffertoN3DS_16("
END_ANCHOR = "SDL_FORCE_INLINE int\nGetDestOffset("

PATCHED_BLOCK = r'''/* CORSIXTH_3DS_LETTERBOX_BEGIN */
/*
 * CorsixTH Old-3DS present path.
 *
 * Upstream copies the window surface into the LCD framebuffer one pixel at a
 * time, iterating in source order.  The framebuffer is column major, so every
 * store lands in a different cache line, and the earlier CorsixTH letterbox
 * patch additionally performed a 64-bit multiply and divide per pixel.  The
 * ARM11 in an Old 3DS has no hardware divider, so a single 400x240 present
 * cost roughly 25 ms before a single game pixel had been drawn.
 *
 * This version:
 *   - precomputes the nearest-neighbour sampling grid with integer stepping
 *     (see cth3ds::build_nearest_axis_table, which the host tests cover),
 *   - walks the destination in memory order (one framebuffer column at a
 *     time) so stores stay sequential,
 *   - only paints the letterbox bars instead of clearing the whole screen.
 *
 * The sampling grid is identical to the reference implementation in
 * src/common/framebuffer_scaler.cpp: source = floor(dest * span / viewport).
 */

#define CTH3DS_MAX_AXIS 512

typedef struct
{
    int x, y, width, height;
} CTH3DS_LetterboxViewport;

SDL_FORCE_INLINE CTH3DS_LetterboxViewport
CTH3DS_CalculateLetterbox(const Dimensions source_dim, const Dimensions dest_dim)
{
    /* The framebuffer is stored rotated: dest_dim.width is the screen height
       and dest_dim.height is the screen width. */
    const int logical_dest_width = dest_dim.height;
    const int logical_dest_height = dest_dim.width;
    CTH3DS_LetterboxViewport viewport = { 0, 0, logical_dest_width, logical_dest_height };

    viewport.height = (int)(((Sint64)source_dim.height * logical_dest_width) / source_dim.width);
    if (viewport.height > logical_dest_height) {
        viewport.height = logical_dest_height;
        viewport.width = (int)(((Sint64)source_dim.width * logical_dest_height) / source_dim.height);
    }
    viewport.width = SDL_max(1, SDL_min(viewport.width, logical_dest_width));
    viewport.height = SDL_max(1, SDL_min(viewport.height, logical_dest_height));
    viewport.x = (logical_dest_width - viewport.width) / 2;
    viewport.y = (logical_dest_height - viewport.height) / 2;
    return viewport;
}

/* source = floor(dest * source_span / viewport_span), without any division in
   the loop.  Returns SDL_FALSE when the span does not fit the fixed tables. */
SDL_FORCE_INLINE SDL_bool
CTH3DS_BuildAxisTable(int source_span, int viewport_span, int *table)
{
    int source = 0;
    int remainder = 0;
    int destination;

    if (source_span <= 0 || viewport_span <= 0 || viewport_span > CTH3DS_MAX_AXIS) {
        return SDL_FALSE;
    }
    for (destination = 0; destination < viewport_span; ++destination) {
        table[destination] = source;
        remainder += source_span;
        while (remainder >= viewport_span) {
            remainder -= viewport_span;
            ++source;
        }
    }
    return SDL_TRUE;
}

/* Present mode.
 *
 * "crop"  : take a 1:1 centre crop of the source. The CorsixTH frame is
 *           640x480 and the top screen is 400x240, so every pixel shown is a
 *           real source pixel and the hospital stays sharp. The lower screen
 *           carries the complete frame, so nothing is lost.
 * "fit"   : the previous behaviour, aspect-preserving nearest-neighbour with
 *           letterbox bars. Kept so a device can fall back without a rebuild.
 *
 * Selected by the CTH3DS_SCREEN_MODE hint; crop is the default.
 */
SDL_FORCE_INLINE SDL_bool
CTH3DS_UseCropMode(void)
{
    const char *mode = SDL_GetHint("CTH3DS_SCREEN_MODE");
    if (mode && SDL_strcmp(mode, "fit") == 0) {
        return SDL_FALSE;
    }
    return SDL_TRUE;
}

typedef struct
{
    int dest_x, dest_y;     /* top-left of the copied block, screen space   */
    int source_x, source_y; /* first source pixel copied                    */
    int width, height;      /* size of the copied block                     */
} CTH3DS_CropView;

SDL_FORCE_INLINE CTH3DS_CropView
CTH3DS_CalculateCrop(const Dimensions source_dim, const Dimensions dest_dim)
{
    const int logical_dest_width = dest_dim.height;
    const int logical_dest_height = dest_dim.width;
    CTH3DS_CropView view;
    view.width = SDL_min(source_dim.width, logical_dest_width);
    view.height = SDL_min(source_dim.height, logical_dest_height);
    view.dest_x = (logical_dest_width - view.width) / 2;
    view.dest_y = (logical_dest_height - view.height) / 2;
    view.source_x = (source_dim.width - view.width) / 2;
    view.source_y = (source_dim.height - view.height) / 2;
    return view;
}

/* 1:1 copy, walking the destination in memory order like the scaled path. */
#define CTH3DS_CROP_BODY(PIXEL, STORE_SRC, STORE_BLACK)                                 \
    do {                                                                                \
        const int fb_stride = dest_dim.width;                                           \
        const int logical_width = dest_dim.height;                                      \
        const int logical_height = dest_dim.width;                                      \
        const CTH3DS_CropView vp = CTH3DS_CalculateCrop(source_dim, dest_dim);          \
        int x, y;                                                                       \
                                                                                        \
        for (x = 0; x < logical_width; ++x) {                                           \
            PIXEL *column = dest + (size_t)fb_stride * (size_t)x + (size_t)(fb_stride - 1); \
            if (x < vp.dest_x || x >= vp.dest_x + vp.width) {                           \
                for (y = 0; y < logical_height; ++y, --column) {                        \
                    STORE_BLACK;                                                        \
                }                                                                       \
            } else {                                                                    \
                const int source_x = vp.source_x + (x - vp.dest_x);                     \
                for (y = 0; y < vp.dest_y; ++y, --column) {                             \
                    STORE_BLACK;                                                        \
                }                                                                       \
                for (y = 0; y < vp.height; ++y, --column) {                             \
                    const PIXEL *s = source +                                           \
                        (size_t)(vp.source_y + y) * (size_t)source_dim.width +          \
                        (size_t)source_x;                                               \
                    STORE_SRC;                                                          \
                }                                                                       \
                for (y = vp.dest_y + vp.height; y < logical_height; ++y, --column) {    \
                    STORE_BLACK;                                                        \
                }                                                                       \
            }                                                                           \
        }                                                                               \
    } while (0)

/* One macro body shared by the three pixel sizes.  PIXEL is the storage type,
   STORE writes a single pixel and BLACK writes a background pixel. */
#define CTH3DS_LETTERBOX_BODY(PIXEL, STORE_SRC, STORE_BLACK)                            \
    do {                                                                                \
        const int fb_stride = dest_dim.width;                                           \
        const int logical_width = dest_dim.height;                                      \
        const int logical_height = dest_dim.width;                                      \
        const CTH3DS_LetterboxViewport vp = CTH3DS_CalculateLetterbox(source_dim, dest_dim); \
        int columns[CTH3DS_MAX_AXIS];                                                   \
        int row_offsets[CTH3DS_MAX_AXIS];                                               \
        int x, y;                                                                       \
                                                                                        \
        if (!CTH3DS_BuildAxisTable(source_dim.width, vp.width, columns) ||               \
            !CTH3DS_BuildAxisTable(source_dim.height, vp.height, row_offsets)) {         \
            return;                                                                     \
        }                                                                               \
        for (y = 0; y < vp.height; ++y) {                                               \
            row_offsets[y] *= source_dim.width;                                         \
        }                                                                               \
                                                                                        \
        for (x = 0; x < logical_width; ++x) {                                           \
            /* Within one framebuffer column, increasing y walks backwards, so          \
               start at the last element and decrement.  Stores stay contiguous. */     \
            PIXEL *column = dest + (size_t)fb_stride * (size_t)x + (size_t)(fb_stride - 1); \
            if (x < vp.x || x >= vp.x + vp.width) {                                     \
                for (y = 0; y < logical_height; ++y, --column) {                        \
                    STORE_BLACK;                                                        \
                }                                                                       \
            } else {                                                                    \
                const int source_x = columns[x - vp.x];                                 \
                for (y = 0; y < vp.y; ++y, --column) {                                  \
                    STORE_BLACK;                                                        \
                }                                                                       \
                for (y = 0; y < vp.height; ++y, --column) {                             \
                    const PIXEL *s = source + (size_t)(row_offsets[y] + source_x);       \
                    STORE_SRC;                                                          \
                }                                                                       \
                for (y = vp.y + vp.height; y < logical_height; ++y, --column) {          \
                    STORE_BLACK;                                                        \
                }                                                                       \
            }                                                                           \
        }                                                                               \
    } while (0)

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_16(u16 *dest, const Dimensions dest_dim, const u16 *source, const Dimensions source_dim)
{
    if (CTH3DS_UseCropMode()) {
        CTH3DS_CROP_BODY(u16, *column = *s, *column = 0);
        return;
    }
    CTH3DS_LETTERBOX_BODY(u16, *column = *s, *column = 0);
}

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_24(u8 *dest, const Dimensions dest_dim, const u8 *source, const Dimensions source_dim)
{
    /* Three bytes per pixel: index arithmetic is done in pixels and scaled on
       access, so the shared body stays identical for all formats. */
    const int fb_stride = dest_dim.width;
    const int logical_width = dest_dim.height;
    const int logical_height = dest_dim.width;
    const CTH3DS_LetterboxViewport vp = CTH3DS_CalculateLetterbox(source_dim, dest_dim);
    int columns[CTH3DS_MAX_AXIS];
    int row_offsets[CTH3DS_MAX_AXIS];
    int x, y;

    if (!CTH3DS_BuildAxisTable(source_dim.width, vp.width, columns) ||
        !CTH3DS_BuildAxisTable(source_dim.height, vp.height, row_offsets)) {
        return;
    }
    for (y = 0; y < vp.height; ++y) {
        row_offsets[y] *= source_dim.width;
    }

    if (CTH3DS_UseCropMode()) {
        const CTH3DS_CropView cv = CTH3DS_CalculateCrop(source_dim, dest_dim);
        for (x = 0; x < logical_width; ++x) {
            u8 *column = dest + ((size_t)fb_stride * (size_t)x + (size_t)(fb_stride - 1)) * 3;
            if (x < cv.dest_x || x >= cv.dest_x + cv.width) {
                for (y = 0; y < logical_height; ++y, column -= 3) {
                    column[0] = 0; column[1] = 0; column[2] = 0;
                }
            } else {
                const int source_x = cv.source_x + (x - cv.dest_x);
                for (y = 0; y < cv.dest_y; ++y, column -= 3) {
                    column[0] = 0; column[1] = 0; column[2] = 0;
                }
                for (y = 0; y < cv.height; ++y, column -= 3) {
                    const u8 *s = source +
                        ((size_t)(cv.source_y + y) * (size_t)source_dim.width +
                         (size_t)source_x) * 3;
                    column[0] = s[0]; column[1] = s[1]; column[2] = s[2];
                }
                for (y = cv.dest_y + cv.height; y < logical_height; ++y, column -= 3) {
                    column[0] = 0; column[1] = 0; column[2] = 0;
                }
            }
        }
        return;
    }

    for (x = 0; x < logical_width; ++x) {
        u8 *column = dest + ((size_t)fb_stride * (size_t)x + (size_t)(fb_stride - 1)) * 3;
        if (x < vp.x || x >= vp.x + vp.width) {
            for (y = 0; y < logical_height; ++y, column -= 3) {
                column[0] = 0; column[1] = 0; column[2] = 0;
            }
        } else {
            const int source_x = columns[x - vp.x];
            for (y = 0; y < vp.y; ++y, column -= 3) {
                column[0] = 0; column[1] = 0; column[2] = 0;
            }
            for (y = 0; y < vp.height; ++y, column -= 3) {
                const u8 *s = source + (size_t)(row_offsets[y] + source_x) * 3;
                column[0] = s[0]; column[1] = s[1]; column[2] = s[2];
            }
            for (y = vp.y + vp.height; y < logical_height; ++y, column -= 3) {
                column[0] = 0; column[1] = 0; column[2] = 0;
            }
        }
    }
}

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_32(u32 *dest, const Dimensions dest_dim, const u32 *source, const Dimensions source_dim)
{
    if (CTH3DS_UseCropMode()) {
        CTH3DS_CROP_BODY(u32, *column = *s, *column = 0xFF000000u);
        return;
    }
    CTH3DS_LETTERBOX_BODY(u32, *column = *s, *column = 0xFF000000u);
}
/* CORSIXTH_3DS_LETTERBOX_END */

'''


class PatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PatchResult:
    changed: bool
    path: str
    commit: str | None


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


def validate_tree(root: Path, allow_unverified: bool) -> tuple[Path, str | None]:
    source = root / RELATIVE_PATH
    if not source.is_file():
        raise PatchError(f"SDL2 N3DS source not found: {source}")
    head = git_head(root)
    if head is not None and head != SDL2_COMMIT and not allow_unverified:
        raise PatchError(
            f"SDL2 commit is {head}; expected pinned {SDL2_COMMIT}. "
            "Pass --allow-unverified only for a deliberately maintained compatible fork."
        )
    text = source.read_text(encoding="utf-8")
    if MARKER not in text and (START_ANCHOR not in text or END_ANCHOR not in text):
        raise PatchError("SDL2 framebuffer anchors do not match the pinned SDL2 source")
    return source, head


def apply_patch_text(text: str) -> tuple[str, bool]:
    def add_hint_include(source: str) -> tuple[str, bool]:
        desired = f"{INCLUDE_ANCHOR}{HINT_INCLUDE}\n"
        if desired in source and source.count(HINT_INCLUDE) == 1:
            return source, False
        if INCLUDE_ANCHOR not in source:
            raise PatchError("cannot locate SDL2 internal include anchor")
        source = source.replace(f"{HINT_INCLUDE}\n", "")
        return source.replace(
            INCLUDE_ANCHOR, f"{INCLUDE_ANCHOR}{HINT_INCLUDE}\n", 1
        ), True

    if MARKER in text:
        if END_MARKER not in text or "CTH3DS_CalculateLetterbox" not in text:
            raise PatchError("partial or damaged CorsixTH 3DS SDL2 patch")
        return add_hint_include(text)
    text, _ = add_hint_include(text)
    start = text.find(START_ANCHOR)
    end = text.find(END_ANCHOR, start + 1)
    if start < 0 or end < 0 or end <= start:
        raise PatchError("cannot locate SDL2 N3DS framebuffer copy implementations")
    return text[:start] + PATCHED_BLOCK + text[end:], True


def check_patch_text(text: str) -> list[str]:
    errors: list[str] = []
    for token in (
        MARKER,
        END_MARKER,
        "CTH3DS_CalculateLetterbox",
        "CTH3DS_BuildAxisTable",
        "CTH3DS_LETTERBOX_BODY",
        "CTH3DS_CROP_BODY",
        "CTH3DS_UseCropMode",
        HINT_INCLUDE,
        "logical_dest_width = dest_dim.height",
        "logical_dest_height = dest_dim.width",
    ):
        if token not in text:
            errors.append(f"missing patch token: {token}")
    if text.count(MARKER) != 1 or text.count(END_MARKER) != 1:
        errors.append("letterbox patch markers must occur exactly once")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdl2", type=Path, help="SDL2 source checkout")
    parser.add_argument("--check", action="store_true", help="verify an already patched tree")
    parser.add_argument("--dry-run", action="store_true", help="validate without writing")
    parser.add_argument("--allow-unverified", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.sdl2.expanduser().resolve()
    try:
        source, head = validate_tree(root, args.allow_unverified)
        original = source.read_text(encoding="utf-8")
        if args.check:
            errors = check_patch_text(original)
            payload = {
                "ok": not errors,
                "mode": "check",
                "path": str(source),
                "commit": head,
                "errors": errors,
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif errors:
                for error in errors:
                    print(f"error: {error}", file=sys.stderr)
            else:
                print(f"SDL2 N3DS letterbox patch verified: {source}")
            return 0 if not errors else 2

        patched, changed = apply_patch_text(original)
        if changed and not args.dry_run:
            temporary = source.with_suffix(source.suffix + ".cth3ds.tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(patched)
            temporary.replace(source)
        payload = PatchResult(changed=changed, path=str(source), commit=head)
        if args.json:
            print(json.dumps(payload.__dict__, indent=2, sort_keys=True))
        else:
            verb = "Would patch" if args.dry_run and changed else ("Patched" if changed else "Already patched")
            print(f"{verb}: {source}")
        return 0
    except (OSError, PatchError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
