# Customizing the prompts

The agent behaves the way the memory prompt tells it to. wenchang ships most of that prompt and leaves four slots for you to fill in. You also choose how the tools are named and described.

You can read the finished prompt in two places: it is the MCP server's `instructions`, and it is the resource `wenchang://memory-prompt`. In Python, `build_memory_prompt(slots)` returns it as markdown with `##` headings and no top-level heading, so a host can nest it in its own system prompt.

## The four slots

`wenchang.prompts.PromptSlots` holds the text that is specific to your deployment. The example below configures an assistant for novelists. Every field is a string and must not be empty. The generic sections of the prompt only say "shared scope", "private scope", and "the `system/` area", so your slots have to say which of your scopes are which.

| Slot | Required | What it does | When to change it |
| --- | --- | --- | --- |
| `purpose` | yes | One or two sentences naming your product and when to use memory. It opens the first section, "Memory". | Always set it. It is how the agent knows what the memory is for. |
| `scope_guidance` | yes | Which scopes exist, which are shared and which private, who may write each, and the rules for each. Becomes the "Scopes" section. | Whenever your scopes or write rules change. This is where you set ask-before-write rules and how to choose a scope. |
| `seed_areas` | yes | The starting areas in each scope, as lowercase slugs, and which scopes have a `system/` area. Becomes "Seed areas". | To steer where facts go. List areas, or tell the agent to pick its own. |
| `systems_of_record` | no | Which other systems hold canonical information and how to refer to their objects. `None` leaves the section out. | When the agent could otherwise copy data that lives elsewhere, such as the manuscript text or an editor's query tracker. |

```python
from wenchang.prompts import SECTION_ORDER, PromptSlots, build_memory_prompt

slots = PromptSlots(
    purpose=(
        "You have persistent memory of your work helping an author write a novel: reference it "
        "and save to it with these tools whenever you work on a manuscript."
    ),
    scope_guidance=(
        "There are three scopes: user, project, and organization. A project is one manuscript. "
        "An organization is a publisher, and an author may work on several manuscripts.\n\n"
        "- user is private: it belongs to the author you are talking with and follows them "
        "across manuscripts.\n"
        "- project is the manuscript, shared by its author, co-author, and editor; any of them "
        "may write to it.\n"
        "- organization is Hanlin Press, shared by every author and editor there; only "
        "editors-in-chief may write to it. It holds press-wide conventions, never facts about "
        "one book.\n\n"
        "Writes to user and project need no ask. If a new fact contradicts one stored in project "
        "or organization, show the stored fact, say what conflicts, and ask which to keep.\n\n"
        "Scope a fact by who it is true for, not who said it: if it would hold for a different "
        "author on this manuscript, use project, or organization if it holds for every book at "
        'the press; otherwise use user. When in doubt, write narrow. "I draft in the morning" '
        'goes in user; "Lin Qiao\'s eyes are grey" in project; "The press spells in British '
        'English" in organization.'
    ),
    # To let the agent choose, say so: "No fixed areas. Create areas as subjects need them."
    seed_areas=(
        "- user: preferences, workflows\n"
        "- project: characters, plot, timeline, style, research\n"
        "- organization: conventions\n\n"
        "Every scope also has a `system/` area."
    ),
    # Optional. None omits the whole section.
    systems_of_record=(
        "- The manuscript text lives in the author's word processor. Never copy chapters into "
        "memory; refer to a chapter by number and title, and store decisions about it.\n"
        "- Editorial queries live in the press's tracker; refer to one by its ID."
    ),
)

print(SECTION_ORDER)
prompt = build_memory_prompt(slots)
print([line for line in prompt.splitlines() if line.startswith("## ")])
```

### Scope guidance

This slot does the most work. A scope name alone tells the agent nothing, so say what each one means and when to use it. Useful things to include:

- Who can see each scope and who can write it. The agent cannot see your roles. If only admins may write `organization`, say so, or it will try and get an error.
- When to ask before writing. The example needs no ask for `user` or `project`. Add an ask rule for any scope where a wrong write is costly.
- What to do when a new fact contradicts a stored one.
- A test for choosing a scope, with one example per scope. The example below uses "scope a fact by who it is true for, not who said it".

### Seed areas, or none

Seeding areas gives the agent a starting shape: `preferences`, `workflows`, `people`. It keeps files consistent from the first session. The agent can still create other areas.

If you would rather let the agent decide, say that in the slot, for example "No fixed areas. Create areas as subjects need them." The slot cannot be empty, but its text can say there is no list. Seed areas if other code or people will rely on the layout. Leave them open if you would rather see what the agent comes up with.

### Systems of record

If a fact is canonical somewhere else, memory should point to it and not copy it. This slot lists those systems. The shipped text adds the rule: never copy their contents, refer to objects by name or ID, store only what the system lacks, and ask the user which is right when memory and the system disagree.

## The fixed sections

These sections ship with the library and are the same for every deployment. They are listed in assembly order. `SECTION_ORDER` in `wenchang.prompts` gives the section ids.

| Heading | What it tells the agent |
| --- | --- |
| Memory | Your `purpose`, then how files are addressed. Call `get_memory_index()` at the start of every session. Name a file by its scope, area, and name. Split a subject that outgrows the file size limit. |
| Scopes | Your `scope_guidance`. |
| Seed areas | Your `seed_areas`. |
| Systems of record | The general rule, then your list. Left out if `None`. |
| Applying memory | Use a fact only if it changes the answer. Do not turn one mention into a trait. Take the user's name only from memory or from what they say. |
| Deciding what to remember | Label each line `[stated]`, `[observed]`, or `[inferred]`. Save a fact if it would help a future session. Write end dates into the text. Save facts as they come up, before answering. |
| What never to store | Financial account numbers, health diagnoses, and anything indicating the user is a minor, in any scope. Extra care for shared scopes. |
| Filing | Put a fact in the file about its subject. Check the index for an existing file first. Update aliases and description on each write. |
| Choosing a write tool | `append_line` to add a fact, `replace_fact` to change or drop one, `write_file` to create or restructure, `delete_file` for a whole file. |
| Curated content | `system/` is read-only. Record a user's correction as a new line in a writable area, and answer from the correction. |
| Forgetting | Remove a fact completely, with no note that it existed. Ask first when a request would remove more than one fact. |

You cannot edit these sections through the slots. The prompt is a plain string, though. To add your own sections, append to the string and pass the same text to the server as both `instructions` and `prompt`:

```python
from mcp.server.mcpserver import MCPServer

from wenchang.mcp import memory_instructions, register_memory_tools

# slots, client, resolver, policy, and credentials_from_context as in the setup page.
prompt = memory_instructions(slots) + (
    "\n## Tone\n\nWhen you save something, say so in one short sentence.\n"
)
server = MCPServer("inkwell-memory", instructions=prompt)
register_memory_tools(
    server,
    prompt=prompt,  # the same text as the instructions
    client=client,
    resolver=resolver,
    policy=policy,
    credentials_from_context=credentials_from_context,
    source="inkwell-web",
)
```

Behavior depends on the model reading the text, and small wording changes can shift it. The repository has a behavioral eval harness that runs scripted scenarios against a real agent and grades what it stored. If you rewrite or extend prompt text, run scenarios of your own against it. See `evals/` in the repository.

## Names on the tools

Three arguments, accepted by `build_server` and `register_memory_tools`, name your deployment.

- **`product`** (optional) puts your product's name in the first line of each tool description, so each tool says whose memory it is. With `product="Inkwell"`, `append_line` begins "Add one fact line to the end of an existing Inkwell memory file." Without it, descriptions are the tools' docstrings. It must be one non-empty line.
- **`tool_prefix`** (optional) registers the tools as `{tool_prefix}_get_memory_index`, `{tool_prefix}_read_file`, and so on. Use it if the server already has tools with those names, or if one server hosts several memories. It must be 1 to 64 letters, digits, `_` or `-`, starting and ending with a letter or digit.
- **`source`** (required) is the surface name written to each file's `sources` metadata. It does not appear in the prompt.

Next: [Authorization](authorization.md).

---

HTML version: <https://msiebert.github.io/wenchang/prompts.html>
