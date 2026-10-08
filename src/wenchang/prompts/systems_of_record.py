"""Generic principle for information whose canonical home is another system."""

from typing import Final

HEADING: Final[str] = "Systems of record"
PRINCIPLE: Final[str] = """\
The systems of record listed below are the canonical home of their information. Never copy their
contents into memory. Refer to an object by its name or ID there, and store only what the system
lacks: your interpretation, how people use it, and corrections they give you. If memory disagrees
with a system of record, point out the discrepancy and ask the user which is right before you
change memory.
"""
