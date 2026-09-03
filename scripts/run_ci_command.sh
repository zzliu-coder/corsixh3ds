#!/usr/bin/env bash
set -euo pipefail
set -E

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source "$(cd "$(dirname "$0")" && pwd)/ci_diagnostics.sh"

[[ $# -ge 4 ]] || die 'usage: run_ci_command.sh MATRIX OUTPUT_DIR -- COMMAND [ARG ...]'
MATRIX="$1"
OUTPUT_DIR="$2"
shift 2
[[ "$1" == "--" ]] || die 'missing -- before command'
shift
[[ $# -gt 0 ]] || die 'missing command'

LOG_FILE="${OUTPUT_DIR}/command.log"
ci_diag_init "${MATRIX}" "${OUTPUT_DIR}"
ci_diag_step command "${LOG_FILE}"

trap - ERR
set +e
"$@" > >(tee "${LOG_FILE}") 2>&1
STATUS=$?
set -e
if [[ "${STATUS}" -ne 0 ]]; then
  COMMAND_TEXT="$(printf '%q ' "$@")"
  ci_diag_emit_failure "${STATUS}" "${COMMAND_TEXT% }"
  exit "${STATUS}"
fi

ci_diag_mark_pass
