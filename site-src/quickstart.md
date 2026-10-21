# Quickstart

Build a memory server for an MCP client in about ten minutes. You will install wenchang, write a short `server.py`, connect it to Claude Code (or any stdio MCP client), and talk to your agent.

wenchang is a library, not a service: there is no CLI, console script, or environment variable. You assemble the server in a few lines of Python.

## Prerequisites {#prerequisites}

- Python 3.12 or newer.
- An MCP client that can launch a stdio server, such as Claude Code.
- For persistent storage: a Google Cloud Storage bucket and Application Default Credentials. For local development: Docker, to run a fake GCS server.

## 1. Install {#install}

wenchang is installed from git; no PyPI release is documented. The `mcp` extra adds the MCP server adapter (`mcp>=2.2,<3`).

```
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"
```

With uv: `uv add "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`.

The GCS client (`google-cloud-storage`) is a core dependency, so it is installed either way.

## 2. A minimal server {#minimal-server}

This `server.py` keeps memory in process (`InMemoryStorage`) and gives every caller the same fixed identity (`SandboxResolver`). It is the quickest way to see the tools working.

<!--include python quick_memory.py-->

What each piece does:

- **`PromptSlots`** is your deployment's part of the memory prompt: `purpose`, `scope_guidance`, and `seed_areas` are required text; `systems_of_record` is optional. The library supplies the rest of the prompt.
- **`Identity`** maps each scope name to a `ScopeGrant(entity_id, role)`. The entity ID becomes the second path segment: this identity's user files live under `user/u-me/`.
- **`MemoryStore`** holds the rules (size limits, versioning, index ordering) over a `Storage`. `scope_priority` decides which scopes the size-capped startup index keeps first.
- **`InProcessClient`** is the `TransportClient` that calls the store directly.
- **`ScopePolicy({})`** restricts no scope. Reads are never role-restricted.
- **`source`** is stamped into each file's `sources` metadata. **`product`** names your product in each tool description.
- **`credentials_from_context`** reads the caller's credentials from each MCP request. With `SandboxResolver` they are ignored; see [customize](customize.md#identity) for real resolvers.

Check that it builds without starting it:

```
python -c "import server; print(server.server)"
```

> **In-memory storage does not persist.** A stdio server runs as a fresh process for each client session, so everything it stored is gone when the session ends. Use GCS for anything you want to keep.

## 3. Persist in GCS {#gcs}

Swap `InMemoryStorage` for `GcsStorage`. It takes a `google.cloud.storage.Bucket`; the bucket must already exist.

<!--include python quick_gcs.py-->

How it stores data: one GCS object per file at `{scope}/{entity_id}/{area}/{name}.md`, the markdown body as the object data, and `description`, `aliases`, `sources`, and `last-updated` as custom object metadata. The version token is the object's GCS generation.

Application Default Credentials come from `gcloud auth application-default login` locally, or from the attached service account on Google Cloud. The identity needs permission to read, create, overwrite, delete, and list objects in the bucket (for example `roles/storage.objectAdmin` on it). Replace `my-gcp-project` and `my-wenchang-memory` with your own.

### Local development with fake-gcs-server {#emulator}

Run the emulator that the repository's integration tests use:

```
docker run -d --rm --name wenchang-fake-gcs -p 4443:4443 fsouza/fake-gcs-server -scheme http -port 4443
```

(From a clone of the repository, `make emulator-up` runs the same command.) Then replace the `bucket = ...` lines of the GCS server with an anonymous client pointed at the emulator, creating the bucket on first use:

<!--include python emulator_block.py-->

Keep the `store = MemoryStore(GcsStorage(bucket), ...)` line and the rest of the file unchanged. Stop the emulator with `docker stop wenchang-fake-gcs`; its data is ephemeral.

## 4. Connect your MCP client {#connect}

Register the script as a stdio server. Use the Python interpreter that has wenchang installed, and absolute paths.

For Claude Code, from the command line:

```
claude mcp add memory -- /path/to/venv/bin/python /path/to/server.py
```

This registers the server for you only (the default `local` scope). Add `--scope project` to write it to the project's `.mcp.json` for everyone, or `--scope user` for all your projects. Or write a project-level `.mcp.json` by hand:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

If you use uv, `"command": "uv"` with `"args": ["run", "--directory", "/path/to/project", "python", "server.py"]` works the same way; the repository's own `evals/mcp.json` does this for its eval server.

Any other MCP client that can launch a stdio command takes the same two values: a command and its arguments. Over HTTP, see [Customize: identity](customize.md#identity).

The server advertises the seven tools and delivers the memory prompt two ways: as the server's `instructions`, and as the resource `wenchang://memory-prompt` for clients that drop `instructions`. In Claude Code the tools appear as `mcp__memory__get_memory_index`, `mcp__memory__read_file`, and so on; `/mcp` shows the server's status.

## 5. Talk to your agent {#talk}

Start a session in your client and tell the agent something worth keeping:

> I prefer bar charts for my weekly reports.

The agent should call `get_memory_index` first, then file the preference, for example with `write_file` under `user/preferences/`. Start a new session and ask:

> Which chart type should I use for this week's report?

It should read the index, open the file, and answer from it. With GCS storage you can also browse the bucket: you will see `user/u-me/preferences/....md` objects whose custom metadata carries the description and aliases.

What you will not see: wenchang does not search file contents. The agent finds files through each file's `description` and `aliases`, which it writes along with each fact.

## Next {#next}

- [Usage](usage.md): five walkthroughs with the exact tool calls.
- [Customize](customize.md): real identities, scope policies, prompt slots, limits, telemetry.
- [Reference](reference.md): every tool and error.
