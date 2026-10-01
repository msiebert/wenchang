# 0015. Path construction from scope and entity ID

Date: 2026-09-30

## Status

Accepted

## Context

AIE-1041 turns a resolved scope name and entity ID, plus an area and file
name, into a storage path following the Notion Section 3 layout
`{root}/{scope_name}/{entity_id}/{area}/{name}.md`. Until now `paths` could
only check a path (`is_valid_path`, `is_valid_prefix`, `is_valid_segment`).
Every caller that needed a path would have had to format and split
`scope/entity_id/area/name.md` by hand. The scope enforcement work (AIE-1040
`system/` read-only, AIE-1042 write restriction) also needs the area segment
of a path without re-splitting it.

The layout has a few edges that force explicit choices. `is_valid_path`
already accepts last segments such as `b.md.md`, `..md`, and `...md`, whose
stems are `"b.md"`, `"."`, and `".."`. A listing prefix has optional
trailing parts, so "omitted" needs a definition. The error type has to fit
both library-internal callers and the agent-facing path, where malformed
paths are `NotFoundError(INVALID_PATH)`.

## Decision

`wenchang.paths` gains `PathParts(scope, entity_id, area, name)`, a frozen
dataclass with no validation of its own whose `name` excludes the final
`.md`, and three pure functions: `build_path(scope, entity_id, area, name)`,
`build_prefix(scope, entity_id=None, area=None)`, and `parse_path(path)`.
`is_valid_path` and `is_valid_prefix` are unchanged.

1. **Paths are built relative to the storage root.** `{root}` in the Notion
   layout is the storage instance (ADR 0007, "The storage root is the storage
   instance"), so it never appears in a built path. This matches what
   `is_valid_path` accepts and what `core` passes to storage as a key.
2. **Always append `.md` to the name.** Approved by the human at spec review,
   2026-09-30. A name is accepted iff it is non-empty and
   `is_valid_segment(name + ".md")`, and `build_path` appends `.md` without
   inspecting the name. Rejected alternatives: rejecting names that already
   end in `.md` (since `is_valid_path` accepts `u/e/a/b.md.md`, rejecting
   `"b.md"` would break `build_path(**asdict(parse_path(p))) == p`), and
   stripping a trailing `.md` (which would map `b` and `b.md` to the same
   file).
3. **`"."` and `".."` are allowed as names.** Approved by the human at spec
   review, 2026-09-30. They produce the last segments `..md` and `...md`,
   which `is_valid_path` already accepts, so allowing them keeps both
   round-trip laws exact. They carry no traversal meaning: storage keys are
   flat strings (GCS object names, and a plain string match in the in-memory
   fake), `"."` and `".."` are already rejected as whole segments, and the
   only way to splice in extra segments is a `/` inside a segment, which
   `is_valid_segment` rejects. Rejected alternatives: rejecting them in the
   builder (breaks the parse-then-build law for existing valid paths) and
   tightening `is_valid_path` (out of scope, and would invalidate keys it
   accepts today).
4. **Construction errors are `ValueError`, not `NotFoundError(INVALID_PATH)`.**
   Approved by the human at spec review, 2026-09-30. These helpers are
   called by library code with values it controls. `build_path` raises
   `ValueError(f"invalid {arg}: {value!r}")` naming the first bad argument in
   the order `scope`, `entity_id`, `area`, `name`; `parse_path` raises
   `ValueError(f"invalid path: {path!r}")` iff `not is_valid_path(path)`.
   Agent-supplied paths keep going through `is_valid_path` in `core`. A
   caller passing agent-supplied values to a builder must validate them
   first or convert the `ValueError` into `NotFoundError(INVALID_PATH)`.
   Rejected alternative: raising `NotFoundError(INVALID_PATH)` directly,
   which would make `paths` import `errors` and treat programmer mistakes as
   agent-recoverable conditions.
5. **No identity-aware helper; `paths` stays dependency-free.** Approved by
   the human at spec review, 2026-09-30. `paths` imports nothing from
   `wenchang`. Callers write `build_path(scope, identity.entity_id(scope),
   area, name)`. Rejected alternatives: a `build_path_for(identity, scope,
   area, name)` in `paths` (couples a dependency-free module to the identity
   model for a one-expression saving) and the same helper in the scope
   module now (the scope lookup and its failure mode for an ungranted scope
   belong to the scope layer when it is designed, not to this issue).
6. **`""` is invalid in `build_prefix`; only `None` means omitted.** Approved
   by the human at spec review, 2026-09-30. A missing value must never widen
   a listing. An `area` without an `entity_id` raises `ValueError("area
   requires entity_id")`, checked before any segment validation, because the
   prefix would otherwise silently shift the area into the entity-ID
   position. Otherwise the first invalid supplied argument raises as in
   `build_path`, and every accepted result satisfies `is_valid_prefix`.
   Rejected alternative: treating `""` as omitted, which would turn
   `build_prefix("user", "")` into the scope-wide `user/`.
7. **Builders validate with the shared public `is_valid_segment`.** It
   rejects `/`, so a builder can never emit a path with the wrong segment
   count, and there is no separate local `/` check. This is the same rule
   `identity` validates scope names and entity IDs with.
8. **`parse_path` and `build_path` are exact inverses.**
   `parse_path(build_path(s, e, a, n)) == PathParts(s, e, a, n)` for every
   accepted argument set, and `build_path(**asdict(parse_path(p))) == p` for
   every `p` with `is_valid_path(p)`. `parse_path` strips only the final
   `.md`. `PathParts` field order equals `build_path`'s parameter order, so
   `astuple` works as well as `asdict`.
9. **Recorded as a new ADR** rather than an amendment to ADR 0007, since it
   is a new decision on top of 0007's relative-path layout.

## Consequences

No caller outside `paths` needs to format or split a memory path by hand.
AIE-1040 and AIE-1042 can read `parse_path(path).area` for `system/` and
write-restriction checks, and the scope layer composes `build_path` with
`Identity.entity_id`. `PathParts` guarantees nothing by itself: only a value
returned by `parse_path` is known to hold valid fields.

The name rule admits stems that look odd (`"."`, `".."`, `"b.md"`, `".md"`),
producing filenames like `...md` and `b.md.md`. That is the cost of keeping
both round-trip laws exact over everything `is_valid_path` accepts.

Because builders raise `ValueError`, any future tool-layer code that feeds
agent-supplied parts into them must pre-validate or translate the error;
forgetting to would surface a `ValueError` to the agent instead of a
recoverable `NotFoundError(INVALID_PATH)`.

Inputs are used verbatim, with no Unicode normalization or case folding.
Characters outside Unicode `Cc`, such as U+200B and U+2028, pass the segment
rule and can form lookalike paths, as they already do for `is_valid_path`.
Lone surrogates (e.g. `"\ud800"`) also pass the segment rule but cannot be
UTF-8 encoded, so a path built from one would fail later at storage. Fixing
that belongs in the shared `is_valid_segment` rule and is left as a
follow-up rather than patched in the builders.
