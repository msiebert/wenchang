# Spec Review: AIE-1030 — Error taxonomy definition

## What & why

Add `wenchang.errors`, the error vocabulary every core API function will
raise. Errors fall into three categories by what the caller does next:
**recoverable** (fix and retry this turn using data the error carries),
**permanent** (stop, don't retry), **transient** (retry). Seven downstream
issues (read_file, write_file, replace_fact, list_prefix, append_line,
delete_file, transport client) are blocked on it. No storage or API
functions are built here.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | Any library error | Caller inspects it | It reports exactly one category and is catchable as `WenchangError` and as its category class only |
| 2 | Version conflict (content C, version V) | Caller reads it | Exposes C and V unchanged |
| 3 | Oversize write (size S, limit L) | Caller reads it | Exposes S and L |
| 4 | Replace-fact match failure, count 0 or ≥ 2 | Caller reads it | Exposes content, version, count; message says widen (0) or narrow (≥ 2) the anchor |
| 5 | Not found: invalid path vs. file absent | Caller reads it | Exposes path + reason; message says correct the path vs. create the file |
| 6 | Any recoverable error | Message rendered | Routine framing, retry same turn, no "fail" wording |
| 7 | Any permanent error | Message rendered | Says "do not retry"; restricted-scope names scope + reason (`system/` read-only or missing role) |
| 8 | Resolver failure | Message rendered | Memory unavailable this session; continue without memory |
| 9 | Transient error (timeout / unavailable) | Message rendered | Retry is appropriate; guarded calls safe; retried `append_line` may duplicate a line |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Exceptions, with a class per category | Result/union return values | Idiomatic Python; `except RecoverableError` branches on category directly |
| Fixed guidance text per category, appended to each message | Per-error free-form wording | Wording consistency is the requirement; one place to tune it |
| `ReplaceFactMatchError` also carries the version token | Content + count only (Notion text) | Caller can retry with a version guard without re-reading |
| `VersionToken = NewType(str)` in its own module | Raw `str`; define it in `errors` | Opaque type that all later core issues reuse |
| Version conflict carries content + version, not metadata | Include metadata now | Metadata type doesn't exist until AIE-1031; adding it later is additive |

## Files/modules to be touched

- `src/wenchang/version_token.py`, `src/wenchang/errors.py` (new)
- `tests/test_errors.py` (new)
- `ARCHITECTURE.md`, a new ADR in `docs/adr/`, `docs/product/glossary.md`

## Open questions / assumptions

- **"No such path" vs. "file does not exist yet"**: I read it as *path isn't a
  valid memory location (malformed or outside any scope)* vs. *valid
  location, no file yet*. Confirm or correct.
- Transport serialization of errors (error parity) is left to AIE-1045/1048.

## Risks

- Guidance wording is tested by keyword checks, which is a proxy. Actual
  agent behavior gets evaluated later, at the prompt/tool layer.
