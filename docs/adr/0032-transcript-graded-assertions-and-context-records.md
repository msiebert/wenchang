# 0032. Transcript-graded assertions and context records

Date: 2026-10-16

## Status

Accepted. Amends [ADR 0028](0028-behavioral-eval-harness.md) decisions 3
and 7. Builds on [ADR 0031](0031-reply-addressee-check.md).

## Context

AIE-1170 deferred ten scenarios. Porting them hit two gaps:

- Three of them (the AIE-1052 cases on what the agent says, not what it
  writes) need a deterministic check on the reply. The judge cannot supply
  it, because judge verdicts never count toward deterministic passes, so a
  wrong scripted driver could not fail on what it said.
- Three need facts the agent would normally get from a lookup tool: an event
  catalog entry, a query history, a delivery log. The eval agent has only the
  seven memory tools.

## Decision

1. **Replies are graded deterministically.** This amends ADR 0028 decision
   3. Graders are pure functions of (scenario, store dump, trace,
   transcript), and `transcript.json` is a grading input. `grade` takes the
   transcript as an optional fourth parameter, so existing callers are
   unchanged. `evals.scenario` and `evals.graders` still never import `mcp`.
   - `reply_matching {pattern, session?, turn?}` passes when some selected
     turn's reply matches the pattern (`re.search`).
   - `reply_not_matching {pattern, session?, turn?}` passes when at least one
     turn is selected and no selected reply matches.
   - Both fail with "no reply recorded" when no recorded turn matches the
     filter, so a missing reply fails, as it does for the judge.
   - A malformed `transcript.json` is recorded as `transcript_error` (as in
     ADR 0031) and graded as an empty transcript. Reply kinds then fail with
     "no reply recorded", other kinds grade normally, and nothing raises.
   - The closed set is now thirteen kinds.

2. **Verbatim copying now matters for results.** This amends ADR 0028
   decision 7. A paraphrased reply used to affect only the judge. It now
   also affects `reply_matching` and `reply_not_matching`. The live gate
   therefore includes a per-shard spot-check that the recorded reply matches
   the subagent's actual reply.

3. **Freshness.** For a scenario that uses a reply kind, `transcript.json`
   joins the set of files whose mtime is compared with `grade.json`. A newer
   transcript triggers a full regrade, because the reply kinds feed
   `results`. For every other scenario, ADR 0031's rule is unchanged: a newer
   transcript recomputes only the reply check and keeps stored results.

4. **`context_records` stands in for lookup tools.** A scenario may carry
   `context_records: [{system, content}]`. `turn-prompt` renders each record
   above every turn as a block, `[From the product's <system>]`, a newline,
   then the content. It is a fidelity proxy: a real host would show these
   through tool results, and here they arrive in the user message.
   - The field is named `context_records`, not `systems_of_record`, which
     would collide with the `PromptSlots.systems_of_record` slot. It does not
     touch that slot.
   - Without records, `turn-prompt` output is byte-identical to before.
   - The runner passes the output to the `Agent` call unchanged, and
     `eval_record_turn` still receives the scenario's turn text alone.
   - Rejected: a memory seed (contradicts "never copy their contents into
     memory"); the user quoting the record (the user would surface the
     discrepancy the agent is meant to find); a per-scenario agent file (the
     agent file is fixed per run and its sha256 is recorded); and an
     observation described by the user (it would become a statement, not
     session data).

5. **Corpus and ordering.** The corpus is 33 scenarios, the 23 from
   AIE-1170 plus the ten ported here, with a new `applying` category. This
   change merges after AIE-1184, whose transcript loading and
   `_grade_is_current` changes it builds on.

## Consequences

- Deterministic results now depend on the runner copying replies verbatim.
  The live gate checks it.
- **Live gate.** Merge waits on a live N=3 run with `--judge` of the ten new
  scenarios, run in two shards and merged.
  - Each new scenario must pass all its deterministic assertions in at least
    2 of 3 trials.
  - Every failing trial is classified. A prompt finding gets a follow-up
    issue and the assertion stays as is. A harness defect is fixed before
    merge. An assertion defect is fixed only with the human's approval. An
    assertion is never loosened to turn a prompt finding into a pass.
  - A miss on `asks-before-removing` in `forgetting-ambiguous-that` is
    registered in advance as a prompt finding.
  - A judge failure caused by a third-person reply is harness noise, not a
    prompt finding.
- Reply regexes are narrow by design. They catch the named mistake, and the
  judge covers the meaning.
- Context blocks add text to every turn of the scenarios that use them, so a
  later turn's replay sits below them.
- The 23 existing scenarios must keep their per-assertion pass counts when
  the AIE-1170 baseline runs are regraded offline with this change.
