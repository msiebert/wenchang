# Spec Review: AIE-1051 — Write mechanics prose

## What & why

Fill in the "Choosing a write tool" section of the memory prompt: add a fact
with `append_line`, change one with `replace_fact` quoting the existing line,
and keep `write_file` for new files or restructuring, so a write cannot
disturb lines the agent was not editing. It also says that new aliases and a
refreshed description ride on the same fact write, and gives the exact
mechanics for dropping one fact line without leaving a blank line.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `write_mechanics` | read | body non-empty; heading "Choosing a write tool"; appears in the assembled prompt |
| 2 | body | read | names `append_line` (add one fact), `replace_fact` (change one fact, quote the existing line, surrounding lines intact), `write_file` (new file, restructuring many lines), and the "mechanically impossible" reason |
| 3 | body | read | `aliases` and `description` go on the same call (`append_line`, `replace_fact`, or the creating/restructuring `write_file`); removing an alias or rewriting the description wholesale with no fact to write is `write_file` |
| 4 | body | read | dropping a line: whole line plus the line break after it (if none follows, the one before it) as `old_string`, empty `new_string`, no blank line; `delete_file` only for the whole file |
| 5 | body | read | no version-conflict, unique-anchor, byte-ceiling, or label-syntax text; under 2500 chars |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Exact prose fixed in plan.md | Let implementer draft | Prose is the whole deliverable; reviewers check it at the spec stage |
| Phrase pins on load-bearing tokens, whitespace-normalized | Pin whole sentences | Wording can be tuned without rewriting tests |
| Negative pins for docstring-owned mechanics | None | Guards the docstring/prompt division of labor (ADR 0025 decision 6) |
| "Wholesale" description rewrite means one with no fact to write, stated in the body | Treat every description change as `write_file` | ADR 0024 lets `description` ride on the fact write; addendum decision 1 keeps `write_file` for wholesale rewrites |
| Drop-line fallback keyed on "if none follows it" rather than "for the last line" | Addendum's literal "for the last line" | Same result for every normal file, and also correct for a last line with no trailing break |

## Files/modules to be touched

- `src/wenchang/prompts/write_mechanics.py` (`BODY` only)
- `tests/test_prompts_write_mechanics.py` (new)
- `specs/AIE-1051-write-mechanics/`

## Open questions / assumptions

- None requiring a human; cross-issue wording follows addendum decisions 1
  and 2.

## Risks

- Parallel sections (filing, forgetting) could word aliases or dropping
  differently; mitigated by the shared addendum wording.

## Adversarial review

- Round 1 (FAIL, 3 SHOULD-FIX): the drop-line fallback "for the last line"
  left a blank line when the dropped line was the file's only line (now
  "if none follows it"); "rewriting the description wholesale" was
  disambiguated only outside the body (now "with no fact to write" in the
  body); the body omitted addendum decision 1's `write_file` branch for
  aliases (added). NITs: merged a redundant metadata sentence, corrected the
  fixture import form, added `existing file` and aliases-sentence pins.
- Round 2 (PASS): one NIT applied (US3.2 wording matches the body); one
  optional wording NIT declined, since `write_file` requires `description`
  anyway.
