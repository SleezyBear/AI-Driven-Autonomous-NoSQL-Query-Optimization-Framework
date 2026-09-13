#!/usr/bin/env bash
# Durable local wrapper for the long R19L–P acceptance chain.

set -uo pipefail

repository_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
log_file="/tmp/r19lp_acceptance.log"
exit_file="/tmp/r19lp_acceptance.exit"
pid_file="/tmp/r19lp_acceptance.pid"

cd "$repository_root"
rm -f "$log_file" "$exit_file" "$pid_file"

export PYTHONUNBUFFERED=1
export OLLAMA_TIMEOUT_SECONDS=600

printf 'START %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$log_file"
printf '%s\n' "$$" > "$pid_file"

finish() {
  local rc="$1"
  printf 'END %s exit_code=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$rc" >> "$log_file"
  printf '%s\n' "$rc" > "$exit_file"
}

rc=0
make r19lp-acceptance >> "$log_file" 2>&1 || rc=$?
finish "$rc"
exit "$rc"
