#!/usr/bin/env bash
set -euo pipefail
set -E
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source "$(cd "$(dirname "$0")" && pwd)/ci_diagnostics.sh"

SKIP_BOOTSTRAP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-bootstrap) SKIP_BOOTSTRAP=1 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

BUILD_EVIDENCE_DIR="${CTH3DS_ROOT}/artifacts/verification/cross-build"
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
[[ -f "${UPSTREAM_DIR}/CorsixTH/Src/3ds/integration-manifest.json" ]] || \
  die 'CorsixTH 3DS integration is missing; run scripts/bootstrap_upstream.sh'
[[ -f "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" ]] || \
  die '3DS dependencies are missing; run scripts/bootstrap_3ds_deps.sh'

TOOLCHAIN="${DEVKITPRO}/cmake/3DS.cmake"
BUILD="${CTH3DS_BUILD_DIR}/CorsixTH"
set_cmake_generator

# CorsixTH keeps its 640x480 logical canvas. The patched SDL2 N3DS framebuffer
# letterboxes it to 400x240 and exposes a second 320x240 window for the touch UI.
ci_diag_step configure "${BUILD_EVIDENCE_DIR}/configure.log"
cmake -S "${UPSTREAM_DIR}" -B "${BUILD}" "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN}" \
  -DCMAKE_BUILD_TYPE=MinSizeRel \
  -DCMAKE_PREFIX_PATH="${CTH3DS_DEPS_PREFIX};${DEVKITPRO}/portlibs/3ds" \
  -DCMAKE_FIND_ROOT_PATH="${CTH3DS_DEPS_PREFIX};${DEVKITPRO}/portlibs/3ds;${DEVKITPRO}/libctru" \
  -DCORSIXTH_3DS=ON \
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
ARCHIVE="$(find "${BUILD}" -name 'libCorsixTH_lib.a' -type f -print -quit)"
[[ -n "${ARCHIVE}" && -s "${ARCHIVE}" ]] || \
  die 'CorsixTH_lib archive was not produced'
ci_diag_step final-elf-runtime-proof "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json"
python3 - "${ELF}" "${ARCHIVE}" "${ARM_NM}" "${ARM_OBJDUMP}" \
  "${BUILD}/runtime-core-link-proof.json" "${BUILD}" <<'PY'
from __future__ import annotations
import json, pathlib, re, subprocess, sys

elf, archive, nm, objdump, report, build = sys.argv[1:]
required = {
    "runtime_session_start": "RuntimeSession::start(",
    "runtime_session_shutdown": "RuntimeSession::shutdown(",
    "runtime_session_menu": "RuntimeSession::enter_menu(",
    "runtime_session_level": "RuntimeSession::enter_level(",
    "runtime_session_save_begin": "RuntimeSession::begin_save_load(",
    "runtime_session_save_finish": "RuntimeSession::finish_save_load(",
    "runtime_session_suspend": "RuntimeSession::suspend(",
    "runtime_session_resume": "RuntimeSession::resume(",
    "bundle_mount": "BundleMount::open_bundle(",
    "resource_acquire": "ResourceManager::acquire(",
    # MinSizeRel is allowed to inline cancel(); the destructor is the retained
    # RAII rollback path and calls cancel whenever a token was not committed.
    "transition_rollback": "TransitionToken::~TransitionToken(",
}

def symbols(path: str) -> str:
    return subprocess.check_output(
        [nm, "-C", "--defined-only", path], text=True, errors="replace"
    )

archive_symbols = symbols(archive)
elf_symbols = symbols(elf)
archive_present = {key: needle in archive_symbols for key, needle in required.items()}
elf_present = {key: needle in elf_symbols for key, needle in required.items()}

disassembly = subprocess.check_output(
    [objdump, "-d", "-C", elf], text=True, errors="replace"
)
functions: dict[str, set[str]] = {}
current: str | None = None
for line in disassembly.splitlines():
    header = re.match(r"^[0-9a-fA-F]+ <(.+)>:$", line)
    if header:
        current = header.group(1)
        functions.setdefault(current, set())
        continue
    if current is None:
        continue
    # GCC tail-calls the production wrapper with `b`; direct calls use `bl` or
    # `blx`. Ignore intra-function branches carrying a +offset suffix.
    call = re.search(r"\b(?:b|bl|blx)\b[^<]*<(.+)>", line)
    if call:
        target = call.group(1)
        if not re.search(r"\+0x[0-9a-fA-F]+$", target):
            functions[current].add(target)

roots = [name for name in functions if "cth3ds::runtime_initialize(" in name]
goals = {name for name in functions if "RuntimeSession::start(" in name}
queue = [(root, [root]) for root in roots]
visited = set(roots)
edge_path: list[str] = []
while queue:
    node, path = queue.pop(0)
    if node in goals:
        edge_path = path
        break
    for target in sorted(functions.get(node, ())):
        if target not in visited:
            visited.add(target)
            queue.append((target, path + [target]))

link_files = list(pathlib.Path(build).rglob("link.txt"))
whole_archive = any("--whole-archive" in path.read_text(errors="replace")
                    for path in link_files)
result = {
    "archive": archive,
    "archive_symbols": archive_present,
    "elf": elf,
    "elf_symbols": elf_present,
    "production_entry": roots,
    "runtime_session_call_path": edge_path,
    "whole_archive_used": whole_archive,
    "pass": all(archive_present.values()) and all(elf_present.values())
            and bool(edge_path) and not whole_archive,
}
pathlib.Path(report).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if not result["pass"]:
    raise SystemExit("Runtime Core archive-to-final-ELF call-edge proof failed")
PY
sha256_file "${OUTPUT}" > "${OUTPUT}.sha256"
python3 - "${CTH3DS_ROOT}" "${BUILD_EVIDENCE_DIR}/artifact-manifest.json" \
  "${OUTPUT}" "${ELF}" "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json" \
  "${UPSTREAM_DIR}/CorsixTH/Src/3ds/integration-manifest.json" \
  "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" <<'PY'
from __future__ import annotations

import hashlib
import json
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
ci_diag_step complete "${BUILD_EVIDENCE_DIR}/configure.log" \
  "${BUILD_EVIDENCE_DIR}/build.log" "${BUILD}/heap-budget.json" \
  "${BUILD}/runtime-core-link-proof.json" "${OUTPUT}.sha256" \
  "${BUILD_EVIDENCE_DIR}/artifact-manifest.json"
ci_diag_mark_pass
log "Nintendo 3DS build complete: ${OUTPUT}"
