#!/bin/zsh
# Durable local runner for the complete R19G-K acceptance chain.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

log_file="/tmp/r19gk_acceptance.log"
pid_file="/tmp/r19gk_acceptance.pid"
exit_file="/tmp/r19gk_acceptance.exit"

: > "$exit_file"
: > "$pid_file"
print -r -- "START $(date -u +%Y-%m-%dT%H:%M:%SZ) R19G-K acceptance" > "$log_file"
print -r -- "$$" > "$pid_file"
PYTHONUNBUFFERED=1 OLLAMA_TIMEOUT_SECONDS=600 make r19gk-acceptance >> "$log_file" 2>&1
acceptance_exit=$?
print -r -- "$acceptance_exit" > "$exit_file"
print -r -- "END $(date -u +%Y-%m-%dT%H:%M:%SZ) exit=$acceptance_exit" >> "$log_file"
exit "$acceptance_exit"
