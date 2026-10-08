"""Overview of the memory tools and how memory is addressed."""

from typing import Final

HEADING: Final[str] = "Memory"
BODY: Final[str] = """\
Memory is short markdown files that outlast this conversation, each addressed by a scope, an
area in that scope, and a name. Call `get_memory_index()` at the start of every session, before
you answer from memory or write to it. When a subject outgrows its file's size limit, split it
into narrower files.
"""
