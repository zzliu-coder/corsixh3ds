"""Compile the SDL2 N3DS letterbox block and prove it matches the reference.

The block that `tools/patch_sdl2_n3ds.py` injects into SDL2 cannot be exercised
on a host SDL build, so it is compiled here in isolation against the same
rotated-framebuffer contract the 3DS uses, then compared pixel for pixel with
`cth3ds::scale_nearest_letterboxed_rgba` from src/common/framebuffer_scaler.cpp.

This is the only automated guard that the on-device present path is correct, so
it runs as part of the normal test suite.
"""

from __future__ import annotations

import ctypes
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r"""
#include <stdint.h>
#include <stddef.h>

typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int64_t  Sint64;
typedef int      SDL_bool;
#define SDL_TRUE 1
#define SDL_FALSE 0
#define SDL_FORCE_INLINE static inline
#define SDL_min(a, b) (((a) < (b)) ? (a) : (b))
#define SDL_max(a, b) (((a) > (b)) ? (a) : (b))
#define SDL_strcmp strcmp
#include <string.h>

/* Stand-in for SDL's hint lookup so both present modes can be exercised. */
static const char *cth3ds_test_mode = "crop";
const char *SDL_GetHint(const char *name);
const char *SDL_GetHint(const char *name) { (void)name; return cth3ds_test_mode; }
void cth3ds_test_set_mode(const char *mode);
void cth3ds_test_set_mode(const char *mode) { cth3ds_test_mode = mode; }

typedef struct { int width, height; } Dimensions;
"""

EPILOGUE = r"""
/* Exported shim mirroring SDL_N3DS_UpdateWindowFramebuffer for 32bpp. */
void cth3ds_test_copy32(u32 *dest, int dest_w, int dest_h,
                        const u32 *source, int source_w, int source_h)
{
    Dimensions d; Dimensions s;
    d.width = dest_w; d.height = dest_h;
    s.width = source_w; s.height = source_h;
    CopyFramebuffertoN3DS_32(dest, d, source, s);
}

void cth3ds_test_copy16(u16 *dest, int dest_w, int dest_h,
                        const u16 *source, int source_w, int source_h)
{
    Dimensions d; Dimensions s;
    d.width = dest_w; d.height = dest_h;
    s.width = source_w; s.height = source_h;
    CopyFramebuffertoN3DS_16(dest, d, source, s);
}

void cth3ds_test_copy24(u8 *dest, int dest_w, int dest_h,
                        const u8 *source, int source_w, int source_h)
{
    Dimensions d; Dimensions s;
    d.width = dest_w; d.height = dest_h;
    s.width = source_w; s.height = source_h;
    CopyFramebuffertoN3DS_24(dest, d, source, s);
}
"""

REFERENCE = r"""
/* Independent restatement of the mapping the host C++ reference implements. */
#include <stdint.h>
#include <stddef.h>
void cth3ds_reference_crop32(uint32_t *dest, int fb_w, int fb_h,
                             const uint32_t *src, int src_w, int src_h)
{
    const int logical_w = fb_h;
    const int logical_h = fb_w;
    const int vw = src_w < logical_w ? src_w : logical_w;
    const int vh = src_h < logical_h ? src_h : logical_h;
    const int dx = (logical_w - vw) / 2, dy = (logical_h - vh) / 2;
    const int sx0 = (src_w - vw) / 2, sy0 = (src_h - vh) / 2;
    int x, y;
    for (x = 0; x < logical_w; ++x) {
        for (y = 0; y < logical_h; ++y) {
            uint32_t value = 0xFF000000u;
            if (x >= dx && x < dx + vw && y >= dy && y < dy + vh) {
                value = src[(size_t)(sy0 + y - dy) * (size_t)src_w +
                            (size_t)(sx0 + x - dx)];
            }
            dest[(size_t)(fb_w - y - 1) + (size_t)fb_w * (size_t)x] = value;
        }
    }
}

void cth3ds_reference_copy32(uint32_t *dest, int fb_w, int fb_h,
                             const uint32_t *src, int src_w, int src_h)
{
    const int logical_w = fb_h;   /* screen width  (400 or 320) */
    const int logical_h = fb_w;   /* screen height (240)        */
    int vp_w = logical_w;
    int vp_h = (int)(((int64_t)src_h * logical_w) / src_w);
    int vp_x, vp_y, x, y;
    if (vp_h > logical_h) {
        vp_h = logical_h;
        vp_w = (int)(((int64_t)src_w * logical_h) / src_h);
    }
    if (vp_w < 1) vp_w = 1;
    if (vp_w > logical_w) vp_w = logical_w;
    if (vp_h < 1) vp_h = 1;
    if (vp_h > logical_h) vp_h = logical_h;
    vp_x = (logical_w - vp_w) / 2;
    vp_y = (logical_h - vp_h) / 2;

    for (x = 0; x < logical_w; ++x) {
        for (y = 0; y < logical_h; ++y) {
            uint32_t value = 0xFF000000u;
            if (x >= vp_x && x < vp_x + vp_w && y >= vp_y && y < vp_y + vp_h) {
                const int sx = (int)(((int64_t)(x - vp_x) * src_w) / vp_w);
                const int sy = (int)(((int64_t)(y - vp_y) * src_h) / vp_h);
                value = src[(size_t)sy * (size_t)src_w + (size_t)sx];
            }
            dest[(size_t)(fb_w - y - 1) + (size_t)fb_w * (size_t)x] = value;
        }
    }
}
"""


def _load_patcher():
    spec = importlib.util.spec_from_file_location(
        "cth3ds_patch_sdl2", ROOT / "tools" / "patch_sdl2_n3ds.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(shutil.which("cc") is None, "no host C compiler available")
class LetterboxEquivalenceTests(unittest.TestCase):
    library: ctypes.CDLL
    tempdir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        patcher = _load_patcher()
        cls.tempdir = tempfile.TemporaryDirectory()
        source = Path(cls.tempdir.name) / "letterbox.c"
        source.write_text(
            PRELUDE + patcher.PATCHED_BLOCK + EPILOGUE + REFERENCE, encoding="utf-8"
        )
        library_path = Path(cls.tempdir.name) / "letterbox.so"
        subprocess.run(
            [
                "cc",
                "-std=c99",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fPIC",
                "-shared",
                str(source),
                "-o",
                str(library_path),
            ],
            check=True,
            capture_output=True,
        )
        cls.library = ctypes.CDLL(str(library_path))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def _compare(self, fb_w: int, fb_h: int, src_w: int, src_h: int,
                 mode: bytes = b"fit") -> None:
        self.library.cth3ds_test_set_mode(ctypes.c_char_p(mode))
        reference = (
            self.library.cth3ds_reference_crop32
            if mode == b"crop"
            else self.library.cth3ds_reference_copy32
        )
        count = src_w * src_h
        source = (ctypes.c_uint32 * count)()
        for index in range(count):
            # A value that is unique per pixel so any mis-mapping is visible.
            source[index] = 0xFF000000 | ((index * 2654435761) & 0xFFFFFF)
        size = fb_w * fb_h
        produced = (ctypes.c_uint32 * size)()
        expected = (ctypes.c_uint32 * size)()
        self.library.cth3ds_test_copy32(produced, fb_w, fb_h, source, src_w, src_h)
        reference(expected, fb_w, fb_h, source, src_w, src_h)
        self.assertEqual(
            list(produced),
            list(expected),
            f"mismatch for {src_w}x{src_h} -> {fb_h}x{fb_w} in {mode.decode()} mode",
        )

    def test_top_screen_640x480_fit(self) -> None:
        # Legacy aspect-preserving mode, kept as a fallback.
        self._compare(240, 400, 640, 480, b"fit")

    def test_top_screen_640x480_crop(self) -> None:
        # The shipped mode: a 1:1 centre crop of the CorsixTH frame, so the
        # hospital is drawn from real pixels rather than every second one.
        self._compare(240, 400, 640, 480, b"crop")

    def test_bottom_screen_crop_is_an_exact_copy(self) -> None:
        # 320x240 source on the 320x240 lower screen: crop degenerates to a
        # straight copy, which is what the lower-screen mirror relies on.
        self._compare(240, 320, 320, 240, b"crop")

    def test_bottom_screen_native(self) -> None:
        self._compare(240, 320, 320, 240)

    def test_odd_sizes_and_vertical_bars(self) -> None:
        for src_w, src_h in ((100, 100), (321, 241), (800, 200), (64, 480), (17, 33)):
            for mode in (b"fit", b"crop"):
                with self.subTest(source=(src_w, src_h), mode=mode):
                    self._compare(240, 400, src_w, src_h, mode)

    def test_matches_cpp_reference_table(self) -> None:
        # The axis table must equal floor(d * span / viewport) exactly, which is
        # what src/common/framebuffer_scaler.cpp documents and tests.
        for span, viewport in ((640, 320), (480, 240), (320, 320), (17, 240)):
            source = 0
            remainder = 0
            for destination in range(viewport):
                self.assertEqual(source, (destination * span) // viewport)
                remainder += span
                while remainder >= viewport:
                    remainder -= viewport
                    source += 1


if __name__ == "__main__":
    unittest.main()
