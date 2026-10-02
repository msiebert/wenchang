# Implementation Plan: Shared transport conformance harness

**Linear issue**: AIE-1047 | **Branch**: `AIE-1047-transport-harness` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

## Summary

Add `src/wenchang/testing/transport_conformance.py` exporting
`TransportConformance` plus the public helper functions, with the class
re-exported from `wenchang.testing`. Three new test files; additions only
to `tests/test_testing_package.py`. No existing module changes. Based on
`AIE-1046-inprocess-client`; PR targets that branch until it merges.

## Technical Context

Python ≥ 3.12; pyright strict; ruff 100. The module imports `pytest` and
from `wenchang`: `core` (`CappedPrefix`, `FileEntry`, `ListPage`,
`MemoryFile`, `MemoryIndex`), `errors` (`ErrorCategory`, `NotFoundError`,
`NotFoundReason`, `OversizeWriteError`, `WenchangError`), `file_format`
(`FileMetadata`), `paths` (`build_path`, `is_valid_segment`), `transport`
(`TransportClient`), `version_token` (`VersionToken`). Follows
`resolver_conformance.py`: module-level helpers, `pytest.fail`
everywhere, `_name` for guarded type names, `cast(object, ...)` before
runtime type checks on typed parameters.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1–T3 each test-writer → implementer |
| II. Tests not negotiable | Existing `ResolverConformance` tests untouched; additions only |
| IV. Strict typing | `expect_error[E: Exception]` returns `cast(E, exc)` after the `type(exc) is expected` check; PEP 695 `type` aliases for canonical tuples |
| V. Storage only through interface | No storage access |
| VI. Spec fidelity | §10 suite shape; §10.2 baseline cases; token opacity read strictly (no `==`). Enforcement bullets left to AIE-1045 pending the human's answer |
| VII. Architecture documented | ARCHITECTURE.md `testing` and `transport` entries; ADR 0021 |
| VIII. Traceability | Test docstrings cite AIE-1047; shipped module cites none |
| IX. Small PR | One new module, one `__init__` line, three test files, one test-file addition |

**Decisions to record in ADR 0021:**

1. **Same shape as `ResolverConformance`**: a pytest mixin in
   `wenchang.testing`, required fixtures, `pytest.fail` with key phrases,
   no marks, no Linear IDs. Rejected: a differential harness comparing
   against a reference store; tokens and timestamps differ between stores
   by construction, so canonicalization is needed anyway.
2. **Seven required fixtures**: `client`, `source`, `scope_map`,
   `max_file_bytes`, `index_max_bytes`, `scope_priority`,
   `list_page_size`. All store settings a case may need to predict
   behavior are fixtures from day one, so AIE-1045 never changes the
   contract. Rejected: a `settings` object (couples to `MemoryStore`'s
   constructor); adding fixtures later (changes a published contract).
3. **Tokens are never compared, not even for equality.** §10.2 and
   `version_token.py` say callers never compare; a remote may return
   different but equivalent token strings. Tokens are checked only by
   handing them back (`test_returned_token_is_accepted`) and by shape
   (`type(v) is str and v`). An `ast` scan pins the rule. AIE-1045 must
   check `VersionConflictError.version` the same way (pass it back), never
   with `version=...` in `expect_error`. Rejected: `write.version ==
   read.version`, which over-constrains a correct remote.
4. **`last_updated` round-trips between the write result and the read
   result**, both stamped by the same server, and is never compared with
   the test's clock. Rejected: dropping it, which leaves §10.2's "all four
   metadata fields" at three.
5. **Deep exact-type canonical readers.** Every nested field of a
   client-returned value is checked by exact type (`FileMetadata`,
   `tuple[str]`, `frozenset[str]`, aware `datetime`, `str` version,
   `CappedPrefix` members, `str | None` cursor). This is the "parity case"
   ADR 0019 decision 8 deferred for `MemoryFile` / `FileEntry` /
   `ListPage`. Rejected: duck-typed reads, which let a remote returning
   lists, sets, dicts, or strings pass or crash uncaught.
6. **`expect_error` is the one parity helper.** Real-type match;
   `category` required for `WenchangError` subclasses and forbidden
   otherwise (`harness misuse`); optional exact `message`; payload compared
   by exact type then value, read through a guard, with truncated reprs;
   positional-only leading parameters. Rejected: `pytest.raises`
   (`isinstance`, no client name, no payload); `!=`-only payload checks
   (StrEnum/`str` lookalikes pass).
7. **`require_fresh` at the start of every stateful case**, with the
   sentinel under the first mapped scope's own entity in its own area
   `conformance-sentinel`. The fixture contract requires every mapped
   scope to be writable through `client` under its bound credentials (the
   probes need this too), so given that contract the harness is valid
   under every answer to the enforcement question. AIE-1045's list and
   index cases filter it (entries and `capped`) with `without_sentinel`
   and budget with `sentinel_entry_bytes`, which lists the sentinel
   through the client rather than constructing a `FileEntry` from a
   token. A
   shared client fails on the second stateful case in any order.
   Rejected: a single isolation case (cannot fire in a single run); a
   factory fixture (doubles the contract); an unmapped entity (a
   scope-enforcing remote server could reject it).
7a. **`test_client_satisfies_protocol` takes all seven fixtures** and
   validates them in the fixed order, so every fixture is required and
   checked from day one even though only AIE-1045's cases use the last
   three. Rejected: validating lazily per case, which lets an adopter
   omit fixtures until the exhaustive cases land.
8. **Baseline cases ship with the harness** so it is self-testable and
   gives AIE-1045 a worked template.
9. **Clock contract**: a client's writes stamp strictly increasing
   `last_updated` within one test; the reference uses a ticking clock.
   Concurrency is modeled as sequential interleavings; no thread safety is
   required. Rejected: a fixed clock (recency cases untestable); real
   threads (demands thread safety nothing else requires).
10. **Enforcement bullets of §10.2 are not decided here.** Open question
    for the human recorded in the ADR's "Open" section with the three
    options and the recommendation (a). AIE-1045 writes the case once
    answered.

## Public interface

### `src/wenchang/testing/__init__.py`

```python
from wenchang.testing.resolver_conformance import ResolverConformance
from wenchang.testing.transport_conformance import TransportConformance

__all__ = ["ResolverConformance", "TransportConformance"]
```

### `src/wenchang/testing/transport_conformance.py`

Module docstring (no Linear IDs) describing the seven fixtures, the
isolation and clock contracts, and an example subclass.

```python
PROBE_AREA: Final = "notes"
PROBE_STEM: Final = "conformance-probe"
PROBE_STEM_2: Final = "conformance-probe-2"
SENTINEL_AREA: Final = "conformance-sentinel"
SENTINEL_STEM: Final = "sentinel"
MIN_FILE_BYTES: Final = 64
_SENTINEL_SOURCE: Final = "conformance-harness"
_SENTINEL_CONTENT: Final = "- [system] conformance sentinel\n"
_REPR_LIMIT: Final = 80

type CanonicalFile = tuple[str, str, str, tuple[str, ...], tuple[str, ...], datetime]
type CanonicalEntry = tuple[str, str, tuple[str, ...], tuple[str, ...], datetime]
type CanonicalPage = tuple[tuple[CanonicalEntry, ...], bool]
type CanonicalIndex = tuple[tuple[CanonicalEntry, ...], tuple[tuple[str, int], ...]]


def _name(t: type) -> str: ...  # as in resolver_conformance
def _short(value: object) -> str: ...  # repr truncated to _REPR_LIMIT, guarded


def check_client(name: str, client: object) -> TransportClient: ...
def check_source(name: str, source: object) -> str: ...
def check_scope_map(name: str, scope_map: object) -> dict[str, str]: ...
def check_positive_int(name: str, fixture: str, value: object) -> int: ...
def check_scope_priority(name: str, value: object) -> tuple[str, ...]: ...


def probe_path(
    name: str, label: str, scope_map: Mapping[str, str], scope: str, area: str, stem: str, /
) -> str:
    """build_path(scope, scope_map[scope], area, stem); fail ("probe scope") if scope absent."""


def sentinel_path(scope_map: Mapping[str, str]) -> str:
    """build_path(first_scope, scope_map[first_scope], SENTINEL_AREA, SENTINEL_STEM)."""


@overload
def without_sentinel(name: str, label: str, value: MemoryIndex, /) -> MemoryIndex: ...
@overload
def without_sentinel(
    name: str, label: str, value: Iterable[FileEntry], /
) -> tuple[FileEntry, ...]: ...
def without_sentinel(
    name: str, label: str, value: MemoryIndex | Iterable[FileEntry], /
) -> MemoryIndex | tuple[FileEntry, ...]:
    """Drop the sentinel entry (and its CappedPrefix, for an index)."""


def sentinel_entry_bytes(
    name: str, client: TransportClient, scope_map: Mapping[str, str], /
) -> int:
    """index_entry_bytes of the sentinel FileEntry as listed through the client."""


def _call[T](name: str, label: str, fn: Callable[[], T], /) -> T:
    """Run fn(); any Exception fails ("unexpected error") naming label and the type."""


def require_fresh(name: str, client: TransportClient, scope_map: Mapping[str, str], /) -> None:
    """Fail ("not isolated") if the sentinel exists; then write it ("sentinel write failed" on error)."""


def expect_error[E: Exception](
    name: str,
    label: str,
    call: Callable[[], object],
    expected: type[E],
    category: ErrorCategory | None,
    /,
    *,
    message: str | None = None,
    **payload: object,
) -> E:
    """Run call(); fail unless it raises exactly `expected` with the given category, message, payload."""


def canonical_file(name: str, label: str, value: object, /) -> CanonicalFile: ...
def canonical_entry(name: str, label: str, value: object, /) -> CanonicalEntry: ...
def canonical_page(name: str, label: str, value: object, /) -> CanonicalPage: ...
def canonical_index(name: str, label: str, value: object, /) -> CanonicalIndex: ...


class TransportConformance:
    """Tests every TransportClient must pass. Subclass with a Test* name and supply fixtures."""

    def test_client_satisfies_protocol(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
        index_max_bytes: int,
        scope_priority: tuple[str, ...],
        list_page_size: int,
    ) -> None: ...  # validates all seven in the fixed order, then the protocol check

    def test_write_then_read_round_trips(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None: ...

    def test_returned_token_is_accepted(
        self, client: TransportClient, source: str, scope_map: Mapping[str, str]
    ) -> None: ...

    def test_read_absent_is_not_found(
        self, client: TransportClient, scope_map: Mapping[str, str]
    ) -> None: ...

    def test_oversize_write_is_rejected(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_file_bytes: int,
    ) -> None: ...
```

Every case begins with `name = _name(type(client))` and the fixture
checks it uses, in the fixed order client, source, scope_map,
max_file_bytes, index_max_bytes, scope_priority, list_page_size (only
the fixtures the case takes). Stateful cases then call `require_fresh`.

Helper rules:

- **Every failure message in the module except the fixture checks is
  `f"{name}: {label}: <phrase> ..."`.** Cases pass labels that name the
  path or result under check: `f"read_file({P})"`, `f"write_file({P})"`,
  `f"write result for {P}"`, `f"read result for {P}"`,
  `f"append_line({Q})"`. `require_fresh` uses `f"read_file({sentinel})"`
  / `f"write_file({sentinel})"`. The `check_*` fixture functions take no
  `label`; their messages are `f"{name}: fixture {fixture} ..."` and carry
  no path. The phrase table below shows the text after the label.
- `_fail(name, label, text) -> NoReturn`: `pytest.fail(f"{name}: {label}:
  {text}")`; every non-fixture failure goes through it.
- `check_client`: `isinstance(cast(object, client), TransportClient)` else
  fail `f"{name}: fixture client must be a TransportClient, got {type}"`.
- `check_source`: `type(source) is str and source` else fail.
- `check_scope_map`: real type `Mapping` (`issubclass(type(x),
  Mapping)`), `len >= 2`, every key and value `type(...) is str` and
  `is_valid_segment`; returns a plain `dict`.
- `check_positive_int(name, fixture, v, minimum=1)`: `type(v) is int
  and v >= minimum` (exact `int` excludes `bool`); `max_file_bytes` uses
  `minimum=MIN_FILE_BYTES`.
- `check_scope_priority`: `type(v) is tuple`, members exact `str`, valid
  segments, no duplicates.
- `sentinel_path`: `first = sorted(scope_map)[0]`; returns
  `build_path(first, scope_map[first], SENTINEL_AREA, SENTINEL_STEM)`.
- `require_fresh`: `path = sentinel_path(scope_map)`; `rl =
  f"read_file({path})"`, `wl = f"write_file({path})"`; `try: result =
  client.read_file(path)` → returned → `_fail(name, rl, "client is not
  isolated: the sentinel exists before this test wrote it")`; `except
  Exception as exc`: `expect_error(name, rl, _reraise(exc),
  NotFoundError, RECOVERABLE, path=path, reason=FILE_ABSENT)` where
  `_reraise(exc)` returns a zero-arg callable that raises `exc`; then
  `try: client.write_file(path, _SENTINEL_CONTENT, FileMetadata(
  "conformance sentinel", (), frozenset(), datetime(2000, 1, 1,
  tzinfo=UTC)), None, source=_SENTINEL_SOURCE)` / `except Exception as
  exc`: `_fail(name, wl, f"sentinel write failed: {_name(type(exc))}")`.
- `without_sentinel`: for entries, run each through `canonical_entry(
  name, label, e)` first (so a malformed path fails `bad field path`),
  then keep those with `parse_path(e.path).area != SENTINEL_AREA`; for a
  `MemoryIndex`, `canonical_index` first, then `MemoryIndex(entries=
  <filtered>, capped=tuple(c for c in index.capped if not
  c.prefix.endswith(f"/{SENTINEL_AREA}/")))` (imports `parse_path`).
- `sentinel_entry_bytes`: `prefix = build_prefix(first,
  scope_map[first], SENTINEL_AREA)`; `label = f"list_prefix({prefix})"`;
  `page = _call(name, label, lambda: client.list_prefix(prefix))`;
  `canonical_page(name, label, page)`; `len(page.entries) == 1` else fail
  `f"{name}: {label}: sentinel missing"`; return `_call(name, label,
  lambda: index_entry_bytes(page.entries[0]))`. Imports
  `index_entry_bytes` from `core` and `build_prefix` from `paths`. No
  `FileEntry` is constructed, so the token rule holds.
- `_call(name, label, fn)`: `try: return fn()` / `except Exception as
  exc: _fail(name, label, f"unexpected error: {_name(type(exc))}")`
  inside the handler. Every setup `write_file` / `read_file` in the cases
  goes through it with a label naming the call and path.
- `expect_error(name, label, call, expected, category, /, *, message,
  **payload)`: `is_taxonomy = issubclass(expected, WenchangError)`;
  `(category is None) == is_taxonomy` → `_fail(name, label, f"harness
  misuse: category must be {'given' if is_taxonomy else 'None'} for
  {_name(expected)}")`. `try: result = call()` / `except Exception as
  exc:` → `type(exc) is not expected` → `_fail(name, label, f"raised
  {_name(type(exc))}, wrong error type, expected {_name(expected)}")`;
  `is_taxonomy and exc.category is not category` → `_fail(..., f"wrong
  category: {exc.category}, expected {category}")`; `message is not
  None`: read `str(exc)` in a guard (a raise → `_fail(..., "wrong
  message: unreadable")`), `!= message` → `_fail(..., f"wrong message:
  {_short(got)}, expected {_short(message)}")`; for each `(attr, want)`:
  `got = getattr(exc, attr)` inside `try` (any `Exception` → `_fail(...,
  f"wrong payload: {attr} unreadable")`), missing → `_fail(..., f"wrong
  payload: {attr} missing")`; `type(got) is not type(want)` → `_fail(...,
  f"wrong payload: {attr} has type {_name(type(got))}, expected
  {_name(type(want))}")`; `got != want` → `_fail(..., f"wrong payload:
  {attr} is {_short(got)}, expected {_short(want)}")`; return `cast(E,
  exc)`. No exception → `_fail(name, label, f"{_name(expected)} did not
  raise; call returned {_name(type(result))}" + ("; check the
  max_file_bytes fixture" if expected is OversizeWriteError else ""))`.
- Canonical readers `canonical_*(name, label, value)`: helper
  `_exact(name, label, field, value, t)` → `_fail(name, label, f"bad
  field {field}: expected {_name(t)}, got {_name(type(value))}")` unless
  `type(value) is t`; collections checked member by member (`aliases[i]`,
  `sources member`); `last_updated`: `utcoffset() is not None` else
  `_fail(..., "bad field last_updated: naive")`; `version`: checked
  inline as `type(value.version) is str and value.version`, never passed
  to `_exact`, `_short`, or any other call (the token `ast` rule would
  flag it), else `_fail(..., "bad field version: not a non-empty str")`.
  Outer type
  wrong → `_fail(name, label, f"wrong result type: expected {T}, got
  {...}")`.
- Round-trip case: `seed = "s0" if source != "s0" else "s1"`; `expected
  = (P, content, "d", ("x", "y"), tuple(sorted({seed, source})))`; `wl =
  f"write result for {P}"`, `rl = f"read result for {P}"`; `written =
  _call(name, f"write_file({P})", ...)`, `read = _call(name,
  f"read_file({P})", ...)`; `cw = canonical_file(name, wl, written)`,
  `cr = canonical_file(name, rl, read)`; for `(label, c)` in `((wl, cw),
  (rl, cr))`: `c[4] != expected[4]` → `_fail(name, label, f"source not
  stamped: sources are {c[4]}, expected {expected[4]}")`; for `i, field`
  in fields 0–3: `c[i] != expected[i]` → `_fail(name, label, f"round trip
  changed {field}: expected {_short(expected[i])}, got {_short(c[i])}")`;
  finally `cw[5] != cr[5]` → `_fail(name, rl, f"round trip changed
  last_updated: wrote {cw[5]}, read {cr[5]}")`.
- Token case: as spec US3.3; setup calls through `_call`; the two
  accepting calls each in `try` → `_fail(name, f"write_file({P})" /
  f"append_line({Q})", f"token not accepted: raised {_name(type(exc))}")`
  (raised inside the handler so context shows).
- Token `ast` rule (a function `find_version_misuse(source: str) ->
  list[int]` in the test module, returning offending line numbers, so it
  can be self-tested): walk the tree; for `Compare` (left and
  comparators), `BinOp` (left, right), `Subscript` (value), and `Call`
  (every positional arg and every keyword value), flag any operand that
  is a `Name` or `Attribute` whose identifier ends with `version`; exempt
  a `Call` whose func is `Name("type")` or an `Attribute` whose value is
  `Name("client")`. Every case parameter for the client is named
  `client`.

### Key phrases

| Phrase | Where |
| ------ | ----- |
| `fixture client` / `fixture source` / `fixture scope_map` / `fixture max_file_bytes` / `fixture index_max_bytes` / `fixture scope_priority` / `fixture list_page_size` | fixture checks |
| `probe scope` | `probe_path` |
| `not isolated`, `sentinel write failed` | `require_fresh` |
| `sentinel missing` | `sentinel_entry_bytes` |
| `unexpected error` | `_call` (setup calls in cases) |
| `harness misuse`, `did not raise`, `wrong error type`, `wrong category`, `wrong message`, `wrong payload` | `expect_error` |
| `wrong result type`, `bad field` | canonical readers |
| `round trip`, `source not stamped` | round-trip case |
| `token not accepted` | token case |

### ARCHITECTURE.md

`testing` entry gains `TransportConformance`: the seven fixtures, the
five baseline methods, the helpers AIE-1045 reuses, the token rule (never
compared), the `last_updated` rule, deep exact-type readers, real-type
error classification, `require_fresh` and the clock contract, and the
open enforcement question. `transport` entry: "the transport conformance
suite is planned" → exists (baseline), exhaustive cases planned.

## Test layout

All files `pytestmark = pytest.mark.unit`; docstrings cite AIE-1047 and
scenario IDs.

- `tests/test_transport_conformance_reference.py` (US1.1, US3): class
  `TestInProcessClient(TransportConformance)` with the reference fixtures
  (ticking clock: a small class with a counter returning `datetime(2024,
  1, 1, tzinfo=UTC) + timedelta(microseconds=n)`).
- `tests/test_transport_conformance_self.py` (US1.2–1.4, US1.6, US2,
  US4): instantiates `TransportConformance()` and calls methods directly
  inside `pytest.raises(pytest.fail.Exception, match=phrase)` where
  `phrase` also contains the escaped probe path; a `_Forwarding` base
  wrapping a real `InProcessClient` with all seven methods forwarding,
  and one broken subclass per US4 item whose override misbehaves only
  when `path in (P, Q)` (never for the sentinel path), otherwise
  forwarding; `_SharedClient` module-level for US4.8 (two different
  cases); a `_SentinelWriteFails` client for `sentinel write failed`; a
  `_RuntimeErrorOnWrite(P)` client for `unexpected error`;
  helper-level tests for `expect_error` (US2.1–2.2), the canonical
  readers (US2.3–2.4, with hand-built `MemoryFile`s whose nested fields
  are wrong types via `object.__new__` + `object.__setattr__`, or a
  frozen-dataclass `replace`), `probe_path`, `sentinel_path`,
  `without_sentinel`, `sentinel_entry_bytes`, and `require_fresh`
  (incl. `sentinel write failed`). US4.4's client overrides both
  `write_file` and `read_file` to strip `source`. US4.8a passes bad
  fixtures to `test_client_satisfies_protocol`. Each self-test also runs
  the case against the reference client.
- `tests/test_testing_package.py` additions (US5): export and
  `Test`-prefix rule; method-name set equals the five; `ast` import scan;
  no marks; the token-rule scan (US2.6) run on the module, plus
  `find_version_misuse` self-tests on the listed violating and allowed
  snippets. Additions only.

## Project Structure

```text
specs/AIE-1047-transport-harness/        spec.md plan.md tasks.md review-spec.md review-pr.md
src/wenchang/testing/__init__.py         # export TransportConformance
src/wenchang/testing/transport_conformance.py  # new
tests/test_transport_conformance_reference.py  # new
tests/test_transport_conformance_self.py       # new
tests/test_testing_package.py            # additions only
ARCHITECTURE.md
docs/adr/0021-transport-conformance-harness.md
```

## Complexity Tracking

None.
