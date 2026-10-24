# wenchang

> A memory store that AI agents write to on their own judgment. Python library, files in Google Cloud Storage, served to the agent as tools.

wenchang is a Python library that lets an AI agent keep what it learns. During a conversation the agent decides what is worth remembering and saves it as markdown files. In later conversations it reads them back. The files live in Google Cloud Storage.

Install (not on PyPI yet):

```
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"
```

The install is one line, but the library does nothing until you configure storage, identity, and prompts. [Setup](setup.md) covers that.

## Memory the agent decides to keep

Most agents forget everything when a conversation ends. wenchang gives the agent a small set of tools for writing and reading memory. Nothing outside the agent decides what gets saved. The agent notices a character detail, a plot decision, or a style preference, and writes it down.

Say an author is writing a novel with an assistant built on wenchang. The author mentions that the protagonist, Lin Qiao, has grey eyes and grew up in a river town. The agent saves it in a file called `project/p-ninth-examination/characters/lin-qiao.md`:

```
description: Lin Qiao, the protagonist
aliases: Qiao
---
- [stated] Has grey eyes.
- [stated] Grew up in Yunmen, a river town.
```

Weeks later, in a new conversation, the author asks for a scene with Lin Qiao. The agent reads its index, opens that file, and gives her grey eyes. If the author changes their mind, the agent edits that one line.

wenchang does not decide what is worth keeping. A prompt that ships with the library tells the agent how to decide, and you can change that prompt. See [Customizing the prompts](prompts.md).

## How it works

### The agent starts from an index

At the start of each session the agent calls `get_memory_index()`. It gets one entry for every file it has written: path, version, a one-line description, and aliases. It does not get file contents. It reads the descriptions, decides which files matter for the current conversation, and opens only those.

```json
// get_memory_index()
{
  "entries": [
    {
      "path": "project/p-ninth-examination/characters/lin-qiao.md",
      "version": "3",
      "description": "Lin Qiao, the protagonist",
      "aliases": ["Qiao"]
    },
    {
      "path": "project/p-ninth-examination/timeline/main-timeline.md",
      "version": "1",
      "description": "Order of events in the novel",
      "aliases": ["chronology", "timeline"]
    }
  ],
  "capped": []
}
```
Real entries also carry `scope`, `area`, `name`, `sources`, and `last_updated`. If the index gets too big, it is cut at a size limit and the agent lists the rest with `list_prefix`. There is no search over file contents. Descriptions and aliases are how the agent finds things, so the agent keeps them up to date as it writes.

### The agent organizes its own files

The agent has seven tools: `get_memory_index`, `read_file`, `list_prefix`, `write_file`, `append_line`, `replace_fact`, and `delete_file`. Each fact is one line. The agent can add a line, change a line, or drop one. It can rewrite a file, create one, or delete one. It can change a file's description and aliases whenever it writes.

The library sets no schema. The agent decides how to split memory into files, which file a fact belongs in, and what to delete when a fact stops being true. The shipped prompt pushes it toward one file per subject, toward appending to an existing file instead of creating a duplicate, and toward removing a fact completely when the user asks it to forget.

### Scopes and areas

Every file path has this shape:

```
{scope}/{entity_id}/{area}/{name}.md
project/p-ninth-examination/characters/lin-qiao.md
```

A **scope** says who can see a file. You define the scopes. A common set is `user` (private to one person), `project` (shared by a team), and `organization` (shared by everyone, writable only by admins). For a novel, `user` is the author's own preferences, `project` is the manuscript, and `organization` is the publisher. The **entity ID** says whose copy of that scope it is: `u-tianlong` is one author, `p-ninth-examination` is one manuscript.

An **area** is a kind of information inside a scope, such as `characters`, `plot`, `timeline`, or `style` in a manuscript. You can seed the areas you care about in the prompt, for example "project: characters, plot, timeline, style". Or you can tell the agent to choose its own. Either way it can add areas by writing a file in a new one.

Every scope also has a `system/` area. You fill it with curated content. The agent can read it and can never change it.

- **Versioned writes.** Every write names the file version the agent read. If someone else changed the file in the meantime, the write fails and returns the current content, and the agent merges and retries.
- **Plain files.** Each memory is a markdown file in one GCS bucket. The description and aliases are stored as object metadata beside it. You can browse the bucket with ordinary tools.
- **Sensitive data.** The prompt tells the agent never to store financial account numbers, health diagnoses, or anything that suggests the user is a minor. This is prompt guidance. No tool filters content.
## How you use it

wenchang is a library. You write a short Python script that assembles a server, then point your agent's MCP client at it.

1. **Install it** and create a GCS bucket for memory files. [Setup](setup.md#install)
2. **Write the server script.** It picks the storage, says who the caller is, and builds the MCP server:

    ```python
    server = build_server(
        slots=slots,  # your prompt text
        client=InProcessClient(MemoryStore(GcsStorage(bucket))),
        resolver=resolver,  # who is calling, and with which scopes
        policy=policy,  # which roles may write which scopes
        credentials_from_context=credentials_from_context,
        source="inkwell-web",
    )
    server.run("stdio")
    ```

    [Setup](setup.md#server)
3. **Register it with your MCP client.** For Claude Code, `claude mcp add memory -- python server.py`. [Setup](setup.md#client)
4. **Tune the prompts.** Four text slots tell the agent what your product is, which scopes exist, and which areas to start with. [Customizing the prompts](prompts.md)
5. **Plug in your own auth** when more than one person uses the server. [Authorization](authorization.md)
## What wenchang is and is not

wenchang provides the primitives for agent memory. It is not a hosted service and not a complete product.

**wenchang provides:**

- The seven tools the agent calls.
- The memory prompt that teaches the agent how to use them.
- The layer that writes to long-term storage (GCS), with versioned writes and size limits.
- Enforcement of your scope rules: the `system/` area is read-only, and restricted scopes accept only the roles you name.
- An MCP adapter, so the tools work in any MCP client.

**You provide:**

- Authentication: verifying who is calling.
- Authorization: mapping each caller to the scopes, entity IDs, and roles they get. wenchang calls your resolver on every tool call and trusts its answer.
- A GCS bucket and credentials.
- The server process: where it runs and how clients reach it.
- Any content filtering beyond what the prompt asks for.

**Not included:**

- Search over file contents.
- A command line tool or ready-made server.
- A remote transport. The tools talk to storage in the same process.
- Storage other than GCS, apart from an in-memory fake for tests.

Version 0.1.0, MIT license, Python 3.12 or newer. See the [reference](reference.md#limitations) for known limits.

---

HTML version: <https://msiebert.github.io/wenchang/>
