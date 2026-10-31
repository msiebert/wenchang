# Status and compatibility

## Version and requirements

| Item | Value |
| --- | --- |
| Version | 0.1.0 |
| License | MIT |
| Python | Python 3.11 or newer |
| Dependencies | `google-cloud-storage>=2.18` |
| `mcp` extra | `mcp>=2.2,<3`, for `wenchang.mcp`. Targets `mcp.server.mcpserver.MCPServer` only; FastMCP and mcp 1.x servers do not work. |
| `testing` extra | `pytest>=8.3`, for the conformance suites in `wenchang.testing`. |

wenchang is installed from git. It is not published on PyPI. The base package works without the `mcp` extra; see [Integrate without MCP](integrate-without-mcp.md).

## Releases and versioning

Releases are git tags named `vX.Y.Z`, each with a GitHub Release. There is no PyPI release. Changes are recorded in [`CHANGELOG.md`](https://github.com/msiebert/wenchang/blob/main/CHANGELOG.md) in the Keep a Changelog format, and the release process is in [`docs/releasing.md`](https://github.com/msiebert/wenchang/blob/main/docs/releasing.md).

Versions follow SemVer over the public surface: the modules, functions, classes, arguments, tool names and schemas, error payloads, and stored format documented on this site.

- While the major version is 0, a breaking change bumps the minor version, and any other change bumps the patch version.
- A change to the shipped prompt wording is at least a minor release, because it can change what agents store.
- A tag is never moved once released.

## Known limitations

- **A library, not a server.** There is no CLI, console script, or ready-made server binary. You supply the identity resolver, scope policy, prompt slots, and a short server script or tool registration. The only server in the repository is the dev-only eval server (`python -m evals.server`), which uses in-memory storage.
- **GCS only.** `GcsStorage` is the only durable backend. `InMemoryStorage` is a fake for tests and trials.
- **No remote transport.** The only `TransportClient` is `InProcessClient`, which calls a `MemoryStore` in the same process. Tools and storage access always run in your process.
- **No content search.** Files are found through `description` and `aliases`. The quality of that metadata is what makes recall work.
- **Not snapshots.** `list_prefix` and `get_memory_index` are not point-in-time snapshots: a file written or deleted while an index is being built may or may not appear. `export` has the same property.
- **Reads are never role-restricted.** A caller can read any area (including `system/`) of any scope it holds a grant for. `ScopePolicy` gates writes only.
- **Privacy is prompt-level.** The prompt tells the agent to refuse financial account numbers, health diagnoses, and anything indicating the user is a minor, and to be stricter in shared scopes. No tool checks content, so a successful write does not mean the content was safe.
- **Behavior depends on the agent.** Where facts get filed, and how well, is up to the model following the prompt. The repository's behavioral evals run scripted scenarios against a real agent and grade what it stored; they are signal for prompt iteration, not release gates.
- **Concurrency is the caller's concern.** MCP tool calls run concurrently on worker threads and share one client. wenchang's own objects are safe to share, but google-cloud-storage does not document `storage.Client` as thread-safe; see [Threads](integrate-without-mcp.md#threads). Direct calls are synchronous and block on storage.
- **The file cap is soft.** Concurrent creates in one entity can pass `max_files_per_entity`; see [Files per entity](storage.md#file-cap).
- **No timeout or retry settings.** `GcsStorage` uses google-cloud-storage's defaults. A GCS outage that outlasts its retries raises an unmapped `RetryError`, which the agent sees as an `internal` error, not a `transient` one; see [Timeouts and retries](storage.md#retries).

---

HTML version: <https://msiebert.github.io/wenchang/status.html>
