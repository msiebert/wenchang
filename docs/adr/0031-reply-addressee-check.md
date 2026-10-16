# 0031. Reply addressee check

Date: 2026-10-16

## Status

Accepted. The preamble part depends on the measurement under Consequences.

## Context

The eval agent is a Claude Code subagent. Claude Code frames a subagent's
output as a report to its parent, and the ADR 0028 preamble ("reply to them
directly") does not always win. In the two N=3 baseline runs (9c51a50 and
a0b1e23, agent sha256 `b668ca85...`), three trials passed every
deterministic assertion but failed a judge item. Their turn 1 reply talked
about the user in the third person ("The user said...").

AIE-1184 asked for a deterministic assertion kind or a judge rubric line
that flags such replies. The report could then separate "wrong answer" from
"right answer, wrong addressee". It also asked for a stronger but still
honest preamble, to be kept only if a measurement showed it helps.

## Decision

1. **Run a harness-wide reply check, not an assertion kind or judge rule.**
   `evals.graders.find_third_person_replies(scenario, transcript)` scans
   every recorded reply. It is pure and imports no `mcp`.
   - It ignores quoted text: fenced code blocks, `>` lines, and `"..."`,
     `“...”`, and `` `...` `` spans on one line.
   - It matches `the user` and `the caller`.
     - Any whitespace run (newlines and NBSP included) may separate the
       words.
     - An optional possessive `'s`, `’s`, or `ʼs` may follow.
     - "the user scope", "the user's scope", "the user-scope", "the
       user—scope", and "the users" do not match.
   - It skips a match that echoes the context. The context is the
     session's user text up to that turn, plus every seed file's content,
     description, and aliases.
     - A phrase with a next word (the match plus that word, normalized)
       must appear at word boundaries. A reply that echoes "Signup means the
       user has verified" is therefore not flagged.
     - A bare match must appear with the same following character, or end
       a context text when it ends the reply. A seed's "the user submits"
       therefore does not exempt "I'll check with the user."
   - It reports at most one flag per reply.

   An assertion kind was rejected for three reasons:
   - `grade(scenario, store, trace)` excludes the transcript (ADR 0028 §3).
   - It would count toward deterministic pass/fail, failing 16 of the 138
     baseline trials.
   - It is opt-in per scenario.

   A judge rule was rejected because it is LLM-graded, it runs only with
   `--judge`, and it would break comparability with the baseline judge
   counts.

2. **The check is a separate signal and never fails anything.**
   - `grade.json` gains `third_person_replies` (a list of `{session, turn,
     phrase}`) when `transcript.json` exists.
   - A malformed, undecodable, or too-deeply-nested transcript gives
     `transcript_error` instead and never blocks deterministic grading.
   - If `transcript.json` is deleted after a check was recorded, the check
     is dropped and the trial counts as unchecked.
   - `results` and `passed` are unchanged.
   - A `grade.json` that is current for the store and trace, but lacks the
     check or is older than the transcript, gets only the check recomputed.
     Its results are kept, so old runs pick up the check without being
     silently regraded.
   - The report adds, per scenario, `third_person_trials`,
     `addressee_unchecked_trials`, and `judge_third_person_fails`, and a
     run-level `third_person` total. The markdown judge table gains a
     "Fails with a third-person reply" column. That count is co-occurrence,
     not cause.
   - An SDK driver that writes `transcript.json` gets the check with no
     extra work.

3. **The preamble is tightened, honestly.** The second sentence becomes:
   "Your reply goes to that user word for word, so in your reply address
   them as "you" and never call them "the user"." The issue's suggested
   "nobody else reads it" was rejected as false, because the runner, the
   later-turn replay, and the judge all read the reply. The rule is scoped
   to the reply so that it does not reach stored fact lines.

## Consequences

- **Calibration.** The shipped check flags 7 of 69 trials in run A and 9
  of 69 in run B, 16 of 138 in all. That includes all 3 judge failures, and
  manual review found no false positives. Re-reporting copies of the
  baseline dirs left their deterministic results unchanged.
- **Gate for the preamble.** It is human-run, over two N=3 `--judge` runs
  at the AIE-1184 head, on the 23 baseline scenario ids only. The preamble
  stays if all three hold:
  - flagged trials are at most floor(16/2) = 8;
  - no scenario's combined deterministic trials-passed is more than 1
    below baseline;
  - summed judge passes are no lower than baseline.

  Otherwise the preamble, the rendered agent file, and its pin test revert
  and the check lands alone. Measure before AIE-1182 or AIE-1183 land, and
  merge AIE-1184 first. One known confound: the baseline predates
  5bd1355's `model=` rule.
- **Outcome: PENDING.** The measured counts go here and in
  `specs/AIE-1184-eval-reply-addressee/review-pr.md`.
- **Limits.**
  - The pattern misses phrasings like "they asked me to", so the count is
    a lower bound.
  - Future analytics scenarios may add noisy hits, such as "where the user
    drops off", "the user ID", "the user property", or "the user profile".
    "user-facing" is never a match, because it has no "the". The check
    never fails a trial, so the noise stays in the count.
  - Two quoting forms are not stripped:
    - a fence opened and closed on one line, such as ```` ```the user``` ````;
    - straight-quote inch marks (`5" wide ... "the user`), which can pair
      with the wrong quote and hide or expose text.
