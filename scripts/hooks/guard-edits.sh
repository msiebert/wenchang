#!/usr/bin/env bash
# PreToolUse hook for Edit|Write|MultiEdit|NotebookEdit: restricts which paths
# each caller (main session vs. named subagent) may write to. Portable to
# macOS bash 3.2 and Linux. Exit 2 (with a stderr reason) blocks the tool
# call; exit 0 allows it.
set -euo pipefail

if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    REPO_ROOT="$(CDPATH="" cd "$CLAUDE_PROJECT_DIR" && pwd)"
else
    REPO_ROOT="$(CDPATH="" cd "$(git rev-parse --show-toplevel)" && pwd)"
fi

INPUT="$(cat)"

# Pull a top-level string field out of the JSON payload, or a nested one via
# a dotted path (e.g. "tool_input.file_path"). Empty string if absent.
extract_field() {
    local field="$1"
    if command -v jq >/dev/null 2>&1; then
        printf '%s' "$INPUT" | jq -r --arg f "$field" '
            ($f | split(".")) as $path
            | getpath($path) // empty' 2>/dev/null
    elif command -v python3 >/dev/null 2>&1; then
        printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cur = data
for part in '$field'.split('.'):
    if not isinstance(cur, dict) or part not in cur:
        cur = None
        break
    cur = cur[part]
if cur is not None:
    print(cur)
"
    fi
}

TOOL_NAME="$(extract_field tool_name)"
FILE_PATH="$(extract_field tool_input.file_path)"
if [ -z "$FILE_PATH" ] && [ "$TOOL_NAME" = "NotebookEdit" ]; then
    FILE_PATH="$(extract_field tool_input.notebook_path)"
fi
AGENT_TYPE="$(extract_field agent_type)"

# Namespaced agent types (e.g. "plugin:implementer") match on the part after
# the last colon.
if [ -n "$AGENT_TYPE" ]; then
    AGENT_TYPE="${AGENT_TYPE##*:}"
fi

# Nothing to check (no file path resolved) -> allow.
if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Resolve FILE_PATH to an absolute path without requiring the file to exist,
# then normalize it relative to the repo root.
resolve_path() {
    local p="$1"
    case "$p" in
        /*) printf '%s\n' "$p" ;;
        *)  printf '%s\n' "$REPO_ROOT/$p" ;;
    esac
}

ABS_PATH="$(resolve_path "$FILE_PATH")"

# Collapse "./", "//" and ".." segments without requiring the path to exist
# (so realpath/readlink -f, which need an existing target, won't work here).
# ".." pops the previous component and is dropped once the stack is empty —
# it can never climb above "/". Uses indexed-array assignment by position
# (not "+=", which needs bash 4+) to stay compatible with bash 3.2.
normalize_path() {
    local path="$1"
    local IFS='/'
    local part
    local -a parts
    local idx=0
    # shellcheck disable=SC2086
    set -- $path
    for part in "$@"; do
        case "$part" in
            ""|".") continue ;;
            "..")
                if [ "$idx" -gt 0 ]; then
                    idx=$((idx - 1))
                fi
                ;;
            *)
                parts[$idx]="$part"
                idx=$((idx + 1))
                ;;
        esac
    done
    local out=""
    local i=0
    while [ "$i" -lt "$idx" ]; do
        out="${out}/${parts[$i]}"
        i=$((i + 1))
    done
    if [ -z "$out" ]; then
        out="/"
    fi
    printf '%s\n' "$out"
}

NORM_ABS_PATH="$(normalize_path "$ABS_PATH")"
NORM_REPO_ROOT="$(normalize_path "$REPO_ROOT")"

# Path outside the repo root -> not our concern, allow.
case "$NORM_ABS_PATH" in
    "$NORM_REPO_ROOT"|"$NORM_REPO_ROOT"/*) ;;
    *) exit 0 ;;
esac

# Relative path from repo root, used for glob-style matching below.
REL_PATH="${NORM_ABS_PATH#"$NORM_REPO_ROOT"/}"

# macOS's default filesystem (APFS/HFS+) is case-insensitive, so "Src/a.py"
# and "src/a.py" are the same file on disk. All pattern matching below runs
# on a lowercased copy of the path (and of each pattern); REL_PATH itself is
# kept as-is for messages.
lc() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

REL_PATH_LC="$(lc "$REL_PATH")"

# Simple glob matcher: supports a leading "dir/**" (dir and everything under
# it) and "dir/*" (direct children only), plus plain literal/glob paths via
# bash's own case-pattern matching. Callers pass an already-lowercased rel
# path; the pattern is lowercased here.
path_matches() {
    local rel="$1"
    local pattern
    pattern="$(lc "$2")"
    case "$pattern" in
        */\*\*)
            local prefix="${pattern%/\*\*}"
            case "$rel" in
                "$prefix"|"$prefix"/*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        *)
            case "$rel" in
                $pattern) return 0 ;;
                *) return 1 ;;
            esac
            ;;
    esac
}

path_matches_any() {
    local rel="$1"
    shift
    local pattern
    for pattern in "$@"; do
        if path_matches "$rel" "$pattern"; then
            return 0
        fi
    done
    return 1
}

deny() {
    echo "$1" >&2
    exit 2
}

# --- Rule 1: protected for everyone, regardless of caller -------------------
PROTECTED_PATTERNS=(
    ".claude/settings.json"
    ".claude/settings.local.json"
    "scripts/hooks/**"
    ".env*"
)
if path_matches_any "$REL_PATH_LC" "${PROTECTED_PATTERNS[@]}"; then
    deny "guard-edits: '$REL_PATH' is protected — edit these by hand."
fi

# --- Rule 2: main session (no agent_type) — the orchestrator ---------------
if [ -z "$AGENT_TYPE" ]; then
    if [ "${WENCHANG_ALLOW_MAIN_EDITS:-}" = "1" ]; then
        exit 0
    fi
    if path_matches_any "$REL_PATH_LC" "specs/**"; then
        exit 0
    fi
    deny "guard-edits: The orchestrator delegates edits: use test-writer for tests/, implementer for src/, doc-updater for docs. Set WENCHANG_ALLOW_MAIN_EDITS=1 when launching Claude to edit directly."
fi

# --- Rule 3: test-writer ----------------------------------------------------
if [ "$AGENT_TYPE" = "test-writer" ]; then
    if path_matches_any "$REL_PATH_LC" "tests/**"; then
        exit 0
    fi
    deny "guard-edits: test-writer may only edit tests/** (attempted '$REL_PATH')."
fi

# --- Rule 4: implementer -----------------------------------------------------
if [ "$AGENT_TYPE" = "implementer" ]; then
    if path_matches_any "$REL_PATH_LC" "src/**" "pyproject.toml" "uv.lock" "Makefile"; then
        exit 0
    fi
    deny "guard-edits: implementer may only edit src/**, pyproject.toml, uv.lock, or Makefile (attempted '$REL_PATH')."
fi

# --- Rule 5: doc-updater -----------------------------------------------------
if [ "$AGENT_TYPE" = "doc-updater" ]; then
    if path_matches_any "$REL_PATH_LC" "ARCHITECTURE.md" "README.md" "docs/**" "specs/**"; then
        exit 0
    fi
    deny "guard-edits: doc-updater may only edit ARCHITECTURE.md, README.md, docs/**, or specs/** (attempted '$REL_PATH')."
fi

# --- Rule 6: any other agent_type (explorer, spec-reviewer, general-purpose,
# Explore, Plan, unknown, etc.) ----------------------------------------------
if path_matches_any "$REL_PATH_LC" "src/**" "tests/**"; then
    deny "guard-edits: agent type '$AGENT_TYPE' may not edit src/** or tests/** (attempted '$REL_PATH')."
fi

exit 0
