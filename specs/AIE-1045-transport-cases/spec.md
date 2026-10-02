# Feature Specification: Transport conformance test cases

**Linear issue**: AIE-1045 — https://linear.app/mixpanel/issue/AIE-1045/transport-conformance-test-cases

**Feature Branch**: `AIE-1045-transport-cases` (based on `AIE-1047-transport-harness`)

**Created**: 2026-10-02

**Status**: Draft. The enforcement question raised in ADR 0021 was
answered by the human on 2026-10-02: option (a). US7.3 asserts that a
`system/` write is accepted at the transport.

**Input**: Linear AIE-1045 ("Write the transport conformance test cases
run through the shared harness, covering the full operation set (read,
write, append, replace_fact, list, delete) and get_memory_index,
exercised against the in-process implementation.") and Notion §10.2's
nine assertion groups: round-trip fidelity, atomicity, version token
opacity, conflict semantics, replace-fact matching, append guarding,
enforcement, index behavior, error parity.

Builds on the harness (AIE-1047, ADR 0021): the seven fixtures,
`require_fresh`, `probe_path`, `expect_error`, the canonical readers,
`without_sentinel`, `sentinel_entry_bytes`, and the message form
`name: label: phrase`.

## Summary

Add the exhaustive §10.2 cases as further `test_*` methods on
`wenchang.testing.TransportConformance`, grouped by §10.2 bullet. Every
case follows the harness contract: fixture checks, `require_fresh`,
every client call under `expect_error` or `_call`, every failure
`name: label: phrase`, tokens only handed back, `last_updated` compared
only between results of the same client. Reference run against
`InProcessClient` passes with no skips; at least one broken-client
self-test per §10.2 group proves the group bites. The method-name test in
`tests/test_transport_conformance_reference.py` is updated to the full
list (the spec for AIE-1047 anticipated this).

Out of scope: corrupt-metadata parity (`MetadataFormatError`,
`UnicodeDecodeError`) — a client cannot seed corrupt stored data through
the transport, so the suite cannot provoke them; recorded in ADR 0023.
Thread-level concurrency (sequential interleavings per ADR 0021). Any
change to `core`, `transport`, or the harness helpers beyond what a
self-test exposes.

## User Scenarios & Testing *(mandatory)*

Notation: `P`, `Q` as in AIE-1047; `R = probe_path(..., second_scope,
PROBE_AREA, "conformance-probe-3")` where `second_scope = sorted(
scope_map)[1]`; `M(desc="d", aliases=("x","y"), sources={seed})` builds a
`FileMetadata` with an arbitrary aware timestamp; `W(path, content,
meta, ev)` is `write_file(path, content, meta, ev, source=source)`
through `_call`; `RD(path)` is `read_file` through `_call`. "Conflict
payload" means `expect_error(..., VersionConflictError, RECOVERABLE,
path=<path>, content=<current content>)` where `content` is the content
the suite last observed through a read, and the carried `version` is
used only by handing it back. Every case begins with the fixture checks
it needs and `require_fresh`.

Fixtures: the AIE-1047 seven, unchanged except that `index_max_bytes`
must be an exact `int` of at least `MIN_INDEX_BYTES = 1024` (checked in
`test_client_satisfies_protocol` and US8.3, failing `fixture
index_max_bytes`). The floor leaves room for the US8.3 probe entries,
including the exact-fit and +1 budget probes.

### User Story 1 - Round-trip fidelity (Priority: P1)

1. `test_round_trip_unicode_content_and_metadata`: content
   `"- [stated] café ☕ 日本語 \U0001F600\n"`, description `"déjà vu"`,
   aliases `("日本", "ñ")`, sources `{seed}` → canonical write and read
   tuples equal and equal to expected (`round trip`).
2. `test_round_trip_markdown_resembling_fact_syntax`: content with lines
   that look like fact lines but are not valid, a CRLF line ending,
   trailing spaces, a blank line, and a fenced block (`"- [shouted] x
   \r\n- stated y\n[stated] z\n\n```\n- [stated] f  \n```\n"`), with an
   empty description → byte-for-byte equal content and metadata on read.
3. `test_round_trip_content_without_trailing_newline` and
   `test_round_trip_empty_content`: `"- [stated] a"` and `""` both
   survive unchanged.
4. `test_round_trip_empty_aliases_and_many_sources`: aliases `()`,
   sources `{seed, seed + "-b", seed + "-c"}` → read sources equal
   `sorted({seed, seed-b, seed-c, source})`.
5. `test_write_replace_round_trips`: after a create, a replace with new
   content, description, aliases, and sources `{seed2}` → read shows the
   new content/description/aliases and sources `sorted({seed, seed2,
   source})` (sources accumulate; ADR 0013).

### User Story 2 - Atomicity (Priority: P1)

1. `test_failed_replace_leaves_content_and_metadata_together`: create
   `P` (content A, description dA); `r1 = RD(P)`; replace with
   `r1.version` → content B, description dB; then attempt a replace with
   the **stale** `r1.version`, content C, description dC → conflict
   payload with `content=B`; `RD(P)` shows content B **and** description
   dB (never C with dB or B with dC).
2. `test_delete_removes_content_and_metadata_together`: after
   `delete_file(P, r.version)` returns `None`, `read_file(P)` →
   `NotFoundError(FILE_ABSENT)` and `list_prefix(<P's area prefix>)` has
   no entry for `P` (via `canonical_page`).
3. `test_append_updates_content_and_last_updated_together`: after an
   append, `RD(P)` has the appended content and a `last_updated` later
   than the pre-append read's (both from the same client; the clock
   contract), and `metadata.sources` includes `source`.

### User Story 3 - Version token opacity (Priority: P1)

1. `test_tokens_from_every_operation_are_accepted`: the token from
   `write_file` (create), from `read_file`, from `append_line`, from
   `replace_fact`, and from a `list_prefix` entry are each accepted by a
   following mutating call on the same path (`token not accepted`
   otherwise). No token is compared.
2. `test_index_entry_tokens_are_accepted`: the `version` of a
   `get_memory_index` entry for `P` is accepted by `delete_file(P, ...)`.

### User Story 4 - Conflict semantics (Priority: P1)

1. `test_stale_write_conflicts_with_current_content`: create, read `r1`,
   replace via `r1.version` (content B), then `write_file(P, C, M,
   r1.version)` → conflict payload `content=B`; retrying with the
   carried version → succeeds; `RD(P).content == C`.
2. `test_create_on_existing_path_conflicts`: `W(P, A, M(), None)`, then
   `RD(P)` (observes content A), then `write_file(P, B, M(), None)` →
   conflict payload with `content=A` (the content the first call wrote,
   as observed by the read); `RD(P).content` is still A.
3. `test_write_with_token_on_absent_path_is_not_found`: `write_file(P,
   ..., _ABSENT_TOKEN)` on an empty store → `NotFoundError(P,
   FILE_ABSENT)` (the token is only handed over, inside the lambda).
4. `test_stale_delete_conflicts`: `delete_file(P, stale)` → conflict
   payload; the file still reads with current content; `delete_file(P,
   carried)` → `None`.
5. `test_delete_absent_is_not_found`: `delete_file(P, _ABSENT_TOKEN)`
   on an empty store → `NotFoundError(P, FILE_ABSENT)`.

### User Story 5 - Replace-fact matching (Priority: P1)

Content `"- [stated] alpha\n- [stated] beta\n- [stated] alpha\n"`.

1. `test_replace_fact_unique_match_succeeds`: `replace_fact(P, "beta",
   "gamma", r.version)` → read content has `gamma` and both `alpha`s.
2. `test_replace_fact_zero_matches_rejected`: `old_string="delta"` →
   `expect_error(ReplaceFactMatchError, RECOVERABLE, path=P,
   content=<current>, match_count=0)`; content unchanged.
3. `test_replace_fact_multiple_matches_rejected`: `old_string="alpha"` →
   `match_count=2`; content unchanged.
4. `test_replace_fact_stale_token_unique_match_reapplies`: read `r1`;
   append `"- [stated] d"` via `r1.version` (so `r1` is stale);
   `replace_fact(P, "beta", "zeta", r1.version)` → succeeds (re-applied);
   read shows the appended line and `zeta` (same length as `beta`, so the
   content stays within `MIN_FILE_BYTES`).
5. `test_replace_fact_stale_token_non_unique_conflicts`: read `r1`;
   via `r1.version` replace `beta` with `alpha` (now three `alpha`s);
   `replace_fact(P, "beta", "x", r1.version)` → conflict payload (zero
   matches at the current version is "genuine overlap"), content
   unchanged.
6. `test_replace_fact_empty_old_string_is_value_error`:
   `old_string=""` → `expect_error(ValueError, None,
   message=MSG_REPLACE_ARGS)` before any storage effect (content
   unchanged).

### User Story 6 - Append guarding (Priority: P1)

1. `test_concurrent_appends_one_lands_one_conflicts`: read `r`; `a1 =
   append_line(P, "- [stated] one", r.version)` succeeds; `append_line(P,
   "- [stated] two", r.version)` → conflict payload with content
   containing `one`; retry with the carried version → succeeds; read
   content has `one` and `two` exactly once each, in that order.
2. `test_retried_append_does_not_duplicate`: after `a1` lands, repeating
   the exact same append with `r.version` → conflict; content has `one`
   exactly once.
3. `test_append_inserts_separator_when_needed`: content `"- [stated] a"`
   (no trailing newline) then append `"- [stated] b"` → `"- [stated]
   a\n- [stated] b\n"`; content `"- [stated] a\n"` then the same append →
   `"- [stated] a\n- [stated] b\n"` (core inserts a separator only when
   the content is non-empty and lacks a trailing newline, and always
   appends `"\n"` after the line).
4. `test_append_to_absent_file_is_not_found_and_creates_nothing`:
   `append_line(P, line, _ABSENT_TOKEN)` → `NotFoundError(P,
   FILE_ABSENT)`; `read_file(P)` → still `FILE_ABSENT`.
5. `test_append_non_fact_line_is_value_error`: `"not a fact"` and
   `"- [stated] a\n- [stated] b"` (two lines; see Edge Cases) →
   `expect_error(ValueError, None, message=MSG_APPEND_ARGS)`; content
   unchanged.

### User Story 7 - Enforcement (Priority: P1)

1. `test_oversize_append_is_rejected`: multi-byte content (e.g. built
   from `"é"`/`"日"` facts) near `max_file_bytes`, then an append that
   pushes the UTF-8 size over it → `OversizeWriteError(path=P, size=S,
   limit=max_file_bytes)` where `S` is the UTF-8 byte length of the
   content core would have written: `content + separator + line + "\n"`
   (separator `"\n"` only if `content` is non-empty and lacks a trailing
   newline); content unchanged.
2. `test_oversize_replace_fact_is_rejected`: multi-byte content near the
   limit containing a unique anchor; `replace_fact` replacing that anchor
   with a longer multi-byte string → `OversizeWriteError(path=P, size=S,
   limit=max_file_bytes)` where `S` is the UTF-8 byte length of the
   post-replacement content; content unchanged.
3. `test_system_area_write_is_accepted_at_transport` (human decision
   2026-10-02, option (a)): `W(build_path(first_scope,
   scope_map[first_scope], "system", "conformance-curated"), "- [system]
   curated\n", M(), None)` succeeds and reads back byte-for-byte; a
   transport that rejects it fails (`unexpected error` or `wrong result
   type`). Enforcement of `system/` and role restriction lives in the
   tool layer (AIE-1044) and the resolver suite (AIE-1039), never at the
   transport, so in-process and remote stay indistinguishable.

### User Story 8 - Index behavior (Priority: P1)

All index results are passed through `without_sentinel` before checks
against expectations about the case's own files. The sentinel is the
oldest entry in the first scope's non-system tier; US8.3 places it there
when replaying the cap.

1. `test_index_fans_out_over_every_scope`: files under both scopes →
   `canonical_index` entries include both, `capped == ()`.
2. `test_index_orders_system_first_then_priority_then_recency`: a
   `system/` file in each scope, a non-system file in each; with the
   fixture's `scope_priority`, the order is: `system/` entries by recency
   (newest first), then non-system entries grouped by priority order
   (listed scopes first, in order; unlisted as one trailing tier), each
   group by recency. The expected sequence is computed in the case from
   the fixture values and the write order (the clock contract makes
   write order the recency order).
3. `test_index_byte_cap_degrades_with_capped_prefixes`: write files with
   200-byte descriptions under `INDEX_AREA` in `second_scope`, one at a
   time (at most 20). After each write, list the `INDEX_AREA` entries
   (`list_prefix`, all pages), size them and the sentinel, and replay
   core's rule (below); stop as soon as the replay predicts that at least
   one `INDEX_AREA` entry, not merely the sentinel, is omitted. Skip with
   `pytest.skip` only if that never happens within 20 files (the
   reference fixture, 4096, does not skip). The replay runs over the full
   expected order — the system tier
   (empty here), then non-system tiers by `scope_priority` (listed scopes
   in order, unlisted as one trailing tier) with the sentinel in its
   tier position, recency (newest first, from write order; the sentinel
   oldest) within each tier — including entries while the cumulative
   `index_entry_bytes` stays ≤ `index_max_bytes` and stopping at the
   first entry that would overflow. Sizes come only from entries returned
   by `list_prefix` or the index, never from self-built `FileEntry`s.
   Assertions: the returned entry paths equal the replayed longest
   fitting prefix exactly, in order (`wrong order`), so the next entry
   would overflow; the returned sizes total at most the budget
   (`budget exceeded`); and the client's raw `capped`, in the order
   returned, equals the replayed omitted entries grouped by area prefix
   with counts, sorted by prefix, including the sentinel's area when the
   replay predicts it capped (`wrong capped`; unsorted or
   sentinel-dropped output fails). `index_max_bytes` must be at least
   `MIN_INDEX_BYTES` (1024), which leaves room for the probe entries.
   Two budget probes follow: a newest `conformance-probe-fit` entry sized
   to fill the leftover budget exactly, then resized one byte past it,
   each rechecked against a fresh replay. The exact fit catches a client
   whose budget is too small; the +1 catches one whose budget is too
   large. If the probe entry cannot be sized exactly within the attempt
   limit, or the leftover budget is below a minimal entry, the probes do
   not run and the first check stands.
4. `test_index_of_empty_scope_map_is_empty`: `canonical_index` of
   `get_memory_index({})` equals `((), ())` (no `require_fresh` needed,
   stateless).

### User Story 9 - Listing (Priority: P1)

1. `test_list_prefix_paginates_with_stable_cursors`: write
   `list_page_size + 1` files under one area; first page has
   `list_page_size` entries and a non-`None` cursor; the second page has
   the rest and `None`; the union equals the written set; entries within
   and across pages are in ascending path order (`wrong order`); a page
   never carries content (structurally guaranteed by `FileEntry`;
   asserted via `canonical_page`).
2. `test_list_prefix_levels`: entity-level and scope-level prefixes
   return supersets of the area-level listing (after
   `without_sentinel`).
3. `test_list_prefix_invalid_prefix_is_not_found`: `"nope"` and `""` →
   `NotFoundError(path=<prefix>, reason=INVALID_PATH)`.
4. `test_list_prefix_malformed_cursor_is_value_error`:
   `ListCursor("!!!")` → `expect_error(ValueError, None,
   message=MSG_MALFORMED_CURSOR.format(cursor=...))`. Foreign cursor:
   write `list_page_size + 1` files under `PROBE_AREA`, take the
   non-`None` `next_cursor` from the real first page, and pass it to
   `list_prefix` with the prefix of a different area (`INDEX_AREA`, same
   scope and entity), which the cursor's key does not start with →
   `expect_error(ValueError, None, message=MSG_FOREIGN_CURSOR.format(
   cursor=..., prefix=...))`. The cursor is only handed back, inside the
   lambda.

### User Story 10 - Error parity (Priority: P1)

1. `test_invalid_path_is_not_found_for_every_operation`: for each of
   `read_file`, `write_file`, `append_line`, `replace_fact`,
   `delete_file`, a malformed path (`"a/b"`, `"a/b/c/d"`,
   `"a/../c/d.md"`, the last having four segments) →
   `NotFoundError(path=<path>, reason=INVALID_PATH)` with no storage
   effect, defined as: a follow-up `read_file(P)` (the probe path, never
   written in this case) → `NotFoundError(P, FILE_ABSENT)`.
2. `test_absent_file_is_not_found_for_every_mutating_read`:
   `read_file`, `append_line`, `replace_fact`, `delete_file` on an
   absent path → `NotFoundError(path=P, reason=FILE_ABSENT)`.
3. `test_empty_source_is_value_error`: the case creates `P` (content
   `_FACTS`) and reads it, then hands back that read's real token in each
   call, because core validates arguments before checking existence or
   version, so the `ValueError` is raised regardless and the file must
   stay unchanged afterwards (`content changed`). `source=""` on `write_file` →
   `message=MSG_WRITE_ARGS`; on `replace_fact` (valid `old_string`) →
   `message=MSG_REPLACE_ARGS`; on `append_line` (valid fact line) →
   `message=MSG_APPEND_ARGS`; each via `expect_error(ValueError, None,
   message=...)`.
4. `test_error_messages_carry_category_guidance`: for one error of each
   kind observable through the transport (`NotFoundError`,
   `VersionConflictError`, `OversizeWriteError`,
   `ReplaceFactMatchError`), the full `str(exc)` equals `str(...)` of a
   locally constructed core error with the same fields (`wrong
   message`), and ends with the imported `RecoverableError.guidance`
   (`missing guidance`), so a remote cannot reshape the agent-facing
   wording. The local `VersionConflictError(path, content,
   _ABSENT_TOKEN)` and `ReplaceFactMatchError(path, content,
   _ABSENT_TOKEN, n)` use `_ABSENT_TOKEN` as the version: the messages
   do not include the version, and the token scan forbids passing
   `exc.version` to a non-client call.
5. `test_get_memory_index_argument_errors_match_core`: a non-Mapping
   `scope_map` (a list), a non-str key, and a non-str value →
   `expect_error(..., TypeError, None)` (type only, no message); an
   invalid scope and an invalid entity_id → `expect_error(...,
   ValueError, None, message=...)` with `MSG_INVALID_SCOPE` /
   `MSG_INVALID_ENTITY`, formatted as core formats them. Duplicate scope
   is excluded (unreachable with a real `Mapping`; ADR 0023).

### User Story 11 - Suite integrity (Priority: P1)

1. The method-name test lists every case above; the reference run
   passes all with no skips (US8.3 does not skip at 4096).
2. At least one broken-client self-test per §10.2 group (US1–US10),
   each matching the phrase and label, and each confirming the
   reference client passes the same case: US1 drops a unicode alias; US2
   returns new content with old description after a conflict; US3
   returns a token the client later rejects; US4 returns success on a
   stale write; US5 reports `match_count=2` for zero matches (a count
   of 1 is invalid for `ReplaceFactMatchError`); US6 lands
   both concurrent appends; US7 accepts an oversize append; US8 returns
   `capped=()` when it omitted entries; US9 returns `next_cursor=None`
   on a full first page; US10 raises `KeyError` for an absent read.
3. The token-rule `ast` scan (`find_version_misuse`) passes on the
   module unchanged; no Linear IDs; no marks. Token rule: a token
   reaches the client only as an argument to a `client.<method>(...)`
   call written inside the lambda passed to `_call` or `expect_error`;
   no private helper takes a token parameter. `_ABSENT_TOKEN: Final =
   VersionToken("1")` is a plain module constant (a literal
   construction is not flagged by the scan).

### Edge Cases

- Message parity for argument errors pins core's exact text; a remote
  must reproduce it (ADR 0019 decision 7). The texts live as module
  constants copied from core's source, one per method where core uses
  one message for several causes: `MSG_WRITE_ARGS = "source must be
  non-empty"`, `MSG_REPLACE_ARGS = "old_string and source must be
  non-empty"`, `MSG_APPEND_ARGS = "line must be a single fact line and
  source must be non-empty"`, plus the cursor and `get_memory_index`
  format constants. A drift test in `tests/` triggers every (method,
  cause) pair on a real `MemoryStore` — including empty `source` on
  `append_line` and `replace_fact`, empty `old_string`, a non-fact line,
  a two-line line, both cursor causes, invalid scope, and invalid
  entity_id (the US10.5 `TypeError`s are type only) — and
  asserts `str(exc)` equals the constant (formatted where needed), so
  drift is caught here rather than in an adopter's suite.
- A two-line `line` is rejected by `append_line`: `parse_fact` uses
  `fullmatch` with `.*` (no DOTALL), so a string containing `"\n"` is
  not a fact line.
- `last_updated` is compared only between two reads from the same client
  (US2.3), as `<`, never against the test's clock.
- Index cap arithmetic uses `index_entry_bytes` over client-returned
  entries and `sentinel_entry_bytes`; the suite never hardcodes sizes.
- Every multi-file case writes under `PROBE_AREA`, `INDEX_AREA =
  "conformance-index"`, or (US8.2, US7.3) `system` only, so
  `without_sentinel` and area filtering are the only cleanup.

## Requirements *(mandatory)*

- **FR-001**: Every §10.2 group MUST have at least one case method on
  `TransportConformance`, following the
  harness contract (fixture checks, `require_fresh`, `_call` /
  `expect_error`, labeled messages, tokens reach the client only inside a
  `client.<method>(...)` call in the lambda; US11.3).
- **FR-002**: The reference run against `InProcessClient` MUST pass every
  case with no skips at the reference fixtures.
- **FR-003**: Each group MUST have a broken-client self-test (US11.2).
- **FR-004**: Argument-error parity cases MUST pin core's exact message,
  with a drift test in `tests/` covering every (method, cause) pair.
- **FR-005**: The shipped module MUST cite no Linear IDs, apply no marks,
  and pass the token-rule scan unchanged (US11.3).
- **FR-006**: Test docstrings under `tests/` MUST cite AIE-1045.

## Success Criteria *(mandatory)*

- **SC-001**: `make check` passes; reference run has zero skips.

## Assumptions

- Corrupt-metadata errors are out of the transport suite's reach
  (recorded in ADR 0023); corrupt stored metadata is covered by core's
  `read_file`/`list_prefix` tests and the storage conformance suite
  (`tests/storage_conformance.py`), and the tool layer passes
  `MetadataFormatError` through.
- US7.3 follows the human's answer (a) to ADR 0021's open question: the
  transport accepts `system/` writes. ADR 0019 already carries the
  "Update (2026-10-02)" amendment to decision 6 and ADR 0021 already
  records decision (a); the docs task verifies both are present, and
  ADR 0023 cites the existing amendment.
- The method-name list in the AIE-1047 reference test changes here, as
  that spec anticipated (US5.3 there).
