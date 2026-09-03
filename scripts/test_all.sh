#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

LOG_DIR="${CTH3DS_ROOT}/artifacts/verification"
PREVIEW_DIR="${CTH3DS_ROOT}/artifacts/preview"
VERIFY_RESUME="${CTH3DS_VERIFY_RESUME:-0}"
require_cmd python3
SOURCE_FINGERPRINT="$(python3 - "${CTH3DS_ROOT}" <<'PY'
from __future__ import annotations
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
roots = [
    root / "CMakeLists.txt",
    root / "VERSION",
    root / "include",
    root / "src",
    root / "tests",
    root / "tools",
    root / "lua",
    root / "config",
    root / "scripts",
    root / "cmake",
    root / "integrations",
]
files: list[pathlib.Path] = []
for candidate in roots:
    if candidate.is_file():
        files.append(candidate)
    elif candidate.is_dir():
        files.extend(
            path for path in candidate.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )

hasher = hashlib.sha256()
for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix().encode("utf-8")
    payload = path.read_bytes()
    hasher.update(len(relative).to_bytes(4, "big"))
    hasher.update(relative)
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)
print(hasher.hexdigest())
PY
)"
if [[ "${VERIFY_RESUME}" != "1" ]]; then
  rm -rf "${LOG_DIR}" "${PREVIEW_DIR}"
fi
mkdir -p "${LOG_DIR}" "${PREVIEW_DIR}"
printf '%s\n' "${SOURCE_FINGERPRINT}" >"${LOG_DIR}/source.sha256"

CTH3DS_ASAN_LEAKS_OPTION="${CTH3DS_ASAN_LEAKS_OPTION:-}"
if [[ -z "${CTH3DS_ASAN_LEAKS_OPTION}" && "$(uname -s)" != "Darwin" ]]; then
  CTH3DS_ASAN_LEAKS_OPTION=':detect_leaks=1'
fi

configure_build_test() {
  local name="$1" cc="$2" cxx="$3" build_type="$4" sanitizers="$5"
  local build="${CTH3DS_ROOT}/build-verify-${name}"
  local fingerprint_file="${LOG_DIR}/${name}-source.sha256"
  if [[ "${VERIFY_RESUME}" == "1" && -f "${fingerprint_file}" &&
        "$(cat "${fingerprint_file}")" == "${SOURCE_FINGERPRINT}" &&
        -f "${LOG_DIR}/${name}-ctest.log" &&
        -s "${LOG_DIR}/${name}-simulator/top.ppm" ]] &&
        grep -q '100% tests passed, 0 tests failed' "${LOG_DIR}/${name}-ctest.log"; then
    log "verification matrix already complete for current source: ${name}"
    return
  fi
  rm -rf "${build}"
  set_cmake_generator
  log "verification matrix: ${name}"
  CC="${cc}" CXX="${cxx}" cmake -S "${CTH3DS_ROOT}" -B "${build}" "${CTH3DS_CMAKE_GENERATOR[@]}" \
    -DCMAKE_BUILD_TYPE="${build_type}" \
    -DCTH3DS_BUILD_TESTS=ON \
    -DCTH3DS_BUILD_SIMULATOR=ON \
    -DCTH3DS_BUILD_3DS_SYNTAX_CHECK=ON \
    -DCTH3DS_WARNINGS_AS_ERRORS=ON \
    -DCTH3DS_ENABLE_SANITIZERS="${sanitizers}" \
    >"${LOG_DIR}/${name}-configure.log" 2>&1
  cmake --build "${build}" --parallel "${CTH3DS_JOBS}" \
    >"${LOG_DIR}/${name}-build.log" 2>&1
  if [[ "${sanitizers}" == "ON" ]]; then
    # Apple ships AddressSanitizer without LeakSanitizer support. Enabling
    # detect_leaks there aborts every sanitized test before it starts.
    ASAN_OPTIONS="halt_on_error=1${CTH3DS_ASAN_LEAKS_OPTION:-}" \
    UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
      ctest --test-dir "${build}" --output-on-failure \
      >"${LOG_DIR}/${name}-ctest.log" 2>&1
  else
    ctest --test-dir "${build}" --output-on-failure \
      >"${LOG_DIR}/${name}-ctest.log" 2>&1
  fi
  "${build}/cth3ds-tests" >"${LOG_DIR}/${name}-cpp-tests.log" 2>&1
  "${build}/cth3ds-simulator" "${LOG_DIR}/${name}-simulator" \
    >"${LOG_DIR}/${name}-simulator.log" 2>&1
  printf '%s\n' "${SOURCE_FINGERPRINT}" >"${fingerprint_file}"
}

require_cmd cmake
require_cmd gcc
require_cmd g++
configure_build_test gcc-debug gcc g++ Debug OFF
configure_build_test gcc-release gcc g++ Release OFF
configure_build_test gcc-sanitized gcc g++ Debug ON
if command -v clang >/dev/null 2>&1 && command -v clang++ >/dev/null 2>&1; then
  configure_build_test clang-debug clang clang++ Debug OFF
else
  log 'clang unavailable; clang matrix skipped'
fi

# Catch flaky state transitions without repeatedly starting the Python runtime.
ctest --test-dir "${CTH3DS_ROOT}/build-verify-gcc-debug" \
  -R '^cth3ds-tests$' --repeat until-fail:50 --output-on-failure \
  >"${LOG_DIR}/repeat-50.log" 2>&1

PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  "${CTH3DS_ROOT}/tools" "${CTH3DS_ROOT}/tests" \
  >"${LOG_DIR}/python-compileall.log" 2>&1
PYTHONPATH="${CTH3DS_ROOT}/tools" \
CTH3DS_SIMULATOR="${CTH3DS_ROOT}/build-verify-gcc-debug/cth3ds-simulator" \
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s "${CTH3DS_ROOT}/tests" -p 'test_*.py' -v \
  >"${LOG_DIR}/python-tests.log" 2>&1

# The device present path is compiled for the real CPU and inspected here: an
# ARM11 has no hardware divider, so a division that creeps back into the
# framebuffer copy would silently cost tens of milliseconds per frame again.
ARM_CHECK_EXECUTED=0
if "${CTH3DS_ROOT}/scripts/check_arm_codegen.sh" >"${LOG_DIR}/arm-codegen.log" 2>&1; then
  if grep -q 'ARM codegen check passed' "${LOG_DIR}/arm-codegen.log"; then
    ARM_CHECK_EXECUTED=1
  fi
else
  cat "${LOG_DIR}/arm-codegen.log" >&2
  die 'ARM codegen check failed'
fi

SHELL_COUNT=0
for script in "${CTH3DS_ROOT}"/scripts/*.sh; do
  bash -n "${script}"
  SHELL_COUNT=$((SHELL_COUNT + 1))
done
python3 "${CTH3DS_ROOT}/tools/check_pins.py" --json \
  >"${LOG_DIR}/pins.json"

ACTUAL_API_CHECKED=0
UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
if [[ -d "${UPSTREAM_DIR}" ]]; then
  python3 "${CTH3DS_ROOT}/tools/check_upstream_lua_api.py" "${UPSTREAM_DIR}" --json \
    >"${LOG_DIR}/upstream-lua-api.json"
  ACTUAL_API_CHECKED=1
else
  printf '{"ok": false, "skipped": true, "reason": "pinned upstream checkout is absent"}\n' \
    >"${LOG_DIR}/upstream-lua-api.json"
fi

python3 "${CTH3DS_ROOT}/tools/make_preview.py" \
  "${LOG_DIR}/gcc-debug-simulator/top.ppm" \
  "${LOG_DIR}/gcc-debug-simulator/bottom.ppm" \
  "${PREVIEW_DIR}/dual-screen-preview.png" \
  >"${LOG_DIR}/preview.log" 2>&1
cp "${LOG_DIR}/gcc-debug-simulator/trace.json" "${PREVIEW_DIR}/trace.json"

CROSS_EXECUTED=0
CROSS_SKIP_REASON=""
VERIFY_CROSS="${CTH3DS_VERIFY_CROSS:-auto}"
if [[ "${VERIFY_CROSS}" == "0" || "${VERIFY_CROSS}" == "off" ]]; then
  CROSS_SKIP_REASON="cross-build disabled by CTH3DS_VERIFY_CROSS"
elif [[ -z "${DEVKITPRO:-}" || ! -f "${DEVKITPRO}/cmake/3DS.cmake" ]]; then
  CROSS_SKIP_REASON="devkitPro/devkitARM is unavailable in this environment"
elif [[ ! -f "${UPSTREAM_DIR}/CorsixTH/Src/3ds/integration-manifest.json" ]]; then
  CROSS_SKIP_REASON="integrated pinned CorsixTH checkout is unavailable"
elif [[ ! -f "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" ]]; then
  CROSS_SKIP_REASON="staged 3DS dependency libraries are unavailable"
else
  "${CTH3DS_ROOT}/scripts/build_3ds.sh" --skip-bootstrap \
    >"${LOG_DIR}/old3ds-cross-build.log" 2>&1
  CROSS_EXECUTED=1
fi

export CTH3DS_VERIFY_ARM_CHECK="${ARM_CHECK_EXECUTED}"
export CTH3DS_VERIFY_SHELL_COUNT="${SHELL_COUNT}"
export CTH3DS_VERIFY_ACTUAL_API="${ACTUAL_API_CHECKED}"
export CTH3DS_VERIFY_CROSS_EXECUTED="${CROSS_EXECUTED}"
export CTH3DS_VERIFY_CROSS_SKIP="${CROSS_SKIP_REASON}"
python3 - "${CTH3DS_ROOT}" "${LOG_DIR}" <<'PY'
from __future__ import annotations
import hashlib, json, os, pathlib, platform, re, shutil, subprocess, sys
root = pathlib.Path(sys.argv[1])
logs = pathlib.Path(sys.argv[2])
matrices = []
for path in sorted(logs.glob('*-ctest.log')):
    name = path.name[:-len('-ctest.log')]
    text = path.read_text(errors='replace')
    match = re.search(r'(\d+)% tests passed, (\d+) tests failed out of (\d+)', text)
    matrices.append({
        'name': name,
        'ctest_total': int(match.group(3)) if match else None,
        'ctest_failed': int(match.group(2)) if match else None,
    })
cpp_text = (logs / 'gcc-debug-cpp-tests.log').read_text(errors='replace')
cpp_match = re.search(r'Ran (\d+) tests; (\d+) failed', cpp_text)
py_text = (logs / 'python-tests.log').read_text(errors='replace')
py_match = re.search(r'Ran (\d+) tests', py_text)
skipped_match = re.search(r'OK \(skipped=(\d+)\)', py_text)
frames = {}
for name in ('top.ppm', 'bottom.ppm', 'trace.json'):
    path = logs / 'gcc-debug-simulator' / name
    frames[name] = hashlib.sha256(path.read_bytes()).hexdigest()
summary = {
    'format': 2,
    'version': (root / 'VERSION').read_text().strip(),
    'platform': platform.platform(),
    'python': platform.python_version(),
    'cmake': subprocess.check_output(['cmake', '--version'], text=True).splitlines()[0],
    'gcc': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
    'clang': subprocess.run(['clang++', '--version'], text=True, capture_output=True).stdout.splitlines()[0] if shutil.which('clang++') else None,
    'matrices': matrices,
    'cpp_tests': int(cpp_match.group(1)) if cpp_match else None,
    'cpp_failed': int(cpp_match.group(2)) if cpp_match else None,
    'python_tests': int(py_match.group(1)) if py_match else None,
    'python_skipped': int(skipped_match.group(1)) if skipped_match else 0,
    'repeat_count': 50,
    'shell_scripts_checked': int(os.environ['CTH3DS_VERIFY_SHELL_COUNT']),
    'pins_validated': True,
    'arm_codegen_checked': os.environ['CTH3DS_VERIFY_ARM_CHECK'] == '1',
    'actual_upstream_api_checked': os.environ['CTH3DS_VERIFY_ACTUAL_API'] == '1',
    'simulator_sha256': frames,
    'preview': 'artifacts/preview/dual-screen-preview.png',
    'true_3ds_cross_build_executed': os.environ['CTH3DS_VERIFY_CROSS_EXECUTED'] == '1',
    'cross_build_skip_reason': os.environ['CTH3DS_VERIFY_CROSS_SKIP'],
    'hardware_tests_executed': False,
}
(logs / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
print(json.dumps(summary, indent=2, sort_keys=True))
PY
python3 "${CTH3DS_ROOT}/tools/write_verification_report.py" \
  "${LOG_DIR}/summary.json" "${LOG_DIR}/report.md"
cp "${LOG_DIR}/report.md" "${CTH3DS_ROOT}/docs/VM_VERIFICATION.md"
log "verification complete: ${LOG_DIR}/summary.json"
