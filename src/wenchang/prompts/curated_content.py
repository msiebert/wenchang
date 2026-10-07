"""Guidance on curated, read-only system content."""

from typing import Final

HEADING: Final[str] = "Curated content"
BODY: Final[str] = """\
The `system/` area holds curated content that a person maintains and replaces wholesale on each
refresh. It is read-only; never attempt to change it.

Correct a curated fact only when the user explicitly says it is wrong, never because of something
you observed or inferred. Record the correction as a new fact line, with its own label, in the
topical file of a writable area; in a shared scope, follow the Scopes section on asking first.
Then tell the user where you saved it, and answer from the correction from then on. Because it
lives outside `system/`, it survives refreshes.
"""
