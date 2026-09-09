#!/usr/bin/env bash
set -euo pipefail
set -E
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source "$(cd "$(dirname "$0")" && pwd)/ci_diagnostics.sh"
source_owner "$0" "$@"

SKIP_BOOTSTRAP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-bootstrap) SKIP_BOOTSTRAP=1 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

BUILD_EVIDENCE_DIR="${CTH3DS_BUILD_EVIDENCE_DIR:-${CTH3DS_ROOT}/artifacts/verification/cross-build}"
mkdir -p "${BUILD_EVIDENCE_DIR}"
rm -f -- "${CTH3DS_BUILD_MANIFEST}"
# A success receipt is usable only after every required build/evidence step.
# Preserve diagnostic logs on failure while invalidating this exact receipt.
BUILD_RECEIPT_COMMITTED=0
trap 'if [[ "${BUILD_RECEIPT_COMMITTED}" != 1 ]]; then rm -f -- "${CTH3DS_BUILD_MANIFEST}"; fi' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
ci_diag_init old3ds-cross-build "${BUILD_EVIDENCE_DIR}"
ci_diag_step preflight
require_devkitpro
require_cmd python3

if [[ "${SKIP_BOOTSTRAP}" -eq 0 ]]; then
  ci_diag_step bootstrap-dependencies "${BUILD_EVIDENCE_DIR}/bootstrap-dependencies.log"
  "${CTH3DS_ROOT}/scripts/bootstrap_3ds_deps.sh" \
    >"${BUILD_EVIDENCE_DIR}/bootstrap-dependencies.log" 2>&1
  ci_diag_step bootstrap-upstream "${BUILD_EVIDENCE_DIR}/bootstrap-upstream.log"
  "${CTH3DS_ROOT}/scripts/bootstrap_upstream.sh" \
    >"${BUILD_EVIDENCE_DIR}/bootstrap-upstream.log" 2>&1
fi

UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${UPSTREAM_DIR}" \
  --overlay-root "${CTH3DS_ROOT}" --build-profile "${CTH3DS_BUILD_PROFILE}" --check
[[ -f "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" ]] || \
  die '3DS dependencies are missing; run scripts/bootstrap_3ds_deps.sh'

TOOLCHAIN="${DEVKITPRO}/cmake/3DS.cmake"
BUILD="${CTH3DS_BUILD_DIR}/CorsixTH"
set_cmake_generator

# CorsixTH draws into its owned 640x480 surface. Runtime copies a native 400x240
# viewport to the upper window and a 320x240 overview to the lower window.
ci_diag_step configure "${BUILD_EVIDENCE_DIR}/configure.log"
cmake -S "${UPSTREAM_DIR}" -B "${BUILD}" "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN}" \
  -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_PREFIX_PATH="${CTH3DS_DEPS_PREFIX};${DEVKITPRO}/portlibs/3ds" \
  -DCMAKE_FIND_ROOT_PATH="${CTH3DS_DEPS_PREFIX};${DEVKITPRO}/portlibs/3ds;${DEVKITPRO}/libctru" \
  -DCORSIXTH_3DS=ON \
  -DCTH3DS_BUILD_PROFILE="${CTH3DS_BUILD_PROFILE}" \
  -DCORSIXTH_3DS_DEPS_PREFIX="${CTH3DS_DEPS_PREFIX}" \
  -DBUILD_CORSIXTH=ON \
  -DBUILD_ANIMVIEW=OFF \
  -DBUILD_TOOLS=OFF \
  -DENABLE_UNIT_TESTS=OFF \
  -DENABLE_SANITIZERS=OFF \
  -DWITH_TRACY=OFF \
  -DWITH_MOVIES=OFF \
  -DWITH_UPDATE_CHECK=OFF \
  -DWITH_MIDI_DEVICE=OFF \
  -DFETCH_SOUNDFONT=OFF \
  -DFETCH_UNICODE_FONT=OFF \
  -DUSE_SOURCE_DATADIRS=OFF \
  -DSEARCH_LOCAL_DATADIRS=OFF \
  -DWITH_FONT="" \
  >"${BUILD_EVIDENCE_DIR}/configure.log" 2>&1

ci_diag_step build "${BUILD_EVIDENCE_DIR}/configure.log" \
  "${BUILD_EVIDENCE_DIR}/build.log"
# Always clean the game target before using the fixed source alias. Dependency
# installations are external to this target and stay cached.
cmake --build "${BUILD}" --target clean >"${BUILD_EVIDENCE_DIR}/clean.log" 2>&1
cmake --build "${BUILD}" --parallel "${CTH3DS_JOBS}" --target corsixth_3dsx \
  >"${BUILD_EVIDENCE_DIR}/build.log" 2>&1
OUTPUT="${BUILD}/CorsixTH-3DS.3dsx"
ELF="${BUILD}/CorsixTH/CorsixTH-3DS.elf"
[[ -s "${OUTPUT}" ]] || die "3DSX output was not produced: ${OUTPUT}"
[[ -s "${ELF}" ]] || die "ELF output was not produced: ${ELF}"

# Prove the allocator override made it through the final link as a strong data
# symbol and that its stored value is exactly 8 MiB. A source-only assertion
# cannot catch a weak/default symbol winning at link time.
ARM_NM="${DEVKITARM}/bin/arm-none-eabi-nm"
ARM_READELF="${DEVKITARM}/bin/arm-none-eabi-readelf"
ARM_OBJDUMP="${DEVKITARM}/bin/arm-none-eabi-objdump"
ci_diag_step final-elf-heap-proof "${BUILD}/heap-budget.json"
SYMBOL_LINE="$("${ARM_NM}" -S --defined-only "${ELF}" | awk '$4 == "__ctru_linear_heap_size" {print $1, $3}')"
[[ -n "${SYMBOL_LINE}" ]] || die '__ctru_linear_heap_size is missing from the final ELF'
read -r SYMBOL_ADDRESS SYMBOL_TYPE <<<"${SYMBOL_LINE}"
[[ "${SYMBOL_TYPE}" == "D" ]] || die "linear heap override is not a strong data symbol: ${SYMBOL_TYPE}"
read -r DATA_ADDRESS DATA_OFFSET <<<"$("${ARM_READELF}" -SW "${ELF}" | awk '$2 == ".data" {print $4, $5}')"
python3 - "${ELF}" "${SYMBOL_ADDRESS}" "${DATA_ADDRESS}" "${DATA_OFFSET}" \
  "${BUILD}/heap-budget.json" <<'PY'
import json, pathlib, struct, sys
elf, symbol_hex, data_hex, offset_hex, report = sys.argv[1:]
symbol = int(symbol_hex, 16)
data_address = int(data_hex, 16)
data_offset = int(offset_hex, 16)
payload = pathlib.Path(elf).read_bytes()
position = data_offset + symbol - data_address
value = struct.unpack_from("<I", payload, position)[0]
result = {
    "symbol": "__ctru_linear_heap_size",
    "symbolAddress": f"0x{symbol:08x}",
    "symbolType": "D",
    "valueBytes": value,
    "expectedBytes": 8 * 1024 * 1024,
    "pass": value == 8 * 1024 * 1024,
}
pathlib.Path(report).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if not result["pass"]:
    raise SystemExit(f"linear heap value is {value}, expected 8388608")
PY
ci_diag_step final-elf-stack-proof "${BUILD}/runtime-stack-proof.json"
python3 "${CTH3DS_ROOT}/tools/check_runtime_stack.py" \
  --elf "${ELF}" --tool-prefix "${DEVKITARM}/bin/arm-none-eabi-" \
  --output "${BUILD}/runtime-stack-proof.json"
ARCHIVE="$(find "${BUILD}" -name 'libCorsixTH_lib.a' -type f -print -quit)"
[[ -n "${ARCHIVE}" && -s "${ARCHIVE}" ]] || \
  die 'CorsixTH_lib archive was not produced'
ci_diag_step final-elf-runtime-proof "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json"
python3 "${CTH3DS_ROOT}/tools/check_resource_link.py" \
  --elf "${ELF}" --archive "${ARCHIVE}" --build "${BUILD}" \
  --nm "${ARM_NM}" --objdump "${ARM_OBJDUMP}" \
  --profile "${CTH3DS_BUILD_PROFILE}" --output "${BUILD}/runtime-core-link-proof.json"
sha256_file "${OUTPUT}" > "${OUTPUT}.sha256"
python3 - "${CTH3DS_ROOT}" "${CTH3DS_BUILD_MANIFEST}" \
  "${OUTPUT}" "${ELF}" "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json" \
  "${BUILD}/runtime-stack-proof.json" \
  "${UPSTREAM_DIR}/CorsixTH/Src/3ds/integration-manifest.json" \
  "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
paths = [pathlib.Path(value) for value in sys.argv[3:]]
files = []
for path in paths:
    payload = path.read_bytes()
    try:
        name = path.relative_to(root).as_posix()
    except ValueError:
        name = path.name
    files.append({
        "path": name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    })
manifest = {
    "format": 1,
    "build_profile": os.environ["CTH3DS_BUILD_PROFILE"],
    "source_commit": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip(),
    "source_tree": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True
    ).strip(),
    "files": files,
}
output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
PY
cp "${UPSTREAM_DIR}/.cth3ds-view.json" "${BUILD_EVIDENCE_DIR}/generated-source.json"
python3 "${CTH3DS_ROOT}/tools/source_view.py" bind --view "${UPSTREAM_DIR}" \
  --overlay "${CTH3DS_ROOT}" --build-profile "${CTH3DS_BUILD_PROFILE}" --binary "${OUTPUT}" \
  --manifest "${CTH3DS_BUILD_MANIFEST}"
ci_diag_step complete "${BUILD_EVIDENCE_DIR}/configure.log" \
  "${BUILD_EVIDENCE_DIR}/build.log" "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json" "${OUTPUT}.sha256" \
  "${BUILD}/runtime-stack-proof.json" \
  "${CTH3DS_BUILD_MANIFEST}"
ci_diag_mark_pass
log "Nintendo 3DS build complete: ${OUTPUT}"
BUILD_RECEIPT_COMMITTED=1
