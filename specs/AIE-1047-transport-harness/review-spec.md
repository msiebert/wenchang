# Spec Review: AIE-1047 — shared transport conformance harness

## What & why

Notion §10.2 says the in-process and remote transports "must be
behaviorally indistinguishable" and that a shared suite exists mainly to
hold them so. This adds `wenchang.testing.TransportConformance`, the
pytest mixin an adopter subclasses with seven fixtures (`client`,
`source`, `scope_map`, and the four store settings), plus the shared
mechanics every case needs: fixture validation, `require_fresh`
(isolation sentinel under the first mapped scope's own entity in area
`conformance-sentinel`, called by every stateful case), `expect_error` (exact type + category + optional message +
exact-typed payload parity), deep exact-type canonical readers, and a
path builder. Tokens are never compared, only handed back; `last_updated`
is round-tripped between two server-stamped results, never against the
test's clock. Five baseline cases ship; AIE-1045 adds the rest of §10.2.

## Acceptance criteria

| # | Given | When | Then |
| - | ----- | ---- | ---- |
| 1 | reference fixtures over `InProcessClient` with a ticking clock | suite runs | five baseline cases pass, none skipped |
| 2 | any bad fixture | cases run | `fixture <name>`, first bad fixture in the fixed order |
| 3 | one shared stateful client | two different stateful cases | second fails `not isolated` naming the sentinel path |
| 4 | `expect_error` | exact type+category+payload / returns / wrong real type or spoof / wrong category / wrong message / payload wrong type (StrEnum vs str) or value / category mismatch with error kind | returns exc / `did not raise` (+ max_file_bytes hint) / `wrong error type` / `wrong category` / `wrong message` / `wrong payload` / `harness misuse` |
| 5 | canonical readers | nested field wrong exact type or naive datetime or empty version / wrong outer type | `bad field <name>` / `wrong result type` |
| 6 | harness module | `ast` scan | no compare, arithmetic, subscript, or non-client call on anything named `version` |
| 7 | round trip | write then read | six canonical fields equal between results incl. `last_updated`; expected content/metadata; `source not stamped` if the union is missing `source` |
| 8 | returned tokens | passed back as `expected_version` | accepted, else `token not accepted` |
| 9 | absent read, oversize write | baseline cases | parity via `expect_error` |
| 10 | each US4 broken client | its case | named phrase; reference client passes the same case |
| 11 | `wenchang.testing` | import | both suites exported; five method names |

## Key design decisions

| Decision | Alternatives rejected | Why |
| -------- | ---------------------- | --- |
| Same mixin + fixtures + `pytest.fail` shape as `ResolverConformance` | Differential harness | Tokens/timestamps differ between stores; canonicalization needed anyway |
| Seven fixtures incl. all four store settings | `settings` object; add later | AIE-1045 never changes the contract; validation lives here |
| Tokens never compared, even `==`; checked by handing back | `write.version == read.version` | §10.2 and `version_token.py` say never compare; a remote may return equivalent-but-different strings |
| `last_updated` round-trips between two server results | Drop it | §10.2 "all four metadata fields" |
| Deep exact-type readers | Duck typing | ADR 0019 deferred `MemoryFile`/`FileEntry`/`ListPage` hardening to this suite |
| `expect_error` with category rule, message, exact-typed payload | `pytest.raises`; `!=` payload | Names the client; rejects StrEnum/str lookalikes and spoofs |
| `require_fresh` in every stateful case, sentinel under the caller's own entity in area `conformance-sentinel`; `without_sentinel` / `sentinel_entry_bytes` for AIE-1045 | Single isolation case; factory fixture; unmapped entity | Fires in a real single run; valid under the enforcement decision (a) |
| `test_client_satisfies_protocol` requires and validates all seven fixtures | Lazy per-case validation | Contract enforced from day one |
| Ticking reference clock; sequential interleavings, no thread safety | Fixed clock; threads | Recency cases testable; no requirement nothing else needs |
| ADR 0021 (AIE-1044 moves to 0022) | — | 1044 is blocked on human decisions and lands later |

## Files/modules to be touched

- `src/wenchang/testing/transport_conformance.py` (new), `src/wenchang/testing/__init__.py`
- `tests/test_transport_conformance_reference.py`, `tests/test_transport_conformance_self.py` (new); additions to `tests/test_testing_package.py`
- `ARCHITECTURE.md`, `docs/adr/0021-transport-conformance-harness.md`

## Open questions / assumptions

- **Decided by the human on 2026-10-02: option (a).** §10.2's "`system/`
  writes rejected; role-restricted writes rejected" bullets vs an
  identity-agnostic transport whose in-process client accepts them.
  Options were (a) transport suite asserts *acceptance* and enforcement
  stays in tools/resolver suites; (b) run enforcement cases through the
  tool layer with identity fixtures; (c) leave unspecified. Under (a), a
  remote server must not enforce scope at the transport (authorization
  happens in the tool layer, where identity is known); ADR 0019 decision
  6 is amended and ADR 0021 records the decision. AIE-1045 adds
  `test_system_area_write_is_accepted_at_transport`. The harness itself
  needed no change: every mapped scope is writable through `client`
  (own-entity writes).
- Sentinel helpers take no `label`: `sentinel_path(scope_map)` takes
  neither `name` nor `label`; `require_fresh` and `sentinel_entry_bytes`
  take `(name, client, scope_map)` and build their own labels from the
  sentinel path or prefix (US2.0).
- Clock contract: a client must stamp strictly increasing `last_updated`
  across sequential writes in one test. `max_file_bytes` must be ≥ 64.
  Both stated in the module docstring.

## Risks

- Deep exact-type checks will fail a remote client that returns `list`
  aliases or a `set` of sources; that is the point, but it binds the wire
  decoding to core's exact value types.
- Any adopter whose server cannot guarantee a monotonic clock cannot run
  AIE-1045's recency cases.
