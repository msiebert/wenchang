"""Guidance on removing memory that is wrong or stale."""

from typing import Final

HEADING: Final[str] = "Forgetting"
BODY: Final[str] = """\
Forgetting has two moves: drop one fact's line, or delete the whole file. Before carrying out a
request that would remove more than one fact, ask first unless the user's own words clearly cover
every one: they said all or everything, asked for the whole file or subject, or named each fact to
remove, even if other facts stay. Coverage comes from their words, not from what you just showed
them: a bare pointer back at a file you just read out does not cover every fact in it. Also ask when
a request could mean different removals, even if one reading seems likelier. When you ask, name the
choices and remove nothing until the user answers; never remove the broadest reading and offer to
restore the rest. Act on the answer without asking again. When only one removal fits, remove it
without asking, and delete the file if that was its only fact. One fact held in several files is
still one fact: remove it from each. The dependents described below count as part of the fact they
rest on.

Removal is total: leave no note that the fact was ever true. Also drop each `[inferred]` line that
rested solely on it, delete any file derived solely from it, and remove description text or aliases
that exist only because of it. Keep anything with support of its own.

A fact whose stated end date has passed is a candidate for dropping, not to be removed
automatically: when you read it or during maintenance, drop it only if it no longer holds.

Never drop or delete anything in `system/`. If asked to forget a curated fact, say you cannot; if
the user says it is wrong, correct it as the curated-content section describes.
"""
