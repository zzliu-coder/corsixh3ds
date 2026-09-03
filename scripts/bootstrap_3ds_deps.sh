#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

require_devkitpro
require_cmd python3
require_cmd git
require_cmd curl

mkdir -p "${CTH3DS_EXTERNAL_DIR}" "${CTH3DS_BUILD_DIR}" \
  "${CTH3DS_DEPS_PREFIX}/include" "${CTH3DS_DEPS_PREFIX}/lib" \
  "${CTH3DS_DEPS_PREFIX}/share/lpeg"

SDL_DIR="${CTH3DS_EXTERNAL_DIR}/SDL2"
MIXER_DIR="${CTH3DS_EXTERNAL_DIR}/SDL2_mixer"
LUA_DIR="${CTH3DS_EXTERNAL_DIR}/lua"
LFS_DIR="${CTH3DS_EXTERNAL_DIR}/luafilesystem"
LPEG_DIR="${CTH3DS_EXTERNAL_DIR}/lpeg-$(pin lpeg.version)"

clone_pinned SDL2 "$(pin sdl2.repository)" "$(pin sdl2.commit)" "${SDL_DIR}"
clone_pinned SDL2_mixer "$(pin sdl2_mixer.repository)" "$(pin sdl2_mixer.commit)" "${MIXER_DIR}"
clone_pinned Lua "$(pin lua.repository)" "$(pin lua.commit)" "${LUA_DIR}"
clone_pinned LuaFileSystem "$(pin luafilesystem.repository)" "$(pin luafilesystem.commit)" "${LFS_DIR}"

python3 "${CTH3DS_ROOT}/tools/patch_sdl2_n3ds.py" "${SDL_DIR}" --allow-unverified
python3 "${CTH3DS_ROOT}/tools/patch_sdl2_n3ds.py" "${SDL_DIR}" --check --allow-unverified

if [[ ! -d "${LPEG_DIR}" ]]; then
  archive="${CTH3DS_EXTERNAL_DIR}/lpeg-$(pin lpeg.version).tar.gz"
  if [[ ! -f "${archive}" ]]; then
    log "downloading LPeg $(pin lpeg.version)"
    curl --fail --location --retry 3 --output "${archive}.tmp" "$(pin lpeg.url)"
    mv "${archive}.tmp" "${archive}"
  fi
  verify_file_sha256 "${archive}" "$(pin lpeg.sha256)"
  extract="${CTH3DS_EXTERNAL_DIR}/.lpeg-extract"
  rm -rf "${extract}"
  mkdir -p "${extract}"
  tar -xzf "${archive}" -C "${extract}"
  found="$(find "${extract}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "${found}" ]] || die 'LPeg archive did not contain a directory'
  mv "${found}" "${LPEG_DIR}"
  rm -rf "${extract}"
fi

TOOLCHAIN="${DEVKITPRO}/cmake/3DS.cmake"
set_cmake_generator

log 'building patched SDL2 for Nintendo 3DS'
cmake -S "${SDL_DIR}" -B "${CTH3DS_BUILD_DIR}/SDL2" "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN}" \
  -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_INSTALL_PREFIX="${CTH3DS_DEPS_PREFIX}" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=OFF \
  -DSDL_SHARED=OFF -DSDL_STATIC=ON -DSDL_TEST=OFF \
  -DSDL2_DISABLE_INSTALL=OFF
cmake --build "${CTH3DS_BUILD_DIR}/SDL2" --parallel "${CTH3DS_JOBS}" --target install

log 'building minimal SDL2_mixer for Nintendo 3DS'
cmake -S "${MIXER_DIR}" -B "${CTH3DS_BUILD_DIR}/SDL2_mixer" "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN}" \
  -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_PREFIX_PATH="${CTH3DS_DEPS_PREFIX}" \
  -DCMAKE_INSTALL_PREFIX="${CTH3DS_DEPS_PREFIX}" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=OFF \
  -DBUILD_SHARED_LIBS=OFF -DSDL2MIXER_INSTALL=ON \
  -DSDL2MIXER_SAMPLES=OFF -DSDL2MIXER_CMD=OFF \
  -DSDL2MIXER_VENDORED=ON -DSDL2MIXER_DEPS_SHARED=OFF \
  -DSDL2MIXER_FLAC=OFF -DSDL2MIXER_GME=OFF -DSDL2MIXER_MOD=OFF \
  -DSDL2MIXER_MP3=OFF -DSDL2MIXER_MIDI=OFF -DSDL2MIXER_OPUS=OFF \
  -DSDL2MIXER_VORBIS=STB -DSDL2MIXER_WAVE=ON -DSDL2MIXER_WAVPACK=OFF
cmake --build "${CTH3DS_BUILD_DIR}/SDL2_mixer" --parallel "${CTH3DS_JOBS}" --target install

ARM_CFLAGS=(
  -Os -g0 -std=gnu11 -ffunction-sections -fdata-sections -fno-strict-aliasing
  -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft -mword-relocations
  -D__3DS__ -I"${DEVKITPRO}/libctru/include"
)
LUA_INCLUDE="${CTH3DS_DEPS_PREFIX}/include/lua54"
mkdir -p "${LUA_INCLUDE}" "${CTH3DS_BUILD_DIR}/lua-objects" \
  "${CTH3DS_BUILD_DIR}/lfs-objects" "${CTH3DS_BUILD_DIR}/lpeg-objects"

LUA_SOURCES=(
  lapi.c lauxlib.c lbaselib.c lcode.c lcorolib.c lctype.c ldblib.c ldebug.c
  ldo.c ldump.c lfunc.c lgc.c linit.c liolib.c llex.c lmathlib.c lmem.c
  loadlib.c lobject.c lopcodes.c loslib.c lparser.c lstate.c lstring.c
  lstrlib.c ltable.c ltablib.c ltm.c lundump.c lutf8lib.c lvm.c lzio.c
)
rm -f "${CTH3DS_BUILD_DIR}/lua-objects"/*.o
for source in "${LUA_SOURCES[@]}"; do
  [[ -f "${LUA_DIR}/${source}" ]] || die "missing Lua source ${source}"
  arm-none-eabi-gcc "${ARM_CFLAGS[@]}" -DLUA_COMPAT_5_3 \
    -I"${LUA_DIR}" -c "${LUA_DIR}/${source}" \
    -o "${CTH3DS_BUILD_DIR}/lua-objects/${source%.c}.o"
done
arm-none-eabi-ar rcs "${CTH3DS_DEPS_PREFIX}/lib/liblua.a" "${CTH3DS_BUILD_DIR}/lua-objects"/*.o
for header in lua.h luaconf.h lualib.h lauxlib.h lua.hpp; do
  if [[ "${header}" == "lua.hpp" && ! -f "${LUA_DIR}/${header}" ]]; then
    # The official Lua source distribution is C-only and omits the customary
    # C++ convenience wrapper. CorsixTH includes <lua.hpp>, so provide the
    # small ABI-safe wrapper when building from that distribution.
    cat > "${LUA_INCLUDE}/${header}" <<'LUA_HPP'
#ifndef CTH3DS_LUA_HPP
#define CTH3DS_LUA_HPP
extern "C" {
#include "lua.h"
#include "lualib.h"
#include "lauxlib.h"
}
#endif
LUA_HPP
  else
    cp "${LUA_DIR}/${header}" "${LUA_INCLUDE}/${header}"
  fi
done

log 'building LuaFileSystem as a statically preloaded Lua module'
rm -f "${CTH3DS_BUILD_DIR}/lfs-objects"/*.o
arm-none-eabi-gcc "${ARM_CFLAGS[@]}" -DLFS_NO_USE_LARGE_FILE \
  -I"${LUA_INCLUDE}" -c "${LFS_DIR}/src/lfs.c" \
  -o "${CTH3DS_BUILD_DIR}/lfs-objects/lfs.o"
arm-none-eabi-ar rcs "${CTH3DS_DEPS_PREFIX}/lib/liblfs.a" \
  "${CTH3DS_BUILD_DIR}/lfs-objects/lfs.o"

log 'building LPeg as a statically preloaded Lua module'
LPEG_SOURCES=(lpcap.c lpcode.c lpcset.c lpprint.c lptree.c lpvm.c)
rm -f "${CTH3DS_BUILD_DIR}/lpeg-objects"/*.o
for source in "${LPEG_SOURCES[@]}"; do
  [[ -f "${LPEG_DIR}/${source}" ]] || die "missing LPeg source ${source}"
  arm-none-eabi-gcc "${ARM_CFLAGS[@]}" -I"${LUA_INCLUDE}" -I"${LPEG_DIR}" \
    -c "${LPEG_DIR}/${source}" \
    -o "${CTH3DS_BUILD_DIR}/lpeg-objects/${source%.c}.o"
done
arm-none-eabi-ar rcs "${CTH3DS_DEPS_PREFIX}/lib/liblpeg.a" \
  "${CTH3DS_BUILD_DIR}/lpeg-objects"/*.o
cp "${LPEG_DIR}/re.lua" "${CTH3DS_DEPS_PREFIX}/share/lpeg/re.lua"

python3 - "${CTH3DS_ROOT}" "${CTH3DS_DEPS_PREFIX}" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
prefix = pathlib.Path(sys.argv[2])
pins = json.loads((root / 'config/upstream-pins.json').read_text())
files = {}
for name in ('libSDL2.a', 'libSDL2main.a', 'libSDL2_mixer.a', 'liblua.a', 'liblfs.a', 'liblpeg.a'):
    path = prefix / 'lib' / name
    if not path.is_file():
        raise SystemExit(f'missing built library: {path}')
    files[name] = {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
manifest = {'format': 1, 'pins': pins, 'files': files}
(prefix / 'cth3ds-dependencies.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
PY
log "3DS dependencies are ready under ${CTH3DS_DEPS_PREFIX}"
