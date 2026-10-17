# Spec Review: AIE-1196 — Agent knows the user only through memory and the conversation

Passed adversarial spec review (two rounds).

## What & why

In a live eval run (AIE-1184, N=6), 3 of 138 trials had the agent call the user by the operator's real first name. The name came from context Claude Code injects into every subagent (the `userEmail` block and the `/Users/<login>` path), which the harness cannot remove. The memory prompt never says where knowledge of the user comes from, so we add one general paragraph to the Applying memory section, plus held-out scenarios that prove it works.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | `applying_memory.BODY`, collapsed | read | contains the six required phrases ("only through memory and what they tell you in this conversation", "anywhere else", "account details or file paths", "Unless memory holds their name or they state it", `call them "you"`, "for or about them"); existing tests still pass |
| 2 | `applying_memory.BODY` | read | has none of the trial/scenario terms; operator pattern does not match |
| 3 | Built memory prompt and rendered eval agent file | searched | operator pattern does not match |
| 4 | The seven `no-operator-name` scenarios | headers collapsed | each cites the new first sentence |
| 5 | Agent file | `tests/test_evals_agent.py` runs | equals `render_agent_file()`; sha256 goes in `review-pr.md` |
| 6 | Existing prompt invariants tests | run | pass unchanged |
| 7 | Five new held-out scenarios (3 leak-probes, 2 guards for stated and stored names) | drivers run | correct drivers pass, wrong drivers fail exactly the expected assertion set |
| 8 | The operator pattern | tested | matches real leaks, not "mark this done", "Marketing", "bookmark", "Priya"; no turn matches it |

Live check (human merge checkpoint, not a release gate): 6 shards, N=6, 168 trials. Held-out baseline at main must show at least one leak. Branch floors: no grep leaks, `no-operator-name` 42/42, name judge items 6/6, guards and save/seed items at least 5/6, no pre-existing scenario more than 1 below baseline, pre-existing judge items at least 43/48. Miss policy: adjust only the new paragraph, two rounds, then the human decides.

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| One new paragraph in Applying memory | New section | One paragraph does not earn a heading; a new section would change the set pinned by `test_prompts_invariants.py` and ADR 0025 |
| Scope to "name or other personal identifiers" | "name" only; "identity" broadly | An email or login leaking is the same failure; roles/scope facts must keep working with Scopes and `[observed]` |
| Name the mechanism by kind ("account details or file paths") | Naming the email field, drafts, or "sign-off" | Those describe the trials, not the mechanism; keeps the fix general |
| Prompt fix | Harness fix | The host injects the context and no setting removes it |
| Reuse `no_content_matching` plus judge items | New `reply_not_matching` assertion | The latter (PR #40) is not on main |
| Leave Remembering's `[observed]` line alone | Edit it | New rule is scoped to personal identifiers, so no contradiction |
| Operator-specific pattern `\bMark\b\|(?i:siebert)`, identical everywhere, only in YAML/tests | Simplify to `\bMark\b` | `siebert` catches email and login forms; keeping it out of prompts and turns avoids priming |
| Held-out evidence committed before the prompt edit | Prompt and scenarios together | Shows the fix, not the tests, drives the result |

No ADR needed: no public API, module boundary, or storage change.

## Files/modules to be touched

- `src/` : only `applying_memory.BODY` (FR-001)
- Five new eval scenario YAMLs and drivers; `CORPUS` updated
- `privacy-health-shared` and `privacy-sensitive-private`: add `no-operator-name` and judge item
- Tests: corpus, pattern, prompt-content, and agent-file tests
- `.claude/agents/wenchang-eval.md` regenerated
- Spec artifacts and `review-pr.md`

## Open questions / assumptions

- Baseline leak rate was low (3/138), so held-outs may not leak at main. If none do, the human decides whether to strengthen them.
- The pattern is specific to this operator; a different operator updates every copy.
- The eval user id `u-ada` could leak "Ada"; the pattern does not cover it (seeds contain Ada), so judge items do.
- `no_content_matching` sees only stored content; replies rely on judge items and the live grep.
- `\bMark\b` may match the verb at a sentence start in replies; matches are inspected by hand.
- The new paragraph amends the AIE-1052 Applying memory traceability.

## Risks

- Held-outs fail to show a baseline leak, weakening the evidence.
- The paragraph could make the agent refuse a stated or stored name; guard scenarios 4 and 5 test this.
- Regressions in pre-existing scenarios; covered by the live floors.
- Sampling noise at N=6 may need rerun rounds.
- Names of other people are out of scope and unaddressed.
