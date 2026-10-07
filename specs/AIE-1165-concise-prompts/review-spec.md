# Spec Review: AIE-1165 — Conciseness pass over prompt sections and tool descriptions

## What & why

The assembled memory prompt and the seven tool descriptions repeat themselves: the slug
rule, the scope/area/name explanation, and the version-conflict paragraph each appear in up
to six docstrings, and several sections restate each other or justify their own rules. This
change trims the nine section texts by 36.2%, the seven docstrings by 40.1%, and
the reference adopter slots by 28.5%, without dropping a rule, exception, or spec-quoted
phrase. Every target text is in plan.md verbatim.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | the nine section modules | read and test | bodies equal plan.md A1-A9; headings unchanged; invariants file untouched and passing; generic text >=35% shorter |
| US2 | the seven tool docstrings | read and test | equal plan.md B1-B7; shared mechanics only in `get_memory_index`; each mutating tool has its own conflict sentence; >=40% shorter |
| US3 | reference slots, `PromptSlots` docstring, README | read | slots equal C1-C3 and restate no generic rule; docstring and README say slots state only deployment facts |
| US4 | tests | count and run | no net loss of test functions per file; changed tests cite AIE-1165; `make check` green |
| US5 | ADR 0025, ARCHITECTURE.md, review-pr.md | read | decision 11 records the hybrid; entries updated; before/after table recorded |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Shared mechanics once in `get_memory_index`; one conflict sentence per mutating tool (decision 4) | All in `get_memory_index` (audit 3a); fully self-contained docstrings (option B); the overview section | Hosts with on-demand tool loading can show a write tool alone, and the conflict rule is needed exactly then; self-contained misses 40%; prompt text may not mention `.md` or "entity" |
| Keep "in a shared scope, follow the Scopes section on asking first" in curated (decision 1) | Cut it | A correction is not obviously a "new fact" to an agent reading adopter guidance |
| Cut filing's create-only negative (decision 2) | Keep it | "Before creating a file" scopes the check |
| Keep privacy's calibration phrases (decision 3) | Cut both | They set how much stricter to be |
| Keep "even if true" (decision 5) | Rely on "only if" | The spec states it; review fidelity |
| Override stated once, in privacy (decision 6) | Pointer in remembering too | One statement is enough |
| Overview floor 3 sentences (decision 7) | Keep 4-6 | The 4-6 range was a design-time guess, not a spec rule |
| Keep every §8.1 phrase earlier tests pinned ("changes the substance", "at the level recorded", "refused outright", "surrounding lines stay intact", "Match the write to the change", "mechanically impossible", "two moves", "happens to be open", "creating a duplicate", "file that is about", "ambiguous", "change one fact", "restructuring many lines", "rather than a note to self", "entire search surface", "next match more likely") | The audit's shorter paraphrases | The Linear issue keeps the exact §8.1 phrases; the generic text still lands at 36.2% |
| Amend ADR 0025 (decision 11) and add a dated note to ADR 0022 decision 8 | No ADR | ADR 0022 decision 8 makes docstrings part of the public contract, so moving shared mechanics changes it (the Linear exception applies) |
| Same-write `aliases`/`description` guidance lives in filing only | Keep the write mechanics paragraph | Removes the cross-section repeat; write mechanics keeps the tool-choice consequence (`write_file` to drop an alias or rewrite the description) |
| Headings unchanged, no merges | Shorter headings; merge curated into filing | Under 1% saving; cross-section pointers depend on headings |

## Files/modules to be touched

- `src/wenchang/prompts/{overview,systems_of_record,applying_memory,remembering,privacy,filing,write_mechanics,curated_content,forgetting}.py` (text constants only)
- `src/wenchang/prompts/slots.py` (class docstring only)
- `src/wenchang/tools.py` (seven method docstrings only)
- `tests/prompts_reference_adopter.py`, `tests/test_prompts_{overview,applying_memory,remembering,privacy,filing,write_mechanics,curated_content,forgetting,assembly,slots}.py`, `tests/test_tools_descriptions.py`
- `docs/adr/0025-prompt-layer-sections-and-slots.md`, `docs/adr/0022-*.md` (dated note), `ARCHITECTURE.md`, `README.md`

## Open questions / assumptions

- None pending. The audit's seven questions were decided by the orchestrator (spec.md
  "Decisions") and are recorded there as settled.
- Assumption: the docstring measurement uses `inspect.cleandoc`, the same method as the
  audit, so the before figure is 4489 chars.

## Risks

- Behavioral drift is not unit-testable: a trimmed sentence could change how an agent acts.
  Mitigation: the rule-disposition list in spec.md names where each cut rule still lives;
  eval scenarios are listed for the later harness.
- A host that never shows `get_memory_index`'s description loses the slug rule and `.md`
  exclusion from the write tools. Mitigation: the tools return `InvalidArgumentError` with a
  message naming the rule, and the agent is told to call `get_memory_index` first.
- The docstring cut is close to the 40% line (40.1% planned, 4 chars of margin). Any later wording change that
  adds a few characters would need to be re-measured.

## Adversarial review

Round 1 (FAIL): 1 BLOCKING, 6 SHOULD-FIX, 7 NIT. Caught: a US6 pin ("as facts arise") that
the target text did not contain; §8.1 phrases dropped inconsistently (restored: "changes the
substance", "at the level recorded", "refused outright", "surrounding lines stay intact", "two
moves", "happens to be open", "creating a duplicate"); remembering dropped the term "confidence
label"; an ungrammatical applying-memory example; filing's "If a file exists" lost "on the
subject"; a false rule-disposition claim for the overview; ADR 0022 decision 8 left stale.
NITs applied: reference scope guidance keeps "is a private scope"/"is a shared scope";
"returned content" reworded to "the content it returns"; dead test constants removed and a
brittle negative pin replaced; privacy opens "The refusals below"; the merge-assert change and
the tests-first exception are documented in the test plan.

Round 2 (FAIL): 0 BLOCKING, 1 SHOULD-FIX, 3 NIT. Caught: four pinned §8.1 phrases still
reworded ("file that is about", "ambiguous", "change one fact", "restructuring many lines"),
all restored; two stale rule-disposition lines; a double semicolon in `replace_fact`'s
docstring; tasks.md T4 not naming the ADR 0022 note. All applied.

Round 3 (PASS): no findings. The reviewer re-ran every F1-F13 pin against the target texts,
confirmed each sentence anchor matches exactly one sentence, and confirmed every section has
pins that fail on main.
