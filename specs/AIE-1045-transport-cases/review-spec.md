# Spec Review: AIE-1045 — transport conformance test cases

## What & why

Notion §10.2 lists nine assertion groups the shared transport suite must
make so the in-process and remote implementations stay indistinguishable.
AIE-1047 built the harness and five baseline cases; this adds the
exhaustive cases (43 methods) on the same mixin, one method per
assertion, grouped by §10.2 bullet, plus a broken-client self-test per
group and a drift test pinning core's exact argument-error messages.

## Acceptance criteria

| # | Group | Then |
| - | ----- | ---- |
| 1 | Round trip (US1) | unicode, fact-like markdown, no trailing newline, empty content, many sources, replace all survive byte-for-byte; sources accumulate |
| 2 | Atomicity (US2) | a rejected stale replace leaves content and metadata together; delete removes both; append updates content and `last_updated` together |
| 3 | Token opacity (US3) | tokens from every operation and from index entries are accepted when handed back; none compared |
| 4 | Conflicts (US4) | stale write/delete → conflict carrying current content, retry with carried version succeeds; create-on-existing conflicts; token on absent → `FILE_ABSENT` |
| 5 | Replace-fact (US5) | unique succeeds; 0 and 2 matches carry count+content; stale unique re-applies; stale non-unique conflicts; empty anchor → exact `ValueError` message |
| 6 | Append (US6) | concurrent appends: one lands, one conflicts, retry lands, no loss/duplication; retried landed append conflicts; separator inserted and trailing `"\n"` always appended; absent → not created; non-fact or two-line → exact `MSG_APPEND_ARGS` |
| 7 | Enforcement (US7) | oversize append/replace rejected with limit and exact UTF-8 size of the would-be content (multi-byte); a `system/` write is **accepted** at the transport (human decision (a), 2026-10-02) |
| 8 | Index (US8) | fan-out; system-first/priority/recency order computed from fixtures; cap replayed with core's stop-at-first-overflow rule: exact returned entries and exact `capped`; empty map → `((), ())` |
| 9 | Listing (US9) | pagination at `list_page_size` with stable cursors, ascending path order; entity/scope levels; invalid prefix → `INVALID_PATH`; malformed cursor and a real cursor used under another area → exact `ValueError` |
| 10 | Parity (US10) | invalid path and absent file for every operation; empty source per method (`MSG_WRITE_ARGS`/`MSG_REPLACE_ARGS`/`MSG_APPEND_ARGS`); full `str(exc)` matches core and ends with the guidance; `get_memory_index` invalid scope/entity_id → exact `ValueError` text, non-Mapping/non-str → `TypeError` (type only); duplicate scope excluded |
| 11 | Integrity (US11) | method-name set complete; reference run no skips; one broken client per group; token scan passes unchanged; tokens reach the client only inside `client.<method>(...)` calls in the lambda |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| One method per assertion, grouped by bullet | Few large scenarios | A failure names one behavior |
| Exact argument-error message parity (per-method constants) with a drift test over every (method, cause) pair | Type-only | ADR 0019 decision 7: message is part of parity; drift caught here |
| Corrupt-metadata parity excluded | `corrupt_storage` fixture | Unreachable through a conforming client; non-uniform |
| Cap replayed from client-returned entries with core's stop-at-first-overflow rule | Hardcoded sizes; "prefix + budget" only | Holds for any fixture values; pins the exact result |
| Tokens only inside `client.<method>(...)` calls in the lambda; helpers take callables; `_ABSENT_TOKEN` a plain constant | Scanner exemption; compare tokens | §10.2 opacity; existing scan already enforces it |
| Recency via the clock contract, `<` between two same-client reads | Compare to test clock | ADR 0021 |
| Transport accepts `system/` writes; enforcement only in tools/resolver suite; ADR 0019 d6's existing amendment cited by ADR 0023 | (b) tool-layer run; (c) unspecified | Human decision (a), 2026-10-02 |
| `get_memory_index` `TypeError` type only; duplicate scope excluded | Pin `TypeError` texts; custom-Mapping duplicate case | Type names are caller-side and a remote may reject at serialization; a JSON-serializing remote legitimately collapses duplicates |
| Recorded in ADR 0023 | — | Suite scope and exclusions |

## Files/modules to be touched

- `src/wenchang/testing/transport_conformance.py` (cases + helpers + message constants)
- `tests/test_transport_conformance_reference.py` (method-name set), `tests/test_transport_conformance_cases_self.py` (new), `tests/test_transport_conformance_messages.py` (new)
- `ARCHITECTURE.md`, `docs/adr/0023-transport-conformance-cases.md`

## Open questions / assumptions

- Enforcement question answered: (a). Nothing open.
- `MetadataFormatError`/`UnicodeDecodeError` parity is out of this suite.

## Risks

- Pinning exact messages couples remote implementations to core's
  wording; that is the §10.2 intent, and the drift test keeps the suite
  honest when core's wording changes.
- US8.3 may skip for adopters with very large caps; the reference does
  not.
- US8.3 rejects `index_max_bytes` below `MIN_INDEX_BYTES` (1024), so
  adopters with smaller caps must raise the fixture value.
