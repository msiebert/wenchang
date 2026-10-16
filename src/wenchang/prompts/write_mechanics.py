"""Guidance on choosing the right write tool."""

from typing import Final

HEADING: Final[str] = "Choosing a write tool"
BODY: Final[str] = """\
Match the write to the change. Use `append_line` to add one fact to an existing file and
`replace_fact` to change one fact, quoting the existing line as `old_string` so surrounding lines
stay intact; this makes it mechanically impossible to disturb lines you were not editing. To change
or correct a fact stored in a file you can write, use `replace_fact` even when you have read the
whole file; never rewrite the file with `write_file` to change a fact. The `new_string` of a
changed fact states only the current fact, with no "previously" or "instead of" clause, and leaves
no note of the old value. Use `write_file` only for creating a file, restructuring many lines,
dropping a name from `aliases`, or rewriting the `description` with no fact to write. To drop one
fact line, call `replace_fact` with an empty `new_string` and the whole line as `old_string`,
including the line break after it (or before it, if none follows), so no blank line remains. Use
`delete_file` only when the whole file goes.
"""
