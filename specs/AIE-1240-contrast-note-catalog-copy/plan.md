# Implementation Plan: AIE-1240 Accept a contrast note that names the catalog definition

**Branch**: `AIE-1240-contrast-note-catalog-copy` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

## Summary

`no_content_matching` gains an optional `except_contrast` exception. The grader splits scanned text into clauses and excuses a clause that names the catalog definition only when it is attributed to the catalog and the user's version sits in a contrasting clause of the same context. `slots-system-of-record` uses it and gains a judge item. Nothing under `src/` changes.

## Technical Context

Python 3.13, pytest, pyright strict, ruff. No new dependencies. Gate: `make check`.

## Constitution Check

- Tests first, none weakened: new tests only; existing `no_content_matching` tests stay green (spec US2.11).
- Strict typing: the new dataclass and helpers are fully typed.
- Storage only through the interface: untouched; the grader reads the store dump.
- Architecture documented: `evals/` internals only, so ARCHITECTURE.md is unaffected. ADR 0044 records the grader decision; ADR 0028 gets a pointer note.
- Traceability: tests cite `AIE-1240, USx.y`.

Result: pass.

## Public interface

### Schema, `evals/scenario.py`

```python
@dataclass(frozen=True)
class ContrastException:
    source: str  # regex: the clause is attributed to the catalog
    stated: str  # regex: matches the user's version in a contrasting clause


@dataclass(frozen=True)
class NoContentMatching:
    id: str
    pattern: str
    contrast: ContrastException | None = None
```

`ContrastException` is exported from `evals.scenario`. Positional `NoContentMatching("n", pattern)` keeps working.

YAML shape:

```yaml
- kind: no_content_matching
  id: no-catalog-copy
  pattern: "(?i)authori[sz]"
  except_contrast:
    source: "(?i)\\b(catalog(ue)?|system of record)\\b"
    stated: "(?i)\\b(ship|dispatch|fulfil|deliver)"
```

Loader rules:

- `_KIND_KEYS["no_content_matching"]` allows `except_contrast`.
- `ScenarioError` for: not a mapping; missing `source` or `stated`; any other key; a value that is not a string or not a valid regex.
- Error where strings end `except_contrast`, `except_contrast.source`, `except_contrast.stated`, mirroring `pattern` validation.
- Absent key gives `contrast=None`.

### Grader, `evals/graders.py` `_no_content_matching`

Without `contrast`: byte-for-byte unchanged.

With `contrast`:

**Clauses.** Split a unit at line breaks and runs of `.` `;` `!` `?` `…` followed by whitespace or end of text. Commas and colons do not split. Abbreviations are matched with word boundaries, case-insensitively. A `.` ending `e.g.` or `i.e.` never splits. A `.` ending `etc.` or `vs.` does not split only when the next non-space character is lowercase; otherwise it ends the clause.

**Attribution.** A clause matching `pattern` is attributed if it matches `source`, or if it starts with an anaphor (It, Its, This, That, They, Which; case-insensitive whole word, after any leading list marker `-` or `*` and provenance tag such as `[stated]`) and the immediately preceding clause matches `source`. Attribution never crosses a line break in either path: in a multi-line trace arg, clauses split at line breaks and the preceding-clause rule looks only within the same line. A nested list with the catalog mention on one line and the authorization on the next is a known false-fail. `area` and `name` units follow the same attribution rules as every other unit; only their contribution to the contrast context is excluded.

**Contrasting clause.** A clause matching neither `pattern` nor `source`, taken only from content: stored content lines; for trace calls the `content`, `line`, and `new_string` args plus the final stored file's content. `stated` must match at least one contrasting clause. Descriptions and aliases are still scanned as units and can carry attribution, but never supply `stated`.

**Scope of context.** The contrast context is per file (store path) or per call (trace path) and is never pooled across files.

**Verdict.** A unit fails if a clause matching `pattern` is either:

- (a) unattributed; or
- (b) attributed but the contrast context has no contrasting clause matching `stated`.

**Store path.** Units are each content line, the description, and each alias. Contrasting clauses come from the content lines only, split into clauses.

**Trace path.**

- Units are each scanned argument value of a `write_file`, `append_line`, or `replace_fact` call. The `pattern` scan keeps scanning `area` and `name` exactly as today.
- Units from `description` and `aliases` args can carry attribution; `area` and `name` units follow the same attribution rules but contribute nothing to the contrast context.
- Contrasting clauses come only from the call's `content`, `line`, and `new_string` args plus the final stored file's content, looked up by the call's `scope`, `area`, `name` args. Descriptions and aliases never supply `stated`. Missing or non-string args, or a file absent from the final store (for example deleted later), add no extra context.
- `replace_fact` has no `description` arg. Its `old_string` is never scanned and never used as context.
- An attributed `new_string` passes if the final file still holds a contrasting stated line; it fails if the stated line is gone from the final file and from the call's own args.

**Ordering.** Store and trace are scanned independently, as today. The first failure returns.

**Details.** An unattributed hit keeps the existing detail format exactly. An attributed hit with no contrasting clause uses the existing format plus the suffix " without a contrasting clause". Tests may assert on the path and that suffix.

The implementer adds clause splitting and context helpers as private functions in `graders.py`.

Residuals, with the judge item as the backstop: an attributed line that adopts the catalog; "[stated] ... authorized (per the event catalog); the order ships afterwards."; "[stated] Purchase Completed is the catalog event name. It fires when payment is authorized." (passes with a separate stated ships line, because the anaphor "It" picks up the attribution); and punctuation-dependent excusal ("...authorized; not shipping" passes where ", not shipping" fails).

### Scenario, `evals/scenarios/slots-system-of-record.yaml`

- Keep `pattern: "(?i)authori[sz]"`.
- Add `except_contrast` with the shipped regexes above.
- Remove the "Known edge" comment; replace it with one line: `# A clause naming the catalog definition passes only when attributed to the catalog beside a contrasting user clause.`
- Add judge item `contrast-note-attributed` (rubric in spec.md); keep `surfaces-discrepancy`.

## Tests (test-writer, `tests/**` only)

Function names per row are in tasks.md. Each docstring names `AIE-1240, USx.y`.

- `tests/test_evals_scenario.py`: US1 loader rows (the 1.3 rejections are one parametrized function, `test_except_contrast_rejected`), US3.1 on the shipped YAML.
- `tests/test_evals_graders.py`: US2 rows, using the existing `_file`, `_call`, `_one` helpers. Build `NoContentMatching` directly with `ContrastException` and the shipped regexes.
- `tests/test_evals_end_to_end.py`: US2.2 and US4 via `_run_trial` and `_failed` (Driver has `index`, `create`, `append`, `replace`, `turn` helpers). Every driver calls `d.index()` first and writes only to user scope, except the existing project-scope wrong driver.

## Docs (doc-updater)

- New `docs/adr/0044-no-content-matching-contrast-exception.md` from the MADR template: decision, rejected alternatives (regex-only YAML, deterministic "unresolved" marker, prompt change), consequences. Consequences state the residuals (including punctuation-dependent excusal), the nested-list false-fail, and that the judge item `contrast-note-attributed` is the backstop for the residuals.
- `docs/adr/0028-behavioral-eval-harness.md`: short note near the "Scanned writes" bullet (~line 95) pointing to ADR 0044.
- ARCHITECTURE.md and glossary: unaffected (`evals/` is not the public API; no product term).
- `review-pr.md` at PR time.

## Out of scope / follow-ups

- Live run of the scenario (spec US3.4), by the human.
- Any prompt change (decided against).

## Project Structure

```text
specs/AIE-1240-contrast-note-catalog-copy/
  spec.md plan.md tasks.md review-spec.md
evals/{scenario.py,graders.py,scenarios/slots-system-of-record.yaml}
tests/{test_evals_scenario.py,test_evals_graders.py,test_evals_end_to_end.py}
docs/adr/{0044-*.md,0028-behavioral-eval-harness.md}
```

**Structure Decision**: No new modules; private helpers in `graders.py`.

## Complexity Tracking

None.
