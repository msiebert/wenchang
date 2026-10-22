<!--md-->
# wenchang

> Persistent, self-organizing memory for AI agents: a virtual filesystem of markdown files in Google Cloud Storage, exposed as seven tools.

Pages: [Quickstart](quickstart.md) · [Usage walkthroughs](usage.md) · [Customize](customize.md) · [Reference](reference.md) · [Source](https://github.com/msiebert/wenchang) · [llms.txt](llms.txt)

<!--/md-->
<!--html-->
<section class="hero">
<div class="hero-text">
<h1>Memory your agent files for itself.<span class="cursor" aria-hidden="true"></span></h1>
<p class="lede">A small filesystem of markdown files for your AI agent. The agent decides what to remember and where to file it. wenchang supplies the storage, versioned writes, scope rules, and the prompt.</p>
<p class="audience">For teams building chat assistants, coding agents, and analytics copilots that should remember users, projects, and organizations.</p>
<p class="cta-row"><a class="btn" href="quickstart.html">Quickstart</a><a href="usage.html">See what usage looks like</a><a href="https://github.com/msiebert/wenchang">View on GitHub</a></p>
<pre class="install"><code>pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"</code></pre>
</div>
<figure class="session-panel">
<div class="sp-head"><span>session: user/u-ada</span><span>illustrative</span></div>
<div class="sp-block">
<p class="sp-label anim" style="--i:0">conversation</p>
<div class="row anim" style="--i:0"><span class="who">you</span><span>I prefer bar charts for my weekly reports.</span></div>
<div class="row anim" style="--i:5"><span class="who">agent</span><span>Got it. I'll use bar charts for your weekly reports.</span></div>
</div>
<div class="sp-block">
<p class="sp-label anim" style="--i:1">tool calls</p>
<div class="row anim" style="--i:1"><span class="arrow">&rarr;</span><code>get_memory_index()</code></div>
<div class="row anim" style="--i:2"><span class="back">&larr;</span><span class="out">{ entries: [], capped: [] }</span></div>
<div class="row anim" style="--i:3"><span class="arrow">&rarr;</span><code>write_file(scope="user", area="preferences", name="charts", expected_version=null)</code></div>
<div class="row anim" style="--i:4"><span class="back">&larr;</span><span class="out">{ path: "user/u-ada/preferences/charts.md", version: "1" }</span></div>
</div>
<div class="sp-block anim" style="--i:5">
<p class="mf-path"><span>user/u-ada/preferences/charts.md</span><span class="stat"><span class="plus">+4</span> new file</span></p>
<ul class="mf-lines">
<li><span class="gutter" aria-hidden="true">+</span><span class="fact"><span class="vh">added: </span><span class="k">description:</span> Chart preferences for reports</span></li>
<li><span class="gutter" aria-hidden="true">+</span><span class="fact"><span class="vh">added: </span><span class="k">aliases:</span> weekly report charts</span></li>
<li><span class="gutter" aria-hidden="true">+</span><span class="fact"><span class="vh">added: </span><span class="rule">---</span></span></li>
<li class="write-line"><span class="gutter" aria-hidden="true">+</span><span class="fact"><span class="vh">added: </span><span class="tag tag-stated">[stated]</span> Prefers bar charts for weekly reports.</span></li>
</ul>
</div>
<p class="caption">Tool names, arguments, and results are real. The agent's wording is representative.</p>
</figure>
</section>

## The memory index {#index}

Every session starts with `get_memory_index()`. Each entry is a path, a version, and a description the agent matches against. These four come from the [usage walkthroughs](usage.md); pick one to follow it.

<nav class="idx" aria-label="Memory files from the walkthroughs">
<div class="idx-cols" aria-hidden="true"><span>path</span><span>ver</span><span>description</span><span></span></div>
<a class="idx-row" href="usage.html#curated"><span class="p"><b>project/</b>p-checkout/system/signup-tracking.md</span><span class="v">v1</span><span class="d">Curated notes on how signups are tracked</span><span class="pill pill-red">read only</span></a>
<a class="idx-row" href="usage.html#recall"><span class="p"><b>user/</b>u-ada/preferences/charts.md</span><span class="v">v1</span><span class="d">Chart preferences for reports</span><span></span></a>
<a class="idx-row" href="usage.html#forget"><span class="p"><b>user/</b>u-ada/preferences/editor.md</span><span class="v">v1</span><span class="d">Code editor preferences</span><span></span></a>
<a class="idx-row" href="usage.html#alias"><span class="p"><b>user/</b>u-ada/workflows/board-deck.md</span><span class="v">v1</span><span class="d">Quarterly board deck the user presents</span><span></span></a>
</nav>
<!--/html-->

<!--md-->
wenchang is a Python library that gives an AI agent a small virtual filesystem of markdown files, stored in Google Cloud Storage (GCS) and exposed as seven tools. The agent decides what is worth remembering and where to file it. The library supplies the mechanism: storage, optimistic concurrency, scope-based authorization hooks, and the instruction text that teaches the agent how to use memory.

**Who it is for:** teams building AI agents (chat assistants, coding agents, analytics copilots) that should remember users, projects, and organizations across conversations.

Install (not published on PyPI; install from git):

```
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"
```
<!--/md-->

## Instructions for AI agents {#for-agents}

<!--md-->
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
<!--/md-->
<!--html-->
<div class="agents">
<p class="bar"><span>wenchang/index.md#for-agents</span><a href="index.md">full text with exact names</a></p>
<ol>
<li><span>Check for Python 3.12 or newer and an MCP client that can launch a stdio server.</span></li>
<li><span>Install from git: <code>pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"</code>. There is no PyPI release, CLI, or environment variable.</span></li>
<li><span>Write <code>server.py</code> from the <a href="quickstart.html">quickstart</a>, ending in <code>build_server(...)</code> and <code>server.run("stdio")</code>.</span></li>
<li><span>Pick storage: <code>InMemoryStorage</code> for trials, <code>GcsStorage(bucket)</code> to persist.</span></li>
<li><span>Ask the user which scopes exist, which are shared, and who may write each. See <a href="customize.html">customize</a>.</span></li>
<li><span>Register the server with the MCP client, for example <code>claude mcp add memory -- /path/to/python /path/to/server.py</code>.</span></li>
<li><span>Verify that exactly seven tools are listed.</span></li>
<li><span>In use, call <code>get_memory_index</code> first, pass <code>expected_version</code> on every write, never write to <code>system/</code>, and never store account numbers, health diagnoses, or signs the user is a minor.</span></li>
</ol>
<p class="more">Machine-readable: <a href="llms.txt">llms.txt</a>, <a href="llms-full.txt">llms-full.txt</a>, and a Markdown twin of every page.</p>
</div>
<!--/html-->

## How it works {#how-it-works}

<!--html-->
<!--include-html diagram.html-->
<!--/html-->
<!--md-->
```
Agent --MCP: 7 tools + memory prompt--> tool layer (wenchang.mcp, wenchang.tools)
      --TransportClient--> MemoryStore --Storage protocol--> GcsStorage --> GCS bucket

GCS bucket: {scope}/{entity_id}/{area}/{name}.md
  user/u-ada/...                 private to one person
  project/p-checkout/...         shared by a project
  organization/o-acme/...        written by admins
```
<!--/md-->

The agent never sees storage. It sees seven tools and a prompt.

1. **The agent** calls a tool such as `append_line(scope, area, name, line, expected_version)`. It addresses a file by scope, area, and name.
2. **The tool layer** (`wenchang.tools`, mounted on MCP by `wenchang.mcp`) resolves the caller's identity on every call, fills in the caller's own entity ID for the scope, refuses writes to `system/` and to scopes the policy gates by role, and forwards the call to a `TransportClient`.
3. **`MemoryStore`** (reached through `InProcessClient` today) enforces the per-file size limit, merges metadata, and makes every write conditional on the version the agent read.
4. **`Storage`** is a small get/put/list protocol. `GcsStorage` implements it on one GCS bucket: markdown body as the object, metadata as custom object metadata, GCS generation as the version.

Files live at `{scope}/{entity_id}/{area}/{name}.md`. A scope is a visibility tier you define (the reference adopter uses `user`, `project`, and `organization`); the entity ID says whose copy of that scope it is.

## See it work {#transcript}

An illustrative exchange. Tool names, arguments, and result shapes are real; the agent's wording is representative, not recorded. The full tool-call detail is on the [usage page](usage.md).

**Session 1**

- **You:** I prefer bar charts for my weekly reports.
- **Agent** calls `get_memory_index()`. The index is empty.
- **Agent** calls `write_file(scope="user", area="preferences", name="charts", content="- [stated] Prefers bar charts for weekly reports.\n", description="Chart preferences for reports", aliases=["weekly report charts"], expected_version=null)`.
- **Agent:** Got it. I'll remember bar charts for your weekly reports.
{: .transcript }

**Session 2, days later, a brand-new conversation**

- **You:** Which chart type should I use for this week's report?
- **Agent** calls `get_memory_index()`. One entry: `user/u-ada/preferences/charts.md`, "Chart preferences for reports".
- **Agent** calls `read_file(scope="user", area="preferences", name="charts")` and reads `- [stated] Prefers bar charts for weekly reports.`
- **Agent:** Use a bar chart. You told me you prefer them for your weekly reports.
{: .transcript }

## Key properties {#properties}

<!--md-->
- **Agent-organized.** No schema is imposed. The agent files each fact in the file about its subject, creates files and areas as needed, and navigates by each file's `description` and `aliases`. There is no content search.
- **Optimistic concurrency.** Every write names the `expected_version` it read; `null` means create-if-absent. A stale version returns a `VersionConflictError` that carries the current content and version, so the agent merges and retries. `append_line` and `replace_fact` change one fact without rewriting the file.
- **Scope authorization.** Each call resolves an `Identity` (a grant of entity ID and role per scope) through your `IdentityResolver`. A `ScopePolicy` names which roles may write which scopes. Paths are always built from the caller's own grants.
- **Curated, read-only `system/` area.** Every scope has a `system/` area that people maintain and the agent can read but never change. Corrections go in a normal area and win over the curated fact.
- **Privacy rules in the prompt.** The shipped prompt tells the agent to refuse to store financial account numbers, health diagnoses, or anything indicating the user is a minor, in any scope. This is prompt guidance, not a content filter: no tool checks for sensitive content.
- **Transport-agnostic.** The tool layer talks to a `TransportClient` protocol. `InProcessClient` calls a `MemoryStore` directly; a remote transport is planned.
- **Observable.** `on_call` receives a `ToolCallRecord` after every MCP tool call.
<!--/md-->
<!--html-->
<ul class="cards">
<li><span class="pill pill-muted">no schema</span><b>Agent-organized</b><span class="d">The agent files each fact in the file about its subject and finds files by description and aliases. There is no content search.</span></li>
<li><span class="pill pill-muted">versioned</span><b>Optimistic concurrency</b><span class="d">Every write names the version it read. A stale version returns the current content, so the agent merges and retries.</span></li>
<li><span class="pill pill-muted">scoped</span><b>Scope authorization</b><span class="d">Each call resolves an <code>Identity</code>. A <code>ScopePolicy</code> says which roles may write which scope, and paths come from the caller's own grants.</span></li>
<li><span class="pill pill-red">read only</span><b>Curated system/ area</b><span class="d">People maintain it. The agent can read it and never change it. A correction goes in a normal area and wins.</span></li>
<li><span class="pill pill-muted">prompt rule</span><b>Privacy in the prompt</b><span class="d">The agent is told to refuse account numbers, health diagnoses, and anything indicating a minor. It is guidance, not a content filter.</span></li>
<li><span class="pill pill-muted">pluggable</span><b>Transport-agnostic</b><span class="d">Tools talk to a <code>TransportClient</code>. <code>InProcessClient</code> calls a <code>MemoryStore</code> directly; a remote transport is planned.</span></li>
<li><span class="pill pill-muted">logged</span><b>Observable</b><span class="d"><code>on_call</code> receives a <code>ToolCallRecord</code> after every MCP tool call.</span></li>
<li><span class="pill pill-muted">markdown</span><b>Plain files</b><span class="d">A markdown body with its metadata stored beside it, at <code>{scope}/{entity_id}/{area}/{name}.md</code>.</span></li>
</ul>
<!--/html-->

## Status {#status}

<!--html-->
<ul class="facts-row"><li><span class="pill pill-raw">v0.1.0</span></li><li><span class="pill">MIT</span></li><li><span class="pill">Python 3.12+</span></li></ul>
<!--/html-->

Version 0.1.0, MIT licensed, Python 3.12+. wenchang is a library: you supply the identity resolver, scope policy, and prompt slots, and write a small server script. The behavioral evals in the repository are signal for prompt iteration, not release gates. See the [reference](reference.md#limitations) for known limits.

## Next {#next}

- [Quickstart](quickstart.md): install, build a server, connect Claude Code.
- [Usage](usage.md): five walkthroughs with real tool calls and file contents.
- [Customize](customize.md): scopes, prompt slots, limits, storage, telemetry.
- [Reference](reference.md): every tool, the file format, and the error taxonomy.
