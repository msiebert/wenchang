# PR Review: AIE-1165 — Conciseness pass over prompt sections and tool descriptions

## What changed & why

The nine generic prompt section bodies, the seven tool docstrings, the three reference adopter slot blobs, and the `PromptSlots` docstring are rewritten for length, with no rule, exception, or spec-quoted phrase lost and no change to headings, signatures, types, errors, or behavior. Mechanics every tool shares (scope/area/name meaning, `.md` exclusion, entity segment, slug rule, `system/` read-only, capped paging) are now stated once, in `get_memory_index`; each mutating tool keeps one self-contained version-conflict sentence because a host that loads tool schemas on demand can show a write tool alone. The reference slots and the `PromptSlots` docstring now state only deployment facts, leaving generic rules to the generic sections. Phrase-pin tests were repointed to the new text; `tests/test_prompts_invariants.py` is unchanged.

## Before / after

Chars of the stripped `BODY`/`PRINCIPLE`, the stripped reference blob, or `inspect.cleandoc(__doc__)`, from `git show main:` vs the branch source; tokens = chars/4.

| Kind | Piece | Before chars | ~tok | After chars | ~tok | Cut |
|---|---|---:|---:|---:|---:|---:|
| section | `overview.BODY` | 688 | 172 | 322 | 80 | 53.2% |
| section | `systems_of_record.PRINCIPLE` | 522 | 130 | 400 | 100 | 23.4% |
| section | `applying_memory.BODY` | 627 | 157 | 423 | 106 | 32.5% |
| section | `remembering.BODY` | 1901 | 475 | 1292 | 323 | 32.0% |
| section | `privacy.BODY` | 1120 | 280 | 792 | 198 | 29.3% |
| section | `filing.BODY` | 1261 | 315 | 945 | 236 | 25.1% |
| section | `write_mechanics.BODY` | 1197 | 299 | 679 | 170 | 43.3% |
| section | `curated_content.BODY` | 1042 | 260 | 611 | 153 | 41.4% |
| section | `forgetting.BODY` | 1440 | 360 | 854 | 214 | 40.7% |
| slot | `REFERENCE_SCOPE_GUIDANCE` | 1458 | 364 | 1248 | 312 | 14.4% |
| slot | `REFERENCE_SEED_AREAS` | 504 | 126 | 195 | 49 | 61.3% |
| slot | `REFERENCE_SYSTEMS_OF_RECORD` | 391 | 98 | 239 | 60 | 38.9% |
| doc | `get_memory_index` | 599 | 150 | 553 | 138 | 7.7% |
| doc | `read_file` | 348 | 87 | 101 | 25 | 71.0% |
| doc | `list_prefix` | 400 | 100 | 241 | 60 | 39.8% |
| doc | `write_file` | 781 | 195 | 432 | 108 | 44.7% |
| doc | `append_line` | 911 | 228 | 586 | 146 | 35.7% |
| doc | `replace_fact` | 963 | 241 | 606 | 152 | 37.1% |
| doc | `delete_file` | 487 | 122 | 170 | 42 | 65.1% |
| **total** | Generic prompt text (9 bodies) | 9798 | 2450 | 6318 | 1580 | **35.5%** (target 35%) |
| **total** | Reference slots (3 blobs) | 2353 | 588 | 1682 | 420 | **28.5%** |
| **total** | Tool docstrings (7) | 4489 | 1122 | 2689 | 672 | **40.1%** (target 40%) |

Assembled reference prompt (headings included): before 12379 chars (~3095 tok), after 8228 chars (~2057 tok), a 33.5% cut.

The generic cut has 51 characters of headroom (6318 vs a 35% ceiling of 6369); the docstring cut has 4 (2689 vs 2693).

## Acceptance criteria → tests

Paths are under `tests/`; line numbers are the `def` line.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 each body equals plan.md A1-A9 | No exact-text test; covered by the phrase pins in US1.4 and the plan diff |
| US1.2 headings unchanged | `test_prompts_assembly.py:140` `test_headings_distinct_and_owned_values_pinned`; per-section heading tests: `test_prompts_applying_memory.py:21`, `test_prompts_remembering.py:37`, `test_prompts_privacy.py:25`, `test_prompts_filing.py:19`, `test_prompts_write_mechanics.py:36`, `test_prompts_curated_content.py:44`, `test_prompts_forgetting.py:24` |
| US1.3 invariant tests pass, file unchanged | `test_prompts_invariants.py:229`, `:245`, `:251`, `:258`, `:274`, `:280` (and the rest of the file); `git diff main` on it is empty |
| US1.4 every pin in plan.md F1-F9 passes | `test_prompts_overview.py:38`, `:44`; `test_prompts_systems_of_record.py:21`; `test_prompts_applying_memory.py:46`, `:51`; `test_prompts_remembering.py:54`, `:71`, `:77`, `:85`, `:98`, `:119`, `:139`, `:145`, `:172`, `:192`; `test_prompts_privacy.py:69`, `:74`; `test_prompts_filing.py:88`, `:104`; `test_prompts_write_mechanics.py:48`-`:206`; `test_prompts_curated_content.py:80`, `:85`, `:97`; `test_prompts_forgetting.py:64`, `:70`, `:77` `test_forgetting_body_says_ask`, `:82`, `:90` |
| US1.5 overview has 3-6 sentences | `test_prompts_overview.py:20` `test_overview_body_is_three_to_six_sentences` |
| US1.6 remembering has no "override"/"refusals" | `test_prompts_remembering.py:198` `test_body_leaves_privacy_override_to_privacy_section` |
| US1.7 curated contains the shared-scope ask-first clause | `test_prompts_curated_content.py:80` (pins "in a shared scope", "Scopes section", "asking first") |
| US1.8 filing carries the `description` rule; write mechanics has no "same call"/"same write" | `test_prompts_filing.py:88` (phrase at :83); `test_prompts_write_mechanics.py:110` `test_us3_2_same_write_rule_lives_in_filing` |
| US1.9 nine bodies at least 35% shorter | Measured; see table (35.5%). No unit test |
| US2.1 each doc equals plan.md B1-B7 | No exact-text test; covered by `test_tools_descriptions.py:209` `test_docstring_contains_pinned_phrase` and the plan diff |
| US2.2 slug rule, `.md`, "is read-only" only in `get_memory_index` | `test_tools_descriptions.py:284` `test_shared_mechanics_stated_once` |
| US2.3 `get_memory_index` states the shared mechanics | `test_tools_descriptions.py:209` (phrases at :43-:55), `:266` `test_name_docstring_says_name_excludes_md`, `:277` `test_area_docstring_states_slug_rule`, `:309` `test_get_memory_index_docstring_explains_entity_segment` |
| US2.4 each mutating doc: "version conflict is routine", "retry", `expected_version` | `test_tools_descriptions.py:236` `test_mutating_docstring_presents_conflict_as_merge_and_retry`; `:258` `test_fact_docstring_says_pass_version_you_read`; `:209` (`expected_version` pins, including `delete_file`'s at :92) |
| US2.5 three docs say "merge your change into the content it returns and retry with its version" | `test_tools_descriptions.py:248` `test_merging_docstring_says_merge_and_retry` |
| US2.6 `delete_file` says "only if the file should still go" | `test_tools_descriptions.py:209` (phrase at :93) |
| US2.7 `append_line`, `replace_fact` each state the five metadata phrases | `test_tools_descriptions.py:227` `test_fact_docstring_explains_aliases_and_description` |
| US2.8 every first line is one sentence ending in "." | `test_tools_descriptions.py:196` `test_docstring_first_line_is_one_sentence` |
| US2.9 seven docs at least 40% shorter | Measured; see table (40.1%). No unit test |
| US3.1 reference blobs equal plan.md C1-C3 | No exact-text test; covered by US3.2-3.4 pins and the plan diff |
| US3.2 seed areas: no "read-only", "slug", "not a fixed list", "agent-writable" | `test_prompts_assembly.py:386` `test_reference_slots_state_only_deployment_facts`; `:374` `test_reference_seed_areas_content` |
| US3.3 systems of record: no "copy", "mirror" | `test_prompts_assembly.py:386`; `:401` `test_reference_systems_of_record_content` |
| US3.4 scope guidance keeps hierarchy, per-scope rules, ask-first, contradiction, containment, scope test, examples | `test_prompts_assembly.py:343` `test_reference_scope_guidance_rules` |
| US3.5 `PromptSlots.__doc__` says "Slots state only deployment facts", keeps vocabulary | `test_prompts_slots.py:254` `test_docstring_says_slots_state_only_deployment_facts`; `:248` `test_docstring_states_vocabulary_contract` |
| US3.6 README snippet comments and added sentence | Doc, no test |
| US4.1 `def test_` count not lower in any file | Counted; see table below |
| US4.2 changed or added tests cite AIE-1165 | Checked by reading the docstrings |
| US4.3 `test_prompts_invariants.py` unchanged | `git diff main...HEAD -- tests/test_prompts_invariants.py` is empty |
| US4.4 `make check` passes | `make check` |
| US5.1 ADR 0025 decision 11 and decision 6 update | Doc, no test |
| US5.1a ADR 0022 decision 8 dated note | Doc, no test |
| US5.2 ARCHITECTURE.md `tools` and `prompts` entries | Doc, no test |
| US5.3 this file has the before/after table | Doc, no test |

`def test_` functions per file (main → branch):

| File | Before | After |
|---|---:|---:|
| `test_prompts_overview.py` | 2 | 3 |
| `test_prompts_systems_of_record.py` | 2 | 2 |
| `test_prompts_applying_memory.py` | 3 | 3 |
| `test_prompts_remembering.py` | 17 | 18 |
| `test_prompts_privacy.py` | 6 | 6 |
| `test_prompts_filing.py` | 6 | 6 |
| `test_prompts_write_mechanics.py` | 24 | 24 |
| `test_prompts_curated_content.py` | 5 | 6 |
| `test_prompts_forgetting.py` | 7 | 8 |
| `test_tools_descriptions.py` | 11 | 14 |
| `test_prompts_assembly.py` | 21 | 22 |
| `test_prompts_slots.py` | 15 | 16 |
| `test_prompts_invariants.py` | 14 | 14 |

No file lost a test function. Collected pytest cases went from 3553 to 3533 passed, because the parametrized phrase cases removed (for example the `name` and `area` checks, formerly parametrized over five and six tools and now run once on `get_memory_index`, and the shorter phrase lists) outnumber the cases added.

## Architecture / ADR changes

- [ADR 0025](../../docs/adr/0025-prompt-layer-sections-and-slots.md): new decision 11, "Shared tool mechanics live in `get_memory_index`; conflict handling stays per tool", with the three rejected options and the slots-state-only-deployment-facts rule; decision 6's docstring list and its "Dropping one fact" bullet updated (write mechanics owns the line-break wording; forgetting says "drop"); a Consequences paragraph on hosts that show a write tool without `get_memory_index`.
- [ADR 0022](../../docs/adr/0022-tool-layer.md) decision 8: a dated note pointing to ADR 0025 decision 11; original text unchanged.
- `ARCHITECTURE.md`: the `tools` entry says where shared mechanics are stated and why each mutating tool keeps its conflict rule; the `prompts` entry's division-of-labor sentence adds that slots state only deployment facts.
- `README.md` "Adopter configuration": the three slot comments and one sentence saying slots state only deployment facts.

## Deviations from spec

- None.

## Look closely at

- The docstring cut is 40.1% against a 40% target, a margin of 4 characters (2689 vs a ceiling of 2693), and the generic cut is 35.5% against 35%, a margin of 51 characters (6318 vs 6369). Later additions can push either under; the targets are one-time goals of this pass, not tests.
- `get_memory_index` is now the single home of the shared tool mechanics. A host that loads tool schemas on demand and shows a write tool without it gives the agent that tool's conflict rule and `expected_version` guidance but not the slug or `system/` rules; the tools still reject a violating call. Check that this trade-off (ADR 0025 decision 11) is acceptable.
- The filing section now owns the same-write rule for both `aliases` and `description` ("On the same write that records a fact, pass in `aliases` ... and pass a new `description` ..."); write mechanics keeps only the `write_file` cases (dropping a name from `aliases`, rewriting the `description` with no fact to write). Check that the two read as one consistent rule in the assembled prompt.

## Follow-ups

- The behavioral eval scenarios in spec.md (on-demand tool loading with a conflicting `append_line`, curated correction in an ask-first shared scope, a new nickname appended without an index rescan, dropping one fact line) are inputs to the later eval harness.
- `append_line`'s docstring lists `[system]` as a writable label, while the remembering section forbids writing new `[system]` lines. Pre-existing; out of scope here.
- `write_file`'s docstring says an oversize write reports "the current size", but `OversizeWriteError.size` is the attempted size and its message says "split". Pre-existing; out of scope here.

## Adversarial review findings

Spec review: round 1 FAIL (1 BLOCKING: a pin missing from target text; 6 SHOULD-FIX: dropped Notion 8.1 phrases, lost "confidence label" term, ungrammatical example, filing antecedent, false disposition claim, ADR 0022 left stale), round 2 FAIL (1 SHOULD-FIX: four more pinned 8.1 phrases restored), round 3 PASS.

Code review round 1:

- Reviewer A (fidelity) FAIL, 2 SHOULD-FIX: the curated precedence rule had become only a step in the correction procedure (restored as "When a correction and a curated fact conflict, answer from the correction."); remembering dropped "when you know it" on saving a pattern (restored as "if you know it"). NITs applied: forgetting "not to be removed automatically", filing "If a file on the subject exists". NITs not applied: a `delete_file` docstring mention of content (no room in the 40% budget; the conflict sentence still says to retry only if the file should still go); the pre-existing `append_line` `[system]` label and `write_file` "current size" wording (out of scope, listed as follow-ups).
- Reviewer B (tests/docs) FAIL, 1 SHOULD-FIX: the remembering and privacy negation pins lost "never"/"even" (they now pin the whole rule sentence). NITs applied: vacuous slug assert removed, `delete_file` and fact-tool `expected_version` guidance pinned, ADR 0025 decision 6 and ADR 0022 note wording, this file's US1.4 row, a test docstring's history wording, a stale ARCHITECTURE.md line.

Code review round 2: reviewer A PASS (one NIT: plan F12 still described a removed assert; plan updated). Reviewer B PASS (re-ran HEAD tests against the round-1 source: exactly the four new wording pins fail there; one NIT: two doc paragraphs needed re-wrapping, done). Spec-reviewer gate: PASS, 34 of 34 criteria, no BLOCKING or SHOULD-FIX. NITs applied: pins added for three short forgetting rules and the privacy strictness rule (unpinned on main too); story IDs in the new tool-description test docstrings; this line; spec status.
