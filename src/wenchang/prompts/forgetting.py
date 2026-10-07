"""Guidance on removing memory that is wrong or stale."""

from typing import Final

HEADING: Final[str] = "Forgetting"
BODY: Final[str] = """\
Forgetting has two moves: drop one fact's line, or delete the whole file. Delete the file if the
fact was the file's only fact or the user means the whole file; if it is ambiguous which they mean,
ask before removing anything.

Removal is total: leave no note that the fact was ever true. Also drop each `[inferred]` line that
rested solely on it, delete any file derived solely from it, and remove description text or aliases
that exist only because of it. Keep anything with support of its own.

A fact whose stated end date has passed is a candidate for dropping, not automatically removed: when
you read it or during maintenance, drop it only if it no longer holds.

Never drop or delete anything in `system/`. If asked to forget a curated fact, say you cannot; if
the user says it is wrong, correct it as the curated-content section describes.
"""
