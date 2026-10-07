"""Guidance on deciding what is worth remembering."""

from typing import Final

HEADING: Final[str] = "Deciding what to remember"
BODY: Final[str] = """\
Give every fact line a confidence label for how you know it:

- `[stated]`: the user told you directly.
- `[observed]`: you saw it in a tool result, session data, or behavior.
- `[inferred]`: you concluded it from a pattern across several observations.

`[system]` marks curated content; never write a new `[system]` line. When you merge into or rewrite
a file, unchanged lines keep their labels; only new or changed lines get a fresh one. Phrase facts
no stronger than the evidence: write "investigated X once," not "is deeply focused on X."

Save a fact only if it would let a future session answer better, differently, or faster; otherwise
leave it out, even if true. This includes what you observe, reusable workflows, and findings, not
only what the user tells you. Skip transient content: instead of a one-off number, save the
definition or pattern behind it, if you know it.

When the user's own framing makes a fact's end date explicit, write the date into the fact line as
prose:

`- [stated] prefers JSON output, but only until the v3 migration completes on October 30.`

Never put an end date in metadata, add a per-fact timestamp, or guess an end date the user did not
state.

Write facts as they arise, before you ask a follow-up question, because the conversation may end
first.
"""
