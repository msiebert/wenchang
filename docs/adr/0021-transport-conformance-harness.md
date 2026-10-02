# 0021. Transport conformance harness

Date: 2026-10-01

## Status

Accepted

## Context

Notion Section 10 says an adopter implements two interfaces, the identity
resolver and the transport client, and that "the library ships an
executable conformance suite for each. Passing defines a correct
implementation." Section 10.2 says the in-process and remote transports
"must be behaviorally indistinguishable" and that the suite "runs
identically against any implementation and asserts" round-trip fidelity
("content and all four metadata fields survive write-then-read
byte-for-byte"), version token opacity ("the suite treats tokens as opaque
strings and never parses, orders, or compares them, modeling correct
caller behavior"), enforcement, index behavior, and error parity ("every
error surfaces in the same category with the same payload across
implementations"). Section 5 says no caller may "parse, compare, order, or
arithmetically treat" a version token.

AIE-1047 builds the harness: the shared machinery that runs the transport
suite against any `TransportClient`, so the in-process client and a future
remote client (e.g. gRPC) are validated by the same cases. The exhaustive
Section 10.2 case list is AIE-1045, which adds further methods to the same
mixin. The pieces under test already exist: `TransportClient` and its
error-parity contract (ADR 0019) and `InProcessClient` over
`MemoryStore`, with `get_memory_index`, `index_entry_bytes`, and the index
settings (ADR 0020).

ADR 0018 established the shape for the resolver suite: an installed
`wenchang.testing` subpackage behind the `wenchang[testing]` extra, a
pytest mixin with required fixtures, `pytest.fail` with fixed key phrases,
no pytest marks, no Linear IDs, and self-tests that call the mixin's
methods directly. It anticipated that the transport suite would reuse that
shape. ADR 0019 decision 8 deferred hardening `MemoryFile`, `FileEntry`,
and `ListPage` against malformed remote-built values to "a
conformance-suite parity case".

A transport suite differs from the resolver suite in three ways that drive
the decisions below. It is stateful: cases write and read through a store,
so they need isolation. Its subjects return values whose tokens and
timestamps legitimately differ between implementations, so equality
against a reference is unavailable. And its main obligation, parity,
concerns errors as much as results.

## Decision

Add `wenchang.testing.transport_conformance`, exporting the mixin
`TransportConformance` (re-exported from `wenchang.testing`) with five
baseline test methods, and public module-level helpers for later cases. No
existing module changes.

1. **Same shape as `ResolverConformance`.** A pytest mixin in
   `wenchang.testing` whose name does not start with `Test`, required
   fixtures, every violation reported with `pytest.fail` and a fixed key
   phrase, a caught exception left attached as context, no pytest marks,
   and no Linear IDs in the shipped module.
   - **Rejected: a differential harness** that runs each operation against
     the adopter's client and a reference `MemoryStore` and compares
     results. Tokens and timestamps differ between stores by construction,
     so results must be canonicalized anyway, and a differential harness
     would still need everything below plus a second store to keep in step.
2. **Seven required fixtures**: `client`, `source`, `scope_map`,
   `max_file_bytes`, `index_max_bytes`, `scope_priority`, and
   `list_page_size`. The last four are the values the client's store was
   configured with. Every store setting a case may need to predict behavior
   (oversize, the index cap, index order, pagination) is a fixture from day
   one, so AIE-1045 never changes the published contract. Each is validated
   by exact type before use, in that fixed order, failing with `fixture
   <name>`: `scope_map` must be a `Mapping` by real type whose `items()`
   yields at least two distinct exact-`str` valid-segment keys with
   exact-`str` valid-segment values (an `items()` that raises or repeats a
   key fails); `max_file_bytes` an exact `int` of at least
   `MIN_FILE_BYTES = 64`; `index_max_bytes` and `list_page_size` exact
   positive `int`s (`bool` rejected); `scope_priority` an exact `tuple` of
   distinct exact-`str` valid segments, even though `MemoryStore` accepts
   any `Sequence`.
   - **Rejected: a single `settings` fixture**, which would couple the
     contract to `MemoryStore`'s constructor.
   - **Rejected: adding fixtures as AIE-1045 needs them**, which changes a
     published contract after adopters have written subclasses.
3. **Version tokens are never compared, not even for equality.** Section
   10.2 says the suite never compares tokens, and `version_token.py` says
   callers never compare them; a remote may legitimately return different
   but equivalent token strings from a write and a following read. The
   suite checks a token only by shape (`type(v) is str and v`) and by
   handing it back: `test_returned_token_is_accepted` passes a read's token
   to `write_file` and a write's token to `append_line`, and a raise fails
   with `token not accepted`. A test-side `ast` scan pins the rule over the
   module: no `Compare`, `BinOp`, `Subscript`, or `Call` may take a `Name`
   or `Attribute` ending in `version` as an operand or argument, except a
   call to `type` or a method on the name `client`. The scan is itself
   tested against listed violations and exemptions. AIE-1045 must check a
   `VersionConflictError.version` the same way, by passing it back, never
   with `version=...` in `expect_error`.
   - **Rejected: `write.version == read.version`**, which over-constrains a
     correct remote and contradicts Section 10.2's wording.
4. **`last_updated` round-trips between the write result and the read
   result**, both stamped by the same server, and is never compared with
   the test's clock.
   - **Rejected: dropping `last_updated` from the round trip**, which
     leaves Section 10.2's "all four metadata fields" at three.
5. **Deep exact-type canonical readers.** `canonical_file`,
   `canonical_entry`, `canonical_page`, and `canonical_index` check every
   nested field of a client-returned value by exact type (`type(x) is T`):
   the outer `MemoryFile`, `FileEntry`, `ListPage`, or `MemoryIndex`;
   `FileMetadata`; `str` path, content, and description; a `tuple` of `str`
   aliases; a `frozenset` of `str` sources; an aware `datetime`; a
   `FileEntry` path that passes `is_valid_path`; `CappedPrefix` members
   with `str` prefix and `int` omitted; a `str | None` cursor. They fail
   with `wrong result type` or `bad field <name>` and return plain tuples
   without the version. Every attribute read is guarded, so a field that
   raises on read fails `bad field <name>: unreadable`. `last_updated` is
   converted to UTC inside the guard that reads its offset (any failure
   there is `bad field last_updated: offset unreadable`), so no later
   comparison or formatting runs client `tzinfo` code, and the same instant
   at another offset compares equal. This is the parity case ADR 0019
   decision 8 deferred.
   - **Rejected: duck-typed reads**, which let a remote returning lists,
     sets, dicts, or strings either pass or crash with an uncaught
     exception.
6. **`expect_error` is the one error-parity helper.** `expect_error(name,
   label, call, expected, category, /, *, message=None, **payload)` requires
   `type(exc) is expected` (a subclass or a spoofed `__class__` fails
   `wrong error type`); `category` is required for a `WenchangError`
   subclass and must be `None` otherwise, a mismatch being `harness
   misuse`; `message`, if given, must equal `str(exc)`, read inside a
   guard; each payload attribute is read inside a guard and compared by
   exact type, then value, with reprs truncated to 80 characters. A call
   that returns fails `did not raise`, with a hint to check the
   `max_file_bytes` fixture when `OversizeWriteError` was expected. The
   leading parameters are positional-only, so a payload attribute named
   `name` or `call` cannot collide. A non-`Exception` `BaseException`
   propagates.
   - **Rejected: `pytest.raises`**, which matches by `isinstance`, does not
     name the client, and does not check the payload.
   - **Rejected: `!=`-only payload checks**, which let a plain `str` stand
     in for a `StrEnum` reason and a `str` subclass stand in for a path.
7. **Isolation by a sentinel, checked at the start of every stateful
   case.** `require_fresh(name, client, scope_map)` reads the sentinel
   path: a returned value fails `not isolated`, naming the returned type;
   anything but
   `NotFoundError(path, FILE_ABSENT)` fails through `expect_error`'s
   phrases; then it writes the sentinel, any exception failing `sentinel
   write failed`. The sentinel is `build_path(first, scope_map[first],
   "conformance-sentinel", "sentinel")`, where `first` is the first scope in
   sorted order: the caller's own entity, in an area no case uses for data.
   The fixture contract requires every mapped scope to be writable through
   `client` under the credentials it was constructed with; the probe paths
   need this too. So a `client` fixture shared across tests fails on the
   second stateful case, in any order. Entity- and scope-level listings and
   the index do see the sentinel (it is the oldest entry in its tier, so
   the likeliest to be capped), so AIE-1045's list and index cases filter
   it with `without_sentinel` (entries and, for a `MemoryIndex`, its
   `CappedPrefix`, rebuilding the index under `_call` so a malformed one
   fails rather than raising) and budget it with `sentinel_entry_bytes`, which lists
   the sentinel through the client and returns `index_entry_bytes` of the
   returned `FileEntry` rather than constructing one around a token.
   - **Rejected: a single isolation case** that writes and expects a
     clean store. Within one run each case gets its own fixture call, so
     such a case can never observe sharing.
   - **Rejected: a factory fixture** (`make_client()`), which doubles the
     contract.
   - **Rejected: a sentinel under an unmapped entity**, which a remote
     server enforcing scope on its side could reject, making the harness
     depend on the open enforcement question (decision 10).

   7a. **`test_client_satisfies_protocol` takes all seven fixtures** and
   validates them in the fixed order. The `client` check first reads each
   of the seven method names, failing with the method named if it is
   missing, not callable, or could not be read, and then runs
   `isinstance(client, TransportClient)` inside a guard, so a client whose
   `__class__` raises fails `fixture client` rather than erroring. So every fixture is required and checked from the first run,
   even though only AIE-1045's cases use `index_max_bytes`,
   `scope_priority`, and `list_page_size`.
   - **Rejected: validating lazily in the cases that use each fixture**,
     which would let an adopter omit fixtures until the exhaustive cases
     land and then break.
8. **Baseline cases ship with the harness**:
   `test_client_satisfies_protocol`, `test_write_then_read_round_trips`,
   `test_returned_token_is_accepted`, `test_read_absent_is_not_found`, and
   `test_oversize_write_is_rejected`. They make the harness self-testable
   (each self-test drives a deliberately broken client through a real case)
   and give AIE-1045 a worked template.
9. **Clock and concurrency contract.** Within one test, a client's writes
   must stamp strictly increasing `last_updated` values; the repo's
   reference run uses a clock that ticks one microsecond per call. Cases
   call the client sequentially, and AIE-1045's concurrency cases are
   modeled as sequential interleavings on one client (two reads at the same
   version, then two writes), so no thread safety is required of a
   `TransportClient`.
   - **Rejected: a fixed clock**, under which recency-ordering cases are
     untestable.
   - **Rejected: real threads**, which demand a thread-safety guarantee
     nothing else in the library requires.
10. **Section 10.2's enforcement bullets are not decided here.** See the
    open question below. AIE-1045 writes the case once it is answered.

Every message except a fixture check's has the form `name: label:
phrase`, where `name` is the client class (read through a guarded helper
that reports `<unnamed>` if `__name__` raises) and `label` names the call
or result under check, such as `read_file(<path>)` or `write result for
<path>`. Every client call a case makes runs under `expect_error` or a
private `_call` wrapper that turns any `Exception` into `unexpected error`,
so no raw exception escapes a case. The self-tests rely on the label: each
matches the probe path in the message, proving the case under test fired
rather than `require_fresh`.

### Open question for the human

Section 10.2 lists "`system/` prefix writes rejected; write-restricted
scopes rejected for callers lacking the role" among the assertions of the
transport suite. But the transport is identity-agnostic (ADR 0019 decision
6), and `MemoryStore` applies no scope rule (ADR 0016, ADR 0017), so
`InProcessClient` accepts a `system/` write. The options:

- **(a)** The transport suite asserts a transport *accepts* `system/` and
  restricted-scope writes (parity with the in-process client), and
  enforcement is tested by the tool-layer and resolver suites. A remote
  server must then not enforce scope at the transport, which amends ADR
  0019 decision 6's "a server can enforce scope on its side" wording.
- **(b)** Enforcement cases run through the tool layer, with identity
  fixtures added to the transport suite for them.
- **(c)** Transport enforcement is left unspecified, and the suite asserts
  nothing about it.

The orchestrator recommends **(a)**: it keeps the transport the pure
mirror of core that ADR 0019 describes, and enforcement already has one
home (`scope.check_write`, called by the tool layer). This harness is
valid under any answer, given the fixture contract that every mapped
scope is writable through `client`: the sentinel and the probe paths are
all own-entity, non-`system/` writes in mapped scopes.

### Adversarial review

The spec went through six rounds of adversarial spec review before
implementation. Findings incorporated: an isolation probe that could never
fire in a single run (now `require_fresh` in every stateful case); a token
`==` check (removed, decision 3); `last_updated` dropped from the round
trip (restored between two server results, decision 4); an `expect_error`
that matched by `isinstance` and `!=` (now exact type and exact-typed
payload, decision 6); a hard-coded `source` (now a fixture); shallow
readers (now deep, decision 5); an ADR number collision with AIE-1044
(this ADR takes 0021, AIE-1044 moves to 0022); the missing writability
contract for the sentinel's scope (decision 7); broken self-test clients
that misbehaved for every path, including the sentinel (now scoped to the
probe paths); and failure messages that did not say which call fired (now
`name: label: phrase`).

An adversarial code review of the implementation then found places where
a malformed client value made a case ERROR with a raw exception instead
of FAIL through `pytest.fail`, against FR-003. All were fixed: unguarded
field reads in the canonical readers (now `bad field <name>:
unreadable`); a client whose `__class__` raises, which escaped the
`isinstance` check (now guarded, after a per-method walk that names a
missing, unreadable, or non-callable method); a `tzinfo` whose
`utcoffset` succeeds once and then raises, which escaped at comparison
time (now normalized to UTC inside the guard); a `scope_map` whose
`items()` repeats a key, which passed with fewer than two distinct scopes
(now rejected, with the count re-checked); and a `MemoryIndex` rebuild in
`without_sentinel` that raised `ValueError` on duplicate entry paths (now
under `_call`). The `not isolated` message gained the returned type, and
the token `ast` scan gained method calls on a token and f-string
interpolation of one.

A coverage review ran 40 mutants against the module and found 14 real
(non-equivalent) survivors. Each now has a killing self-test, among
them: an oversize write that stores the file before raising, a store
whose limit is one byte high, a client that strips the fixture's own
`source`, a non-callable method, a `dict` returned by the token case's
rewrite or append, a `list` `capped`, a capped prefix that only looks
like the sentinel's, an unreadable `category` in `expect_error`, an
`items()` that raises, a generator that raises mid-iteration, wrong
`CappedPrefix` field types, and a changed description in the round trip.
The review also added a `pytester` test that a subclass missing a
fixture errors at setup (US1.5), which had no dedicated test.

## Consequences

An adopter verifies a transport client by subclassing
`TransportConformance` and supplying seven fixtures; the repo runs the
suite against `InProcessClient(MemoryStore(InMemoryStorage(), ...))`, and
self-tests prove each baseline case fails for a deliberately broken
client. Because the suite defines correctness, a change to it needs a
matching self-test. AIE-1045 adds the exhaustive cases as further methods
on the same mixin without changing the fixture contract.

The deep exact-type checks bind a remote client's decoding to core's exact
value types: a client that returns `list` aliases, a `set` of sources, a
naive `datetime`, or a `str` subclass where core returns `str` fails, even
if its values are equal. That is the intent of Section 10.2's
"indistinguishable", but it means a remote client must rebuild exactly
`MemoryFile`, `FileMetadata`, `FileEntry`, `ListPage`, `MemoryIndex`, and
`CappedPrefix` with exact member types.

An adopter whose server clock cannot guarantee strictly increasing
`last_updated` within one test cannot pass the recency-ordering cases
AIE-1045 adds. An adopter whose scopes are not all writable through the
test client must narrow `scope_map` to scopes that are. Neither is
checked directly; both are stated in the module docstring.

The sentinel occupies a slot in entity- and scope-level listings and in
the index, so every later list or index case must filter it and account
for its bytes. Forgetting to is a case bug, not an adopter bug.

Because tokens are never compared, the suite cannot detect a client that
returns a stale-but-accepted token, or two different tokens for the same
version; it detects only a token the client itself rejects. That matches
what a correct caller can observe.

The enforcement case waits on the open question. AIE-1044, the tool layer,
records its decisions as ADR 0022.
