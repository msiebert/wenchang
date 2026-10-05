# 0024. Optional aliases and description on append_line and replace_fact

Date: 2026-10-05

## Status

Accepted

## Context

Notion Section 8.1 sets two rules for writes. Alias upkeep: every write
adds the names the subject will later be looked up by, because `description`
and `aliases` are the entire search surface (Section 4). Write mechanics: a
fact is added with `append_line` and changed with `replace_fact`; a full
`write_file` is for new files and restructuring.

Before AIE-1151 the two rules conflicted. Only `write_file` carried
`description` and `aliases`, and it replaced both. An agent that appended a
fact naming a new nickname could not record the alias without rewriting the
whole file, which costs a full rewrite and widens the conflict window for a
one-alias change.

Section 5 gives the signatures `append_line(path, line, expected_version)`
and `replace_fact(path, old_string, new_string, expected_version)`, and
requires one lock and one token per file with no metadata-only update.

The human decided on 2026-10-05 to change the API rather than rely on
prompt guidance or relax the alias-upkeep rule.

## Decision

1. **Both calls gain optional `aliases` and `description` at every layer.**
   - Core `MemoryStore`:
     `append_line(path, line, expected_version, *, source, aliases:
     Sequence[str] | None = None, description: str | None = None) ->
     MemoryFile` and `replace_fact(path, old_string, new_string,
     expected_version, *, source, aliases: Sequence[str] | None = None,
     description: str | None = None) -> MemoryFile`.
   - `TransportClient` and `InProcessClient` mirror those signatures
     exactly (the existing `inspect.signature(..., eval_str=True)` parity
     test). `InProcessClient` forwards both keywords explicitly, as the
     same objects, including `None`.
   - Tools: `append_line(scope, area, name, line, expected_version,
     aliases=None, description=None)` and `replace_fact(scope, area, name,
     old_string, new_string, expected_version, aliases=None,
     description=None)`. They are positional-or-keyword with defaults, like
     `list_prefix(scope, area=None, cursor=None)`, so a host schema derived
     from the signature marks them optional
     ([ADR 0022](0022-tool-layer.md)). The tool forwards `aliases` as an
     exact `tuple` of exact `str` and `description` as an exact `str`, or
     `None`. Both tool docstrings tell the agent that aliases are added and
     never removed, that `write_file` replaces the whole set, and that a
     one-line `description` replaces the stored one.
2. **`aliases` is a union.** The result is the stored aliases first,
   exactly as stored (never reordered or deduplicated, so a stored
   duplicate stays), followed by each given alias not already present, in
   the given order. Comparison is exact string equality with no
   normalization; duplicates within the given sequence are dropped. These
   calls never remove an alias; removing or reordering aliases is
   `write_file`'s job, which still replaces the whole set.
3. **`description` replaces when not `None`.** `None`, the default, leaves
   the field unchanged; so does `aliases=None` or an empty `aliases`
   sequence. Empty-string aliases and an empty description are accepted,
   as in `write_file`.
4. **Metadata commits with the content.** The new metadata is computed from
   the `FileMetadata` read in the attempt that commits (`append_line` has
   one attempt; `replace_fact` retries up to three times), with `source`
   unioned into `sources` and `last_updated` stamped from the clock as
   before. It goes into the same single conditional put as the content, so
   one lock and one token per file still holds and no metadata-only
   operation exists. Because the union runs on the committing attempt's
   read, a concurrent alias addition seen on a stale-token `replace_fact`
   re-apply or on a precondition-failure retry is kept.
   `append_line`'s landed-retry check compares the re-read bytes and
   metadata map against what this call tried to write, new aliases and
   description included; a mismatch is a `VersionConflictError` as before.
5. **Core validates by real type, before any storage call.** After the
   existing checks (invalid path `NotFoundError(INVALID_PATH)`, then the
   existing `ValueError`), core checks `aliases`, then `description`:
   - `aliases` whose real type is `str`, `bytes`, or `bytearray`, or is not
     a `Sequence` (`issubclass(type(x), Sequence)`, so a spoofed `__class__`
     fails): `TypeError("aliases must be a sequence of str, not <type>")`.
   - a non-`str` member: `TypeError("aliases entry must be str, got
     <type>")`. Members are normalized with `str.__str__`.
   - a non-`str` `description`: `TypeError("description must be a str, not
     <type>")`; it is normalized with `str.__str__`.
   - a `description` containing `"\n"` or `"\r"`: `ValueError("description
     must not contain a newline or carriage return")`, the text
     `FileMetadata` uses.
6. **The tools raise `InvalidArgumentError`, through shared helpers.** The
   tools validate agent-supplied values with the module-private
   `_aliases` (already used by `write_file`) and `_description` helpers,
   so the details match `write_file`'s for the same value: wrong types,
   unencodable text (chained from `UnicodeEncodeError`), any
   `str.splitlines` boundary in `description`, and `\n`/`\r` (chained from
   `FileMetadata`'s `ValueError`). The check order is the existing one
   (segment checks, grant, path build, area and name rules,
   `check_write`), then the remaining arguments in signature order: `line`
   (or `old_string` and `new_string`), `expected_version`, `aliases`,
   `description`. So a `system/` write with bad `aliases` is still
   `RestrictedScopeError`.
7. **`write_file` check precedence shifts for one combination.**
   `write_file` now calls `_description` at its existing position (after
   `content`, before `aliases`), and that helper includes the `\n`/`\r`
   check that used to run later, at `FileMetadata` construction. A
   description containing `\n` or `\r` is therefore reported before a bad
   `aliases` or `expected_version`. No other observable `write_file`
   behavior changes, and no existing test pinned that combination.
8. **Error parity: only the newline `ValueError` joins the contract.** The
   `TransportClient` docstring's well-typed error-parity list adds "a
   `description` containing a newline or carriage return" to its
   `ValueError`s. Wrongly typed `aliases` and `description` are outside
   [ADR 0019](0019-transport-client-interface.md) decision 7's well-typed
   contract; the conformance suite checks those `TypeError`s by type only,
   following [ADR 0023](0023-transport-conformance-cases.md) decision 8,
   because their text names caller-side types a remote may reject at
   serialization in its own words.
9. **Six conformance cases.** `wenchang.testing.TransportConformance` adds
   `test_append_unions_aliases`, `test_append_replaces_description`,
   `test_replace_fact_unions_aliases_and_replaces_description`,
   `test_omitted_aliases_and_description_leave_metadata_unchanged`,
   `test_replace_fact_reapply_unions_onto_current_aliases`, and
   `test_alias_and_description_argument_errors_match_core`, plus the
   message constant `MSG_DESCRIPTION_NEWLINE`, pinned to core's text by the
   drift test. Each success case checks the returned file and a read-back;
   the argument-errors case checks the unchanged state through a read-back.
   Each case has a broken-client self-test.
10. **Deviation from the Notion Section 5 signatures.** The spec lists
    `append_line` and `replace_fact` without metadata arguments. This
    extension is deliberate: it is the only way to satisfy Section 8.1's
    alias upkeep and write mechanics together without a metadata-only
    operation, which Section 5 forbids. Calls that omit the new arguments
    behave exactly as Section 5 describes.
11. **Two behaviors are orchestrator defaults, pending human confirmation.**
    - A stale-token `replace_fact` that re-applies (match still unique) with
      a `description` overwrites any description committed since the
      caller's read: last writer wins for description, as it already does
      for content outside the quoted span. Aliases are unioned, so none are
      lost. Alternative: raise `VersionConflictError` on a stale token
      whenever `description` is given. The default follows from decisions 3
      and 4 and from [ADR 0009](0009-replace-fact-semantics.md)'s re-apply
      semantics.
    - `replace_fact` with `new_string == old_string` plus `aliases` or
      `description` changes only metadata. It still goes through the
      content-write path, the same conditional put, and the same token, so
      one lock, one token holds and the API gains no separate metadata-only
      operation. Core has never rejected `old_string == new_string`.
      Alternative: reject `old_string == new_string`, a new public-API rule.

### Rejected alternatives

- **Prompt-only guidance: do a full `write_file` whenever metadata
  changes.** Contradicts Section 8.1's write mechanics, costs a full
  rewrite, and widens the conflict window for a one-alias change.
- **Relax alias upkeep to file creation and full writes.** Weakens the
  search surface that Section 4 makes load-bearing.
- **Replace aliases, as `write_file` does.** A fact write would have to
  resend every existing alias, and one that forgot would silently drop
  them.
- **Normalized comparison (case folding, trimming) in the union.**
  `write_file` does no normalization, so these calls match it; any
  normalization belongs to prompt guidance, not tool code.
- **Validate only in the tool layer.** Core's arguments are
  library-controlled values and follow the repo convention of `TypeError`
  / `ValueError` there, with `InvalidArgumentError` reserved for
  agent-supplied values at the tools.

## Consequences

An agent can record a new alias or refresh the description in the same
call that adds or changes a fact, at no extra round trip and with the same
conflict window as the fact write alone. Alias upkeep and write mechanics
in Section 8.1 no longer pull against each other, and prompt text
(AIE-1049, AIE-1051) can require both.

Aliases only grow through these calls; trimming a stale or wrong alias
still needs a full `write_file`. Concurrent alias additions survive
`replace_fact`'s re-apply, but a concurrent description change does not
(decision 11, pending human).

Every `TransportClient` implementation, including adopters' remote clients
and test doubles, must accept the two new keyword parameters, and a remote
client passes the six new conformance cases only if it unions and replaces
exactly as core does. Calls that omit the new arguments are unchanged, so
existing callers keep working.

`write_file` reports a newline in `description` earlier than before when
the same call also has a bad `aliases` or `expected_version` (decision 7).
