# Implementation Plan: AIE-1252 Remove `path` from agent-facing tool results

**Branch**: `AIE-1252-remove-path-results` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

## Summary

The render layer (`render_result`, `render_error`), error message text, the overview prompt, and the eval harness stop exposing a storage path. The agent names locations as scope, area, name. Core value types and error attributes keep `.path`; nothing in `core`, `scope`, storage, or `mcp.py` changes.

## Technical Context

Python 3.13, pytest, pyright strict, ruff. No new dependencies. Gate: `make check` (constitution III).

## Constitution Check

- I/II Tests-first, tests not weakened: tests that assert rendered `path` are updated to the new spec text, not deleted (the spec requires the change). Tests for the retired reply-path check are removed along with the feature they test; this is the issue's explicit scope and is called out in review-spec.
- IV Strict typing: no new untyped code.
- V Storage only through the interface: untouched.
- VI Spec fidelity: the change deviates from ADR 0022 and 0033 (not the Notion spec); recorded in a new ADR.
- VII Architecture documented: public render shape changes, so new ADR plus ARCHITECTURE.md in the same PR.
- VIII Traceability: tests cite `AIE-1252, USx.y`.
- IX Single issue: yes.
- XI Review artifacts: review-spec.md now, review-pr.md at PR.

Result: pass, no complexity violations.

## Public interface after the change

### `render_result(value)` in `src/wenchang/tools.py`

Key order shown; `path` and `prefix` never appear at any depth.

- `None` -> `{"ok": True}` (unchanged; `delete_file`).
- `MemoryFile` (`read_file`, `write_file`, `append_line`, `replace_fact`):
  `scope, area, name, content, version, description, aliases, sources, last_updated`.
- `ListPage` (`list_prefix`): `{"entries": [<entry>...], "next_cursor": str | None}`. `<entry>` = `scope, area, name, version, description, aliases, sources, last_updated` (no `content`). `next_cursor` is the opaque string unchanged; omitted only if not an exact `str` (as today).
- `MemoryIndex` (`get_memory_index`): `{"entries": [<entry>...], "capped": [{"scope", "area", "omitted"}...]}`. `area` is `None` for a scope- or entity-level prefix. A capped row is still skipped if its real prefix is not a `str` or `omitted` is not an `int`; the prefix is read internally only to derive `scope`/`area`.
- Degradation unchanged: entry path a malformed `str` -> `scope`, `area`, `name` all `None`; entry path not an exact `str` -> those three omitted; other field guards as today. Still never raises.

Implementation: `_file_fields` keeps reading `entry.path` and `parse_path` but stops writing `fields["path"]`. `_capped_fields` stops writing `"prefix"`.

### `render_error(exc)`

Remove `"path"` from `_ERROR_FIELDS`. Output keys per kind (`error`, `category`, `message` always present):

| Error | Extra keys |
| ----- | ---------- |
| `VersionConflictError` | `scope, area, name, content, version` |
| `OversizeWriteError` | `scope, area, name, size, limit` |
| `ReplaceFactMatchError` | `scope, area, name, content, version, match_count` |
| `NotFoundError` (`FILE_ABSENT`) | `scope, area, name, reason` |
| `NotFoundError` (`INVALID_PATH`, unparseable) | `reason` only |
| `RestrictedScopeError` | `scope, area, name, reason`, plus `required_roles` for `ROLE_REQUIRED` |
| `InvalidArgumentError` | `argument` (unchanged) |
| Transient/internal kinds | unchanged |

`scope`, `area`, `name` come from a new guarded step in `_wenchang_error_fields`: read `error.path`; if it is an exact `str` and `parse_path` succeeds, set `area` and `name` (and `scope` unless the error already has its own `scope` attribute, which `RestrictedScopeError` does and which wins). Any failure drops the keys; never raises. `required_roles`, `content`, etc. render as before via `_json_value`.

### `src/wenchang/errors.py`

Constructors, attributes, and `category`/`guidance` are unchanged (`.path` stays). Only message text changes. A private helper `_location(path: str) -> str | None` imports `parse_path` from `wenchang.paths` (that module imports nothing from wenchang, so no cycle) and returns `scope {scope}, area {area}, name {name}` (for example `scope user, area preferences, name csv`), or `None` if the path does not parse.

Message formats (`{loc}` = the helper's string; `.` terminates sentences as today):

- `VersionConflictError`: `The file at {loc} changed since it was read; the current content and version are attached; merge your change into the current content and retry with the current version.`
- `OversizeWriteError`: `The write to {loc} is {size} bytes, over the {limit}-byte limit; split the content across multiple files.` If the path does not parse, `{loc}` is `the file`.
- `ReplaceFactMatchError`: `old_string matched {n} spans in {loc}; ...` rest unchanged.
- `NotFoundError(FILE_ABSENT)`: `No file exists at {loc} yet; you may create it.`
- `NotFoundError(INVALID_PATH)`: `That is not a valid memory location; correct the scope, area, and name.` (no echo of the raw string).
- `RestrictedScopeError`, with `{loc}` from `path`, falling back to `scope {scope}`:
  - `SYSTEM_READ_ONLY`: `The file at {loc} cannot be written: the system/ area of scope {scope} is read-only (curated content).`
  - `NOT_GRANTED`: `The file at {loc} cannot be written: the caller's identity does not include this entity in scope {scope}.`
  - `ROLE_REQUIRED`: `The file at {loc} cannot be written: scope {scope} is role-gated and the caller lacks a permitted role ({roles}).`

Tests should assert: the message contains `scope user, area preferences, name csv` (or the fallback), and contains neither `/`-joined path, `.md`, nor the entity ID. Exact full-string pins are fine for the formats above.

Where `NotFoundError.path` holds a prefix (core `list_prefix`), `parse_path` fails and the message uses the invalid-location text for `INVALID_PATH`.

### `get_memory_index` docstring (`tools.py`, `MemoryTools.get_memory_index`)

Replace the path-form sentences with:

```
Load the metadata index of every memory scope available in this session.

Call this first. Each entry gives a file's scope, area, name, metadata, and version, without
content. Pass `scope`, `area`, and `name` (without `.md`) to the other tools, as in
`read_file(scope, area, name)`. Areas are lowercase ASCII slugs. The `system/` area is read-only.
An area with more files than fit is listed under `capped` with the number omitted; page it with
`list_prefix(scope, area)`.
```

`tool_descriptions` pins in existing tests (first lines, product substitution) must still pass; update any pin that quotes the removed sentences.

### Prompt: `src/wenchang/prompts/overview.py` `BODY`

```
Memory is short markdown files that outlast this conversation, each addressed by a scope, an
area in that scope, and a name. When you tell the user where something is stored, name its scope,
area, and name. Call `get_memory_index()` at the start of every session, before you answer from
memory or write to it. When a subject outgrows its file's size limit, split it into narrower
files.
```

Wrapped at 100 columns. Only backtick span is `get_memory_index()`. Then regenerate `.claude/agents/wenchang-eval.md` with `uv run python -m evals render-agent` (it mirrors `BODY`; hand edits are not the mechanism). `tests/test_prompts_overview.py` pins change: the old sentence constant is replaced by the new one, the backtick-token assertion (`== ["path"]`) becomes "no backtick span in the sentence", and a no-`path`-word check is added.

### Evals

Removed from `evals/graders.py` (and `__all__`): `find_unmatched_reply_paths`, `UnmatchedReplyPath`, `PATH_ROOTS`, `_LOCATION_KEYS`, `_result_locations`, `_known_locations`, and any helper only they use (implementer to confirm by grep; keep helpers also used by the operator-identity or third-person checks).

`evals/report.py`:

- Drop the import; `_REPLY_CHECK_KEYS` becomes `("third_person_replies", "transcript_error")`.
- `_reply_check` stops taking/using the trace for paths and stops writing `unmatched_reply_paths`; `_refresh_reply_check` stops loading `trace.json` for this purpose (keep it only if another check needs it).
- Remove `_REPLY_PATH_FIELDS`, the `unmatched_reply_paths` branch in `_load_grade` (a leftover key in an old `grade.json` is ignored, not rejected; confirm `_checked` does not reject unknown keys), `path_flagged`/`path_unchecked` in `build_report`, the fields `reply_path_trials`, `reply_path_unchecked_trials`, `reply_paths`, `_paths_line`, and the two markdown lines ("Trials with an unmatched reply path", "Unmatched reply paths:", "Reply paths not checked:"). The operator-identity `path` field (`_IDENTITY_HIT_FIELDS`) is unrelated and stays.
- Staleness check at report.py ~534: confirm removing the key does not mark every old grade stale in a way that triggers errors.

Scenarios under `evals/scenarios/` (ids unchanged; update `source:` to this spec and `title:` wording):

- `filing-says-saved-path`: replace `names-full-path` with a judge item `names-scope-area-name`: `The turn 1 reply says where the fact was saved by giving the file's scope, area, and name.` Replace `no-rebuilt-path` with `reply_not_matching` id `no-entity-id` pattern `(?i)\bu-ada\b`, session 1, turn 1. Title: `Names the scope, area, and name when asked where a new fact went`.
- `recall-says-stored-path`: judge item `names-scope-area-name`: `The reply tells the user the file holding the enterprise definition by its scope (organization), area (vocabulary), and name (account-tiers).` Replace `no-rebuilt-path` with `no-entity-id` pattern `(?i)\bo-acme\b`. Keep `no-write`. The `organization/vocabulary/account-tiers` values are seed fixture facts of this scenario, not prompt text. Title: `Names the scope, area, and name of the file holding a definition when asked where it is`.
- `slots-says-shared-path`: replace `no-rebuilt-path` with `no-entity-id` pattern `(?i)\bp-checkout\b`, session 1. Title: `Names no entity ID after a shared save`.
- `applying-no-path-unasked`: keep the pattern check (id `no-path-in-reply`) and the judge; the pattern already forbids any scope-rooted path or `.md` in the reply. Verify it still passes the existing correct/wrong drivers; no change expected beyond `source:`.
- `curated-correction` judge `says-where-saved` is wording-neutral; unchanged.
- Every `# Prompt:` header citing the overview must quote a sentence that exists now; replace the two uses of the old "quote the full `path`" wording if any, and keep those citing the addressing sentence.

A scenario no longer needs to enforce a slash path form, so the entity-id patterns only catch the failure the old check was guarding against (leaking `scope/entity/...`). Whether a slash-joined `scope/area/name` reply is acceptable is an open question in review-spec; this plan allows it.

## Tests (test-writer, `tests/` only)

Update to the new shapes, citing `AIE-1252, USx.y`:

- `tests/test_tools_render.py` (lines about 69, 91, 187, 230, 239, 250, 259, 287, 308, 412, 461, 611, 623, 650, 678, 741): remove `path` from expected dicts; add a recursive `path`/`prefix` absence walk; capped rows exactly `{scope, area, omitted}`; error cases per the table above including `scope/area/name` and message formats; malformed and non-str path degradation.
- `tests/test_tools_end_to_end.py` (~141-235), `tests/test_mcp_server.py` (~759, add text and structured no-`path` check), `tests/test_evals_server.py` (~196, 326, 382), `tests/test_reference_adopter_end_to_end.py` (~78, 189, 276, 400, 496, 542-579): drop `path` expectations; where a test used the rendered `path` to chain calls, use scope/area/name.
- `tests/test_errors*.py` (find by grep for the message strings): message-format tests; `.path` attribute still present.
- `tests/test_prompts_overview.py`, `tests/test_prompts*.py`/`tests/test_evals_agent.py`: new sentence, regenerated agent file pin.
- `tests/test_evals_graders.py` (~1725-2065) and `tests/test_evals_report.py` (~1410-1943): delete the reply-path tests; add report tests for: no reply-path fields in grade/report/markdown, old `grade.json` with `unmatched_reply_paths` loads and refreshes without error.
- `tests/test_evals_end_to_end.py`, `tests/test_evals_scenario.py`: correct/wrong drivers for the four scenarios with exact fail sets.
- `tests/test_core_*.py`: untouched.

Any test deletion must be limited to the reply-path check and `path` assertions that this issue removes (constitution II).

## Docs (doc-updater, after approval)

- New ADR `docs/adr/0036-no-path-in-agent-results.md` (next number; verify): supersedes ADR 0033 (set 0033 Status to `Superseded by 0036`, add `Superseded by` pointer), amends ADR 0022 decision 11's render shape (add an `Amended by 0036` note at 233-283 and 372-380) and touches ADR 0020 line ~184 if it describes the render shape (add pointer only). Records: decision, rejected alternatives (keep path; add `entity` field; keep path in errors), consequences (fewer tokens; breaking for hosts parsing rendered `path`; dropped reply-path guard; scenario rewrites).
- `ARCHITECTURE.md`: render shape at ~947-962, mentions at ~196-198 and ~1298-1302, evals bullets at ~1201-1203 and ~1229-1230; the "never shows a memory path or entity ID" line at ~1053 stays true and may be tightened.
- `docs/product/glossary.md` ~221-224: note that **Memory path** is internal and not shown to agents; add a **Location** entry (scope, area, name).
- `specs/AIE-1252-remove-path-results/review-pr.md` at PR time.

## Out of scope / follow-ups

- `site-src/reference.md` (lines 15, 90-91, 101, 114-116, 140, 226, 243-248), `site-src/usage.md` (JSON examples at 45, 83, 134, 163, 180, 242, 276, 339, 382, 407, 421, 446), `site-src/index.md` (72, 83, 89, 104), `site-src/prompts.md` (45) document the old shape. They are outside every subagent's edit scope and need a human decision (see tasks T6). `README.md` has no result-shape mention.
- A live `/run-evals` run of the rewritten scenarios, by the human.
- Historical ADRs 0034/0035 mention `unmatched_reply_paths` and stay as history.

## Project Structure

```text
specs/AIE-1252-remove-path-results/
  spec.md plan.md tasks.md review-spec.md
src/wenchang/{tools.py,errors.py,prompts/overview.py}
evals/{graders.py,report.py,scenarios/*.yaml}
.claude/agents/wenchang-eval.md        (generated)
tests/...  docs/adr/0036-*.md  ARCHITECTURE.md  docs/product/glossary.md
```

**Structure Decision**: No new modules. One new private helper in `errors.py`.

## Complexity Tracking

None.
