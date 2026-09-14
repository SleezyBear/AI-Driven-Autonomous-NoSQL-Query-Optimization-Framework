#!/usr/bin/env zsh
# Durable wrapper for the final R19 integration/regression acceptance chain.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
log_file="/tmp/r19_acceptance.log"
exit_file="/tmp/r19_acceptance.exit"
pid_file="/tmp/r19_acceptance.pid"

cd "$root"
rm -f "$exit_file" "$pid_file"
print -r -- "START $(date -u +%Y-%m-%dT%H:%M:%SZ) R19 acceptance" > "$log_file"
print -r -- "$$" > "$pid_file"
export PYTHONUNBUFFERED=1
export OLLAMA_TIMEOUT_SECONDS=600

rc=0
make r19-acceptance >> "$log_file" 2>&1 || rc=$?
print -r -- "END $(date -u +%Y-%m-%dT%H:%M:%SZ) exit=$rc" >> "$log_file"
print -r -- "$rc" > "$exit_file"
exit "$rc"
