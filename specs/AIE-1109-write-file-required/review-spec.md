# Spec Review: AIE-1109 — write_file required `source`

## What & why

`write_file` stores whatever `sources` the caller passes, so a replace can
wipe a file's write history and never has to record who wrote it. This adds
a required `source=` argument (like `replace_fact` and `append_line`) and
makes stored `sources` only ever grow. `append_line` already does this, so
only `write_file` changes.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | no file | create, `metadata.sources={}`, `source="chat"` | `sources == {"chat"}` |
| 2 | no file | create, `metadata.sources={"cli"}`, `source="chat"` | `{"cli","chat"}` |
| 3 | stored `{"cli"}` at V | replace at V, `metadata.sources={}`, `source="chat"` | `{"cli","chat"}` |
| 4 | stored `{"cli","api"}` | replace with `metadata.sources={"cli"}`, `source="cli"` | `{"cli","api"}` — can't remove |
| 5 | any | `source=""` | `ValueError`, no storage call |
| 6 | any | `source` omitted / positional | `TypeError` |
| 7 | file at V2 | replace at V1 | `VersionConflictError(current content, V2)` |
| 8 | no file | replace at V | `NotFoundError(FILE_ABSENT)` |
| 9 | write lands between read and put | replace | `VersionConflictError`, other write intact |
| 10 | stored metadata corrupt | replace at V | `MetadataFormatError`, file unchanged |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Replace stores `stored ∪ caller ∪ {source}` | Ignore caller `sources`; reject non-empty caller `sources` | Keeps one `FileMetadata` shape; silently dropping input is surprising; lets a migration seed history |
| Replace reads before its conditional put | Blind put (today) | Can't union the stored set without reading it; the read also gives an early version check |
| Corrupt stored metadata → `MetadataFormatError` | Overwrite with caller's `sources` | Overwriting loses the history this issue protects; matches `replace_fact`/`append_line` |
| No change to `append_line` | Re-touch it | Already has required `source` + union (AIE-1036) |
| Recorded in ADR 0013 | Amend ADR 0009 | New decision, separate record |

## Files/modules to be touched

- `src/wenchang/core.py` — `write_file`
- `tests/test_core_write_file.py` (46 call sites + new tests), `tests/test_core_delete_file.py` (1 call site)
- `ARCHITECTURE.md`, `docs/adr/0013-write-file-source.md`

## Open questions / assumptions

- **Union vs. ignore caller `sources`** — the issue asks for this call; spec picks union. Confirm.
- A corrupt-metadata file can no longer be repaired by `write_file`; it would need `delete_file` + create. Acceptable?

## Risks

- Replace now costs one extra `get`. Negligible at 16 KB files.
- Existing replace tests asserting verbatim `sources` change to union expectations (required by the issue, not a weakening).
