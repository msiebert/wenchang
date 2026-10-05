# Feature Specification: Optional aliases and description on append_line and replace_fact

**Linear issue**: AIE-1151 — append_line and replace_fact: optional aliases and description arguments

**Feature Branch**: `AIE-1151-append-replace-aliases`

**Created**: 2026-10-05

**Status**: Draft — human decision recorded 2026-10-05 (API change over
prompt-only guidance or relaxing the alias-upkeep rule).

**Input**: Notion §8.1 says every write adds the names the subject will later
be looked up by (alias upkeep), and that a fact is added with `append_line`
and changed with `replace_fact`, with full-file `write_file` reserved for new
files or restructuring. Today only `write_file` carries `aliases` and
`description`, and it replaces them. An agent that appends a fact naming a
new nickname cannot record the alias without a full rewrite.

## Summary

`append_line` and `replace_fact` gain two optional keyword arguments,
`aliases` and `description`, at every layer: core `MemoryStore`, the
`TransportClient` protocol and `InProcessClient`, and the tools.

- `aliases` is **unioned** into the stored alias tuple: the existing aliases
  first, exactly as stored, then each given alias not already present, in the
  given order. Exact string equality; no normalization; duplicates within the
  given sequence are dropped. Aliases are never removed by these calls.
- `description`, when not `None`, replaces the stored description.
- `None` (the default) leaves that field unchanged.
- The metadata change commits on the same conditional put as the content
  change, so one lock and one token per file (§5) still holds and no
  metadata-only operation exists. `sources` gains `source` and
  `last_updated` is stamped exactly as today.
- Removing an alias stays a `write_file` job.

This extends the Notion §5 signatures
`append_line(path, line, expected_version)` and
`replace_fact(path, old_string, new_string, expected_version)`; ADR 0024
records it as a deliberate spec deviation.

## Human decision (2026-10-05)

| Alternative | Why rejected |
| ----------- | ------------ |
| Prompt-only guidance: do a full `write_file` whenever metadata changes | Contradicts §8.1 write mechanics; costs a full rewrite and widens the conflict window for a one-alias change |
| Relax alias upkeep to file creation and full writes only | Weakens the load-bearing search surface (§4: metadata is the entire search surface) |

## User stories and acceptance criteria

Fixture notation: a file `F` exists with content `- [stated] a\n`,
description `"d"`, aliases `("x", "y")`, and some sources. `S` is the
call's `source`. `S1` is a `str` subclass whose `__eq__`, `__hash__`, and
`__str__` lie.

### US1 — Core `MemoryStore.append_line`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1.1 | `F` | `append_line(p, "- [stated] b", v, source=S, aliases=["y", "z", "w", "z"])` | stored and returned aliases are exactly `("x", "y", "z", "w")` (exact `tuple` of exact `str`); content appended as today; description unchanged |
| 1.2 | `F` | `append_line(..., description="d2")` | stored and returned description is `"d2"`; aliases unchanged `("x", "y")` |
| 1.3 | `F` | `append_line(..., aliases=["z"], description="d2")` | both applied; `sources` is old sources plus `S`; `last_updated` is the clock value; exactly one `put_if_version` call carries content and metadata together |
| 1.4 | `F` | neither argument; or `aliases=None, description=None`; or `aliases=[]` | description and aliases equal the stored ones exactly; behavior identical to today |
| 1.5 | `F` | `aliases=["x", "y"]` (all present) | aliases unchanged `("x", "y")` |
| 1.6 | `F` | `aliases=[S1("q")]` | stored alias is exact `str` `"q"` (normalized with `str.__str__`); dedup compares exact strings |
| 1.7 | `F` | `aliases` is a `str`, `bytes`, `bytearray`, a non-`Sequence` (`5`, a `set`, an iterator), or an object whose `__class__` claims `list` but whose real type is not a `Sequence` | `TypeError("aliases must be a sequence of str, not <type name>")`; storage never called |
| 1.8 | `F` | `aliases=["a", 5]` | `TypeError("aliases entry must be str, got int")`; storage never called |
| 1.9 | `F` | `description=5` | `TypeError("description must be a str, not int")`; storage never called |
| 1.10 | `F` | `description="a\nb"` or `"a\rb"` | `ValueError("description must not contain a newline or carriage return")`; storage never called |
| 1.11 | `F` | `description=S1("d2")` | stored description is exact `str` `"d2"` |
| 1.12 | invalid path, or empty `source`, or non-fact `line`, together with bad `aliases` | call | the existing error wins (`NotFoundError(INVALID_PATH)` first, then the existing `ValueError`); then aliases `TypeError`, then description `TypeError`, then description `ValueError` |
| 1.13 | the conditional put fails its precondition and the re-read finds exactly the bytes and metadata map this call tried to write (a landed backend retry), with new aliases and description | call | success, returning the new metadata and the re-read version |
| 1.14 | precondition fails and the re-read shows the same bytes but a different metadata map (e.g. aliases differ) | call | `VersionConflictError` as today |
| 1.15 | `F` but stored aliases `("x", "x")` (a pre-existing duplicate) | `aliases=["z"]` | `("x", "x", "z")`: stored aliases are kept as stored, never deduplicated or reordered |

### US2 — Core `MemoryStore.replace_fact`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.1 | `F` with content `- [stated] beta\n` | `replace_fact(p, "beta", "gamma", v, source=S, aliases=["y", "z", "z"], description="d2")` | content replaced; aliases `("x", "y", "z")`; description `"d2"`; `sources` gains `S`; one put |
| 2.2 | as 2.1 | neither argument, or both `None` | metadata other than sources/last_updated unchanged |
| 2.3 | stale `expected_version`; since the caller's read another writer appended a line with `aliases=["w"]` (stored now `("x", "y", "w")`), and the match is still unique | `replace_fact(..., aliases=["z"])` | re-applied against the current object: aliases `("x", "y", "w", "z")` |
| 2.4 | the first put fails its precondition because a concurrent write changed aliases to `("x", "y", "q")`; the second attempt commits | `aliases=["z"]` | `("x", "y", "q", "z")`: the union is computed on the object read in the committing attempt |
| 2.5 | bad `aliases` / `description` as in 1.7–1.11 | call | same errors and messages as US1; no storage call |
| 2.6 | invalid path, or empty `old_string`/`source`, together with bad `aliases` | call | existing error wins; same order as 1.12 |
| 2.7 | a `ReplaceFactMatchError` or `VersionConflictError` outcome | call with `aliases`/`description` | the file is unchanged, content and metadata |

### US2b — Accepted consequences (orchestrator default, pending human)

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 2.8 | stale token; another writer set description `"q"` since the caller's read; match still unique | `replace_fact(..., description="d2")` | re-applies; description `"d2"` (last writer wins), no conflict |
| 2.9 | `F` with `beta` | `replace_fact(p, "beta", "beta", v, source=S, aliases=["z"])` | content unchanged, aliases `("x", "y", "z")`, new version; one conditional put |

### US3 — Transport protocol and `InProcessClient`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 3.1 | — | `inspect.signature(..., eval_str=True)` of `TransportClient.append_line` / `.replace_fact` | equals `MemoryStore`'s (the existing parity test passes unchanged) |
| 3.2 | `InProcessClient` over a recording store | `append_line(p, l, v, source=S, aliases=A, description=D)` | the store receives `(p, l, v)` positionally and `source=S, aliases=A, description=D` as keywords, the same objects (`is`); returns the store's object |
| 3.3 | as 3.2 | the new arguments omitted | the store receives `aliases=None, description=None` |
| 3.4 | as 3.2, 3.3 | `replace_fact` | same |
| 3.5 | the store raises | call with the new arguments | the exception propagates as raised |
| 3.6 | — | `TransportClient` class docstring | its well-typed error-parity `ValueError` list adds a `description` containing a newline or carriage return; wrongly typed `aliases`/`description` stay outside the contract (ADR 0019 decision 7) |

The existing forwarding table in `tests/test_transport_inprocess.py` passes the new keywords explicitly so its exact-equality assertion holds; keyword identity (3.2) is a separate new test.

### US4 — Tools `append_line` and `replace_fact`

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 4.1 | valid call | `append_line(scope, area, name, line, v, aliases=["x"], description="d")` | client called once: `(path, line, v)` positional, `source=<surface>, aliases=("x",), description="d"`; `aliases` forwarded as an exact `tuple` of exact `str` |
| 4.2 | valid call | new arguments omitted | client receives `aliases=None, description=None` |
| 4.3 | as 4.1, 4.2 | `replace_fact` | same |
| 4.4 | `aliases` is `"ab"`, `b"ab"`, `bytearray(b"ab")`, `5`, an iterator, a `frozenset`, `["a", 5]`, `("a", None)`, a `__class__` spoof | either tool | `InvalidArgumentError(argument="aliases")` with exactly the detail and `__cause__` `write_file` gives for the same value; no client call |
| 4.5 | alias member with a lone surrogate | either tool | `InvalidArgumentError("aliases")` chained from `UnicodeEncodeError` |
| 4.6 | `description=5` | either tool | `InvalidArgumentError("description")`, detail `Argument description is invalid: description must be a string, not int`, `__cause__ is None` |
| 4.7 | `description` with `\n` or `\r` | either tool | `InvalidArgumentError("description")` chained from `ValueError`, same detail as `write_file` |
| 4.8 | `description` containing any of U+000B, U+000C, U+001C, U+001D, U+001E, U+0085, U+2028, U+2029 | either tool | `InvalidArgumentError("description")`, same detail as `write_file` (`... description must be a single line`) |
| 4.9 | `description` with a lone surrogate | either tool | `InvalidArgumentError("description")` chained from `UnicodeEncodeError` |
| 4.10 | `str`-subclass `description` / alias members | either tool | forwarded as exact `str` |
| 4.11 | `area="system"` plus bad `aliases` or `description` | either tool | `RestrictedScopeError`; `check_write` precedes the new checks; no client call |
| 4.12 | bad `line` / `old_string` / `new_string` / `expected_version` together with bad `aliases` | either tool | the earlier argument's error wins; remaining arguments are validated in signature order |
| 4.13 | `write_file` | every existing test | passes unchanged; `write_file` shares the `_description` helper |
| 4.14 | — | `inspect.signature` of the tools | `append_line(self, scope, area, name, line, expected_version, aliases=None, description=None)`; `replace_fact(self, scope, area, name, old_string, new_string, expected_version, aliases=None, description=None)` |
| 4.15 | `InProcessClient` over a real `MemoryStore` | tool `append_line(..., aliases=["z"], description="d2")` on a file with aliases `("x",)`, then `read_file` | read-back aliases `("x", "z")`, description `"d2"` (`tests/test_tools_end_to_end.py`) |

### US5 — Tool descriptions

| # | Then |
| - | ---- |
| 5.1 | the `append_line` and `replace_fact` docstrings each contain the paragraph in plan.md; `tests/test_tools_descriptions.py` pins, against the whitespace-normalized docstring (`" ".join(doc.split())`), `added to the file's existing aliases`, `never removed`, `write_file`, `replaces the whole set`, and ``one-line `description` replaces the stored one`` for both |
| 5.2 | no `AIE-\d+` in `src/` (existing tests) |

### US6 — Transport conformance suite

New public cases on `wenchang.testing.TransportConformance` (exact names in
plan.md). Each passes for `InProcessClient`; each has at least one broken
client in `tests/test_transport_conformance_cases_self.py` that makes it
fail with the case's key phrase.

| # | Case covers |
| - | ----------- |
| 6.1 | append unions aliases (existing first, given order, duplicates dropped) in both the returned file and a read-back |
| 6.2 | append replaces the description and leaves aliases unchanged |
| 6.3 | `replace_fact` with both arguments: union and replace, returned and read back |
| 6.4 | omitted and explicit-`None` arguments leave description and aliases unchanged, for both methods |
| 6.5 | a stale-token `replace_fact` re-apply unions onto the current aliases |
| 6.6 | argument errors for both methods: a `str` passed as `aliases`, a non-`str` alias member, and a non-`str` `description` raise `TypeError`; a description with `"\n"` raises `ValueError` with core's exact message; content and metadata unchanged |
| 6.7 | the suite's method-name pin (`test_suite_public_methods_are_exactly_the_listed_cases`) includes the new group |
| 6.8 | `MSG_DESCRIPTION_NEWLINE` equals core's message (pinned in `tests/test_transport_conformance_messages.py`) |

### US7 — Docs

| # | Then |
| - | ---- |
| 7.1 | ADR 0024 "Optional aliases and description on append_line and replace_fact" records the decision, union semantics, the deviation from the Notion §5 signatures with rationale, rejected alternatives, the `write_file` check-precedence note, the US2.8 and US2.9 behaviors as orchestrator defaults pending human, and the type-only `TypeError` conformance checks (ADR 0023 decision 8; outside ADR 0019's well-typed parity contract) |
| 7.2 | ARCHITECTURE.md entries for `core`, `transport`, `tools`, `testing`, and the key invariant "One lock, one token per file" describe the new arguments |
| 7.3 | the glossary "Aliases" entry (`docs/product/glossary.md`) says `append_line`/`replace_fact` add aliases and only `write_file` removes them |

## Out of scope

- A metadata-only update operation (§5 forbids it).
- Removing aliases through `append_line` / `replace_fact`.
- Alias normalization (case folding, trimming) or rejecting empty aliases;
  `write_file` does neither and these calls match it.
- Changing `write_file` semantics (it still replaces description and aliases).
- Prompt text (AIE-1049, AIE-1051 build on this).
- `delete_file`, `read_file`, `list_prefix`, `get_memory_index`.
