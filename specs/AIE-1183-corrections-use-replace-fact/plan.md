# Implementation Plan: A changed fact states only what is true now (AIE-1183)

**Spec**: `specs/AIE-1183-corrections-use-replace-fact/spec.md`

This change touches no public interface, docstring, grader, or assertion
kind. It ships as two commits.

## Commit 1: held-out evidence (before any prompt edit)

### 1.1 `evals/scenarios/write-correct-seeded-fact.yaml`

Append:

```yaml
  - kind: line_absent
    id: old-format-gone
    pattern: "(?i)pdf"
    scope: user
    area: preferences
    name: report-format
```

In `tests/test_evals_end_to_end.py`, the `CASES` fail set becomes
`{"replaced-quoting-old", "one-format-line", "old-format-gone"}`.

### 1.2 `evals/scenarios/write-superseded-tool.yaml`

```yaml
# Prompt: "Use `append_line` to add one fact to an existing file and
# `replace_fact` to change one fact, quoting the existing line as `old_string`
# so surrounding lines stay intact" and "Writes to user need no ask."
id: write-superseded-tool
title: Replaces a one-line fact when the user switches tools, keeping only the current tool
category: write-mechanics
source: specs/AIE-1051-write-mechanics/spec.md
seed:
  - scope: user
    area: workflows
    name: standup-notes
    content: |
      - [stated] Keeps standup notes in Notion.
    description: Where the user keeps standup notes
    aliases: [standup-notes]
sessions:
  - turns:
      - "We moved standup notes over to Confluence last week."
assertions:
  - kind: index_read_first
    id: index-first
  - kind: tool_called
    id: replaced-tool-line
    tool: replace_fact
    args: {name: standup-notes, old_string: {matches: "(?i)notion"}}
    succeeded: true
  - kind: tool_not_called
    id: no-overwrite
    tool: write_file
    args: {name: standup-notes}
  - kind: line_absent
    id: old-tool-gone
    pattern: "(?i)notion"
    scope: user
  - kind: line_present
    id: new-tool-saved
    pattern: "(?i)confluence"
    scope: user
  - kind: no_duplicate_fact
    id: one-notes-line
    pattern: "(?i)standup"
    scope: user
```

Scripted drivers:

- **Correct:** `index`, then replace the seed line with `- [stated] Keeps
  standup notes in Confluence.`, then `turn(1, 1)`.
- **Wrong:** `index`, then append that line instead. It fails exactly
  `{replaced-tool-line, old-tool-gone, one-notes-line}`.

### 1.3 `evals/scenarios/recall-superseded-definition.yaml`

```yaml
# Prompt: "Use `append_line` to add one fact to an existing file and
# `replace_fact` to change one fact" and "Writes to user need no ask."
id: recall-superseded-definition
title: Replaces an analysis definition the user changes in a later session
category: recall
source: specs/AIE-1051-write-mechanics/spec.md
sessions:
  - turns:
      - "For activation analysis I use a 7-day window."
  - turns:
      - "I've switched to a 14-day window for activation analysis."
assertions:
  - kind: index_read_first
    id: index-first
  - kind: tool_called
    id: replaced-in-session-2
    tool: replace_fact
    args: {scope: user}
    session: 2
    succeeded: true
  - kind: no_duplicate_fact
    id: one-window-line
    pattern: "(?i)activation"
    scope: user
  - kind: line_absent
    id: old-window-gone
    pattern: "(?i)\\b(7|seven)[- ]day"
    scope: user
  - kind: line_present
    id: new-window-saved
    pattern: "(?i)\\b(14|fourteen)[- ]day"
    scope: user
```

Scripted drivers:

- **Correct:**
  - Session 1: `index`, then create `user/workflows/activation-analysis`
    with `- [stated] Uses a 7-day window for activation analysis.\n` and
    description "Activation analysis settings", then `turn(1, 1)`.
  - Session 2: `index`, then replace that line with `- [stated] Uses a
    14-day window for activation analysis.`, then `turn(2, 1)`.
- **Wrong:** session 2 appends the 14-day line instead. It fails exactly
  `{replaced-in-session-2, one-window-line, old-window-gone}`.

### 1.4 `evals/scenarios/write-added-not-superseded.yaml` (over-correction guard)

```yaml
# Prompt: "Use `append_line` to add one fact to an existing file" and "Keep
# anything with support of its own."
id: write-added-not-superseded
title: Adds a second audience without dropping the existing one
category: write-mechanics
source: specs/AIE-1051-write-mechanics/spec.md
seed:
  - scope: user
    area: workflows
    name: funnel-dashboard
    content: |
      - [stated] Shares the checkout funnel dashboard with the design team.
    description: Who the user shares the checkout funnel dashboard with
    aliases: [funnel-dashboard]
sessions:
  - turns:
      - "I share the checkout funnel dashboard with the sales team too."
assertions:
  - kind: index_read_first
    id: index-first
  - kind: line_present
    id: design-kept
    pattern: "(?i)design"
    scope: user
  - kind: line_present
    id: sales-saved
    pattern: "(?i)sales"
    scope: user
  - kind: tool_not_called
    id: file-kept
    tool: delete_file
```

Scripted drivers:

- **Correct:** append `- [stated] Shares the checkout funnel dashboard with
  the sales team.`
- **Wrong:** replace the design line with the sales line. It fails exactly
  `{design-kept}`.

### 1.5 `evals/scenarios/write-superseded-kept-on-request.yaml` (over-correction guard)

In commit 1 the header cites an existing sentence. Commit 2 adds the new
exception sentence (§2.4).

```yaml
# Prompt: "Save a fact only if it would let a future session answer better,
# differently, or faster" and "Writes to user need no ask."
id: write-superseded-kept-on-request
title: Keeps a record of a replaced tool when the user asks for one
category: write-mechanics
source: specs/AIE-1051-write-mechanics/spec.md
seed:
  - scope: user
    area: workflows
    name: deploys
    content: |
      - [stated] Deploys with Jenkins.
    description: How the user deploys
    aliases: [deploys]
sessions:
  - turns:
      - "We switched deploys from Jenkins to GitHub Actions. Please keep a record that we used Jenkins before, because our old runbooks still reference it."
assertions:
  - kind: index_read_first
    id: index-first
  - kind: line_present
    id: old-tool-recorded
    pattern: "(?i)jenkins"
    scope: user
  - kind: line_present
    id: new-tool-saved
    pattern: "(?i)github actions"
    scope: user
  - kind: tool_not_called
    id: file-kept
    tool: delete_file
```

Scripted drivers:

- **Correct:** replace the line with `- [stated] Deploys with GitHub
  Actions.`, then append `- [stated] Deployed with Jenkins before GitHub
  Actions; old runbooks still reference it.`
- **Wrong:** do only the replace. It fails exactly `{old-tool-recorded}`.

### 1.6 Tests

- Add `CASES` rows for the four scenarios with the fail sets above.
- Add the four ids to `CORPUS` in `tests/test_evals_scenario.py`.

## Commit 2: prompt edit

### 2.1 `src/wenchang/prompts/forgetting.py`

Append a new paragraph after "Keep anything with support of its own.",
wrapped at 100 columns:

> When a fact changes, its old value is gone too: rewrite the line to state
> only what is true now, as though it had always read that way, with no note,
> date, or comparison recording the change. Keep an earlier value only if the
> user asks you to keep a record of it.

- **Constraints checked:** forgetting tests ban tool names and "used to",
  "formerly", and "previously believed". The new text has none of them.
- **Forward end dates are unaffected:** a forward end date describes the
  current fact, not the change.

### 2.2 `src/wenchang/prompts/write_mechanics.py`

- Remove the two sentences added earlier on this branch, restoring main's
  text.
- Insert this sentence after "...lines you were not editing.":

  > Changing one fact is still `replace_fact` when it is the file's only line
  > or when the change also updates `description` or `aliases`.

### 2.3 Tests (write first)

`tests/test_prompts_write_mechanics.py`:

- Replace the two branch tests with one test:
  `_only_sentence_containing("the file's only line")` names `replace_fact`,
  `description`, and `aliases`.
- Add an absence test for "previously", "instead of", "even when you have
  read the whole file", and "of a changed fact".

`tests/test_prompts_forgetting.py`:

- Add a parametrized phrase test for "its old value is gone", "state only
  what is true now", "recording the change", and "keep a record".

`tests/test_evals_scenario.py`:

- The header test asserts that `recall-replace-fact`'s header cites "When a
  fact changes, its old value is gone too" and "Changing one fact is still
  `replace_fact` when it is the file's only line".

### 2.4 Scenario headers

`recall-replace-fact.yaml` header:

```
# Prompt: "Use `append_line` to add one fact to an existing file and
# `replace_fact` to change one fact", "Changing one fact is still
# `replace_fact` when it is the file's only line or when the change also
# updates `description` or `aliases`", "When a fact changes, its old value is
# gone too: rewrite the line to state only what is true now", and "Writes to
# user need no ask."
```

`write-superseded-kept-on-request.yaml`: add the citation "Keep an earlier
value only if the user asks you to keep a record of it."

### 2.5 Render the agent file

Run `uv run --directory <worktree> python -m evals render-agent`, then
record the sha256 in `review-pr.md`.

## Docs

`review-pr.md` covers:

- The diagnosis.
- The final text.
- The held-outs.
- The live gate and floors (spec).
- The baseline-at-main procedure:

  ```
  git -C /Users/marksiebert/p/github/wenchang fetch origin
  git -C /Users/marksiebert/p/github/wenchang worktree add --detach /tmp/wenchang-baseline origin/main
  make -C /tmp/wenchang-baseline install
  git -C /tmp/wenchang-baseline checkout origin/AIE-1183-replace-fact-corrections -- evals/scenarios/write-superseded-tool.yaml evals/scenarios/recall-superseded-definition.yaml evals/scenarios/write-added-not-superseded.yaml evals/scenarios/write-superseded-kept-on-request.yaml evals/scenarios/write-correct-seeded-fact.yaml
  # launch the eval session from /tmp/wenchang-baseline and run:
  /run-evals --model sonnet --trials 3 --judge write-superseded-tool recall-superseded-definition write-added-not-superseded write-superseded-kept-on-request write-correct-seeded-fact
  git -C /Users/marksiebert/p/github/wenchang worktree remove --force /tmp/wenchang-baseline
  ```

  Held-outs that pass at main do not demonstrate the fix.

## Risks

- The corpus test conflicts textually with #37 and #40 at rebase. `CASES`
  conflicts with #40.
- `.claude/agents/wenchang-eval.md` must be re-rendered after the rebase.
- `curated-*` correction lines may drop their reference to the curated
  note. No assertion depends on it.

## Revision 2 (generality review)

This revision supersedes the matching parts of §1 and §2 above. The spec
is authoritative.

### Commit A: scenarios only

- **`write-superseded-tool`**
  - Turn: "I moved my standup notes to Confluence last week."
  - Add `line_absent` `no-change-date`, pattern `(?i)last week`, scope
    user.
  - Set `source:` to the AIE-1183 spec.
- **`write-superseded-kept-on-request`**
  - Turn: "I switched my deploys from Jenkins to GitHub Actions; keep a
    record that I used Jenkins before, since my old runbooks reference
    it."
  - Add `line_absent` `old-line-changed`, pattern
    `^- \[stated\] Deploys with Jenkins\.?$`, scope user.
  - Add a second wrong driver that only appends `- [stated] Deploys with
    GitHub Actions; used Jenkins before, and old runbooks still reference
    it.`. It fails exactly `{old-line-changed}`, in a separate test.
  - Set `source:` to the AIE-1183 spec.
- **`recall-superseded-definition` and `write-added-not-superseded`**
  - Set `source:` to the AIE-1183 spec.
  - Both turns are already first person.
- **New `write-superseded-shared-fact`**
  - Header:

    ```
    # Prompt: "If a new fact contradicts one stored in a shared scope, show
    # the stored fact, say what conflicts, and ask which to keep."
    ```

  - Seed `project/conventions/release-cadence` with
    `- [stated] This project ships a release every two weeks.`, description
    "How often this project ships releases", and aliases `[release-cadence]`.
  - Turn: "This project ships a release every week now."
  - Assertions:
    - `index-first`.
    - `tool_not_called` `no-shared-write-before-ask` over the four write
      tools, with args scope matching `^(project|organization)$`, session
      1, turn 1.
    - `line_present` `old-fact-kept`, pattern `(?i)every two weeks`, scope
      project.
  - Judge item `asks-which-to-keep`: "The turn 1 reply restates the stored
    release cadence (every two weeks), says it conflicts with a weekly
    release, and asks the user which to keep."
  - Correct driver: index, then the turn.
  - Wrong driver: replace the project line with a weekly line. It fails
    exactly `{no-shared-write-before-ask, old-fact-kept}`.
- **`CORPUS`:** add the new id.

### Commit B: prompt and citations

- `forgetting.py` and `write_mechanics.py`: the text in the spec "Fix"
  section.
- Pins: spec US2.1 and US2.2.
- Headers that quote the reworded `replace_fact` sentence are updated:
  - `write-correct-seeded-fact`
  - `write-superseded-tool`
- The Forgetting principle sentence is added to these headers:
  - `write-correct-seeded-fact`
  - `write-superseded-tool`
  - `recall-superseded-definition`
- `recall-replace-fact`'s header cites the new wording, and its header test
  is updated.
- Re-render the agent file and record the sha256.
