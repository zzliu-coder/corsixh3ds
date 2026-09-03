#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

require_cmd cmake
require_cmd python3
require_cmd git
require_cmd rg
require_cmd shasum

ACCEPT_ROOT="${CTH3DS_ROOT}/work/runtime-core-acceptance"
ASAN_BUILD="${CTH3DS_ROOT}/work/runtime-core-acceptance-asan"
EVIDENCE_DIR="${CTH3DS_ROOT}/docs/evidence"
mkdir -p "${ACCEPT_ROOT}" "${EVIDENCE_DIR}"

SOURCE_FINGERPRINT="$(python3 - "${CTH3DS_ROOT}" <<'PY'
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
hasher = hashlib.sha256()
for relative in ("CMakeLists.txt", "include", "lua", "scripts", "src", "tests", "tools"):
    candidate = root / relative
    paths = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
    for path in paths:
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        name = path.relative_to(root).as_posix().encode()
        data = path.read_bytes()
        hasher.update(len(name).to_bytes(4, "big"))
        hasher.update(name)
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
print(hasher.hexdigest())
PY
)"
printf '%s\n' "${SOURCE_FINGERPRINT}" >"${ACCEPT_ROOT}/source-tree.sha256"

set_cmake_generator
CC=clang CXX=clang++ cmake -S "${CTH3DS_ROOT}" -B "${ASAN_BUILD}" \
  "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCTH3DS_ENABLE_SANITIZERS=ON \
  -DCTH3DS_BUILD_TESTS=ON \
  -DCTH3DS_BUILD_SIMULATOR=ON \
  -DCTH3DS_BUILD_3DS_SYNTAX_CHECK=ON \
  -DCTH3DS_WARNINGS_AS_ERRORS=ON \
  >"${ACCEPT_ROOT}/asan-configure.log" 2>&1
cmake --build "${ASAN_BUILD}" --parallel "${CTH3DS_JOBS}" \
  >"${ACCEPT_ROOT}/asan-build.log" 2>&1

# AppleClang on macOS does not provide LeakSanitizer. ASan and UBSan remain
# mandatory, with immediate abort on the first finding.
ASAN_OPTIONS=halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  ctest --test-dir "${ASAN_BUILD}" --output-on-failure \
  >"${ACCEPT_ROOT}/asan-ctest.log" 2>&1

CTH3DS_RUNTIME_CYCLES=10000 \
CTH3DS_RUNTIME_WORKERS=1 \
CTH3DS_RUNTIME_PROBE="${ASAN_BUILD}/cth3ds-runtime-probe" \
PYTHONPATH="${CTH3DS_ROOT}/tools:${CTH3DS_ROOT}/tests" \
ASAN_OPTIONS=halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  python3 -m unittest \
    tests.test_th3ds_runtime_core.Th3dsRuntimeCoreTests.test_generated_bundle_runs_the_production_session_vertical_slice \
    tests.test_th3ds_runtime_core.Th3dsRuntimeCoreTests.test_audio_and_sprite_runtime_reads_are_bounded_and_nonresident \
    -v >"${ACCEPT_ROOT}/vertical-10000.log" 2>&1

[[ -n "${CTH3DS_EXTERNAL_DIR:-}" ]] || die 'CTH3DS_EXTERNAL_DIR is required for final-ELF acceptance'
[[ -n "${CTH3DS_DEPS_PREFIX:-}" ]] || die 'CTH3DS_DEPS_PREFIX is required for final-ELF acceptance'
python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" \
  "${CTH3DS_EXTERNAL_DIR}/CorsixTH" \
  >"${ACCEPT_ROOT}/integrate.log" 2>&1
"${CTH3DS_ROOT}/scripts/build_3ds.sh" --skip-bootstrap \
  >"${ACCEPT_ROOT}/cross-build.log" 2>&1

CROSS_BUILD="${CTH3DS_BUILD_DIR}/CorsixTH"
ELF="${CROSS_BUILD}/CorsixTH/CorsixTH-3DS.elf"
THREEDSX="${CROSS_BUILD}/CorsixTH-3DS.3dsx"
LINK_PROOF="${CROSS_BUILD}/runtime-core-link-proof.json"
HEAP_PROOF="${CROSS_BUILD}/heap-budget.json"
for artifact in "${ELF}" "${THREEDSX}" "${LINK_PROOF}" "${HEAP_PROOF}"; do
  [[ -s "${artifact}" ]] || die "acceptance artifact is missing: ${artifact}"
done
CTH3DS_RUNTIME_LINK_PROOF="${LINK_PROOF}" \
  python3 -m unittest tests.test_final_elf_runtime_core -v \
  >"${ACCEPT_ROOT}/final-elf-tests.log" 2>&1

git -C "${CTH3DS_ROOT}" diff --check
git -C "${CTH3DS_ROOT}" ls-files >"${ACCEPT_ROOT}/tracked-files.txt"
if rg -i '(^|/)(sound-[0-9]+\.dat|lang-[0-9]+\.dat|hospital\.exe)$|\.th3ds(\.json)?$' \
    "${ACCEPT_ROOT}/tracked-files.txt"; then
  die 'tracked game data or generated TH3DS payload found'
fi

ELF_SHA="$(shasum -a 256 "${ELF}" | awk '{print $1}')"
THREEDSX_SHA="$(shasum -a 256 "${THREEDSX}" | awk '{print $1}')"
export CTH3DS_ACCEPT_SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT}"
export CTH3DS_ACCEPT_ELF_SHA="${ELF_SHA}"
export CTH3DS_ACCEPT_3DSX_SHA="${THREEDSX_SHA}"
export CTH3DS_ACCEPT_LINK_PROOF="${LINK_PROOF}"
export CTH3DS_ACCEPT_HEAP_PROOF="${HEAP_PROOF}"
export CTH3DS_ACCEPT_HEAD="$(git -C "${CTH3DS_ROOT}" rev-parse HEAD)"
export CTH3DS_ACCEPT_PLATFORM="$(uname -s)-$(uname -m)"

python3 - "${EVIDENCE_DIR}/runtime-core-acceptance.json" \
  "${EVIDENCE_DIR}/runtime-core-acceptance.md" <<'PY'
import json, os, pathlib, sys
json_path, markdown_path = map(pathlib.Path, sys.argv[1:])
link = json.loads(pathlib.Path(os.environ["CTH3DS_ACCEPT_LINK_PROOF"]).read_text())
heap = json.loads(pathlib.Path(os.environ["CTH3DS_ACCEPT_HEAP_PROOF"]).read_text())
gates = {
    "RH01": "PASS", "RH02": "PASS", "RH03": "PASS", "RH04": "PASS",
    "RH05": "PASS", "RH06": "PASS", "RH07": "PASS", "RH08": "PASS",
    "RH09": "PASS", "RH10": "PASS",
}
gate_evidence = {
    "RH01": "synthetic every-kind converter and C++ mount/typed lookup tests",
    "RH02": "two-root bundle and package SHA-256 equality tests",
    "RH03": "mutation matrix plus AppleClang ASan/UBSan CTest",
    "RH04": "selected-language dependency and unused-language exclusion tests",
    "RH05": "AudioBank bounded stream spy <= 16,384 bytes and zero resident payload",
    "RH06": "SpriteSheet bounded stream spy <= 65,536 bytes and zero unrequested pixels",
    "RH07": "live/pin/dependency/LRU plus 10,000 owner and lifecycle cycles",
    "RH08": "every-pool cap-1/cap/cap+1 arithmetic and atomic rejection tests",
    "RH09": "missing/corrupt package plus save/transition/heap/linear reserve tests",
    "RH10": "tracked-file scan and no-game package/release tests",
}
evidence = {
    "schema": 1,
    "git_head_at_run": os.environ["CTH3DS_ACCEPT_HEAD"],
    "candidate_source_fingerprint": os.environ["CTH3DS_ACCEPT_SOURCE_FINGERPRINT"],
    "platform": os.environ["CTH3DS_ACCEPT_PLATFORM"],
    "host_runtime_core": "PASS",
    "cross_build": "PASS",
    "device": "NOT_PROVEN",
    "leak_sanitizer": "UNAVAILABLE_ON_MACOS",
    "asan_ubsan": "PASS",
    "lifecycle_cycles": 10000,
    "owner_mount_shutdown_cycles": 10000,
    "rh_gates": gates,
    "rh_evidence": gate_evidence,
    "elf_sha256": os.environ["CTH3DS_ACCEPT_ELF_SHA"],
    "three_dsx_sha256": os.environ["CTH3DS_ACCEPT_3DSX_SHA"],
    "heap_proof": heap,
    "final_elf_proof": link,
    "rd_gates": {f"RD{index:02d}": "NOT_PROVEN" for index in range(1, 15)},
    "commands": [
        "AppleClang ASan/UBSan configure, build, and CTest",
        "10,000 generated-bundle RuntimeSession lifecycle cycles",
        "devkitARM --skip-bootstrap final 3DSX build",
        "final ELF symbol and production call-edge proof",
        "git diff --check and tracked game-data scan",
    ],
}
json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
rows = "\n".join(
    f"| {name} | {gates[name]} | {gate_evidence[name]} |" for name in gates
)
rd = ", ".join(f"RD{index:02d}" for index in range(1, 15))
call_path = " → ".join(link["runtime_session_call_path"])
markdown_path.write_text(f"""# Runtime Core acceptance evidence

Candidate source fingerprint: `{evidence['candidate_source_fingerprint']}`<br>
Git HEAD when verification ran: `{evidence['git_head_at_run']}`

Host Runtime Core: **PASS**<br>
devkitARM cross-build: **PASS**<br>
Old 3DS device: **NOT_PROVEN**

| Gate | Result | Evidence |
|---|---|---|
{rows}

AppleClang ASan/UBSan completed with zero findings. LeakSanitizer is unavailable
in AppleClang on macOS and is recorded separately. The generated-bundle vertical
probe completed 10,000 acquire/level/menu/save/suspend/resume cycles and one
production mount/shutdown. A separate 10,000-cycle owner test repeated validated
mount adoption, transition, save and shutdown. Both ended with zero packages,
entries, leases and pins.

Final ELF SHA-256: `{evidence['elf_sha256']}`<br>
3DSX SHA-256: `{evidence['three_dsx_sha256']}`<br>
Linear heap proof: `{heap['valueBytes']}` bytes, strong `{heap['symbolType']}` symbol<br>
Production call path: `{call_path}`

Hardware boundary: {rd} remain **NOT_PROVEN**. Historical `S70 OOM` remains an
unsuperseded device **FAIL**. This run performed no device upload and used no
original game data.
""")
PY

log "Runtime Core host acceptance PASS: ${EVIDENCE_DIR}/runtime-core-acceptance.json"
