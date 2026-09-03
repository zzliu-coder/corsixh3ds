#!/usr/bin/env bash
set -euo pipefail

CTH3DS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CTH3DS_EXTERNAL_DIR="${CTH3DS_EXTERNAL_DIR:-${CTH3DS_ROOT}/external}"
CTH3DS_BUILD_DIR="${CTH3DS_BUILD_DIR:-${CTH3DS_ROOT}/build-3ds}"
CTH3DS_DEPS_PREFIX="${CTH3DS_DEPS_PREFIX:-${CTH3DS_BUILD_DIR}/deps}"
CTH3DS_DIST_DIR="${CTH3DS_DIST_DIR:-${CTH3DS_ROOT}/dist}"
CTH3DS_JOBS="${CTH3DS_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
PIN_FILE="${CTH3DS_ROOT}/config/upstream-pins.json"

log() { printf '[cth3ds] %s\n' "$*"; }
die() { printf '[cth3ds] error: %s\n' "$*" >&2; exit 2; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }

pin() {
  python3 "${CTH3DS_ROOT}/tools/check_pins.py" --manifest "${PIN_FILE}" --get "$1"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    python3 - "$1" <<'PY'
import hashlib, pathlib, sys
p = pathlib.Path(sys.argv[1])
h = hashlib.sha256()
with p.open('rb') as f:
    for b in iter(lambda: f.read(1024 * 1024), b''):
        h.update(b)
print(h.hexdigest())
PY
  fi
}

clone_pinned() {
  local name="$1" repo="$2" commit="$3" destination="$4"
  mkdir -p "$(dirname "${destination}")"

  # A source archive is a valid pinned checkout when the network can reach
  # codeload.github.com but the Git smart-HTTP endpoint is unavailable. The
  # marker records the exact repository and commit so later runs cannot reuse
  # an unrelated unpacked tree by accident.
  local marker="${destination}/.cth3ds-source.json"
  if [[ -d "${destination}" && ! -d "${destination}/.git" ]]; then
    if [[ -f "${marker}" ]] && python3 - "${marker}" "${repo}" "${commit}" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
raise SystemExit(0 if data.get("repository") == sys.argv[2] and data.get("commit") == sys.argv[3] else 1)
PY
    then
      log "using archived ${name} source at ${destination}"
      return 0
    fi
    [[ "${CTH3DS_ACCEPT_UNPACKED:-0}" == "1" ]] || \
      die "${destination} exists but is not a pinned git checkout or archived source"
    log "using explicitly accepted unpacked ${name} source at ${destination}"
    return 0
  fi

  if [[ "${CTH3DS_ARCHIVE_FALLBACK:-0}" == "1" ]]; then
    require_cmd curl
    require_cmd tar
    local archive_url archive_tmp extract found
    case "${repo}" in
      https://github.com/*.git)
        archive_url="https://codeload.github.com/${repo#https://github.com/}"
        archive_url="${archive_url%.git}/tar.gz/${commit}"
        ;;
      *)
        die "cannot derive a source archive URL for ${repo}"
        ;;
    esac
    archive_tmp="${destination}.cth3ds-download.$$.tmp"
    extract="${destination}.cth3ds-extract.$$"
    log "downloading pinned ${name} source archive"
    curl --fail --location --retry 4 --retry-delay 2 \
      --output "${archive_tmp}" "${archive_url}"
    mkdir -p "${extract}"
    tar -xzf "${archive_tmp}" -C "${extract}"
    found="$(find "${extract}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    [[ -n "${found}" ]] || die "${name} source archive did not contain a directory"
    mv "${found}" "${destination}"
    rm -rf "${extract}" "${archive_tmp}"
    python3 - "${marker}" "${repo}" "${commit}" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({"repository": sys.argv[2], "commit": sys.argv[3]}, sort_keys=True) + "\n", encoding="utf-8")
PY
    return 0
  fi

  require_cmd git
  if [[ ! -d "${destination}/.git" ]]; then
    [[ ! -e "${destination}" ]] || die "${destination} exists but is not a git checkout"
    log "cloning ${name}"
    git clone --filter=blob:none --no-checkout "${repo}" "${destination}"
  fi
  git -C "${destination}" remote set-url origin "${repo}"
  if ! git -C "${destination}" cat-file -e "${commit}^{commit}" 2>/dev/null; then
    log "fetching pinned ${name} commit"
    git -C "${destination}" fetch --depth 1 origin "${commit}"
  fi
  git -C "${destination}" checkout --detach --force "${commit}"
  git -C "${destination}" clean -ffd
  local actual
  actual="$(git -C "${destination}" rev-parse HEAD)"
  [[ "${actual}" == "${commit}" ]] || die "${name} checkout mismatch: ${actual}"
}

require_devkitpro() {
  [[ -n "${DEVKITPRO:-}" ]] || die 'DEVKITPRO is not set'
  [[ -n "${DEVKITARM:-}" ]] || export DEVKITARM="${DEVKITPRO}/devkitARM"
  [[ -f "${DEVKITPRO}/cmake/3DS.cmake" ]] || die "3DS CMake toolchain missing under ${DEVKITPRO}/cmake"
  require_cmd arm-none-eabi-gcc
  require_cmd arm-none-eabi-g++
  require_cmd arm-none-eabi-ar
  require_cmd cmake
}

cmake_generator_args() {
  if command -v ninja >/dev/null 2>&1; then
    printf '%s\n' '-G' 'Ninja'
  fi
}

# Bash 3.2 (the system shell on macOS) does not provide mapfile/readarray.
# Keep generator selection in one small helper so all scripts can use arrays
# without requiring a newer shell.
set_cmake_generator() {
  CTH3DS_CMAKE_GENERATOR=()
  if command -v ninja >/dev/null 2>&1; then
    CTH3DS_CMAKE_GENERATOR=(-G Ninja)
  fi
}

verify_file_sha256() {
  local file="$1" expected="$2" actual
  actual="$(sha256_file "${file}")"
  [[ "${actual}" == "${expected}" ]] || die "SHA-256 mismatch for ${file}: ${actual}"
}
