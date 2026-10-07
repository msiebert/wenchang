"""Guidance on choosing the right write tool."""

from typing import Final

HEADING: Final[str] = "Choosing a write tool"
BODY: Final[str] = """\
Match the write to the change. To add one fact to an existing file, use `append_line`. To
change one fact, use `replace_fact` and quote the existing line as `old_string`, with its new
form as `new_string`, so only that fact changes and the surrounding lines stay intact. Reserve
`write_file` for creating a new file or restructuring many lines. Writing this way makes it
mechanically impossible to disturb lines you were not editing.

When a write introduces a new name for the subject, pass that name in `aliases` on the same
call: `append_line`, `replace_fact`, or the `write_file` that creates or restructures the file.
When a fact changes what the file's one-line `description` should say, pass the new
`description` on the same call too, so adding a name or refreshing the description never forces
a full rewrite. Removing an alias, or rewriting the description wholesale with no fact to write,
is a `write_file`.

To drop one fact line, call `replace_fact` with the whole line as `old_string`, including the
line break that follows it (if none follows it, the line break before it), and an empty
`new_string`, so no blank line is left behind. Use `delete_file` only when the whole file goes.
"""
