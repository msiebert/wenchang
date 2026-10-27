# 0036. No path in agent results

Date: 2026-10-26

## Status

Accepted. Supersedes [ADR 0033](0033-reply-path-check.md). Amends the render
shape in [ADR 0022](0022-tool-layer.md) decision 11.

## Context

The tools take `(scope, area, name)`, yet `render_result` and `render_error`
also returned the full memory path, `{scope}/{entity_id}/{area}/{name}.md`.
The entity ID is internal: the agent never types it and cannot act on it.
Handing it back invited agents to quote or rebuild paths in replies, often
wrongly (ADR 0033 measured 209 of 594 trials flagged). ADR 0033 answered with
a prompt sentence and a reply-path check. Both treat the leak as an agent
error when the cause is that the result exposes the path at all.

## Decision

1. **Results carry no `path`.** A file, a list entry, and an index entry
   render `scope`, `area`, and `name`, parsed from the core path, and no
   `path`. A capped index row is exactly `{scope, area, omitted}`; `prefix` is
   dropped. `next_cursor` is unchanged, and delete still renders
   `{"ok": true}`. A malformed path still renders the three as `None`.
2. **Errors carry no `path`.** `render_error` emits `scope`, `area`, and
   `name` parsed from `error.path`. A `RestrictedScopeError`'s own `scope`
   wins. An unparseable `INVALID_PATH` emits no location keys.
3. **Messages name locations, not paths.** Error message text says `scope S,
   area A, name N`, with fallbacks "the file" and "scope X".
4. **Core is unchanged.** `MemoryFile`, `FileEntry`, and `CappedPrefix` keep
   `.path` and `.prefix`, and error classes keep `.path`. Only the rendered,
   agent-facing form changes.
5. **Prompt.** The overview sentence is now "When you tell the user where
   something is stored, name its scope, area, and name."
6. **Evals.** The reply-path check is removed (`find_unmatched_reply_paths`,
   `UnmatchedReplyPath`, `PATH_ROOTS`, and the grade and report fields).
   An old `grade.json` that has `unmatched_reply_paths` still loads. The
   filing, recall, and slots scenarios now fail a reply that contains the
   entity ID (`no-entity-id`); filing and recall also use a
   `names-scope-area-name` judge item.
   `applying-no-path-unasked` also fails on volunteered scope or area wording.

## Consequences

- A host that parses the rendered `path` or a capped row's `prefix` breaks.
  In-process hosts that use the typed core results are unaffected.
- The agent cannot rebuild a path it was never shown, so the failure ADR 0033
  measured has no source. The check that policed it is no longer needed.
- Locations are conveyed as scope, area, and name. A reply can still join them
  with slashes; that is acceptable as long as no entity ID appears.

Rejected:

- **Keep `path` and rely on the prompt and check (ADR 0033).** It leaves the
  entity ID in front of the agent.
- **Add an `entity` field.** It exposes the internal ID the agent never needs.
- **Keep `path` in errors only.** The leak recurs through the repair loop, and
  a second shape costs hosts a special case.
- **Slash-joined locations in messages** (`user/preferences/editor`). They
  look like paths and invite the same rebuild.
