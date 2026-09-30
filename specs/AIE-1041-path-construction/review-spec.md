# Spec Review: AIE-1041 — Path construction from scope and entity ID

## What & why

Callers building or splitting memory paths would otherwise format
`scope/entity_id/area/name.md` by hand. This adds `build_path`,
`build_prefix`, `parse_path`, and a `PathParts` value to `wenchang.paths`.
Building and parsing are exact inverses, and the area segment becomes
extractable for `system/` enforcement later. Paths stay relative to the
storage root, so `{root}` never appears.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `"user","u_42","preferences","editor"` | `build_path` | `"user/u_42/preferences/editor.md"` |
| 2 | segment `""`, `"."`, `".."`, or with `/`, `\`, Cc char | `build_path` | `ValueError` naming first bad arg |
| 3 | name `"b.md"`, `"."`, `".."` | `build_path` | `".md"` appended: `b.md.md`, `..md`, `...md` |
| 4 | decomposed `"café"` | `build_path` | used verbatim, no NFC |
| 5 | `"user"` / `+"u_42"` / `+"preferences"` | `build_prefix` | `"user/"`, `"user/u_42/"`, `"user/u_42/preferences/"` |
| 6 | `area` set, `entity_id` `None` | `build_prefix` | `ValueError("area requires entity_id")`, before segment checks |
| 7 | `""` as entity ID or area | `build_prefix` | `ValueError`; only `None` means omitted |
| 8 | `"u/e/a/b.md.md"` | `parse_path` | `PathParts("u","e","a","b.md")` |
| 9 | any string `is_valid_path` rejects | `parse_path` | `ValueError` |
| 10 | any valid parts / any valid path | build then parse / parse then build | identical result |

## Key design decisions

All five were settled by the human on 2026-09-30.

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Always append `".md"` to the name | Reject names ending `.md`; strip it | Rejecting breaks parse-then-build for stored `b.md.md`; stripping merges two files |
| Allow `"."` and `".."` as names | Reject in builder; tighten `is_valid_path` | Keeps the inverse laws; keys are flat strings, so no traversal |
| Raise `ValueError` | `NotFoundError(INVALID_PATH)` | Internal helpers; agent-facing callers convert or pre-validate |
| No identity-aware helper | Helper in `paths`; helper in scope module | Keeps `paths` dependency-free; scope lookup belongs to the scope layer |
| `""` is invalid in `build_prefix` | Treat `""` as omitted | A missing value must never widen a listing |
| Recorded in ADR 0015 | Amend ADR 0007 | New decision, separate record |

## Files/modules to be touched

- `src/wenchang/paths.py` — `PathParts`, `build_path`, `build_prefix`, `parse_path`
- `tests/test_paths_build.py` (new); `tests/test_paths.py` unchanged
- `ARCHITECTURE.md`, `docs/adr/0015-path-construction.md`

## Open questions / assumptions

- Depends on AIE-1043's public `is_valid_segment`, which rejects `"/"`. T1
  stops if it isn't merged.
- `PathParts` does no validation of its own. Only `parse_path` guarantees
  valid fields.

## Risks

- Characters outside Cc, such as U+200B and U+2028, are accepted and can make
  lookalike paths. This matches `is_valid_path` today.
- Follow-up: lone surrogates (e.g. `"\ud800"`) pass the segment rule but
  cannot be UTF-8 encoded, so storage would fail later. Rejecting them
  belongs in the shared segment rule, not this issue.
- Both this issue and AIE-1043 edit `paths.py`. This one merges second.
