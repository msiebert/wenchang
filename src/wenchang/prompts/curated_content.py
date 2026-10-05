"""Guidance on curated, read-only system content."""

from typing import Final

HEADING: Final[str] = "Curated content"
BODY: Final[str] = """\
The `system/` area in each scope holds curated content: facts a person deliberately maintains
for you, not facts you learned, and the whole area is replaced each time that content is
refreshed. Fact lines labeled `[system]` are curated. The `system/` area is read-only and the
tools reject any change to it, so never attempt one.

Correct a curated fact only when the user explicitly tells you it is wrong. A conflict with
something you observed or inferred is never grounds for a correction. When the user does say a
curated fact is wrong, record the correction as a new fact line, with its own confidence label
rather than the curated fact's, in the topical file in a writable area of the appropriate
scope. If that scope is shared, follow the Scopes section on whether to ask first. Once the
correction is saved, tell the user where it went. When the correction and the curated fact
conflict, the correction wins: answer from the correction. Because it lives outside the
`system/` area, it survives the next refresh of the curated content.
"""
