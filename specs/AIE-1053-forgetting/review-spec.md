# Spec Review: AIE-1053 — Forgetting

## What & why

The prompt's last section, "Forgetting", is empty on main. This fills
`forgetting.BODY` with Notion §8.1's forgetting rule: two moves (drop one fact
with `replace_fact`, or delete the whole file with `delete_file`), removal is
total with no softened rewrite, anything derived solely from the removed fact
goes too, and ask when it is unclear which move the user means. It adds the
Linear issue's point that a fact past its own stated end date is a candidate
for dropping, judged by the agent, never removed automatically. A new test file
pins the load-bearing tokens.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| US1 | `forgetting` module / valid slots | read / `build_memory_prompt` | body non-empty; heading `Forgetting`; assembled prompt ends with that section |
| US2 | `BODY` | read | `two moves`, `` `replace_fact` `` + `fact line`, `` `delete_file` `` + `whole file`, `write-tool section says how to take the line break`, `the file's only fact`; no `` `write_file` `` / `` `append_line` `` |
| US3 | `BODY` | read | `Removal is total`, `solely`, `` `[inferred]` ``, `description or alias` + `exists only because of the removed fact`; never `used to` / `used-to` / `formerly` / `previously believed` |
| US4 | `BODY` | read | `ambiguous` and the word `ask` |
| US5 | `BODY` | read | `end date`, `candidate`, `not automatically`, `maintenance` |
| US6 | `BODY` | read | `` `system/` ``, `curated-content section`, `Never drop or delete` |
| US7 | `BODY` | shared invariant suite | ASCII, <=100 cols, <=2500 chars, real tool names, no paths or adopter scope names |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Paraphrase "no softened rewrite" without quoting "used to think" | Quote §8.1's example | Quoting models the phrase the agent must never write, and the negative pin forbids it |
| Refer to the write-tool section for the line break | Restate it here | Addendum decision 2: write mechanics owns the detail, so the two sections cannot drift |
| Name `[inferred]` as the derived-line case | Say "derived lines" only | The Linear content requirement names it; labels are still defined only in the remembering section |
| Lapsed end date = candidate, judged at read or maintenance | Automatic removal rule | Linear issue and addendum decision 5 |
| `system/`: never drop or delete; on a forget request say it cannot be removed; correct via the curated-content section only if the user says it is wrong | Restate the correction path; let the agent decide a curated fact is wrong | Addendum decision 6; AIE-1052 gates correction on the user saying it is wrong |
| Dropping a file's only fact means deleting the file | Leave an empty file | An empty file keeps its description and aliases in the index: a trace |
| A description or alias that points to the removed fact is updated too, via the write-tool section | Leave the index untouched | Description and aliases are the search surface; "Removal is total" |

## Files/modules to be touched

- `src/wenchang/prompts/forgetting.py` (`BODY` only)
- `tests/test_prompts_forgetting.py` (new)
- `specs/AIE-1053-forgetting/`

## Open questions / assumptions

- None requiring a human. No ADR: the text follows §8.1.

## Risks

- The pointers ("write-tool section", "curated-content section") assume
  AIE-1051 and AIE-1052 land with those sections; they are sibling issues in
  the same wave, under the headings "Choosing a write tool" and "Curated
  content". AIE-1051's plan carries the line-break sentence and the
  alias-removal / description-rewrite rule this section points to.

## Adversarial review

Round 1 (FAIL, 4 SHOULD-FIX, 4 NIT), all applied except NIT 6:
- Total removal left traces in the description and aliases: added the update
  sentence and pin US3.5, scenario E6.
- Dropping a file's only fact left an empty file: added "delete the file
  instead" and pin US2.6.
- "judge whether it has really lapsed" was circular: now "judge whether the
  fact still holds".
- `system/` paragraph did not cover a plain forget request and implied the
  agent could decide a curated fact is wrong: rewritten imperatively, with
  correction gated on the user saying it is wrong; pin US6.2, scenario E5.
- NIT 6 (match AIE-1051's "whole line" wording) declined: addendum decision 2
  says "whole fact line", which this text uses.

Round 2: PASS. Three NITs applied: clarified which file's description and
aliases are updated, aligned scenario E4 with "still holds", reordered the
sentence trace.

Code review then tightened three pins to phrases unique to one sentence and
reworded the only-fact and description/alias sentences (see review-pr.md).
