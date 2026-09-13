#!/bin/zsh
# Durable local runner for the focused real-Ollama R19G-K diagnosis gate.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

log_file="/tmp/r19gk_ollama_focus.log"
pid_file="/tmp/r19gk_ollama_focus.pid"
exit_file="/tmp/r19gk_ollama_focus.exit"

: > "$exit_file"
: > "$pid_file"
print -r -- "START $(date -u +%Y-%m-%dT%H:%M:%SZ) R19G-K real-Ollama focus" > "$log_file"
PYTHONUNBUFFERED=1 make r19gk-real-ai >> "$log_file" 2>&1 &
pytest_pid=$!
print -r -- "$pytest_pid" > "$pid_file"

wait "$pytest_pid"
pytest_exit=$?
print -r -- "$pytest_exit" > "$exit_file"
print -r -- "END $(date -u +%Y-%m-%dT%H:%M:%SZ) exit=$pytest_exit" >> "$log_file"
exit "$pytest_exit"
