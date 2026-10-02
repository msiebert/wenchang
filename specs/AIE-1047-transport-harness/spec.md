# Feature Specification: Shared transport conformance harness

**Linear issue**: AIE-1047 — https://linear.app/mixpanel/issue/AIE-1047/shared-transport-conformance-test-harness

**Feature Branch**: `AIE-1047-transport-harness` (based on `AIE-1046-inprocess-client`)

**Created**: 2026-10-01

**Status**: Draft

**Input**: Linear AIE-1047 ("Build the shared test harness that runs the
transport conformance suite against any pluggable transport client
implementation, so both the in-process implementation and future
implementations (e.g. gRPC) can be validated against the same cases.")
and Notion:

- §10: "The library ships an executable conformance suite for each.
  Passing defines a correct implementation."
- §10.2: "The in-process and remote implementations must be behaviorally
  indistinguishable ... The suite runs identically against any
  implementation and asserts: Round-trip fidelity (content and all four
  metadata fields survive write-then-read byte-for-byte ...) ... Version
  token opacity (the suite treats tokens as opaque strings and never
  parses, orders, or compares them, modeling correct caller behavior)
  ... Enforcement ... Index behavior ... Error parity (every error
  surfaces in the same category with the same payload across
  implementations)."
- §5: "No caller may parse, compare, order, or arithmetically treat
  [the version token]."

Builds on `TransportClient` and `InProcessClient` (AIE-1048, AIE-1046),
`ResolverConformance` and the `wenchang[testing]` extra (AIE-1039, ADR
0018), and the error taxonomy (AIE-1030).

## Summary

Add `wenchang.testing.TransportConformance`, a pytest mixin an adopter
subclasses as `class TestMyClient(TransportConformance)` with **seven
fixtures**: `client` (a fresh `TransportClient` over an empty store, per
test, whose writes stamp strictly increasing `last_updated` within one
test), `source`, `scope_map` (≥ 2 scopes), `max_file_bytes`,
`index_max_bytes`, `scope_priority`, and `list_page_size` (the values the
client's store was configured with, so AIE-1045's oversize, cap, ordering,
and pagination cases are computable). The harness supplies the mechanics
every case needs:

- fixture validation, in a fixed order, failing with `fixture <name>`;
- `require_fresh`, called at the start of every stateful case, which
  fails with `not isolated` if a sentinel file written by an earlier case
  exists, then writes it; the sentinel lives under the first mapped
  scope's own entity, in its own area `conformance-sentinel`, and
  `without_sentinel` filters it out of list and index results for
  AIE-1045's cases. **Fixture contract**: every scope in `scope_map` must
  be writable through `client` under its bound credentials (the probe
  paths and the sentinel are all own-entity writes in those scopes);
- `probe_path`, a path builder over the fixture's scopes;
- deep canonical readers (`canonical_file`, `canonical_entry`,
  `canonical_page`, `canonical_index`) that check every nested field's
  exact type and return plain tuples; `version` is checked for shape only
  and never compared;
- `expect_error`, which asserts a call raises exactly one expected type
  with the expected category (for taxonomy errors), optional exact
  message, and payload attributes compared by exact type and value, so
  §10.2 error parity is one helper every case uses.

Five **baseline cases** ship with it: protocol check, a round trip of
ASCII content and all four metadata fields (`last_updated` compared
between the write result and the read result, both server-stamped), a
behavioral token check (a token handed back is accepted as
`expected_version`), absent-read parity, and oversize rejection. The full
§10.2 case list is AIE-1045, added as further methods on this mixin
using these helpers.

The repo runs the harness against `InProcessClient(MemoryStore(
InMemoryStorage(), clock=ticking, ...))` and self-tests that each baseline
case fails for a deliberately broken client.

Out of scope: the exhaustive cases (AIE-1045), any remote client, the tool
layer, changes to `core` or `transport`. The §10.2 enforcement bullets
are AIE-1045's to place; this issue records the human's decision,
option (a) on 2026-10-02 (see Assumptions).

## User Scenarios & Testing *(mandatory)*

"The suite" means a `Test...` subclass with the seven fixtures. "Fails"
means `pytest.fail` with a message naming the client class and containing
the key phrase in plan.md. Reference fixtures: `client =
InProcessClient(MemoryStore(InMemoryStorage(), clock=_Ticking(),
max_file_bytes=256, index_max_bytes=4096, scope_priority=("user", "org"),
list_page_size=2))` where `_Ticking` returns a new aware datetime one
microsecond later on each call; `source = "conformance"`; `scope_map =
{"user": "u-1", "org": "o-9"}`; `max_file_bytes = 256`; `index_max_bytes =
4096`; `scope_priority = ("user", "org")`; `list_page_size = 2`.

Constants: `PROBE_AREA = "notes"`, `PROBE_STEM = "conformance-probe"`,
`PROBE_STEM_2 = "conformance-probe-2"`, `SENTINEL_AREA =
"conformance-sentinel"`, `SENTINEL_STEM = "sentinel"`, `MIN_FILE_BYTES =
64`. "The probe path `P`" is `probe_path(scope_map, first_scope,
PROBE_AREA, PROBE_STEM)` and `Q` is the same with `PROBE_STEM_2`, where
`first_scope = sorted(scope_map)[0]`. Every case binds its client fixture
to the parameter name `client` (the token `ast` rule exempts calls on
that name).

### User Story 1 - Fixture contract (Priority: P1)

**Acceptance Scenarios**:

1. **Given** the reference fixtures, **When** the suite runs, **Then**
   every baseline case passes and none is skipped.
2. **Given** a `client` fixture returning an object that does not satisfy
   `TransportClient` (`isinstance` False), **Then** every case fails
   (`fixture client`) naming the object's type.
3. **Given** a bad `source` (not a non-empty exact `str`), `scope_map`
   (not a `Mapping` by real type, fewer than two entries, or any key or
   value not an exact `str` passing `is_valid_segment`), `max_file_bytes`
   (not an exact `int` ≥ `MIN_FILE_BYTES`; `bool` rejected),
   `index_max_bytes` / `list_page_size` (not an exact `int` > 0; `bool`
   rejected), or `scope_priority` (not an exact `tuple` of exact `str`
   valid segments without duplicates; a `str` or `list` rejected),
   **Then** the cases that use it fail (`fixture <name>`) naming the
   problem. When several fixtures are bad, the first in the order client,
   source, scope_map, max_file_bytes, index_max_bytes, scope_priority,
   list_page_size is reported. `test_client_satisfies_protocol` takes all
   seven fixtures and validates them in that order, so every fixture is
   required and checked from the first run, even before AIE-1045's cases
   use the last three.
4. **Given** a `client` fixture that returns one shared stateful object
   across tests, **When** two different stateful cases run in sequence,
   **Then** the second fails (`not isolated`) naming the sentinel path.
   Verified by calling two different baseline cases on one client.
5. **Given** a missing fixture, **Then** pytest reports a collection
   error, as with `ResolverConformance`.
6. **Given** the sentinel path, **Then** it is `build_path(first_scope,
   scope_map[first_scope], SENTINEL_AREA, SENTINEL_STEM)`: the caller's
   own entity in a writable scope (fixture contract), in an area no case
   uses for data. **Given** `without_sentinel(index_or_entries)`, **Then**
   for an iterable of `FileEntry` it returns a tuple of the entries whose
   area segment is not `SENTINEL_AREA`, and for a `MemoryIndex` it returns
   a `MemoryIndex` with those entries and with any `CappedPrefix` whose
   prefix ends in `/conformance-sentinel/` removed (signature
   `without_sentinel(name, label, value)`), for AIE-1045's list
   and index cases (the sentinel is the oldest entry in its tier, so it is
   the likeliest to be capped, and it occupies one slot on entity- and
   scope-level `list_prefix` pages). `sentinel_entry_bytes(name, client,
   scope_map)` (no `label` parameter; it labels its calls
   `list_prefix(<sentinel prefix>)`) lists `build_prefix(first_scope,
   scope_map[first_scope], SENTINEL_AREA)` through `client`, checks the
   page with
   `canonical_page`, requires exactly one entry (else fails `sentinel
   missing`), and returns `index_entry_bytes` of that client-returned
   `FileEntry`; it never constructs a `FileEntry` from a token.

---

### User Story 2 - Harness mechanics (Priority: P1)

**Acceptance Scenarios**:

0. **Every failure message in the module except the fixture checks
   starts `f"{name}: {label}: "`**, where `name` is the client class name
   and `label` names what is being checked (e.g. `f"read_file({P})"`,
   `f"write result for {P}"`). Every helper other than the `check_*`
   fixture functions and the three sentinel helpers takes `name, label` as
   its first two positional-only parameters, and the cases' own failures
   (`round trip`, `source not stamped`, `token not accepted`) use the same
   form. So a self-test can match the probe path in the message and know
   which call fired. The sentinel helpers take no `label` parameter:
   `sentinel_path(scope_map)` takes neither `name` nor `label` and never
   fails; `require_fresh(name, client, scope_map)` builds its own labels
   from the sentinel path (`read_file(<sentinel>)`,
   `write_file(<sentinel>)`); and `sentinel_entry_bytes(name, client,
   scope_map)` builds `list_prefix(<sentinel prefix>)`. The `check_*`
   functions take no `label` and their messages carry no path.
1. **Given** `expect_error(name, label, call, NotFoundError,
   ErrorCategory.RECOVERABLE, path=P, reason=NotFoundReason.FILE_ABSENT)`,
   **When** `call()` raises `NotFoundError(P, FILE_ABSENT)`, **Then** it
   returns the exception. **When** `call()` returns, **Then** fail (`did
   not raise`) naming the returned type and, for `OversizeWriteError`,
   adding "check the max_file_bytes fixture". **When** it raises a
   different real type (a subclass or a `__class__` spoof included),
   **Then** fail (`wrong error type`) naming both. **When** the type is
   right but `exc.category is not category`, **Then** fail (`wrong
   category`). **When** a payload attribute is missing, raises on read,
   has a different exact type (`"file_absent"` for
   `NotFoundReason.FILE_ABSENT`; a `str` subclass for `path`), or a
   different value, **Then** fail (`wrong payload`) naming the attribute
   and both values, each `repr` truncated to 80 characters. A non-
   `Exception` `BaseException` propagates.
2. **Given** `expected` that is not a `WenchangError` subclass
   (`ValueError`, `MetadataFormatError`, `UnicodeDecodeError`), **Then**
   `category` must be `None`, else the call fails (`harness misuse`);
   **given** a `WenchangError` subclass with `category=None`, likewise.
   **Given** `message="..."`, **Then** `str(exc)` must equal it exactly,
   else fail (`wrong message`); `str(exc)` is read inside a guard and a
   raise fails (`wrong message`) with "unreadable". `expect_error`'s
   parameters `name`, `label`, `call`, `expected`, `category` are
   positional-only so a payload attribute can never collide with them.
3. **Given** `canonical_file(name, label, value)`, **Then** it checks, by exact
   type and in this order, `type(value) is MemoryFile`; `path` and
   `content` exact `str`; `metadata` exact `FileMetadata`; `description`
   exact `str`; `aliases` exact `tuple` of exact `str`; `sources` exact
   `frozenset` of exact `str`; `last_updated` exact `datetime` with
   `utcoffset() is not None`; `version` exact non-empty `str`. The first
   failure fails (`wrong result type`) for the outer type, or (`bad
   field`) naming the field. It returns `(path, content, description,
   aliases, tuple(sorted(sources)), last_updated)`. `version` is not in
   the tuple and is never compared.
4. **Given** `canonical_entry` (`FileEntry`: path, metadata, version →
   `(path, description, aliases, sorted sources, last_updated)`),
   `canonical_page` (`ListPage` → `(tuple of canonical entries,
   next_cursor is None)`, with `next_cursor` exact `str` or `None`), and
   `canonical_index` (`MemoryIndex` → `(tuple of canonical entries,
   tuple((prefix, omitted)))`, with each `capped` member exact
   `CappedPrefix`), **Then** they apply the same exact-type rules and
   phrases.
5. **Given** `probe_path(name, label, scope_map, scope, area, stem)`, **Then** it
   returns `build_path(scope, scope_map[scope], area, stem)` and fails
   (`probe scope`) for a scope not in the map (a harness or case bug, not
   a fixture problem).
6. **Given** the harness module, **Then** it never parses, orders,
   compares, slices, or does arithmetic on a version token, and never
   passes one to a builtin or method other than the client's own methods
   and `type()`. Pinned by an `ast` scan: no `Compare`, `BinOp`,
   `Subscript`, or `Call` node whose operand, positional argument, or
   keyword value is a `Name` or `Attribute` whose identifier ends with
   `version`, except a `Call` whose func is the name `type` or an
   `Attribute` on the name `client`. The scan is itself tested: it flags
   `a.version == b.version`, `x.version[0]`, `int(x.version)`,
   `f(version=r.version)`, `sorted(v.version)`, and allows
   `type(x.version)` and `client.write_file(p, c, m, r.version,
   source=s)`. The shape check is `type(v) is str and v` (truthiness,
   not `!= ""`).
7. **Given** `require_fresh(name, client, scope_map)`, **Then** it runs
   `expect_error(name, lambda: client.read_file(sentinel), NotFoundError,
   RECOVERABLE, path=sentinel, reason=FILE_ABSENT)` but with the
   "did not raise" outcome reported as `not isolated` naming the path
   (implemented by catching the result first: a returned value → `not
   isolated`; otherwise the normal `expect_error` phrases apply), then
   writes the sentinel (`"- [system] conformance sentinel\n"`, description
   `"conformance sentinel"`, no aliases, no sources,
   `source="conformance-harness"`, `expected_version=None`) inside a
   guard: any exception fails (`sentinel write failed`) naming the type.
   With `max_file_bytes >= MIN_FILE_BYTES` the sentinel content (32
   bytes) always fits.
8. **Given** any client call a case makes that is not under
   `expect_error` (the setup writes and reads in US3.2–3.3), **Then** it
   runs inside `_call(name, label, fn)`, which returns the result or
   fails (`unexpected error`) naming `label` and the exception type, so
   FR-003 holds for every check in the module. `without_sentinel` runs
   each entry through `canonical_entry` before reading its area (a
   malformed path fails `bad field path`, never a raw `ValueError`), and
   `sentinel_entry_bytes` wraps `index_entry_bytes` in `_call`.

---

### User Story 3 - Baseline cases (Priority: P1)

Each is a `test_*` method on the mixin. Every stateful case (3.2–3.5)
calls `require_fresh` first.

**Acceptance Scenarios**:

1. `test_client_satisfies_protocol`: takes all seven fixtures and
   validates them in the fixed order (US1.3); then `isinstance(client,
   TransportClient)` and every one of the seven methods is callable;
   fails (`fixture client`) otherwise. Stateless (no `require_fresh`).
2. `test_write_then_read_round_trips`: with `seed = "s0" if source !=
   "s0" else "s1"` and `expected = (P, "- [stated] a\n", "d", ("x", "y"),
   tuple(sorted({seed, source})))`, `w = write_file(P, "- [stated] a\n",
   FileMetadata("d", ("x", "y"), frozenset({seed}), datetime(2000, 1, 1,
   tzinfo=UTC)), None, source=source)` then `r = read_file(P)`. Checks,
   in order: (i) both results canonicalize (US2.3); (ii) for each of
   `cw` then `cr`, field 4 (`sources`) `!= expected[4]` fails (`source not
   stamped`) naming the result (`write result` / `read result`), and any
   of fields 0–3 differing fails (`round trip`) naming the field and the
   result; (iii) `cw[5] != cr[5]` fails (`round trip`) naming
   `last_updated`. So `last_updated` is round-tripped between the two
   server-stamped results and never compared with the test's clock.
3. `test_returned_token_is_accepted`: `write_file(P, ...)` as in 3.2;
   `r = read_file(P)`; `write_file(P, "- [stated] b\n", r.metadata,
   r.version, source=source)` must succeed and canonicalize; then `w =
   write_file(Q, "- [stated] q\n", <same metadata>, None,
   source=source)` and `append_line(Q, "- [stated] c", w.version,
   source=source)` must succeed. Any exception from the two accepting
   calls fails (`token not accepted`) naming the call. No token is
   compared.
4. `test_read_absent_is_not_found`: `read_file(P)` →
   `expect_error(NotFoundError, RECOVERABLE, path=P,
   reason=NotFoundReason.FILE_ABSENT)`.
5. `test_oversize_write_is_rejected`: `write_file(P, "x" *
   (max_file_bytes + 1), ...)` → `expect_error(OversizeWriteError,
   RECOVERABLE, path=P, size=max_file_bytes + 1, limit=max_file_bytes)`;
   then `read_file(P)` → `NotFoundError(FILE_ABSENT)`.

---

### User Story 4 - Self-tests (Priority: P1)

Broken clients wrap a real `InProcessClient`, forward every call, and
misbehave **only for the probe paths `P` and `Q`** (never for the
sentinel path), so `require_fresh` passes and the case under test is
what fires. Every self-test matches both the key phrase and the probe
path `P` (or `Q`) in the failure message, which every message carries
through its `label` (US2.0), proving the case fired rather than
`require_fresh` (whose labels name the sentinel path). The one exception
is US4.8's second client, which misbehaves on the sentinel path.

**Acceptance Scenarios**:

1. `read_file(P)` returns a `dict` for an existing file (absent reads
   still raise) → round trip fails (`wrong result type`).
2. `read_file` returns a `MemoryFile` whose `aliases` is a `list` → (`bad
   field` naming `aliases`); whose `metadata.last_updated` is naive →
   (`bad field` naming `last_updated`); whose `version` is `""` → (`bad
   field` naming `version`).
3. `read_file` drops an alias → (`round trip` naming `aliases`); alters
   the trailing newline → (`round trip` naming `content`); returns a
   different `last_updated` than the write result → (`round trip`
   naming `last_updated`); returns a `MemoryFile` with the wrong `path`
   → (`round trip` naming `path`).
4. A client whose `write_file` and `read_file` both strip `source` from
   the returned `sources` (both methods overridden, since the store
   stamps it and the two results are compared with `expected` before
   each other) → (`source not stamped` naming `write result`).
5. `read_file` raises `KeyError` for an absent path → (`wrong error
   type` naming `KeyError`); raises a `__class__`-spoofing exception →
   (`wrong error type`); raises `NotFoundError` with `reason` set to the
   plain string `"file_absent"` → (`wrong payload` naming `reason`);
   raises a `NotFoundError` whose instance `category` is overridden to
   `TRANSIENT` → (`wrong category`).
6. `write_file` accepts the oversize write → (`did not raise` containing
   "max_file_bytes"); raises `NotFoundError(P, INVALID_PATH)` instead →
   (`wrong error type`); raises `OversizeWriteError(P, 1, 1)` → (`wrong
   payload` naming `size`).
7. `write_file` returns a `MemoryFile` whose `version` the client later
   rejects (a client that forgets its own tokens, raising
   `VersionConflictError`) → `test_returned_token_is_accepted` fails
   (`token not accepted`).
8. Two different baseline cases run on one shared stateful client → the
   second fails (`not isolated`). A client whose `write_file` raises
   only for the sentinel path → (`sentinel write failed`). A client whose
   `write_file(P)` raises `RuntimeError` → the round-trip case fails
   (`unexpected error`) naming `write_file` and `RuntimeError`.
8a. `test_client_satisfies_protocol` with any one of the seven fixtures
   bad → (`fixture <name>`); with two bad, the earlier in the fixed
   order is named.
9. `expect_error(..., ValueError, ErrorCategory.RECOVERABLE)` → (`harness
   misuse`); `expect_error(..., NotFoundError, None)` → (`harness
   misuse`); `expect_error(..., ValueError, None, message="x")` against
   `ValueError("y")` → (`wrong message`).
10. Each self-test also confirms the same case passes for the reference
    client.

---

### User Story 5 - Packaging and boundaries (Priority: P1)

**Acceptance Scenarios**:

1. `wenchang.testing` exports `ResolverConformance` and
   `TransportConformance`; the latter's name does not start with `Test`.
2. `src/wenchang/testing/transport_conformance.py` imports `pytest` and
   from `wenchang` only `core`, `errors`, `file_format`, `paths`,
   `transport`, `version_token`; applies no pytest marks; cites no Linear
   IDs. The `wenchang.testing` import guard for the rest of the library is
   unchanged.
3. `TransportConformance`'s `test_*` names are exactly the five in US3.
4. The token-rule `ast` scan of US2.6 passes on the module, flags each
   listed violation, and allows each listed exemption.

### Edge Cases

- `last_updated` is compared only between two results from the same
  client in one test, never against the test's clock.
- Tokens are never compared, even for equality: a remote may return
  different but equivalent token strings from a write and a read. Tokens
  are checked only by handing them back.
- A client must stamp strictly increasing `last_updated` across
  sequential writes within one test; the reference fixture uses a
  ticking clock. An adopter whose server clock cannot guarantee this
  cannot run the recency-ordering cases AIE-1045 adds; that contract is
  stated in the module docstring.
- Concurrency cases (AIE-1045) are modeled as sequential interleavings
  on one client (two reads at the same version, then two writes), so no
  thread safety is required of a `TransportClient`.
- The sentinel lives under the first mapped entity in area
  `conformance-sentinel`, so entity- and scope-level `list_prefix` and
  `get_memory_index` *do* see it, it may appear in `capped`, and it takes
  a page slot; AIE-1045's cases filter with `without_sentinel` (entries
  and capped) and budget with `sentinel_entry_bytes`. Given the fixture
  contract that every mapped scope is writable, `require_fresh` is valid
  under the enforcement decision (option (a)) and would have been under
  any other.
- `scope_priority` must be an exact `tuple` even though `MemoryStore`
  accepts any `Sequence`; the module docstring says so.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `wenchang.testing` MUST export `TransportConformance`, a
  pytest mixin whose test methods take only the seven fixtures.
- **FR-002**: The harness MUST provide `require_fresh`, `sentinel_path`,
  `without_sentinel`, `sentinel_entry_bytes`, `probe_path`,
  `expect_error`, `canonical_file`, `canonical_entry`, `canonical_page`,
  `canonical_index`, and the fixture check functions as public
  module-level functions with the behavior in US1.6 and US2.
- **FR-003**: Every violation MUST be reported with `pytest.fail`, never a
  bare `assert`, naming the client class and a fixed key phrase; every
  client call a case makes runs under `expect_error` or `_call`, so no
  raw exception escapes a case.
- **FR-004**: The harness MUST NOT parse, order, compare, slice, or do
  arithmetic on version tokens (US2.6), and MUST NOT compare
  `last_updated` against anything but another result from the same
  client.
- **FR-005**: Fixture values MUST be validated before use, in the order
  of US1.3.
- **FR-006**: All type checks on client-returned values MUST be exact
  (`type(x) is T`), nested through metadata fields and collection
  members.
- **FR-007**: The shipped module MUST cite no Linear IDs and apply no
  pytest marks; test docstrings under `tests/` MUST cite AIE-1047.

## Success Criteria *(mandatory)*

- **SC-001**: The reference run passes; every self-test broken client
  fails its named case; `make check` passes.

## Assumptions

- Seven fixtures now, so AIE-1045 never changes the contract. The three
  store settings beyond `max_file_bytes` are required even though no
  baseline case uses them, because validation and documentation of the
  fixture contract live here.
- ADR number: this issue takes **ADR 0021**; AIE-1044 (blocked on human
  decisions) moves to 0022.
- **Decided by the human on 2026-10-02: option (a).** §10.2 lists
  "`system/` prefix writes rejected; write-restricted scopes rejected for
  callers lacking the role" among the transport suite's assertions, but
  the transport is identity-agnostic (ADR 0019) and `MemoryStore`
  enforces no scope rule (ADR 0016/0017), so the in-process client accepts
  a `system/` write. Options: (a) the transport suite asserts a transport
  *accepts* `system/` writes (parity; enforcement belongs to tools and
  resolver suites; a remote server must then not enforce at the
  transport, amending ADR 0019 decision 6's "server can enforce"
  wording); (b) run enforcement cases through the tool layer with
  identity fixtures; (c) leave transport enforcement unspecified. The
  human chose **(a)**: the transport suite asserts a `system/` write is
  accepted at the transport; `system/` read-only and role restriction are
  enforced only in the tool layer (tested by the tool-layer and resolver
  suites); a remote server must not enforce scope at the transport,
  since authorization happens in the tool layer, where identity is known.
  ADR 0021 records the decision and ADR 0019 carries the amendment to
  decision 6. AIE-1045 adds `test_system_area_write_is_accepted_at_transport`.
  This harness needed no change: given the fixture contract that every
  mapped scope is writable through `client`, the sentinel and probes are
  own-entity writes in those scopes.
- Branch is rebased onto the final `AIE-1046-inprocess-client` commit
  (ADR 0020 present) before T1; tasks.md checks this.
