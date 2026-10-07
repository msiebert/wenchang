# 0025. Prompt layer: generic section text and adopter slots

Date: 2026-10-05

## Status

Accepted

## Context

The Notion spec splits the agent's guidance between tools and prompt text.
Section 1, design principle 1, says tools carry no embedded policy and
anything requiring judgment lives in prompt text layered on top. Section 8
defines that prompt layer and opens:

> The library ships instruction text, since the agent behaviors below are
> what make a set of markdown files function as memory. As much as possible
> is generic library-core text; adopter-specific pieces are pulled into
> named slots spliced into it.

Section 8.1 covers the generic text (filing and deduplication, alias
upkeep, confidence calibration, write mechanics, curated-content
correction, applying memory, forgetting, and privacy). Section 8.2 defines
the slots:

> **Scope guidance.** One text blob describing the adopter's scopes: names,
> structure, any hierarchy layered on top, and every rule that assumes a
> particular shape — which scopes are shared versus private, whether the
> agent asks permission before writing to a given scope, how contradictions
> in shared scopes are handled, and any containment rule such as a broad
> tier staying agnostic of a narrower one. Illustrative examples belong in
> this blob. Holding definitions, rules, and examples in one slot means an
> adopter whose scopes are not hierarchical writes their own version rather
> than inheriting an assumption embedded in generic text.
>
> **Seed areas.** One text blob listing starting folder names per scope,
> presented to the agent as extensible. The same listing marks which
> folders are curated `system/` areas and which are agent-writable.
>
> **Scope priority order** (configuration, not prompt text). An optional
> ranking of the adopter's scopes, used only to order the startup index
> when the byte cap is hit (Section 5). Defaults to flat.
>
> **Systems-of-record guidance.** One text blob listing what already has a
> canonical home in the adopter's product and is therefore not duplicated
> in memory. The principle is generic — reference the canonical object,
> store interpretation and corrections rather than a copy, and surface a
> discrepancy rather than diverging silently — but the list of systems is
> adopter-specific.

Section 9 gives a reference adopter
configuration (three scopes, user, project, and organization, with their
seed areas, write rules, and systems of record) and says it illustrates an
adopter rather than being part of the library. Section 10.3 says prompt
behavior is evaluated, not unit-tested.

Milestone 4 builds the prompt layer across seven issues. AIE-1055 builds
the splicing mechanism and the slots; AIE-1049 through AIE-1054 each write
the prose for one or two generic sections, in parallel, after AIE-1055
merges. The layout therefore has to let six issues land independently
without touching shared lines.

The tool layer (ADR 0022) already exists, with scope-relative tools
`(scope, area, name)` whose docstrings are the per-call descriptions the
agent sees. Scope priority already exists as
`MemoryStore(scope_priority=...)` (ADR 0020), ordering the capped startup
index.

Two decisions were taken on 2026-10-05 before the spec was written:

1. `systems_of_record` is optional (human decision).
2. Adopters cannot omit, reorder, or override generic sections
   (orchestrator default, pending human confirmation at PR review).

The orchestrator also assigned the overview section, which no milestone
issue owned, to AIE-1055.

## Decision

Add the subpackage `src/wenchang/prompts/`. No existing module changes.

1. **One Python module per section, holding `Final[str]` constants.** The
   package has `assemble.py`, `slots.py`, and one module per section:
   `overview`, `systems_of_record`, `applying_memory`, `remembering`,
   `privacy`, `filing`, `write_mechanics`, `curated_content`, and
   `forgetting`. Each issue that writes prose edits only its own module, so
   the parallel issues do not collide; pyright checks the names and ruff
   checks line length; there is no packaging change and no runtime I/O.
   This is the same pattern as the tool docstrings pinned by tests.
   - **Rejected: one `prompts.py`**, which every generic issue would edit,
     guaranteeing merge conflicts.
   - **Rejected: `.md` resources read with `importlib.resources`.** Prose
     would diff like docs, but reading it is file I/O at import or call
     time, pyright and ruff cannot see it, and a resource that is missing
     or renamed only fails at runtime.
2. **The public API is three names.** `wenchang.prompts.__all__` is
   `["SECTION_ORDER", "PromptSlots", "build_memory_prompt"]`, in the order
   ruff's RUF022 sort requires, with `build_memory_prompt(slots, /) ->
   str`. Section modules are importable (tests use them) but not exported.
   Section wording is not API: changing it needs no ADR unless the change
   departs from Section 8.1, in which case that issue adds its own ADR.
   Nothing is added to the top-level `wenchang` package.
3. **`PromptSlots(scope_guidance, seed_areas, systems_of_record=None)`, a
   frozen dataclass.** In `__post_init__`, every type check runs before any
   value check, in field order. A field whose real type
   (`issubclass(type(v), str)`) is not `str` raises `TypeError`;
   `systems_of_record` also accepts `None`. Each `str` value is normalized
   with `str.__str__` and `str.strip`, so a `str` subclass is stored as an
   exact `str`. An empty or whitespace-only value raises `ValueError`, and
   so does a value that cannot be encoded as UTF-8, chained from the
   `UnicodeEncodeError`. These are adopter-side arguments, so the errors
   are `TypeError`/`ValueError`, not `InvalidArgumentError`, as for
   `ScopePolicy`. Slot content is not policed beyond that; adopter prose
   is the adopter's. `build_memory_prompt` accepts `PromptSlots`
   subclasses and trusts their validated fields; a subclass that bypasses
   `__post_init__` validation is unsupported.
   `systems_of_record` is optional (human decision, 2026-10-05). This
   deviates from Section 8.2, which lists it beside the required blobs.
   Not every adopter has a system of record. When it is `None`, the whole
   section is omitted, principle and list together, so the agent never
   sees the principle without a list to apply it to.
4. **A fixed `SECTION_ORDER`, and generic sections the adopter cannot
   change.** The order is `("overview", "scope_guidance", "seed_areas",
   "systems_of_record", "applying_memory", "remembering", "privacy",
   "filing", "write_mechanics", "curated_content", "forgetting")`. The map
   comes before the rules: the generic text speaks of shared and private
   scopes and the `system/` area, and the slots define those terms, so the
   slots come right after the overview. The rest follows a session: apply
   memory, decide whether to write, the privacy veto (before filing and
   mechanics, so the agent does not plan a write the veto then forbids),
   where to file, which write tool to use, the curated-content exception,
   and removal.
   Adopters cannot omit, reorder, or override a generic section; only the
   three slots are theirs (orchestrator decision, 2026-10-05, pending
   human confirmation). The generic text is the library's contract, and an
   override API can be added later.
   AIE-1055 creates every section module up front, with its heading and an
   empty `BODY`, and `build_memory_prompt` omits any section whose body is
   empty or whitespace-only. Each later issue then changes one module.
   - **Rejected: each issue appends its id to `SECTION_ORDER`**, which
     puts adjacent-line conflicts in the same tuple on every merge and lets
     merge order decide prompt order. The omit-empty rule also handles the
     optional systems-of-record slot.
5. **Scope priority stays on `MemoryStore`.** Section 8.2 lists scope
   priority order among the slots but marks it "configuration, not prompt
   text", and it already exists as `MemoryStore(scope_priority=...)`, where
   it orders
   only the capped startup index and defaults to one flat tier. A
   `PromptSlots` field would be a second source of truth that could drift
   from the store's. The reference adopter order is `("user", "project",
   "organization")`. This issue adds no code for it, only documentation.
6. **Docstrings own per-call mechanics; the prompt owns judgment.** Tool
   docstrings cover argument meaning, error repair, conflicts as routine,
   the slug rule, the `.md` exclusion, the byte ceiling, and `system/`
   rejecting writes. The mechanics every tool shares (scope, area, and name
   meaning, the `.md` exclusion, the entity segment, the slug rule,
   `system/` being read-only, capped paging) are stated once, in the
   `get_memory_index` docstring; each mutating tool's docstring states its
   own conflict rule and `expected_version`, and, where it applies, the
   byte ceiling and metadata behavior (decision 11). The prompt covers what to write, where, with which
   tool, and when to ask. It refers to tools by name in tool terms
   (`scope`, `area`, `name`) and does not restate argument contracts,
   except where judgment depends on one. Known contradiction risks between
   the two, and how each is handled:
   - **Label set.** The `append_line` docstring lists all four labels,
     `[system]` included. The `remembering` section must say `[system]`
     marks curated content and the agent uses `stated`, `observed`, or
     `inferred`.
   - **Alias upkeep vs. write mechanics.** "Every write adds aliases"
     conflicts with "reserve full-file writes for new files": only
     `write_file` carries `aliases` and `description`, and it replaces
     them. The same applies to `description` drift. This gap is open
     here; a separate issue in this milestone (AIE-1151) handles it
     by adding optional `aliases` and `description` arguments to
     `append_line` and `replace_fact`; that issue's own ADR records the
     resolution. The generic prose that depends on it (AIE-1049, AIE-1051)
     is written after it lands.
   - **Dropping one fact.** Removing a line uses `replace_fact` with an
     empty `new_string`; the text must say to quote the line with its line
     break, or a blank line is left behind. The write-mechanics section
     owns this wording; the forgetting section says "drop" and defers to
     it rather than restating the call.
   - **Capped index vs. deduplication.** Deduplication reads the loaded
     index. When the target area appears under `capped`, the text allows
     one `list_prefix(scope, area)` on that area only, never a listing of
     the whole store.
   - **No paths.** The `get_memory_index` docstring shows entry paths;
     prompt text never does. It speaks only in scope, area, and name.
   The overview owns the point that a subject outgrowing its file is split
   into narrower files rather than left to bloat; later sections refer to
   it rather than restate it.
7. **Vocabulary contract.** Generic sections refer to scope shape only as
   "shared scope", "private scope", and "the `system/` area". The
   `PromptSlots` docstring and the README tell adopters that
   `scope_guidance` must say which of their scopes are shared and which
   are private. Scope-graduated guidance, such as privacy strictness,
   depends on that mapping.
8. **Unit tests pin structure and vocabulary; behavior is evaluated.**
   Following Section 10.3, unit tests cover the artifact: slot validation,
   assembly, the owned prose's load-bearing terms, and an invariant test
   parametrized over every section module discovered under the package
   (so later issues are covered without editing it). For every text it
   checks: ASCII only; lines of at most 100 columns; at most 2500
   characters; no Linear IDs in any file of the package; no memory paths,
   `.md`, braces, or "entity"; every backticked tool call names a real
   tool with real parameter names, read with `inspect.signature` at test
   time; every backticked snake_case identifier is a real tool, parameter,
   rendered key, or enum value; no reference-adopter scope names; and
   imports confined to the package. Agent behavior is evaluated, not
   unit-tested: each issue's spec lists eval scenarios as input to a later
   harness.
9. **ASCII-only prose and a per-section budget.** ASCII avoids ruff's
   confusable-character warnings on curly quotes and dashes and renders
   the same on every host. Each text is at most 2500 characters, a
   test-local constant, which keeps the whole prompt near 7k tokens.
10. **The Section 9 reference configuration is a test fixture.**
    `tests/prompts_reference_adopter.py` holds Section 9 as three slot
    blobs and the reference scope priority. Section 9 says it is not part
    of the library, so it is not in `src/`; it serves as the worked
    example for adopters.
11. **Shared tool mechanics live in `get_memory_index`; conflict handling
    stays per tool (2026-10-07, AIE-1165).** The mechanics every tool
    shares are stated once, in the `get_memory_index` docstring: what
    `scope`, `area`, and `name` mean (`name` without `.md`), that the
    entity segment is filled in, the slug rule ("Areas are lowercase ASCII
    slugs."), "The `system/` area is read-only.", and paging a `capped`
    prefix with `list_prefix(scope, area)`. Each of the four mutating tools
    keeps one self-contained version-conflict sentence ("A version conflict
    is routine: ...") and says what to pass as `expected_version`.
    `replace_fact` states its own `aliases` and `description` behavior, in
    the same words as `append_line`, with no cross-reference. `read_file`
    keeps its read-side exception that any area, `system/` included, may
    be read. Some hosts load tool schemas on demand (Claude Code loads MCP
    tool schemas through tool search), so a write tool's description can
    be shown without `get_memory_index`'s; the conflict rule is the one
    mechanic an agent needs at the moment a write fails.
    - **Rejected: the overview section as the home.** The invariant tests
      ban `.md` and "entity" in prompt text, and an adopter using
      `MemoryTools.tools()` without `build_memory_prompt` would lose the
      mechanics.
    - **Rejected: fully self-contained docstrings.** Repeating every
      shared mechanic in each docstring cuts only about 30% of their
      length, below the 40% target.
    - **Rejected: everything in `get_memory_index`, conflict rule
      included.** A host with on-demand tool loading can show a write tool
      alone, and the agent would not learn that a conflict is routine.
    Slots state only deployment facts. The reference slots and the
    `PromptSlots` docstring say so: the generic filing section presents
    seed areas as extensible, and the generic curated-content section says
    `system/` is read-only, so the seed-areas slot repeats neither, and the
    systems-of-record slot does not repeat the principle's "never copy".
    Section 8.2 asks that seed areas be "presented to the agent as
    extensible"; the assembled prompt still does that, from generic text.

AIE-1055 also writes the two pieces of prose it owns: the overview (what
memory is, call `get_memory_index()` at session start, scope/area/name
addressing, split rather than bloat) and the generic systems-of-record
principle (refer to the canonical object, store only interpretation and
corrections, surface discrepancies rather than letting the two diverge).

## Consequences

Six issues can write prose in parallel, each touching one source module
and its own test file, with no shared-line conflicts. ARCHITECTURE.md
describes the whole module now, so later prose changes need no
ARCHITECTURE edit or ADR unless they depart from Section 8.1.

Adopters get one function and one value type. Wrong types and blank slots
fail at construction, and the output is plain markdown with `##` headings
and no H1, so a host can nest it in its own system prompt. Adopters cannot
remove or replace a generic section; one who needs to must post-process
the string, or wait for an override API.

Until AIE-1049 through AIE-1054 land, the prompt on main is incomplete:
the overview, the slots, and the systems-of-record section only. The
invariant tests pass trivially over the empty bodies; each issue's own
non-empty test closes that gap.

The vocabulary contract cannot be checked: the library does not parse
adopter prose, so a `scope_guidance` that never says which scopes are
shared or private silently weakens any guidance graded by scope.

Prose can drift from tool docstrings as either changes. The tool and
parameter name checks catch renamed tools and arguments, but not changed
meaning.

With shared mechanics only in `get_memory_index` (decision 11), a host
that shows a write tool's description without it gives the agent that
tool's conflict rule and `expected_version` guidance but not the slug or
`system/` rules; the tools still enforce both and reject a violating call
with an error. An adopter whose slots restate generic rules
gets no error, only a longer prompt.

`systems_of_record` being optional deviates from Section 8.2, which
presents it as one of the blobs with no provision for its absence (decision
3). Scope priority living on `MemoryStore` rather than in `PromptSlots`
follows Section 8.2's "configuration, not prompt text"; the deviation is
only in packaging, since the slots API does not carry it (decision 5).
