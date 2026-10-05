"""Generic principle for information whose canonical home is another system."""

from typing import Final

HEADING: Final[str] = "Systems of record"
PRINCIPLE: Final[str] = """\
Some information already has a canonical home in the product you work in; the list below
names those systems of record. Do not copy their contents into memory. Refer to the canonical
object by the name or ID it has there, and store only what that system does not hold: your
interpretation of it, how people use it, and corrections they have given you. If memory
disagrees with the system of record, do not let the two diverge silently: point out the
discrepancy to the user and ask which is right before you change memory.
"""
