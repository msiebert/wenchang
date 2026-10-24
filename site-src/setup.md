# Setup

This page takes you from nothing to an MCP server that stores memory in GCS and works in Claude Code. The setup is for one developer or a small team that trusts each other. For a server with real users, finish here and then read [Authorization](authorization.md).

wenchang is a library. It has no command line tool, no ready-made server, and no configuration file. You write a short `server.py`.

## What you need {#needs}

- Python 3.12 or newer.
- A GCP project and a GCS bucket for memory files.
- An MCP client that can launch a stdio server, such as Claude Code.

## 1. Install {#install}

wenchang is not on PyPI. Install it from git into the environment the server will run in. The `mcp` extra adds the MCP adapter (`mcp>=2.2,<3`).

```
pip install "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"
```

With uv: `uv add "wenchang[mcp] @ git+https://github.com/msiebert/wenchang"`.

## 2. Create the bucket {#bucket}

Memory files are objects in one bucket. Create it and give your credentials access:

```
gcloud storage buckets create gs://hanlin-inkwell-memory --project my-gcp-project --location us-central1 --uniform-bucket-level-access
gcloud auth application-default login
gcloud storage buckets add-iam-policy-binding gs://hanlin-inkwell-memory --member user:tianlong@example.com --role roles/storage.objectUser
```

wenchang finds credentials through Application Default Credentials. Locally that is the `gcloud auth application-default login` above. On Google Cloud it is the attached service account. Whatever identity the server runs as needs to read, create, overwrite, delete, and list objects in the bucket. `roles/storage.objectUser` grants those on the bucket.

<!--html-->
<div class="callout"><strong>One bucket, many people.</strong> Every user and project writes into the same bucket under their own path prefix. Access control between users is wenchang's scope rules, not bucket permissions. Anyone who can read the bucket directly can read all of it.</div>
<!--/html-->
<!--md-->
> **One bucket, many people.** Every user and project writes into the same bucket under their own path prefix. Access control between users is wenchang's scope rules, not bucket permissions. Anyone who can read the bucket directly can read all of it.
<!--/md-->

## 3. Write the server {#server}

This `server.py` uses GCS storage, three scopes (the author, the manuscript, the publisher), and settings from environment variables.

<!--include python setup_server.py-->

What each part does:

- **`PromptSlots`** is the text that tells the agent about your deployment. See [Customizing the prompts](prompts.md).
- **`Identity`** says who the caller is: one `ScopeGrant(entity_id, role)` per scope. The entity ID becomes the second path segment, so this user's private files live under `user/<their id>/`. Here the identity comes from the environment and is trusted. [Authorization](authorization.md) replaces this with a resolver that verifies each request.
- **`MemoryStore`** applies the rules (size limits, versioned writes, index order) on top of a `Storage`. `GcsStorage` is the storage that talks to your bucket. `scope_priority` decides which scopes the size-capped startup index keeps first.
- **`InProcessClient`** connects the tools to the store in the same process.
- **`ScopePolicy`** lists the roles that may write a scope. Here only `admin` and `owner` may write `organization`, and the identity above is a plain `member`, so the agent can read the press's files and cannot change them. Scopes not listed are open to anyone with a grant. Writes to `system/` are always refused.
- **`source`** is recorded in each file's `sources` metadata, so you can tell which app wrote what. **`product`** puts your product's name in each tool description.

Check that it builds, without starting it:

```
WENCHANG_USER=u-tianlong WENCHANG_PROJECT=p-ninth-examination WENCHANG_ORG=o-hanlin-press WENCHANG_BUCKET=hanlin-inkwell-memory python -c "import server; print(server.server)"
```

## 4. Register it with your client {#client}

A stdio MCP client starts the server as a child process. Give it the interpreter that has wenchang installed, an absolute path to the script, and the environment the script reads.

For Claude Code, put this in the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/server.py"],
      "env": {
        "WENCHANG_BUCKET": "hanlin-inkwell-memory",
        "WENCHANG_ORG": "o-hanlin-press",
        "WENCHANG_PROJECT": "p-ninth-examination",
        "WENCHANG_USER": "u-tianlong"
      }
    }
  }
}
```

`WENCHANG_USER` differs per person, so in a shared repo keep that one out of `.mcp.json` and set it per person. The same registration from the command line, for just you:

```
claude mcp add memory -e WENCHANG_BUCKET=hanlin-inkwell-memory -e WENCHANG_ORG=o-hanlin-press -e WENCHANG_PROJECT=p-ninth-examination -e WENCHANG_USER=u-tianlong -- /path/to/venv/bin/python /path/to/server.py
```

The server sends the memory prompt as its `instructions`, and also serves it as the resource `wenchang://memory-prompt` for clients that ignore `instructions`. In Claude Code the tools show up as `mcp__memory__get_memory_index`, `mcp__memory__read_file`, and so on. `/mcp` shows whether the server connected.

## 5. Try it {#try}

Tell the agent something worth keeping:

> Lin Qiao has grey eyes and grew up in Yunmen, a river town.

It should call `get_memory_index`, then write a file. Start a new session and ask for a scene with Lin Qiao. It should read the index, open the file, and use what it saved. Look at what was stored:

```
gcloud storage ls --recursive gs://hanlin-inkwell-memory/project/p-ninth-examination/
```

Each object is a markdown file. The description and aliases are in the object's custom metadata. If nothing is written, check that the agent listed the memory tools and read the server's `instructions`. Memory is only as good as the prompt, so also read [Customizing the prompts](prompts.md).

## Seed curated content {#seed}

The `system/` area holds content that people maintain. Here that is Hanlin Press's house style. The agent can read it but cannot write it. You write it with a script that uses the store directly, which has no `system/` restriction.

<!--include python setup_seed.py-->

Seeded files appear in the agent's index like any others, and the `system/` entries come first.

## Run it without GCS {#local}

For development, `InMemoryStorage()` from `wenchang.storage.memory` replaces `GcsStorage(bucket)`. Everything is lost when the process exits, and a stdio server starts a fresh process for every client session, so it forgets between sessions.

To test against the real GCS API locally, run the emulator the repository's integration tests use:

```
docker run -d --rm --name wenchang-fake-gcs -p 4443:4443 fsouza/fake-gcs-server -scheme http -port 4443
```

Then point the client at it:

```python
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

client = storage.Client(
    project="test",
    credentials=AnonymousCredentials(),
    client_options={"api_endpoint": "http://localhost:4443"},
)
bucket = client.bucket("wenchang-dev")
if not bucket.exists():
    bucket = client.create_bucket("wenchang-dev")
```

## Next {#next}

- [Customizing the prompts](prompts.md): tell the agent about your scopes and areas.
- [Authorization](authorization.md): serve many users over HTTP.
