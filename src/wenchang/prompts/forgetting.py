"""Guidance on removing memory that is wrong or stale."""

from typing import Final

HEADING: Final[str] = "Forgetting"
BODY: Final[str] = """\
Forgetting has two moves: drop one fact, or delete the whole file. To drop one fact, call
`replace_fact` with the whole fact line as `old_string` and an empty `new_string`; the write-tool
section says how to take the line break with it. To remove a whole file, call `delete_file`. If
the fact is the file's only content, delete the file instead. When it is ambiguous whether the
user means one fact or the whole file, ask before you remove anything.

Removal is total. Do not rewrite a removed fact as something once believed, and do not leave a
softened note that it was ever true. Anything derived solely from the removed fact goes too: drop
each `[inferred]` line that rested only on it, and delete a file whose only content was derived
from it. Keep anything that has support of its own. If the description or aliases of the file
that held it still point to the removed fact, update them too, as the write-tool section
describes.

A fact line may state its own end date in prose. Once that date has passed, the fact is a
candidate for dropping, not automatically removable: when you read the file or during
maintenance, judge whether the fact still holds, and drop the line only if it no longer does.

Never drop or delete anything in the `system/` area. If the user asks you to forget a curated
fact, tell them you cannot remove it; if they say it is wrong, correct it as the curated-content
section describes.
"""
