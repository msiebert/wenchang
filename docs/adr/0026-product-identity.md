# 0026. Product identity in the prompt and tool descriptions

Date: 2026-10-08

## Status

Accepted

## Context

Nothing in the assembled memory prompt (ADR 0025) or the tool descriptions
(ADR 0022) says which product the memory serves. An agent holding many
tools selects among them by the first line of each description, and "Add
one fact line to the end of an existing memory file" does not say it is
Mixpanel memory. An adopter must be able to tell the agent, in effect:
"You have memory tools for Mixpanel. Reference and save memories with them
when you work with Mixpanel."

There are two surfaces. The system prompt is assembled from `PromptSlots`
by `build_memory_prompt`, so the product can arrive as slot text. The tool
descriptions are the tool docstrings, which are static, shared by every
adopter, and public contract (ADR 0022 decision 8); AIE-1165 set a length
budget for them and pinned their load-bearing phrases. The product cannot
live in a docstring.

## Decision

1. **`purpose` is a required first field of `PromptSlots`.** The
   constructor is `PromptSlots(purpose, scope_guidance, seed_areas,
   systems_of_record=None)`. `purpose` is one or two sentences naming the
   product and when to use memory. It is validated like the other required
   slots (ADR 0025 decision 3): every type check before any value check,
   each in field order, so `purpose` is checked first; a wrong real type
   raises `TypeError`, an empty or whitespace-only value or one that is not
   UTF-8 encodable raises `ValueError`, and the stored value is an exact,
   stripped `str`. This is a breaking change to the constructor: every
   caller must pass `purpose`.
   - **Rejected: an optional slot.** Every adopter has a product, and an
     optional slot means some prompts would never name it.
   - **Rejected: its own section.** A new `SECTION_ORDER` entry would sit
     below the generic overview, so the product would not open the prompt,
     and it would change `SECTION_ORDER`.
2. **`purpose` opens the overview ("Memory") section.** The section 1 body
   is `purpose + "\n\n" + overview.BODY` (the body stripped and read at
   call time). `overview.BODY` stays product-neutral. Because `purpose` is
   never blank, section 1 is never omitted: with a blank `overview.BODY`
   its body is `purpose` alone. `SECTION_ORDER`, the headings, and every
   other section are unchanged.
   - **Note (2026-10-08).** `overview.BODY` opens "Memory is short markdown
     files that outlast this conversation, ..." rather than "You have
     persistent memory: short markdown files ...". A `purpose` such as
     `REFERENCE_PURPOSE` already opens "You have persistent memory of your
     work in Mixpanel", so the old opening repeated it. `purpose` carries
     the "you have" framing; `overview.BODY` states the mechanism. The rest
     of `overview.BODY` is unchanged.
3. **`product` is a session setting on `MemoryTools`.**
   `MemoryTools(client, identity, policy, *, source, product=None)` and
   `bind_tools(client, resolver, credentials, policy, *, source,
   product=None)` take a keyword-only `product: str | None`, exposed as a
   read-only `product` property. It is an adopter-side constructor
   argument (ADR 0022 decision 2): a non-`str`, non-`None` real type
   raises `TypeError`; after `str.__str__` and `str.strip`, an empty value,
   a value containing any `str.splitlines` boundary, or one that is not
   UTF-8 encodable raises `ValueError`. Constructor checks run in argument
   order, so a bad `source` wins over a bad `product`. `bind_tools`
   resolves the identity first, so a resolver error wins too. The agent
   cannot set `product`, and no tool signature has it.
   - **Rejected: a module-level function taking a product.** The session
     object already carries adopter configuration such as `source`; a
     separate function would make the host thread the product through by
     hand.
   - **Rejected: templating or formatting the docstrings themselves.**
     Docstrings are static and are public contract (ADR 0022 decision 8);
     mutating them would make one adopter's product leak into every
     instance in the process.
4. **`descriptions()` templates only the first line.** `descriptions()`
   returns a fresh read-only mapping from each name in `TOOL_NAMES`, in
   order, to that tool's description. With `product` `None`, each value is
   the `inspect.cleandoc`'d docstring unchanged. With a product, the first
   line comes from a fixed per-tool template, with the product inserted by
   plain replacement (braces in a product are verbatim), and every line
   after the first is the cleandoc'd docstring unchanged, so the AIE-1165
   docstring budget and phrase pins stand. Each template is the docstring's
   first line with one phrase inserted: `"{product} "` for six tools, and
   `"{product} memory "` for `list_prefix`, because "a Mixpanel scope or
   area" would not say the tool is about memory. With product `Mixpanel`
   the first lines are:
   - `get_memory_index`: "Load the metadata index of every Mixpanel memory
     scope available in this session."
   - `read_file`: "Read one Mixpanel memory file: its content, metadata,
     and version."
   - `list_prefix`: "List the files in a Mixpanel memory scope or area, one
     page at a time, without content."
   - `write_file`: "Create a Mixpanel memory file or replace one whole."
   - `append_line`: "Add one fact line to the end of an existing Mixpanel
     memory file."
   - `replace_fact`: "Change one fact in a Mixpanel memory file by quoting
     the text to replace."
   - `delete_file`: "Delete a Mixpanel memory file."
   - **Rejected: the product in every paragraph.** It breaks the AIE-1165
     budget and adds noise; the first line is what a host shows for tool
     selection.
   - **Rejected: an a/an article heuristic.** Choosing the article depends
     on pronunciation, not spelling; the templates use a fixed "a".
5. **Hosts register descriptions from `descriptions()`.** A host registers
   each tool from `tools()` with `descriptions()[name]` as its
   description, rather than the method's `__doc__`. `tools()` is
   unchanged.
6. **Relation to AIE-1060.** The MCP server that AIE-1060 builds registers
   each tool with `descriptions()[name]`. It may also pass the assembled
   prompt, or the `purpose` text, as the MCP server's `instructions`; that
   wiring belongs to AIE-1060.

## Consequences

The agent sees the product in two places: the opening lines of the memory
prompt, and the first line of every tool description when the host sets
`product` and registers from `descriptions()`. A host that registers from
`__doc__` still works but shows product-neutral descriptions.

`PromptSlots` without `purpose` now fails with `TypeError`. This is a
breaking change for adopters, accepted before 1.0. The reference adopter
fixture (`tests/prompts_reference_adopter.py`) gains `REFERENCE_PURPOSE`.

The docstrings remain the single source of the tool descriptions; the
templates restate only their first lines, and an import-time guard keeps
the template map's keys equal to `TOOL_NAMES`. A change to a docstring's
first line must be mirrored in its template.

The fixed article "a" reads oddly before a product name that takes "an",
such as "Amplitude" ("a Amplitude memory file") in four of the templates.

A blank `overview.BODY` no longer omits section 1, which ADR 0025's
omit-empty rule did before.
