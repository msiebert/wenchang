#!/usr/bin/env bash
# PostToolUse hook for Edit|Write|MultiEdit.
#
# Reads the hook JSON payload from stdin, and if the edited file is a .py
# file under the repo, runs ruff format, ruff check --fix, then pyright on
# it. Any remaining pyright error exits 2 with a concise message on stderr
# so the model sees it and fixes it.
set -euo pipefail

if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    REPO_ROOT="$(CDPATH="" cd "$CLAUDE_PROJECT_DIR" && pwd)"
else
    REPO_ROOT="$(CDPATH="" cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

INPUT="$(cat)"

extract_file_path() {
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null
    elif command -v python3 >/dev/null 2>&1; then
        printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(data.get("tool_input", {}).get("file_path", "") or "")
'
    else
        echo ""
    fi
}

FILE_PATH="$(extract_file_path)"

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

case "$FILE_PATH" in
    *.py) ;;
    *) exit 0 ;;
esac

# Normalize to an absolute path and confirm it is under the repo.
case "$FILE_PATH" in
    /*) ABS_PATH="$FILE_PATH" ;;
    *) ABS_PATH="$REPO_ROOT/$FILE_PATH" ;;
esac

case "$ABS_PATH" in
    "$REPO_ROOT"/*) ;;
    *) exit 0 ;;
esac

if [ ! -f "$ABS_PATH" ]; then
    exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "post-edit hook: 'uv' was not found on PATH; cannot run ruff/pyright." >&2
    exit 2
fi

cd "$REPO_ROOT"

# Guard each tool with a timeout so a hang doesn't block the agent forever.
# Prefer GNU coreutils' `timeout`; macOS without coreutils only has
# `gtimeout` (via `brew install coreutils`), and if neither exists run bare.
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout 120"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout 120"
fi

$TIMEOUT_CMD uv run ruff format "$ABS_PATH" >/dev/null 2>&1 || true
$TIMEOUT_CMD uv run ruff check --fix "$ABS_PATH" >/dev/null 2>&1 || true

PYRIGHT_OUTPUT="$($TIMEOUT_CMD uv run pyright "$ABS_PATH" 2>&1)" && exit 0

echo "pyright reported errors in $FILE_PATH; fix them before continuing:" >&2
echo "$PYRIGHT_OUTPUT" >&2
exit 2
