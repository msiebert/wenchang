"""Guidance on where a remembered fact is filed."""

from typing import Final

HEADING: Final[str] = "Filing"
BODY: Final[str] = """\
Put each fact in the file that is about its subject, not in whichever file happens to be open
from earlier in the session. The seed areas are a starting shape: create new files and areas as
subjects need them.

Before you create a new file, check whether one already exists on the subject. Scan the
descriptions and aliases in the index you loaded with `get_memory_index()`. If nothing there
matches and the area you would file into is listed under `capped` in the index, call
`list_prefix(scope, area)` for that one area only and check its entries the same way. When a
match is ambiguous, read the top one or two candidates with `read_file` to confirm, never the
whole store. If a file on the subject exists, append to it or edit it instead of creating a
duplicate. This check runs only when you create a file; appending to a file you already know
does not trigger it.

Every write should carry any new names the subject will later be looked up by: nicknames,
acronyms, and the phrasings people use for it. Pass them as `aliases` on the same write that
records the fact. Descriptions and aliases are the entire search surface: there is no content
search, so a later mention finds a file only through them, and each write should make the next
match more likely.
"""
