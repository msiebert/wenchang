# Spec Review: AIE-1151 — Optional aliases and description on append_line and replace_fact

## What & why

Notion §8.1 asks every write to add the names a subject will be looked up
by, and asks agents to append or replace one fact instead of rewriting the
file. Only `write_file` could change aliases, and it replaces them. This
change lets `append_line` and `replace_fact` add aliases (union, never remove)
and replace the description, in the same write as the content, at the core,
transport, and tool layers.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | file with aliases `("x", "y")` | `append_line(..., aliases=["y", "z", "w", "z"])` | aliases `("x", "y", "z", "w")` |
| 2 | file with description `"d"` | `append_line(..., description="d2")` | description `"d2"`, aliases unchanged |
| 3 | unique match | `replace_fact(..., aliases=..., description=...)` | content, union, and description in one put |
| 4 | stale token, concurrent alias added | `replace_fact(..., aliases=["z"])` re-applies | union onto the current aliases |
| 5 | arguments omitted or `None` | either call | metadata as today |
| 6 | bad types / newline description | core | `TypeError` / `ValueError`, no storage call |
| 7 | bad values | tools | `InvalidArgumentError`, same details as `write_file`, after `check_write` |
| 8 | — | `TransportClient`, `InProcessClient` | signatures equal core; pure pass-through |
| 9 | — | conformance suite | six new cases with broken-client self-tests |

Full table: spec.md US1–US7.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Optional keyword arguments on the existing writes | Prompt-only full `write_file`; relaxing alias upkeep | Human decision 2026-10-05; keeps one lock, one token |
| Union, existing first, exact equality | Replace; normalized comparison | Never lose an alias via a fact write; `write_file` does not normalize either |
| Stored duplicates kept as stored | Dedupe the whole tuple | These calls only add; restructuring is `write_file`'s job |
| Union computed on the committing attempt's read | On the caller's read | Concurrent alias additions are kept |
| Empty aliases / description accepted | Reject | Parity with `write_file` |
| Core raises `TypeError`/`ValueError`; tools raise `InvalidArgumentError` | Tool-layer only | Repo convention: library-controlled vs agent-supplied values |
| Tool parameters positional-or-keyword with `None` defaults | Keyword-only | Matches `list_prefix`; host schemas mark them optional |
| Shared `_description` helper in tools | Duplicate the checks | Reuse; one consequence is `write_file` reports a `\n` description before a bad `aliases` |

## Files/modules to be touched

- `src/wenchang/core.py`, `transport.py`, `tools.py`, `testing/transport_conformance.py`
- tests for each, plus signature updates to every `TransportClient` test double
- `docs/adr/0024-...`, `ARCHITECTURE.md`, glossary if it defines aliases

## Open questions / assumptions

- **Orchestrator default, pending human:** a stale-token `replace_fact` that
  re-applies with a `description` overwrites a description committed since
  the caller's read (last writer wins; aliases are unioned so none are lost).
  Alternative: raise `VersionConflictError` on a stale token whenever
  `description` is given. Default chosen because it follows directly from
  the settled rules (description replaces; metadata computed on the
  committing attempt) and from ADR 0009's re-apply semantics. Spec US2.8.
- **Orchestrator default, pending human:** `replace_fact` with
  `new_string == old_string` plus `aliases`/`description` changes only
  metadata. Accepted: it is still the content-write path, same conditional
  put, same token, so §5's one-lock, one-token rule holds and the API gains
  no metadata-only operation. Alternative: reject `old_string ==
  new_string` (a new public-API rule). Spec US2.9.

## Risks

- Every `TransportClient` test double needs the new parameters for pyright;
  mechanical but wide.
- `write_file` check precedence shifts for one multi-error combination.

## Adversarial review

Round 1 (FAIL, 0 BLOCKING, 4 SHOULD-FIX, 5 NIT). Caught:
- Transport docstring would have extended error parity to wrongly typed
  arguments, contradicting ADR 0019 decision 7; now only the newline
  `ValueError` is added and `TypeError` checks are type-only per ADR 0023.
- Docstring phrase pins could break on line wrapping; plan now fixes the
  exact lines and the tests normalize whitespace.
- Two unstated behaviors (stale-token description overwrite; no-op
  `replace_fact` as metadata-only change) now recorded as orchestrator
  defaults pending human (US2.8, US2.9) and in ADR 0024.
- NITs fixed: conformance fixtures and byte budget specified; glossary
  update made definite; end-to-end criterion added (US4.15); forwarding
  table change and separate keyword-identity test called out.

Round 2 (PASS, 0 BLOCKING, 0 SHOULD-FIX, 3 NIT). NITs fixed: plan Files
glossary parenthetical dropped; US7.1 now lists the US2.8/US2.9 defaults and
the type-only `TypeError` conformance approach for ADR 0024; US4 rows
reordered.
