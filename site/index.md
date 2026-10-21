# wenchang

> Persistent, self-organizing memory for AI agents: a virtual filesystem of markdown files in Google Cloud Storage, exposed as seven tools.

Pages: [Quickstart](quickstart.md) · [Usage walkthroughs](usage.md) · [Customize](customize.md) · [Reference](reference.md) · [Source](https://github.com/msiebert/wenchang) · [llms.txt](llms.txt)

wenchang is a Python library that gives an AI agent a small virtual filesystem of markdown files, stored in Google Cloud Storage (GCS) and exposed as seven tools. The agent decides what is worth remembering and where to file it. The library supplies the mechanism: storage, optimistic concurrency, scope-based authorization hooks, and the instruction text that teaches the agent how to use memory.

**Who it is for:** teams building AI agents (chat assistants, coding agents, analytics copilots) that should remember users, projects, and organizations across conversations.

Install (not published on PyPI; install from git):

```
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"
```

## Instructions for AI agents

If you are an AI agent asked to install and wire wenchang for your user, follow these steps. Every name below is verified against the source at version 0.1.0.

1. **Check the environment.** wenchang needs Python 3.12 or newer and an MCP client that can launch a stdio server (Claude Code, for example).
2. **Install from git** into the environment the server will run in: `pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`. The `mcp` extra pulls in `mcp>=2.2,<3`. There is no documented PyPI release. There is no CLI, console script, or environment variable to configure.
3. **Write a server script.** wenchang ships no ready-made server binary. Create `server.py` from the [quickstart](quickstart.md): build a `PromptSlots`, a `MemoryStore` over a `Storage`, an identity resolver, and a `ScopePolicy`, then call `wenchang.mcp.build_server(...)` and `server.run("stdio")`.
4. **Pick storage.** `InMemoryStorage` is for trials only: a stdio server is a fresh process per client session, so everything is lost on exit. For persistence use `GcsStorage(bucket)` from `wenchang.storage.gcs` with an existing bucket and Application Default Credentials, or a local fake-gcs-server for development.
5. **Ask the user about scopes.** Which scopes exist (for example `user`, `project`, `organization`), which are shared, and which roles may write each. Encode the answer in `PromptSlots.scope_guidance`, the identity grants, and `ScopePolicy`. See [customize](customize.md).
6. **Register the server** with the user's MCP client, for example `claude mcp add memory -- /path/to/python /path/to/server.py`, or an entry under `mcpServers` in `.mcp.json`.
7. **Verify.** The server must list exactly seven tools: `get_memory_index`, `read_file`, `list_prefix`, `write_file`, `append_line`, `replace_fact`, `delete_file` (each prefixed `{tool_prefix}_` if you set `tool_prefix`). The memory prompt is the server's `instructions` and also the resource `wenchang://memory-prompt`.
8. **Use memory correctly.** Call `get_memory_index` first in every session. Address files by `(scope, area, name)`. Pass the `version` you read as `expected_version` on every write (`null` creates). Never write to the `system/` area. Never store financial account numbers, health diagnoses, or anything indicating the user is a minor.

Machine-readable versions of this site: [llms.txt](llms.txt), [llms-full.txt](llms-full.txt) (every page in one file), and a Markdown twin of every page (`index.md`, `quickstart.md`, `usage.md`, `customize.md`, `reference.md`).

## How it works

```
Agent --MCP: 7 tools + memory prompt--> tool layer (wenchang.mcp, wenchang.tools)
      --TransportClient--> MemoryStore --Storage protocol--> GcsStorage --> GCS bucket

GCS bucket: {scope}/{entity_id}/{area}/{name}.md
  user/u-ada/...                 private to one person
  project/p-checkout/...         shared by a project
  organization/o-acme/...        written by admins
```

The agent never sees storage. It sees seven tools and a prompt.

1. **The agent** calls a tool such as `append_line(scope, area, name, line, expected_version)`. It addresses a file by scope, area, and name.
2. **The tool layer** (`wenchang.tools`, mounted on MCP by `wenchang.mcp`) resolves the caller's identity on every call, fills in the caller's own entity ID for the scope, refuses writes to `system/` and to scopes the policy gates by role, and forwards the call to a `TransportClient`.
3. **`MemoryStore`** (reached through `InProcessClient` today) enforces the per-file size limit, merges metadata, and makes every write conditional on the version the agent read.
4. **`Storage`** is a small get/put/list protocol. `GcsStorage` implements it on one GCS bucket: markdown body as the object, metadata as custom object metadata, GCS generation as the version.

Files live at `{scope}/{entity_id}/{area}/{name}.md`. A scope is a visibility tier you define (the reference adopter uses `user`, `project`, and `organization`); the entity ID says whose copy of that scope it is.

## See it work

An illustrative exchange. Tool names, arguments, and result shapes are real; the agent's wording is representative, not recorded. The full tool-call detail is on the [usage page](usage.md).

**Session 1**

- **You:** I prefer bar charts for my weekly reports.
- **Agent** calls `get_memory_index()`. The index is empty.
- **Agent** calls `write_file(scope="user", area="preferences", name="charts", content="- [stated] Prefers bar charts for weekly reports.\n", description="Chart preferences for reports", aliases=["weekly report charts"], expected_version=null)`.
- **Agent:** Got it. I'll remember bar charts for your weekly reports.

**Session 2, days later, a brand-new conversation**

- **You:** Which chart type should I use for this week's report?
- **Agent** calls `get_memory_index()`. One entry: `user/u-ada/preferences/charts.md`, "Chart preferences for reports".
- **Agent** calls `read_file(scope="user", area="preferences", name="charts")` and reads `- [stated] Prefers bar charts for weekly reports.`
- **Agent:** Use a bar chart. You told me you prefer them for your weekly reports.

## Key properties

- **Agent-organized.** No schema is imposed. The agent files each fact in the file about its subject, creates files and areas as needed, and navigates by each file's `description` and `aliases`. There is no content search.
- **Optimistic concurrency.** Every write names the `expected_version` it read; `null` means create-if-absent. A stale version returns a `VersionConflictError` that carries the current content and version, so the agent merges and retries. `append_line` and `replace_fact` change one fact without rewriting the file.
- **Scope authorization.** Each call resolves an `Identity` (a grant of entity ID and role per scope) through your `IdentityResolver`. A `ScopePolicy` names which roles may write which scopes. Paths are always built from the caller's own grants.
- **Curated, read-only `system/` area.** Every scope has a `system/` area that people maintain and the agent can read but never change. Corrections go in a normal area and win over the curated fact.
- **Privacy rules in the prompt.** The shipped prompt tells the agent to refuse to store financial account numbers, health diagnoses, or anything indicating the user is a minor, in any scope. This is prompt guidance, not a content filter: no tool checks for sensitive content.
- **Transport-agnostic.** The tool layer talks to a `TransportClient` protocol. `InProcessClient` calls a `MemoryStore` directly; a remote transport is planned.
- **Observable.** `on_call` receives a `ToolCallRecord` after every MCP tool call.

## Status

Version 0.1.0, MIT licensed, Python 3.12+. wenchang is a library: you supply the identity resolver, scope policy, and prompt slots, and write a small server script. The behavioral evals in the repository are signal for prompt iteration, not release gates. See the [reference](reference.md#limitations) for known limits.

## Next

- [Quickstart](quickstart.md): install, build a server, connect Claude Code.
- [Usage](usage.md): five walkthroughs with real tool calls and file contents.
- [Customize](customize.md): scopes, prompt slots, limits, storage, telemetry.
- [Reference](reference.md): every tool, the file format, and the error taxonomy.

---

HTML version: <https://msiebert.github.io/wenchang/>
