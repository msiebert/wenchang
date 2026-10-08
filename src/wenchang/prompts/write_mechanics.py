"""Guidance on choosing the right write tool."""

from typing import Final

HEADING: Final[str] = "Choosing a write tool"
BODY: Final[str] = """\
Match the write to the change. Use `append_line` to add one fact to an existing file and
`replace_fact` to change one fact, quoting the existing line as `old_string` so surrounding lines
stay intact; this makes it mechanically impossible to disturb lines you were not editing. Use
`write_file` only for creating a file, restructuring many lines, dropping a name from `aliases`, or
rewriting the `description` with no fact to write. To drop one fact line, call `replace_fact` with
an empty `new_string` and the whole line as `old_string`, including the line break after it (or
before it, if none follows), so no blank line remains. Use `delete_file` only when the whole file
goes.
"""
