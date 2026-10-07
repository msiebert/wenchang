"""Guidance on where a remembered fact is filed."""

from typing import Final

HEADING: Final[str] = "Filing"
BODY: Final[str] = """\
File each fact in the file that is about its subject, not whichever file happens to be open. Seed
areas are a starting shape; create files and areas as subjects need them.

Before creating a file, check the index's descriptions and aliases for one on the subject. If none
matches and the target area is listed under `capped`, call `list_prefix(scope, area)` for that area
only and check it the same way. If a match is ambiguous, read the top one or two candidates with
`read_file`, never the whole store. If one exists, append to it or edit it instead of creating a
duplicate.

Descriptions and aliases are the entire search surface; there is no content search. On the same
write that records a fact, pass in `aliases` any new names the subject will be looked up by
(nicknames, acronyms, phrasings people use), and pass a new `description` if the fact changes what
it should say, so each write makes the next match more likely.
"""
