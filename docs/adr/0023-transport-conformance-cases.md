# 0023. Transport conformance cases

Date: 2026-10-02

## Status

Accepted

## Context

Notion Section 10.2 says the in-process and remote transports "must be
behaviorally indistinguishable" and that the shared transport suite
asserts nine groups: round-trip fidelity, atomicity, version token
opacity, conflict semantics, replace-fact matching, append guarding,
enforcement, index behavior, and error parity.

AIE-1047 built the harness ([ADR 0021](0021-transport-conformance-harness.md)):
the `TransportConformance` mixin with seven fixtures, five baseline cases,
`require_fresh` and the conformance sentinel, `probe_path`,
`expect_error`, the deep exact-type canonical readers, `without_sentinel`,
`sentinel_entry_bytes`, the `name: label: phrase` message form, the clock
contract, and the rule that version tokens are never compared, pinned by
an `ast` scan (`find_version_misuse`) in the repo's tests. AIE-1045 adds
the exhaustive Section 10.2 cases as further methods on the same mixin.
It keeps the fixture set and the existing harness helpers, but raises
the `index_max_bytes` minimum (decision 9).

Three things had to be settled first:

- **Enforcement.** Section 10.2 lists "`system/` prefix writes rejected;
  write-restricted scopes rejected for callers lacking the role", but the
  transport is identity-agnostic and `MemoryStore` applies no scope rule.
  ADR 0021 put this to the human, who chose option (a) on 2026-10-02: the
  transport suite asserts a `system/` write is *accepted* at the
  transport, and enforcement is tested only by the tool-layer and resolver
  suites. ADR 0021 records the decision, and ADR 0019 carries the matching
  "Update (2026-10-02)" amendment to decision 6 (a remote server must not
  enforce scope at the transport). Both are present and unchanged by this
  ADR.
- **How strict error parity is.** [ADR 0019](0019-transport-client-interface.md)
  decision 7 says a remote must reproduce core's non-taxonomy errors
  exactly, including the message, but not every such error can be
  provoked through a client, and some messages embed caller-side details.
- **How to test the index byte cap** without hardcoding sizes that depend
  on the fixture values, the sentinel, and the entry encoding
  ([ADR 0020](0020-memory-index-and-in-process-client.md)).

## Decision

Add 43 case methods to `TransportConformance`, grouped by Section 10.2
bullet, plus private case helpers and pinned message constants in
`wenchang.testing.transport_conformance`. No change to `core` or
`transport`; the existing harness helpers keep their behavior, and the
only fixture-contract change is the `index_max_bytes` floor (decision
9). The repo's method-name test lists
the full set; the reference run against `InProcessClient` passes all of
them with no skips; each group has a broken-client self-test in
`tests/test_transport_conformance_cases_self.py`; and
`tests/test_transport_conformance_messages.py` is the message drift test.

1. **One method per assertion, grouped by Section 10.2 bullet**, each
   self-contained (its own writes and probe paths, after
   `require_fresh`), so a failure names one behavior.
   - **Rejected: a few large scenario methods**, which hide which
     assertion failed and let one early failure mask the rest.
2. **Argument-error parity pins core's exact message text.** Module
   constants copy core's wording, one per method where core uses one
   message for several causes: `MSG_WRITE_ARGS` (`"source must be
   non-empty"`), `MSG_REPLACE_ARGS` (`"old_string and source must be
   non-empty"`), `MSG_APPEND_ARGS` (`"line must be a single fact line and
   source must be non-empty"`), plus the format constants
   `MSG_MALFORMED_CURSOR`, `MSG_FOREIGN_CURSOR`, `MSG_INVALID_SCOPE`, and
   `MSG_INVALID_ENTITY`. Cases check them through `expect_error(...,
   ValueError, None, message=...)`. A drift test in the repo's tests
   provokes every (method, cause) pair on a real `MemoryStore` (empty
   `source` on `write_file`, `replace_fact`, and `append_line`; empty
   `old_string`; a non-fact and a two-line `line`; malformed and foreign
   cursors; invalid scope and invalid entity_id) and requires `str(exc)`
   to equal the constant, so a change to core's wording fails here rather
   than in an adopter's suite. For the taxonomy errors,
   `test_error_messages_carry_category_guidance` requires the full
   `str(exc)` to equal that of a locally built core error with the same
   fields and to end with `RecoverableError.guidance`.
   - **Rejected: type-only checks for `ValueError`**, which would let a
     remote reshape the text the agent reads; ADR 0019 decision 7 makes
     the message part of parity.
3. **Corrupt-metadata parity is out of the transport suite.**
   `MetadataFormatError` and `UnicodeDecodeError` arise only from corrupt
   stored data, which a conforming client cannot write, so the suite has
   no way to provoke them. Corrupt stored metadata is covered by core's
   `read_file`/`list_prefix` tests and the storage conformance suite
   (`tests/storage_conformance.py`); the tool layer passes
   `MetadataFormatError` through.
   - **Rejected: a `corrupt_storage` fixture**, which only an in-process
     adopter could supply and would make the suite run differently per
     transport, against "runs identically against any implementation".
4. **The index byte cap is replayed, not hardcoded.** The cap case writes
   files with 200-byte descriptions under area `INDEX_AREA =
   "conformance-index"` in the second sorted scope, one at a time, at
   most 20. After each write it lists them through the client (all
   pages), sizes each returned `FileEntry` with `index_entry_bytes` and
   the sentinel with `sentinel_entry_bytes`, and replays core's rule over
   the full expected order (system tier, then `scope_priority` tiers with
   unlisted scopes as one trailing tier, newest first within a tier, the
   sentinel oldest in its tier): include entries while the running total
   stays within `index_max_bytes`, stop at the first that would overflow.
   It stops writing once the replay omits at least one `INDEX_AREA` entry,
   not merely the sentinel, and skips only if that never happens within
   20 files (the reference fixture, 4096 bytes, does not skip). It then
   asserts that the returned paths equal the replayed included prefix
   exactly (`wrong order`), that their sizes total at most the budget
   (`budget exceeded`), and that the client's raw `capped`, in the order
   returned, equals the replayed omitted entries grouped by area prefix
   with counts, sorted by prefix, including the sentinel's area when the
   replay predicts it capped (`wrong capped`); unsorted or
   sentinel-dropped output fails. Sizes come only from client-returned
   entries, never from self-built `FileEntry`s. `index_max_bytes` has a
   floor of `MIN_INDEX_BYTES = 1024` so the probe entries fit.
   Two budget probes follow: a newest `conformance-probe-fit` entry sized
   to fill the leftover budget exactly, then one byte past it, each
   rechecked against a fresh replay. The exact fit catches a client whose
   budget is too small; the +1 catches one whose budget is too large. If
   the entry cannot be sized exactly within `_FIT_ATTEMPTS` writes, or the
   leftover budget is below a minimal entry, the probes do not run and the
   first check stands.
   - **Rejected: hardcoded sizes or file counts**, which hold only for one
     fixture value and one entry encoding.
   - **Rejected: asserting only "a prefix within budget"**, which a client
     that drops entries early, or orders tiers wrongly, would pass.
   - **Rejected: stopping as soon as the sentinel alone is capped**, which
     at some budgets gives a case whose only capped area is the
     sentinel's and so checks nothing about the probe files.
5. **Tokens reach the client only inside `client.<method>(...)` calls in
   the lambda passed to `_call` or `expect_error`.** No helper takes a
   token parameter; helpers such as `_write`, `_read`, `_conflict`, and
   `_accepted` take a zero-argument callable instead. A
   `VersionConflictError.version` is checked by handing it back to the
   client, never by `version=` in `expect_error`. Calls on absent or
   malformed paths pass `_ABSENT_TOKEN = VersionToken("1")`, a plain
   module constant, since any token there must yield `NotFoundError`; the
   local errors built for message comparison also use it as their
   version, since their messages do not include the version. The existing
   `ast` scan passes the module unchanged.
   - **Rejected: a scanner exemption** for case helpers, which would widen
     the places a token could be misused without the scan noticing.
   - **Rejected: passing a real `exc.version` to a local error
     constructor**, which the scan flags as a non-client use of a token.
6. **Recency relies on the clock contract.** Within one test a client's
   writes stamp strictly increasing `last_updated`, so write order is
   recency order for the index-order and cap cases, and the append case
   compares two reads from the same client with `<`, never against the
   test's clock.
   - **Rejected: comparing `last_updated` with the test's clock**, which a
     remote with its own clock would fail.
7. **The transport accepts `system/` writes (the human's decision of
   2026-10-02, option (a) in ADR 0021).**
   `test_system_area_write_is_accepted_at_transport` writes under the
   first scope's `system` area and requires it to succeed and read back
   byte-for-byte; a transport that rejects it fails `unexpected error`.
   Enforcement of `system/` read-only and role restriction belongs to the
   tool layer and the resolver suite. This relies on ADR 0019's
   "Update (2026-10-02)" amendment to decision 6.
   - **Rejected: (b) running enforcement cases through the tool layer**,
     which would add identity fixtures and make this a tool-layer suite.
   - **Rejected: (c) leaving transport enforcement unspecified**, which
     lets in-process and remote transports differ on a whole class of
     writes, weakening "indistinguishable".
8. **`get_memory_index` argument errors: `ValueError` text pinned,
   `TypeError` type only, duplicate scope excluded.** An invalid scope and
   an invalid entity_id raise `ValueError` with core's exact text
   (`MSG_INVALID_SCOPE`, `MSG_INVALID_ENTITY`). A non-`Mapping` map and a
   non-`str` key or value must raise `TypeError`, checked by type only:
   core's text embeds the Python type names of caller-side values, which a
   remote client may detect at serialization in its own words, and the
   type alone shows the call was rejected before any storage effect.
   Duplicate scopes are not tested: they cannot be built with a real
   `Mapping`, and a remote that serializes the map to JSON would
   legitimately collapse them.
   - **Rejected: pinning the `TypeError` texts**, which binds remotes to
     wording about values outside the well-typed contract ADR 0019 covers.
   - **Rejected: a custom `Mapping` that yields a duplicate key**, which
     tests a caller bug, not transport parity.
9. **`index_max_bytes` has a floor of `MIN_INDEX_BYTES = 1024`, and the
   cap case adds three private helpers.** The floor leaves headroom for
   the US8.3 probe entries and the exact-fit and +1 budget probes; a
   smaller value fails `fixture index_max_bytes` in every case that
   validates fixtures, including `test_client_satisfies_protocol`. This
   amends ADR 0021 decision 2, which allowed any positive `int`. The
   helpers are `_check_cap` (asserts one `get_memory_index` result
   against a replay: order, budget, raw `capped`), `_listed_sizes`
   (`index_entry_bytes` of listed entries by path, failing if an
   expected path is missing), and `_utf8_len` (UTF-8 byte length, used
   to size the fit probe). The existing harness helpers are unchanged.
   - **Rejected: keeping any positive `int` and skipping the probes at
     small budgets**, which silently weakens the cap case for adopters
     with small caps.

### Adversarial review

The spec went through two rounds of adversarial review before
implementation. Findings incorporated: the separator rule for appends
(core always appends `"\n"` after the line and inserts one before it only
when non-empty content lacks a trailing newline); a misreading of the
token scan (it flags names and attributes ending in `version` as
operands, so `_ABSENT_TOKEN` and `VersionToken("1")` need no exemption,
but passing `exc.version` to a local error constructor would be flagged);
per-method message constants, since core shares one message across
causes within a method but not across methods; and an edge in the cap
arithmetic, where stopping as soon as the total exceeded the budget could
cap only the sentinel. Later tightening during implementation: the empty
`source` case creates the file and hands back its real token (core
validates arguments before existence), and the cap case's stop rule moved
from a size threshold to the replay's prediction.

## Consequences

The transport suite is complete for Section 10.2: an adopter's remote
client passes it only if it reproduces core's results, ordering, cap
behavior, error types, payloads, and argument-error messages exactly. A
change to core's argument-error wording fails the drift test and must
update the suite's constants in the same change; adopters then see the
new wording as a suite failure until their transport matches.

The cap case adapts to any fixture values, but an adopter whose
`index_max_bytes` is so large that 20 probe files never overflow it gets
a skip, not a pass, for that one case. An adopter whose
`index_max_bytes` is below 1024 fails fixture validation and must
configure a larger cap for the suite.

Corrupt-metadata errors and duplicate scopes are not checked by this
suite. Corrupt stored metadata is exercised only in-process, by core's
tests and the storage conformance suite, so a remote that mishandles it
(or collapses duplicate scopes wrongly) is not caught by any shipped
suite.

Under option (a), a remote transport that enforces scope fails
`test_system_area_write_is_accepted_at_transport`; the tool layer
(AIE-1044, ADR 0022) is the only enforcement point and consumes these
transport semantics as given.

Because every case is a separate method, the suite has 48 public cases;
the method-name test and the `pytester` fixture-error test derive or pin
that set, so adding a case requires updating the method-name list and a
matching self-test.
