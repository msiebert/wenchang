# Spec Review: AIE-1034 — replace_fact

## What & why

Add `MemoryStore.replace_fact(path, old_string, new_string, expected_version)`
so an agent can change one fact line without resending (and risking) the
rest of the file. The anchor must match exactly once. If someone else wrote
the file in the meantime, the edit is re-applied to the fresh content
automatically; the caller only hears about the conflict when that write
touched the anchor itself.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | File at `V`, `old` occurs once | `replace_fact(p, old, new, V)` | Only that span changes; new version; read agrees |
| 2 | File at `V`, `old` occurs 0 / k≥2 times (overlaps count) | same | `ReplaceFactMatchError(content, V, count)`; file unchanged |
| 3 | `old == ""` / malformed path | call | `ValueError` / `NotFoundError(INVALID_PATH)`, no storage call |
| 4 | Caller holds stale `V`; other writer changed a *different* line | call | Succeeds; both changes present |
| 5 | Caller holds stale `V`; other writer changed/removed/duplicated the anchor | call | `VersionConflictError(current content, version)`; unchanged |
| 6 | A write races between read and put, anchor survives | call | Re-applied and succeeds |
| 7 | Put fails 3 times in a row | call | `VersionConflictError` with last-read state |
| 8 | Success with `source=S` | — | Stored metadata carried over, `S` added to `sources`, `last_updated` = clock |
| 8b | `source == ""` | call | `ValueError`, no storage call |
| 9 | Result > `max_file_bytes` | call | `OversizeWriteError(resulting size, limit)`; nothing written |
| 10 | File absent (first read or after a failed put) | call | `NotFoundError(FILE_ABSENT)` |
| 11 | Backend down / corrupt object | call | Error propagates unchanged |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| "Genuine overlap" = anchor no longer matches exactly once in current content | Diff base vs. current (3-way) | Base content is unavailable without GCS object versioning; an anchor test is exact and cheap |
| Stale + non-unique → `VersionConflictError`; current + non-unique → `ReplaceFactMatchError` | Always `ReplaceFactMatchError` | A stale caller should re-read and re-derive, not tweak an anchor against content it hasn't seen |
| Put guarded on the version just read, not the caller's token | Guard on caller's token | That's what re-applying means |
| Count overlapping occurrences | `str.count` (non-overlapping) | `"aa"` in `"aaa"` is ambiguous; `str.count` says 1 |
| Empty `old_string` → `ValueError` | Treat as match error | Empty matches everywhere; no anchor fix exists |
| 3 attempts, internal constant | Unbounded / configurable | Bounded under contention; no caller needs to tune it yet |
| No `metadata` parameter; carry stored metadata | Accept metadata | Signature is fixed by the spec; alias edits go through `write_file` |
| Required keyword-only `source: str`, unioned into `sources` | Leave `sources` alone; optional `source` | Otherwise a replace_fact surface is never recorded; required so no write path skips stamping. Deviation from Notion signature → ADR |

## Files/modules to be touched

- `src/wenchang/core.py` — `replace_fact`
- `tests/test_core_replace_fact.py` — new
- `ARCHITECTURE.md`, `docs/adr/0009-replace-fact-semantics.md`

## Open questions / assumptions

- Resolved: a stale call whose anchor no longer matches raises
  `VersionConflictError` (approved).
- Resolved: `sources` is stamped via a required keyword-only `source`
  argument (raised at review). `append_line` (AIE-1036) should follow suit.

## Risks

- Retry isn't idempotent when `new_string` contains `old_string` (e.g.
  `"foo"` → `"foo bar"`): a retry after a lost response applies twice.
  Accepted as ordinary editing, like duplicate appends; documented in the ADR.
- The anchor test can't see a concurrent edit elsewhere that makes this
  change semantically wrong. That's inherent to span replacement.
