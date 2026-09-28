# 0007. Core API shape and storage layer

Date: 2026-09-28

## Status

Accepted

## Context

AIE-1032 delivers the first core API function, `read_file`, and — since no
storage issue exists yet and `read_file` cannot be tested without one — the
internal storage layer it reads through (ADR 0003 set the protocol's shape;
this issue implements it). Several points needed a decision beyond a literal
reading of the Notion spec and the Linear issue text.

## Decision

- **The core API is methods on a `MemoryStore` object constructed with a
  `Storage`, not free functions taking storage as an argument.** The Notion
  spec's "plain functions" reads as "no protocol/server awareness," not as a
  ban on grouping them under one object. Later core functions need their own
  configuration (a size limit, an index cap), and the in-process transport
  wraps one object; a `MemoryStore` gives both a home without threading extra
  parameters through every call. Rejected alternative: `read_file(storage,
  path)` and siblings as module-level functions, which would need a second
  mechanism for shared configuration.
- **`{root}` in the Notion path layout is the storage instance itself** — for
  GCS, one bucket — and every path given to `core` is relative to it, used
  unchanged as the storage key. Rejected alternative: a configurable key
  prefix inside one shared bucket now; deferred as YAGNI since it can be
  added later without changing any caller.
- **A well-formed path is exactly four segments**,
  `{scope}/{entity_id}/{area}/{name}.md`; nested areas are not valid. This
  matches the Notion path layout as given and keeps `is_valid_path` a flat
  segment-count check. Relaxing it later to allow nested areas is a
  compatible change.
- **The storage protocol carries `VersionToken` directly; only `GcsStorage`
  converts it to and from a generation number.** No other module parses a
  token, keeping the conversion in exactly one place, consistent with the
  token's opacity everywhere else in the library.
- **A corrupt stored object raises a `ValueError` subclass, not a taxonomy
  error.** A metadata map that fails to parse (`MetadataFormatError`, from
  AIE-1031) or bytes that are not valid UTF-8 (`UnicodeDecodeError`) indicate
  a data-integrity failure, not a condition the calling agent can repair by
  correcting its own request — consistent with ADR 0006. `read_file` lets
  both propagate unchanged rather than wrapping them in a `NotFoundError` or
  a new taxonomy error.
- **`put` is unconditional in this issue.** The `Storage` protocol gets
  exactly `get` and `put` so tests (and `read_file` itself) can place
  objects; a generation-match precondition and the version-conflict path are
  AIE-1033's scope (`write_file`).
- **`GcsStorage.get` pins its download to the generation `get_blob` fetched**
  (`download_as_bytes(if_generation_match=blob.generation)`), so content and
  metadata always come from the same write rather than two independent calls
  that could straddle a concurrent write. If the object changed or vanished
  between the two calls (`PreconditionFailed` / `NotFound` on download), `get`
  retries from `get_blob` up to three attempts total, then raises
  `BackendUnavailableError(UNAVAILABLE)` — treating a persistent generation
  race as backend unavailability rather than surfacing GCS's precondition
  error directly. Rejected alternative: two unpinned calls (`get_blob` then
  `download_as_bytes` with no precondition), which cannot guarantee the
  bytes and metadata returned belong to the same write.

## Consequences

`read_file` and the storage layer it depends on can be tested end-to-end
against `InMemoryStorage` with no network, and the same conformance suite
(`tests/storage_conformance.py`) runs against `GcsStorage` and
`fake-gcs-server` to hold the two implementations identical. Folding the
storage layer into this issue makes the PR larger than a typical single-issue
change, a tradeoff made explicitly because `read_file` has no way to be
exercised without it. The four-segment path rule and single-bucket storage
root are both conservative readings that can be relaxed later (nested areas,
a key prefix) without breaking existing callers, since both are internal to
`paths` and `core` respectively. AIE-1033 (`write_file`) adds the
generation-match precondition `put` still lacks, and any conflict-handling
tests must account for `get`'s existing pinned-generation retry when
composing read-modify-write flows.
