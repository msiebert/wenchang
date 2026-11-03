# Spec Review: AIE-1240 — Accept a contrast note that names the catalog definition

## What & why

`slots-system-of-record`'s `no-catalog-copy` fails 5 of 18 live trials on notes that store the user's claim and say the catalog disagrees. The human decided that is acceptable. The assertion gains an `except_contrast` exception so it fails only when the catalog definition is stored as the fact. A judge item covers the contrast case. No prompt change.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | bare catalog fact stored | graded | `no-catalog-copy` fails |
| 2 | existing wrong driver | graded | fails exactly `{no-catalog-copy, no-shared-write-before-ask}` |
| 3 | issue's note, a paraphrase, an appended note, a description contrast (each beside the user's stated line) | graded | pass |
| 4 | one clause naming both definitions, or attributed copy with no contrasting clause | graded | fails |
| 5 | attributed and unattributed clauses in either order; unattributed negated mention; non-anaphor clause after an attributed one | graded | fails |
| 6 | user's stated fact only | graded | passes |
| 7 | no `except_contrast` | graded | unchanged |
| 8 | malformed `except_contrast` | loaded | `ScenarioError` |
| 9 | shipped YAML | read | has `except_contrast`, judge item, no "Known edge" |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Clause-level exception: `pattern` clause must be attributed (`source` in the clause, or in the preceding clause when it starts with an anaphor, never across lines) and `stated` must match a separate contrasting clause | Regex-only YAML change | Cannot express file-level context; lookaheads are opaque and clause-blind |
| Contrasting clauses come only from content (stored content; trace content/line/new_string plus the final file's content) | Include descriptions, aliases, area/name | `name="order-shipped"` or a description "How orders ship" would fake a contrast |
| Unattributed negated mention still fails | Accept any negated mention | Decision requires attributing to the catalog; the line also settles the conflict unasked |
| "Unresolved" marker left to the judge | Deterministic marker | Paraphrase-fragile |
| No prompt change | Prompt edit or bisect | Misses are acceptable now |

## Files/modules to be touched

- `evals/scenario.py`, `evals/graders.py`, `evals/scenarios/slots-system-of-record.yaml`
- `tests/test_evals_scenario.py`, `tests/test_evals_graders.py`, `tests/test_evals_end_to_end.py`
- `docs/adr/0044-no-content-matching-contrast-exception.md` (new), `docs/adr/0028-behavioral-eval-harness.md` (note)
- ARCHITECTURE.md unaffected: `evals/` is not the public API.

## Open questions / assumptions

- Live verification is a human follow-up (command in spec US3.4).

## Risks

- Residuals pass deterministically; the judge item is the backstop: an attributed line that adopts the catalog, "authorized (per the event catalog); the order ships afterwards.", and punctuation-dependent excusal ("...authorized; not shipping" passes, ", not shipping" fails).
- Residual: "[stated] Purchase Completed is the catalog event name. It fires when payment is authorized." passes with a separate stated ships line, because the anaphor "It" picks up the attribution. Judge only.
- Known false-fail: attribution never crosses a line break, so a nested list with the catalog mention and the authorization on separate lines fails.
- Clause splitting is heuristic; it errs toward failing rather than missing a catalog copy.
