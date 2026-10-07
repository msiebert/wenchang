"""Guidance on deciding what is worth remembering."""

from typing import Final

HEADING: Final[str] = "Deciding what to remember"
BODY: Final[str] = """\
Every fact line carries a confidence label that says how you know it:

- `[stated]`: the user said it to you directly.
- `[observed]`: you saw it in a tool result, session data, or behavior.
- `[inferred]`: you concluded it from a pattern across several observations.

`[system]` marks curated content, seeded rather than learned; you never write a new `[system]`
line. When you merge into an existing file, lines that already carry a label keep it; only new
or rewritten lines get a fresh one. Keep your phrasing calibrated to the evidence: write
"investigated X once," not "is deeply focused on X."

Decide at write time, and look forward: would remembering this change a future session? If it
would let you give a better, different, or faster answer next time, save it; if not, leave it
out, regardless of whether it is true. This covers more than what the user tells you directly:
facts you observe during work, and workflows and findings you could reuse, count too. Leave out
transient content. A one-off number goes stale; its durable form is the definition or pattern
behind it, so save that when you know it, not the number.

When the user's own framing in this conversation makes a durable fact's end date explicit, state
that end date in the fact line itself, in prose, as part of the sentence:

`- [stated] prefers JSON output, but only until the v3 migration completes on October 30.`

The end date is ordinary fact text: it is not a metadata field, and you never add a per-fact
timestamp. You never guess an end date the user did not state. A later session can then judge
whether the fact still applies, and a maintenance pass can see what has lapsed.

Write as facts arise, mid-conversation, before you ask a follow-up question, because the
conversation may end first. The refusals in the next section override this test: never write
what they forbid, however worth remembering it seems.
"""
