# Implementation Plan: Optional aliases and description on append_line and replace_fact

**Linear issue**: AIE-1151 | **Branch**: `AIE-1151-append-replace-aliases` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

## Summary

Add keyword-only `aliases` and `description` to `append_line` and
`replace_fact` in `wenchang.core.MemoryStore`, `wenchang.transport`
(`TransportClient`, `InProcessClient`), and `wenchang.tools.MemoryTools`;
add conformance cases to `wenchang.testing.transport_conformance`. ADR 0024.

## Technical Context

Python >= 3.12; pyright strict; ruff 100 columns. No new dependencies; no
import-graph change. Storage format unchanged (aliases are still a JSON array
under the `aliases` key).

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests first | T1–T3 each test-writer then implementer |
| II. Tests not negotiable | No test deleted, skipped, or weakened. Test doubles implementing `TransportClient` gain the new parameters (required by the protocol change). The `InProcessClient` forwarding table passes the new keywords explicitly so its exact-equality assertion is kept |
| Storage via interface only | Unchanged; still one `put_if_version` per committing attempt |
| Architecture changes documented | ADR 0024; ARCHITECTURE.md `core`, `transport`, `tools`, `testing`, key invariant |

## Public interface

### `wenchang.core.MemoryStore`

```python
def append_line(
    self,
    path: str,
    line: str,
    expected_version: VersionToken,
    *,
    source: str,
    aliases: Sequence[str] | None = None,
    description: str | None = None,
) -> MemoryFile: ...


def replace_fact(
    self,
    path: str,
    old_string: str,
    new_string: str,
    expected_version: VersionToken,
    *,
    source: str,
    aliases: Sequence[str] | None = None,
    description: str | None = None,
) -> MemoryFile: ...
```

`Sequence` is `collections.abc.Sequence` (already imported in core).

**Validation** (before any storage call, after the existing checks):

1. `NotFoundError(path, INVALID_PATH)` if `path` is invalid (existing).
2. The existing `ValueError` (`"line must be a single fact line and source
   must be non-empty"` / `"old_string and source must be non-empty"`).
3. `aliases` (when not `None`): real-type check with `type()`, never
   `isinstance`. If `issubclass(type(aliases), (str, bytes, bytearray))` or
   not `issubclass(type(aliases), Sequence)`:
   `TypeError(f"aliases must be a sequence of str, not {_type_name(type(aliases))}")`.
   Each member, in order: if not `issubclass(type(m), str)`:
   `TypeError(f"aliases entry must be str, got {_type_name(type(m))}")`.
   Members are normalized with `str.__str__`. (Style matches
   `scope_priority` in `MemoryStore.__init__`.)
4. `description` (when not `None`): if not `issubclass(type(d), str)`:
   `TypeError(f"description must be a str, not {_type_name(type(d))}")`;
   normalize with `str.__str__`; if it contains `"\n"` or `"\r"`:
   `ValueError("description must not contain a newline or carriage return")`
   (the same text `FileMetadata.__post_init__` uses).

Empty-string aliases and an empty description are accepted, as with
`write_file`.

**Metadata on commit**, computed from the `FileMetadata` read in the
attempt that commits (`append_line` has one attempt; `replace_fact` up to
`_MAX_REPLACE_ATTEMPTS`):

- `aliases`: `stored.aliases` followed by each normalized given alias that is
  neither in `stored.aliases` nor already added, in given order. Exact `str`
  equality. Stored aliases are never reordered or deduplicated. `None` or an
  empty sequence leaves the tuple unchanged. Result is an exact `tuple`.
- `description`: the normalized given value if not `None`, else
  `stored.description`.
- `sources`: `stored.sources | {source}`; `last_updated`: `self._clock()`
  (unchanged).

`dataclasses.replace(stored, aliases=..., description=..., sources=...,
last_updated=...)` builds it; the result goes through the same single
`put_if_version` as the content. The returned `MemoryFile.metadata` is that
object. `append_line`'s precondition-failure path compares `cur.data == data
and cur.metadata == meta_map` where `meta_map = metadata_to_map(stamped)`
now includes the new aliases and description; nothing else changes there.

Two consequences, accepted and recorded in ADR 0024 (orchestrator default,
pending human):

- A stale-token `replace_fact` that re-applies (match still unique) with a
  `description` overwrites any description committed since the caller's
  read: last writer wins for description, as it does for content outside the
  quoted span. Aliases are unioned, so none are lost.
- `replace_fact(p, s, s, v, aliases=...)` (`new_string == old_string`)
  changes only metadata. It still goes through the same content-write path,
  the same conditional put, and the same token, so §5's one lock, one token
  holds; no separate metadata-only operation exists in the API. Core does
  not reject `old_string == new_string` (it never has).

Docstrings of both methods gain: "`aliases`, if given, are added to the
stored aliases in order, skipping any already present; stored aliases are
never removed or reordered. `description`, if given, replaces the stored
description. Both commit in the same write as the content. Raises TypeError
for a wrongly typed `aliases`, alias, or `description`, and ValueError for a
`description` containing a newline or carriage return, all without calling
storage."

Private helpers (names are implementer's choice; tests must not import
them): one to validate/normalize aliases, one for description, one for the
union.

### `wenchang.transport`

`TransportClient.append_line` / `.replace_fact` and `InProcessClient`
methods have exactly the core signatures above (`inspect.signature(...,
eval_str=True)` equality). `InProcessClient` forwards every argument
unchanged, always passing the keywords explicitly:

```python
return self._store.append_line(
    path, line, expected_version, source=source, aliases=aliases, description=description
)
return self._store.replace_fact(
    path,
    old_string,
    new_string,
    expected_version,
    source=source,
    aliases=aliases,
    description=description,
)
```

The `TransportClient` class docstring's error-parity list (which covers
well-typed arguments only, ADR 0019 decision 7) adds only "a `description`
containing a newline or carriage return" to its `ValueError` list. Wrongly
typed `aliases` / `description` stay outside the parity contract; the
conformance suite checks them by exception type only, following ADR 0023
decision 8 (the `get_memory_index` precedent).

### `wenchang.tools.MemoryTools`

```python
def append_line(
    self,
    scope: str,
    area: str,
    name: str,
    line: str,
    expected_version: VersionToken,
    aliases: Sequence[str] | None = None,
    description: str | None = None,
) -> MemoryFile: ...


def replace_fact(
    self,
    scope: str,
    area: str,
    name: str,
    old_string: str,
    new_string: str,
    expected_version: VersionToken,
    aliases: Sequence[str] | None = None,
    description: str | None = None,
) -> MemoryFile: ...
```

Positional-or-keyword with defaults, like `list_prefix(scope, area=None,
cursor=None)`, so a host schema derived from the signature marks them
optional (ADR 0022).

**Check order**: type/UTF-8 checks of segments, grant, path build,
area/name rules, `check_write` (all existing, in `_path` and the method),
then the remaining arguments in signature order:

- `append_line`: `line` (existing exact, encodable, `parse_fact`),
  `expected_version` (existing), then `aliases` if not `None` via the
  existing `_aliases(...)` helper, then `description` if not `None` via a new
  `_description(...)` helper.
- `replace_fact`: `old_string`/`new_string` (existing, unchanged order),
  `expected_version`, then `aliases`, then `description`, as above.

Then one client call:

```python
self._client.append_line(
    path,
    line,
    expected_version,
    source=self._source,
    aliases=alias_tuple,
    description=description,
)
```

where `alias_tuple` is `None` or the exact tuple from `_aliases`, and
`description` is `None` or the exact str from `_description`. Same for
`replace_fact`.

**`_description(value: object) -> str`** (module-private, shared with
`write_file`):

```python
description = _exact("description", value)
_encodable("description", description)
if any(boundary in description for boundary in _LINE_BOUNDARIES):
    raise InvalidArgumentError("description", "description must be a single line")
try:
    FileMetadata(description, (), frozenset(), _UNSET_TIMESTAMP)
except ValueError as exc:
    raise InvalidArgumentError("description", str(exc)) from exc
return description
```

`write_file` replaces its inline description checks with
`description = _description(description)` at the same position (after
`content`, before `aliases`). Its later `FileMetadata(...)` construction no
longer needs a `try`. Observable `write_file` behavior is unchanged except
precedence: a description containing `\n`/`\r` is now reported before a bad
`aliases` or `expected_version` (previously after). No existing test pins that
combination; ADR 0024 records it.

Resulting errors (agent-facing; details are the `InvalidArgumentError`
rendering `Argument <arg> is invalid: <detail>`):

| Input | Error |
| ----- | ----- |
| `aliases` str/bytes/bytearray/non-Sequence/`__class__` spoof | `InvalidArgumentError("aliases", f"aliases must be a list of strings, not {type}")`, no cause |
| non-str alias member | `InvalidArgumentError("aliases", f"aliases must be a string, not {type}")`, no cause |
| unencodable alias member | `InvalidArgumentError("aliases", "aliases is not valid UTF-8 text")` from `UnicodeEncodeError` |
| non-str `description` | `InvalidArgumentError("description", f"description must be a string, not {type}")`, no cause |
| unencodable `description` | `InvalidArgumentError("description", "description is not valid UTF-8 text")` from `UnicodeEncodeError` |
| `description` with a `_LINE_BOUNDARIES` char | `InvalidArgumentError("description", "description must be a single line")`, no cause |
| `description` with `\n`/`\r` | `InvalidArgumentError("description", "description must not contain a newline or carriage return")` from `ValueError` |

**Docstrings.** Both tools insert this paragraph after the paragraph
ending "Areas are lowercase ASCII slugs." and before the version-conflict
paragraph, as these exact lines at the method docstring's 8-space indent:

```
        Optional `aliases` are added to the file's existing aliases and
        never removed; to drop an alias, use `write_file`, which replaces
        the whole set. An optional one-line `description` replaces the
        stored one.
```

The new phrase-pin tests compare against the whitespace-normalized
docstring, `" ".join(doc.split())`, so wrapping never matters. Pinned
phrases (both tools): `added to the file's existing aliases`,
`never removed`, `write_file`, `replaces the whole set`,
``one-line `description` replaces the stored one``.

### `wenchang.testing.transport_conformance`

New module constant:

```python
MSG_DESCRIPTION_NEWLINE: Final = "description must not contain a newline or carriage return"
```

New public cases on `TransportConformance` (group "aliases and
description"); each takes the fixtures `client`, `source`, `scope_map`
only, starts with `check_client`, `check_source`, `check_scope_map`,
`require_fresh`, and uses the probe path like existing cases.

Fixture for every case: create the probe file with content
`"- [stated] alpha\n- [stated] beta\n"` (33 bytes) and metadata
`_meta("d", ("x", "y"), sources=frozenset({_seed(src)}))`, then read it.
Appends use `"- [stated] c"`; the first replace is `beta` -> `zeta`, a second
replace in the same case is `zeta` -> `beta` (same length). Every case's
content stays under `MIN_FILE_BYTES` (64).

| Case | Behavior | Key failure phrase(s) |
| ---- | -------- | --------------------- |
| `test_append_unions_aliases` | create with aliases `("x", "y")`, append with `aliases=["y", "z", "w", "z"]`; returned and read-back aliases are `("x", "y", "z", "w")`; description unchanged | `aliases not unioned` |
| `test_append_replaces_description` | append with `description="d2"`; returned and read-back description `"d2"`; aliases unchanged | `description not replaced`, `aliases changed` |
| `test_replace_fact_unions_aliases_and_replaces_description` | `replace_fact` with `aliases=["y", "z", "z"]`, `description="d2"`; content replaced; aliases `("x", "y", "z")`; description `"d2"`, returned and read back | `aliases not unioned`, `description not replaced` |
| `test_omitted_aliases_and_description_leave_metadata_unchanged` | append and replace_fact once omitting the arguments and once with explicit `None`; description and aliases unchanged after each | `metadata changed` |
| `test_replace_fact_reapply_unions_onto_current_aliases` | read r1; append with `aliases=["w"]`; `replace_fact` at the stale `r1.version` with `aliases=["z"]` and a still-unique match; aliases `("x", "y", "w", "z")` | `aliases not unioned` |
| `test_alias_and_description_argument_errors_match_core` | for each of `append_line` and `replace_fact`: `aliases="ab"` -> `TypeError`; `aliases=["a", 5]` -> `TypeError`; `description=5` -> `TypeError`; `description="a\nb"` -> `ValueError` with `MSG_DESCRIPTION_NEWLINE`; afterwards content, description, and aliases unchanged | via `expect_error`; `content changed` / `metadata changed` |

Failure messages follow the suite's `"{name}: {label}: {phrase}: ..."`
convention via `_fail` / `expect_error`. File sizes stay within
`MIN_FILE_BYTES`.

## Files

- `src/wenchang/core.py`, `src/wenchang/transport.py`, `src/wenchang/tools.py`,
  `src/wenchang/testing/transport_conformance.py`
- `tests/test_core_append_line.py`, `tests/test_core_replace_fact.py`,
  `tests/test_transport_protocol.py`, `tests/test_transport_inprocess.py`,
  `tests/test_tools.py`, `tests/test_tools_descriptions.py`,
  `tests/test_tools_end_to_end.py`, `tests/test_transport_conformance_reference.py`,
  `tests/test_transport_conformance_cases_self.py`,
  `tests/test_transport_conformance_self.py`,
  `tests/test_transport_conformance_messages.py` (doubles' signatures + new tests)
- `docs/adr/0024-append-replace-aliases-description.md`, `ARCHITECTURE.md`,
  `docs/product/glossary.md`
