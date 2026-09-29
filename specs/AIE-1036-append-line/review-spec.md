# Spec Review: AIE-1036 — append_line

## What & why

Add `MemoryStore.append_line(path, line, expected_version, *, source)`,
which adds one fact line to the end of an existing memory file, only if the
file is still at `expected_version`. This makes every mutating call
version-guarded. A retried append whose first attempt landed now fails its
guard instead of duplicating the line. The original design was an unguarded
append. It was changed at the spec checkpoint, and Notion and Linear were
updated to match.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | file at `V`, `"- [stated] a\n"` | append `"- [observed] b"` at `V` | content `"…a\n- [observed] b\n"`; returns new content + new version |
| 2 | content lacks a trailing `\n` / is empty | append | one `\n` separator inserted / content is `line\n` |
| 3 | metadata `sources={"cli"}` | append, `source="chat"` | `sources={"cli","chat"}`, `last_updated=clock()`, other fields unchanged |
| 4 | caller holds stale `V1`, file at `V2` | append | `VersionConflictError(current content, V2)`; file unchanged; no re-apply |
| 5 | append at `V` succeeded | identical retry at `V` | `VersionConflictError`; line present exactly once |
| 6 | two callers both hold `V` | both append | first lands, second conflicts; retry with new version lands; both lines once |
| 7 | own write landed but the backend retry saw a 412 | append | stored bytes + metadata equal what was written → returns success, no second append |
| 8 | malformed path | append | `NotFoundError(INVALID_PATH)`, no storage call |
| 9 | file doesn't exist | append | `NotFoundError(FILE_ABSENT)`, nothing created |
| 10 | line not exactly one fact line, or `source=""` | append | `ValueError`, no storage call |
| 11 | result exceeds `max_file_bytes` | append at current version | `OversizeWriteError(size, limit)`; exactly at the limit succeeds |
| 12 | backend error / corrupt metadata | append | propagates unchanged |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Required `expected_version` (deviates from Notion; ADR 0011) | Unguarded (Notion); optional token | Every write is guarded, and retries never duplicate. The cost is that concurrent appends conflict instead of commuting. |
| No automatic re-apply on a stale token | Re-apply like `replace_fact` | Re-applying an append always succeeds, so a landed-then-retried append would duplicate again. |
| Landed check after a 412 | Always raise a conflict | The GCS client retries conditional uploads itself. Without the check, a lost response would surface as a spurious conflict. |
| Missing file → `FILE_ABSENT` | Implicit create | A created file would have no description or aliases, the only search surface. |
| `line` must parse as exactly one fact line | Any text; multiple lines | The verb is "add a fact line", and the check is exact. |
| Required keyword-only `source` | Optional / none | Follows ADR 0009 and `replace_fact`. |

## Files/modules to be touched

- `src/wenchang/core.py` — `append_line`
- `tests/test_core_append_line.py` — new
- `ARCHITECTURE.md`, `docs/adr/0011-append-line-version-guard.md`

## Open questions / assumptions

- Notion (Sections 5, 10.2, 11) and the Linear issue were updated
  2026-09-29 to specify the guarded append.
- `[system]` label isn't rejected here. Label policy stays in the prompt
  layer, and `system/` path enforcement is AIE-1040.

## Risks

- Agents appending to a busy shared file now take a conflict and retry turn.
  Tool wording (AIE-1044) must present that as routine.
- Each append rewrites the whole file (≤16 KB).
