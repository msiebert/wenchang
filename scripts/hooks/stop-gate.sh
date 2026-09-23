#!/usr/bin/env bash
# Stop hook: enforces `make check` and guards against test tampering before
# the agent is allowed to stop. Portable to macOS bash 3.2 and Linux.
set -euo pipefail

if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    REPO_ROOT="$(CDPATH="" cd "$CLAUDE_PROJECT_DIR" && pwd)"
else
    REPO_ROOT="$(CDPATH="" cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
cd "$REPO_ROOT"

INPUT="$(cat)"

extract_bool_field() {
    local field="$1"
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$INPUT" | jq -r --arg f "$field" '.[$f] // false' 2>/dev/null
    elif command -v python3 >/dev/null 2>&1; then
        printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print('false')
    sys.exit(0)
print(str(bool(data.get('$field', False))).lower())
"
    else
        echo "false"
    fi
}

STOP_HOOK_ACTIVE="$(extract_bool_field stop_hook_active)"
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    exit 0
fi

# Resolve a base to diff against: prefer the merge-base with main, else HEAD.
if git rev-parse --verify main >/dev/null 2>&1; then
    BASE_REF="$(git merge-base HEAD main 2>/dev/null || true)"
fi
if [ -z "${BASE_REF:-}" ]; then
    BASE_REF="HEAD"
fi

# Committed + staged + unstaged changes under src/ or tests/, plus untracked files.
CHANGED_FILES="$(git diff --name-only "$BASE_REF" -- src tests 2>/dev/null || true)"
UNTRACKED_FILES="$(git ls-files --others --exclude-standard -- src tests 2>/dev/null || true)"

if [ -z "$CHANGED_FILES" ] && [ -z "$UNTRACKED_FILES" ]; then
    exit 0
fi

# --- Test tampering detection -------------------------------------------
DIFF_TEXT="$(git diff "$BASE_REF" -- tests 2>/dev/null || true)"
TAMPER_REASONS=""

DELETED_TEST_FILES="$(git diff --diff-filter=D --name-only "$BASE_REF" -- tests 2>/dev/null | grep -E '(^|/)(test_[^/]*\.py|[^/]*_test\.py)$' || true)"
if [ -n "$DELETED_TEST_FILES" ]; then
    TAMPER_REASONS="${TAMPER_REASONS}deleted test file(s):
${DELETED_TEST_FILES}
"
fi

ADDED_TEST_DEFS="$(printf '%s\n' "$DIFF_TEXT" | grep -Ec '^[+][[:space:]]*def test_' || true)"
ADDED_TEST_DEFS="${ADDED_TEST_DEFS:-0}"
REMOVED_TEST_DEFS="$(printf '%s\n' "$DIFF_TEXT" | grep -Ec '^-[[:space:]]*def test_' || true)"
REMOVED_TEST_DEFS="${REMOVED_TEST_DEFS:-0}"
if [ "${REMOVED_TEST_DEFS:-0}" -gt "${ADDED_TEST_DEFS:-0}" ]; then
    TAMPER_REASONS="${TAMPER_REASONS}net removal of test functions (removed ${REMOVED_TEST_DEFS}, added ${ADDED_TEST_DEFS})
"
fi

NEW_SKIPS="$(printf '%s\n' "$DIFF_TEXT" | grep -E '^[+]' | grep -E 'pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(' || true)"
if [ -n "$NEW_SKIPS" ]; then
    TAMPER_REASONS="${TAMPER_REASONS}newly added skip/xfail marker(s):
${NEW_SKIPS}
"
fi

# Also scan untracked test files (not yet tracked by git, so they won't show
# up in the diff above) for skip/xfail markers. Read line by line and quote
# paths so filenames with spaces or globs are handled safely; a plain
# for-loop over an unquoted variable would word-split and glob-expand them.
UNTRACKED_TEST_FILES="$(git ls-files --others --exclude-standard -- tests 2>/dev/null || true)"
UNTRACKED_SKIP_MATCHES=""
if [ -n "$UNTRACKED_TEST_FILES" ]; then
    while IFS= read -r utf; do
        [ -z "$utf" ] && continue
        [ -f "$utf" ] || continue
        MATCH="$(grep -nE 'pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(' "$utf" 2>/dev/null || true)"
        if [ -n "$MATCH" ]; then
            UNTRACKED_SKIP_MATCHES="${UNTRACKED_SKIP_MATCHES}${utf}:
${MATCH}
"
        fi
    done <<EOF
$UNTRACKED_TEST_FILES
EOF
fi
if [ -n "$UNTRACKED_SKIP_MATCHES" ]; then
    TAMPER_REASONS="${TAMPER_REASONS}newly added skip/xfail marker(s) in untracked test file(s):
${UNTRACKED_SKIP_MATCHES}"
fi

if [ -n "$TAMPER_REASONS" ]; then
    ALLOWED=false
    CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    LINEAR_ID="$(printf '%s' "$CURRENT_BRANCH" | grep -Eo 'AIE-[0-9]+' | head -1 || true)"
    if [ -n "$LINEAR_ID" ]; then
        for spec_file in "$REPO_ROOT"/specs/"$LINEAR_ID"*/spec.md; do
            [ -f "$spec_file" ] || continue
            if grep -q '^Allow-test-changes:' "$spec_file"; then
                ALLOWED=true
                break
            fi
        done
    fi

    if [ "$ALLOWED" != true ]; then
        echo "Stop blocked: possible test tampering detected." >&2
        echo "$TAMPER_REASONS" >&2
        echo "Restore the affected tests, or if the spec for this issue explicitly" >&2
        echo "requires this change, add a line 'Allow-test-changes:' to the spec's" >&2
        echo "spec.md explaining why, then retry." >&2
        exit 2
    fi
fi

# --- make check gate ------------------------------------------------------
# Fail closed: if we can't actually run `make check`, block the stop rather
# than silently letting it through.
if ! command -v make >/dev/null 2>&1; then
    echo "Stop blocked: 'make' was not found on PATH, so 'make check' cannot be run." >&2
    echo "Install make, or otherwise ensure 'make check' can run, then retry." >&2
    exit 2
fi

if [ ! -f Makefile ] || ! grep -q '^check:' Makefile 2>/dev/null; then
    echo "Stop blocked: no 'check:' target found in Makefile, so 'make check' cannot be verified." >&2
    echo "Add a 'check:' target to the Makefile, then retry." >&2
    exit 2
fi

CHECK_STATUS=0
CHECK_OUTPUT="$(make check 2>&1)" || CHECK_STATUS=$?

if [ "$CHECK_STATUS" -ne 0 ]; then
    echo "Stop blocked: 'make check' failed. Fix the issues before stopping." >&2
    echo "--- tail of make check output ---" >&2
    printf '%s\n' "$CHECK_OUTPUT" | tail -60 >&2
    exit 2
fi

exit 0
