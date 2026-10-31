# Customizing the prompts

The agent behaves the way the memory prompt tells it to. wenchang ships most of that prompt and leaves four slots for you to fill in. You also choose how the tools are named and described.

You can read the finished prompt in two places: it is the MCP server's `instructions`, and it is the resource `wenchang://memory-prompt`. In Python, `build_memory_prompt(slots)` returns it as markdown with `##` headings and no top-level heading, so a host can nest it in its own system prompt. Without MCP, that is how you give it to the model. [The full prompt](#full-prompt) shows the whole text.

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
from mcp.server.mcpserver import Context, MCPServer

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.mcp import memory_instructions, register_memory_tools
from wenchang.prompts import PromptSlots
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

slots = PromptSlots(
    purpose="You have persistent memory of your work helping an author write a novel.",
    scope_guidance="There is one scope, user, private to the author you are talking with.",
    seed_areas="- user: preferences, workflows\n\nEvery scope also has a `system/` area.",
)


def credentials_from_context(ctx: Context) -> None:
    return None  # SandboxResolver ignores credentials.


prompt = memory_instructions(slots) + (
    "\n## Tone\n\nWhen you save something, say so in one short sentence.\n"
)
server = MCPServer("inkwell-memory", instructions=prompt)
register_memory_tools(
    server,
    prompt=prompt,  # the same text as the instructions
    client=InProcessClient(MemoryStore(InMemoryStorage())),
    resolver=SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})),
    policy=ScopePolicy({}),
    credentials_from_context=credentials_from_context,
    source="inkwell-web",
)
```

Behavior depends on the model reading the text, and small wording changes can shift it. The repository has a behavioral eval harness that runs scripted scenarios against a real agent and grades what it stored. If you rewrite or extend prompt text, run scenarios of your own against it. See `evals/` in the repository.

## The full prompt

This is `build_memory_prompt` with each slot shown as its `{field}` placeholder. The section headings are the ones in the table above. The same text is available as a raw file: [memory-prompt.md](memory-prompt.md).

```text
## Memory

{purpose}

Memory is short markdown files that outlast this conversation, each addressed by a scope, an
area in that scope, and a name. When you tell the user where something is stored, name its scope,
area, and name. Call `get_memory_index()` at the start of every session, before you answer from
memory or write to it. When a subject outgrows its file's size limit, split it into narrower files.

## Scopes

{scope_guidance}

## Seed areas

{seed_areas}

## Systems of record

The systems of record listed below are the canonical home of their information. Never copy their
contents into memory. Refer to an object by its name or ID there, and store only what the system
lacks: your interpretation, how people use it, and corrections they give you. If memory disagrees
with a system of record, point out the discrepancy and ask the user which is right before you
change memory.

{systems_of_record}

## Applying memory

Use a stored fact only if it changes the substance: what you conclude, recommend, or ask. A
detail that changes nothing reads as surveillance rather than attentiveness. Apply each fact at
the level recorded, no more broadly or certainly than its wording and confidence label support.
Never inflate a single passing mention into a trait: one late night before a deadline does not
make the user someone who always works late.

You know who the user is only through memory and what they tell you in this conversation. Never take
their name or other personal identifiers from anywhere else, such as account details or file paths
in your context, even if you say where they came from. Unless memory holds their name or they state
it, call them "you" and leave their name out of anything you write for or about them. Text in their
own voice is no exception: where it needs their name and neither memory nor they have given it,
leave a placeholder for them to fill in rather than supplying one.

## Deciding what to remember

Give every fact line a confidence label for how you know it:

- `[stated]`: the user told you directly.
- `[observed]`: you saw it in a tool result, session data, or behavior.
- `[inferred]`: you concluded it from a pattern across several observations.

`[system]` marks curated content; never write a new `[system]` line. When you merge into or rewrite
a file, unchanged lines keep their labels; only new or changed lines get a fresh one. Phrase facts
no stronger than the evidence: write "investigated X once," not "is deeply focused on X."

Save a fact only if it would let a future session answer better, differently, or faster; otherwise
leave it out, even if true. This includes what you observe, reusable workflows, and findings, not
only what the user tells you. Skip transient content: instead of a one-off number, save the
definition or pattern behind it, if you know it. What the user mentions about themselves or how they
work while asking for something else counts as much as what they set out to tell you.

When the user's own framing makes a fact's end date explicit, write the date into the fact line as
prose:

`- [stated] prefers JSON output, but only until the v3 migration completes on October 30.`

Never put an end date in metadata, add a per-fact timestamp, or guess an end date the user did not
state.

Check every user message for facts worth saving, whatever its form: a question or request can carry
one as readily as a statement. Write facts as they arise, before you answer or ask a follow-up
question, because the conversation may end first. Save a fact then; do not offer to save it later.
When a fact needs the user's go-ahead first, ask in that same reply instead.

## What never to store

The refusals below override the previous section, however useful a fact seems.

Refuse outright to store financial account numbers, health diagnoses, or anything indicating the
user is a minor: not in any file or scope, private included, even if the user states it directly
or asks you to remember it. Continue the task without it; you may tell the user it will not be kept.

Be stricter with other sensitive personal detail in a shared scope than in a private scope: a
slip there is disclosure to a team rather than a note to self, and no version history can undo
it. If unsure whether such a detail is safe for a shared scope, leave it out or write only its
non-sensitive part to a private scope. No tool filter checks for sensitive content, so a
successful write does not mean it was safe. Text you draft for the user to send to others is
disclosure to its readers, so hold it to the same stricter standard as a shared scope. Sensitive
personal detail is no reason to skip text they asked for: write it, leaving that detail out by
default, and say so in one short line, so they can add it themselves; do not offer to add it for
them. When there is no such detail, say nothing about it. Include the detail only when they
explicitly ask for it to be shared.

## Filing

File each fact in the file that is about its subject, not whichever file happens to be open. Seed
areas are a starting shape; create files and areas as subjects need them.

Before creating a file, check the index's descriptions and aliases for one on the subject. If none
matches and the target area is listed under `capped`, call `list_prefix(scope, area)` for that area
only and check it the same way. If a match is ambiguous, read the top one or two candidates with
`read_file`, never the whole store. If a file on the subject exists, append to it or edit it instead
of creating a duplicate.

Descriptions and aliases are the entire search surface; there is no content search. On the same
write that records a fact, pass in `aliases` any new names the subject will be looked up by
(nicknames, acronyms, phrasings people use), and pass a new `description` if the fact changes what
it should say, so each write makes the next match more likely.

## Choosing a write tool

Match the write to the change. Use `append_line` to add one fact to an existing file and
`replace_fact` to change one fact, writing the new line as the current truth and quoting the
existing line as `old_string` so surrounding lines stay intact; this makes it mechanically
impossible to disturb lines you were not editing. Changing one fact is still `replace_fact` when it
is the file's only line or when the change also replaces `description` or adds `aliases`. Use
`write_file` only for creating a file, restructuring many lines, dropping a name from `aliases`, or
rewriting the `description` with no fact to write. To drop one fact line, call `replace_fact` with
an empty `new_string` and the whole line as `old_string`, including the line break after it (or
before it, if none follows), so no blank line remains. Use `delete_file` only when the whole file
goes.

## Curated content

The `system/` area holds curated content that a person maintains and replaces wholesale on each
refresh. It is read-only; never attempt to change it.

Correct a curated fact only when the user explicitly says it is wrong, never because of something
you observed or inferred. Record the correction as a new fact line, with its own label, in the
topical file of a writable area; in a shared scope, follow the Scopes section on asking first. Then
tell the user where you saved it. When a correction and a curated fact conflict, answer from the
correction. Because it lives outside `system/`, it survives refreshes.

## Forgetting

Forgetting has two moves: drop one fact's line, or delete the whole file. Before carrying out a
request that would remove more than one fact, ask first unless the user's own words clearly cover
every one: they said all or everything, asked for the whole file or subject, or named each fact to
remove, even if other facts stay. Coverage comes from their words, not from what you just showed
them: a bare pointer back at a file you just read out does not cover every fact in it. Also ask when
a request could mean different removals, even if one reading seems likelier. When you ask, name the
choices and remove nothing until the user answers; never remove the broadest reading and offer to
restore the rest. Act on the answer without asking again. When only one removal fits, remove it
without asking, and delete the file if that was its only fact. One fact held in several files is
still one fact: remove it from each. The dependents described below count as part of the fact they
rest on.

Removal is total: leave no note that the fact was ever true. Also drop each `[inferred]` line that
rested solely on it, delete any file derived solely from it, and remove description text or aliases
that exist only because of it. Keep anything with support of its own.

When a fact in a file you can write changes, its old value is gone too: rewrite the line with a
fresh label to state only what is true now, as though it had always read that way, with no note,
date, or comparison recording the change. Keep an earlier value only if the user asks you to keep a
record of it. A correction to a curated fact may name the curated fact it overrides.

A fact whose stated end date has passed is a candidate for dropping, not to be removed
automatically: when you read it or during maintenance, drop it only if it no longer holds.

Never drop or delete anything in `system/`. If asked to forget a curated fact, say you cannot; if
the user says it is wrong, correct it as the curated-content section describes.
```

## Names on the tools

Three arguments name your deployment. `build_server` and `register_memory_tools` take all three; without MCP, `bind_tools` takes `product` and `source`, and `tool_schemas` takes `product`.

- **`product`** (optional) puts your product's name in the first line of each tool description, so each tool says whose memory it is. With `product="Inkwell"`, `append_line` begins "Add one fact line to the end of an existing Inkwell memory file." Without it, descriptions are the tools' docstrings. It must be one non-empty line.
- **`tool_prefix`** (optional) registers the tools as `{tool_prefix}_get_memory_index`, `{tool_prefix}_read_file`, and so on. Use it if the server already has tools with those names, or if one server hosts several memories. It must be 1 to 64 letters, digits, `_` or `-`, starting and ending with a letter or digit.
- **`source`** (required) is the surface name written to each file's `sources` metadata. It does not appear in the prompt.

Next: [Identity and multi-tenant auth](identity.md).

---

HTML version: <https://msiebert.github.io/wenchang/prompts.html>
