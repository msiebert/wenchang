# Spec Review: AIE-1196 — Agent knows the user only through memory and the conversation

Passed adversarial spec review; rework after review folded in below.

## What & why

In a live eval run (AIE-1184, N=6), 3 of 138 trials had the agent call the user by the operator's real first name. The name came from context Claude Code injects into every subagent (the `userEmail` block and the working-directory path), which the harness cannot remove. The memory prompt never says where knowledge of the user comes from, so we add one general paragraph to the Applying memory section, held-out scenarios that exercise it, and a harness-level operator-identity check that resolves the operator at grade time, so no real name is stored in the repo.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `applying_memory.BODY`, collapsed | read | contains the required phrases ("only through memory and what they tell you in this conversation", "anywhere else", "account details or file paths", "Unless memory holds their name or they state it", `call them "you"`, "for or about them"); existing tests still pass |
| 2 | `applying_memory.BODY` | read | has none of the trial/scenario terms; the identity check (fake identity) finds no hit |
| 3 | Built memory prompt and rendered eval agent file | searched | the identity check finds no hit |
| 4 | The seven identity-judged scenarios | headers collapsed | each cites the new first sentence |
| 5 | Agent file | `tests/test_evals_agent.py` runs | equals `render_agent_file()`; sha256 goes in `review-pr.md` |
| 6 | Existing prompt invariants tests | run | pass unchanged |
| 7 | Five new held-out scenarios (3 leak-probes, 2 guards for stated and stored names) | drivers run | correct drivers pass, wrong drivers fail exactly the expected set (`operator-identity` means the check flagged the trial) |
| 8 | A fake identity (Grace Hopper) | the check runs | first name matches Title-case and ALL-CAPS only; last name, email pieces and logins match case-insensitively; common words, short tokens and generic accounts are skipped; the verb rule, scenario-context exemption and eval identity ids prevent false hits |
| 9 | A hit | recorded | carries location and token kind only, never the matched text; a path containing a token is `<redacted>`; `results` is untouched |
| 10 | Missing transcript | graded | `replies_scanned: false`; store and write scan still runs |
| 11 | `build_report` | re-reports a run | recomputes the check and `passed` only on change; no resolvable identity keeps recorded hits |
| 12 | Every shipped scenario | correct driver plus a leaked stored line, and separately a leaked reply | trial fails via the check |

Historical check (offline, `cp -Rp` copies): `aie1184-n6` flags exactly the 3 known trials; counts for the other three runs go in `review-pr.md`.

Live check (human merge checkpoint, not a release gate): 6 shards, N=6, 53 scenarios, 318 trials. Held-out baseline at main must show at least one leak. Branch floors: 0 flagged trials, `sources` includes git `user.name` and every trial has replies scanned, name judge items 6/6, guards and save/seed items at least 5/6, no pre-existing scenario more than 1 below its re-reported baseline (explicit exceptions list), pre-existing judge items at least 43/48. Miss policy: adjust only the new paragraph, two rounds, then the human decides.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| One new paragraph in Applying memory | New section | One paragraph does not earn a heading; a new section would change the set pinned by `test_prompts_invariants.py` and ADR 0025 |
| Scope to "name or other personal identifiers" | "name" only; "identity" broadly | An email or login leaking is the same failure; roles/scope facts must keep working with Scopes and `[observed]` |
| Name the mechanism by kind ("account details or file paths") | Naming the email field, drafts, or "sign-off" | Those describe the trials, not the mechanism; keeps the fix general |
| Prompt fix | Harness fix | The host injects the context and no setting removes it |
| Harness-level operator-identity check, run on every trial, resolved at grade time from git config, `$USER`, home | Per-scenario assertion kind; hard-coded pattern | Identity is an input of the environment, not the scenario; corpus-wide and retroactive coverage; no real name in the repo; works for any operator |
| Check counts toward `passed` but not `results` | Report-only (like ADR 0031) | A hit is a real privacy failure; per-assertion counts stay comparable |
| Case-sensitive Title-case/ALL-CAPS first name plus verb rule, context exemption, common-word skip | Case-insensitive match | Avoids false hits on verbs and English-word names; lowercase is never matched |
| Leave Remembering's `[observed]` line alone | Edit it | New rule is scoped to personal identifiers, so no contradiction |
| Held-out evidence committed before the prompt edit | Prompt and scenarios together | Shows the fix, not the tests, drives the result |

ADR 0034 (operator-identity check) is added, cross-referencing ADR 0028 and 0031, and ARCHITECTURE.md's `evals.graders` and `evals.report` bullets are updated, in the same commit as the code.

## Files/modules to be touched

- `src/`: only `applying_memory.BODY` (FR-001)
- `evals/` grader, runner and report modules: resolver, pure check, grade and report fields
- Five new eval scenario YAMLs and drivers; `CORPUS` updated; `no-operator-name` removed from the seven YAMLs that had it
- `privacy-health-shared` and `privacy-sensitive-private`: add the `no-unstated-name` judge item
- Tests: hermetic identity fixture, resolver, grader, report, corpus, prompt-content and agent-file tests; the old pattern tests are deleted
- `.claude/agents/wenchang-eval.md` regenerated
- ADR 0034, ARCHITECTURE.md, spec artifacts; `review-pr.md` is regenerated and scrubbed at PR time

## Open questions / assumptions

- Baseline leak rate was low (3/138), so held-outs may not leak at main. If none do, the human decides whether to strengthen them.
- `passed` depends on who re-reports, so pass counts compare only when re-reported by the same operator (documented in ADR 0034).
- A title-case heading equal to the operator's first name can flag (known limit).
- The eval user id `u-ada` is part of scenario context, so "Ada" is not an identity token; judge items fail any name the user did not give.
- Baseline runs are gitignored and must not be cleaned up before merge.
- The new paragraph amends the AIE-1052 Applying memory traceability.

## Risks

- Held-outs fail to show a baseline leak, weakening the evidence.
- The paragraph could make the agent refuse a stated or stored name; guard scenarios 4 and 5 test this.
- Regressions in pre-existing scenarios; covered by the live floors.
- Sampling noise at N=6 may need rerun rounds.
- A run on a machine with no resolvable identity is unchecked; the live floor requires git `user.name` in `sources`.
- Names of other people are out of scope and unaddressed.
