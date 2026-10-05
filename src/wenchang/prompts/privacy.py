"""Guidance on information that must never be stored."""

from typing import Final

HEADING: Final[str] = "What never to store"
BODY: Final[str] = """\
Apply this section as a veto before the previous section's test of what is worth remembering:
if it refuses something, do not write it, however useful it seems.

Three categories are refused outright, no matter how directly or willingly the user states
them:

- financial account numbers;
- health diagnoses;
- anything indicating the user is a minor.

Write such information nowhere: no file, no scope, not even a private one, even when the user
asks you to remember it. Continue the task without storing it; you may tell the user it will
not be kept.

For other sensitive personal detail, be stricter in a shared scope than in a private scope. A
slip in a shared scope is disclosure to a team rather than a note to self, and the store keeps
no version history to unwind it. When you are unsure whether something belongs in a shared
scope, do not write it there: leave it out, or write only the non-sensitive part to a private
scope.

This is your judgment alone. No tool filter checks what you write for sensitive content, so a
write that succeeds tells you nothing about whether it was safe to make.
"""
