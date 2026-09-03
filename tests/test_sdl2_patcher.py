from __future__ import annotations

import sys
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from patch_sdl2_n3ds import END_MARKER, HINT_INCLUDE, MARKER, apply_patch_text, main


ORIGINAL = r'''#include "../../SDL_internal.h"

typedef struct
{
    int width, height;
} Dimensions;

SDL_FORCE_INLINE void CopyFramebuffertoN3DS_16(u16 *dest, const Dimensions dest_dim, const u16 *source, const Dimensions source_dim);
SDL_FORCE_INLINE int GetDestOffset(int x, int y, int dest_width);

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_16(u16 *dest, const Dimensions dest_dim, const u16 *source, const Dimensions source_dim)
{
    old16();
}

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_24(u8 *dest, const Dimensions dest_dim, const u8 *source, const Dimensions source_dim)
{
    old24();
}

SDL_FORCE_INLINE void
CopyFramebuffertoN3DS_32(u32 *dest, const Dimensions dest_dim, const u32 *source, const Dimensions source_dim)
{
    old32();
}

SDL_FORCE_INLINE int
GetDestOffset(int x, int y, int dest_width)
{
    return dest_width - y - 1 + dest_width * x;
}
'''


class Sdl2PatcherTests(unittest.TestCase):
    def test_patch_is_idempotent_and_replaces_all_copy_functions(self) -> None:
        patched, changed = apply_patch_text(ORIGINAL)
        self.assertTrue(changed)
        self.assertEqual(patched.count(MARKER), 1)
        self.assertEqual(patched.count(END_MARKER), 1)
        self.assertNotIn("old16", patched)
        self.assertIn("CTH3DS_CalculateLetterbox", patched)
        self.assertEqual(patched.count(HINT_INCLUDE), 1)
        second, changed_again = apply_patch_text(patched)
        self.assertFalse(changed_again)
        self.assertEqual(second, patched)

    def test_migrates_existing_patch_missing_hint_declaration(self) -> None:
        patched, _ = apply_patch_text(ORIGINAL)
        old_patch = patched.replace(f"{HINT_INCLUDE}\n", "", 1)
        migrated, changed = apply_patch_text(old_patch)
        self.assertTrue(changed)
        self.assertEqual(migrated.count(HINT_INCLUDE), 1)
        self.assertIn("CTH3DS_UseCropMode", migrated)

    def test_moves_misplaced_hint_include_to_include_section(self) -> None:
        patched, _ = apply_patch_text(ORIGINAL)
        misplaced = patched.replace(f"{HINT_INCLUDE}\n", "", 1).replace(
            MARKER, f"{HINT_INCLUDE}\n\n{MARKER}", 1
        )
        migrated, changed = apply_patch_text(misplaced)
        self.assertTrue(changed)
        self.assertIn(
            f'#include "../../SDL_internal.h"\n{HINT_INCLUDE}\n', migrated
        )
        self.assertEqual(migrated.count(HINT_INCLUDE), 1)

    def test_cli_patch_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/video/n3ds/SDL_n3dsframebuffer.c"
            source.parent.mkdir(parents=True)
            source.write_text(ORIGINAL, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(root), "--allow-unverified"]), 0)
                self.assertEqual(main([str(root), "--check", "--allow-unverified"]), 0)

    def test_rejects_unknown_source(self) -> None:
        with self.assertRaisesRegex(Exception, "cannot locate"):
            apply_patch_text("unrelated")


if __name__ == "__main__":
    unittest.main()
