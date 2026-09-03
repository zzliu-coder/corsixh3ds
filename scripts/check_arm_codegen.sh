#!/usr/bin/env bash
# Cross-compile the port's own sources for the Old 3DS CPU and assert that the
# hot present loop contains no runtime division.
#
# The ARM11 in an Old 3DS has no hardware divider, so a 64-bit division inside a
# per-pixel loop costs hundreds of cycles. The previous framebuffer copy had
# exactly that, which is why a single present took tens of milliseconds. This
# check exists so the regression cannot come back unnoticed.
#
# Only needs a bare-metal arm-none-eabi-g++ (for example Debian/Ubuntu's
# gcc-arm-none-eabi); the full devkitPro toolchain is not required.
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

ARM_TOOL_DIR="${DEVKITARM:-${DEVKITPRO:-/opt/devkitpro}/devkitARM}/bin"
if [[ -x "${ARM_TOOL_DIR}/arm-none-eabi-g++" ]]; then
  ARM_CXX="${ARM_TOOL_DIR}/arm-none-eabi-g++"
  ARM_CC="${ARM_TOOL_DIR}/arm-none-eabi-gcc"
  ARM_OBJDUMP="${ARM_TOOL_DIR}/arm-none-eabi-objdump"
elif command -v arm-none-eabi-g++ >/dev/null 2>&1; then
  ARM_CXX="$(command -v arm-none-eabi-g++)"
  ARM_CC="$(command -v arm-none-eabi-gcc)"
  ARM_OBJDUMP="$(command -v arm-none-eabi-objdump)"
else
  log 'arm-none-eabi-g++ not found; skipping ARM codegen check'
  exit 0
fi

OUT="${CTH3DS_BUILD_DIR}/arm-check"
rm -rf "${OUT}"
mkdir -p "${OUT}"

ARM_FLAGS=(
  -std=c++17 -Os -march=armv6k -mtune=mpcore -mfloat-abi=soft -Wno-psabi
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Werror
  -D__3DS__=1 -DCTH3DS_STUB_BUILD=1
  -I"${CTH3DS_ROOT}/tests/stubs" -I"${CTH3DS_ROOT}/include" -I"${CTH3DS_ROOT}/src/3ds"
)

count=0
for source in "${CTH3DS_ROOT}"/src/common/*.cpp "${CTH3DS_ROOT}/src/3ds/runtime_3ds.cpp"; do
  "${ARM_CXX}" "${ARM_FLAGS[@]}" -c "${source}" -o "${OUT}/$(basename "${source}").o"
  count=$((count + 1))
done
log "cross-compiled ${count} sources for armv6k with warnings as errors"

# The SDL2 framebuffer patch lives outside this tree, so compile it here in the
# same shape the device build sees and inspect the generated code.
python3 - "${CTH3DS_ROOT}" "${OUT}" <<'PY'
import importlib.util, sys, pathlib
root, out = map(pathlib.Path, sys.argv[1:3])
spec = importlib.util.spec_from_file_location("p", root / "tools" / "patch_sdl2_n3ds.py")
module = importlib.util.module_from_spec(spec); sys.modules["p"] = module
spec.loader.exec_module(module)
prelude = """
#include <stdint.h>
#include <stddef.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int64_t Sint64;
typedef int SDL_bool;
#define SDL_TRUE 1
#define SDL_FALSE 0
#define SDL_FORCE_INLINE static inline
#define SDL_min(a,b) (((a)<(b))?(a):(b))
#define SDL_max(a,b) (((a)>(b))?(a):(b))
#include <string.h>
#define SDL_strcmp strcmp
const char *SDL_GetHint(const char *name);
const char *SDL_GetHint(const char *name) { (void)name; return "crop"; }
typedef struct { int width, height; } Dimensions;
static inline int GetDestOffset(int x,int y,int w){return w-y-1+w*x;}
static inline int GetSourceOffset(int x,int y,int w){return x+y*w;}
"""
epilogue = """
void cth3ds_present(u32 *d, Dimensions dd, const u32 *s, Dimensions ss)
{ CopyFramebuffertoN3DS_32(d, dd, s, ss); }
"""
(out / "letterbox.c").write_text(prelude + module.PATCHED_BLOCK + epilogue)
PY

"${ARM_CC}" -std=gnu99 -O2 -march=armv6k -mtune=mpcore -mfloat-abi=soft \
  -Wall -Wextra -Werror -c "${OUT}/letterbox.c" -o "${OUT}/letterbox.o"
"${ARM_OBJDUMP}" -d "${OUT}/letterbox.o" > "${OUT}/letterbox.asm"

# Divisions are permitted in the once-per-present viewport setup, which runs
# before any loop. No loop body may contain one.
python3 - "${OUT}/letterbox.asm" <<'PYCHECK'
import re, sys, pathlib

# The ARM11 has no hardware divider, so every division is a libgcc call costing
# on the order of a hundred cycles. The present path needs exactly two: the
# aspect-ratio comparison in CTH3DS_CalculateLetterbox, evaluated once per
# frame. Anything beyond that means a division crept back into a loop, which is
# what made the previous implementation cost tens of milliseconds per present.
ALLOWED_DIVISION_SITES = 2

text = pathlib.Path(sys.argv[1]).read_text()
sites = re.findall(r"bl\s+[0-9a-f]+ <(__aeabi_[a-z]*div[a-z]*)>", text)
if len(sites) > ALLOWED_DIVISION_SITES:
    print(
        "error: %d division call sites in the present path (at most %d allowed): %s"
        % (len(sites), ALLOWED_DIVISION_SITES, ", ".join(sorted(set(sites)))),
        file=sys.stderr,
    )
    raise SystemExit(1)

# The per-pixel copy must also stay a tight, branch-light loop.
lines = [l for l in text.splitlines() if re.match(r"^\s*[0-9a-f]+:\t", l)]
position_of = {}
for position, line in enumerate(lines):
    position_of[int(line.split(":")[0].strip(), 16)] = position
spans = []
for position, line in enumerate(lines):
    match = re.search(r"\b(bne|beq|blt|bgt|ble|bge|bcc|bcs|bhi|bls)\s+([0-9a-f]+)\s+<", line)
    if not match:
        continue
    begin = position_of.get(int(match.group(2), 16))
    if begin is not None and begin <= position:
        spans.append(position - begin + 1)
if not spans:
    raise SystemExit("no loop found in the generated present path")
print(
    "present path: %d division call sites (limit %d), innermost loop %d instructions"
    % (len(sites), ALLOWED_DIVISION_SITES, min(spans))
)
PYCHECK

log 'ARM codegen check passed'
