# Eval report: AIE-1384 index tool name

- Date: 2026-11-13
- Subject: Sonnet 5.5 via `--model sonnet`, 3 trials per scenario
- Panel: 10 scenarios (see [ADR 0049](../../docs/adr/0049-index-tool-name-experiment.md))
- Agent prompt off, no judge
- Run dirs: `evals/runs/aie1384-<name>`. Runs are local and gitignored.

## Compare output

# Eval arm comparison

Baseline: aie1384-get_memory_index. Rates are percent (passes/total); other rows show the change in points.

| Run | Index tool | Agent prompt | Model | Trials | Sessions | First call is index | No memory call | Index read first | Labeled fact lines | Assertions | Judge |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| aie1384-get_memory_index | get_memory_index | off | sonnet | 3 | 33 | 87.9% (29/33) | 12.1% (4/33) | 100.0% (30/30) | 100.0% (22/22) | 83.0% (112/135) | n/a |
| aie1384-load_memory | load_memory | off | sonnet | 3 | 33 | 84.8% (28/33) -3.0 | 15.2% (5/33) +3.0 | 100.0% (30/30) +0.0 | 100.0% (22/22) +0.0 | 85.9% (116/135) +3.0 | n/a |
| aie1384-get_memory_rules_and_index | get_memory_rules_and_index | off | sonnet | 3 | 33 | 81.8% (27/33) -6.1 | 18.2% (6/33) +6.1 | 100.0% (30/30) +0.0 | 100.0% (20/20) +0.0 | 83.7% (113/135) +0.7 | n/a |
| aie1384-start_memory_session | start_memory_session | off | sonnet | 3 | 33 | 84.8% (28/33) -3.0 | 15.2% (5/33) +3.0 | 100.0% (30/30) +0.0 | 100.0% (22/22) +0.0 | 85.2% (115/135) +2.2 | n/a |
| aie1384-get_memory_entrypoint | get_memory_entrypoint | off | sonnet | 3 | 33 | 81.8% (27/33) -6.1 | 18.2% (6/33) +6.1 | 100.0% (30/30) +0.0 | 100.0% (22/22) +0.0 | 84.4% (114/135) +1.5 | n/a |

## Reading

- No candidate meets the rule. Every candidate's call-first rate is 3 to 6
  points below baseline (the rule needed +15).
- Label rate is 100% everywhere. Pass rates are within +0.7 to +3.0 of
  baseline.
- The differences are 1 to 2 sessions out of 33, within noise.
- In every arm, `index_read_first` passed 30/30: whenever the model made a
  memory call, the index tool came first.
- All call-first misses are sessions with no memory call at all (4 to 6 of
  33), for example scenarios where not touching memory may be correct
  (`privacy-account-number`). The name cannot move those.
- Caveat: the subject was a Claude Code subagent. Claude Desktop and claude.ai
  may behave differently.
- Side observation: in headless `dontAsk` runs, Agent results arrived wrapped
  in a "[Subagent hand-back]" frame. The reply inside was verbatim, and the
  harness reads replies from the transcript, so the recorded replies are
  valid.

## Decision

Keep `get_memory_index`. No rename, and no follow-up rename issue.
