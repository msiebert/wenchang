# Tasks: AIE-1293 Optional adopter-injected index cache

Tests first for each task; implementation never edits `tests/`.

- [ ] T1 — `index_cache` module. Tests: US1.1–1.4, US8.1–8.3
  (`tests/test_index_cache.py`). Implement `IndexCache`,
  `InMemoryIndexCache`, `DEFAULT_KEY_PREFIX` in `src/wenchang/index_cache.py`.
- [ ] T2 — `MemoryStore` wiring and cached reads. Tests: US1.5–1.6, US2,
  US3, US6.4, US7 (`tests/test_core_index_cache.py`). Implement the
  constructor argument, `index_cache` property, token/listing keys, value
  encode/decode, cached `get_memory_index`, logged-and-swallowed cache calls.
- [ ] T3 — Invalidation. Tests: US4, US6.1–6.3. Implement `_invalidate_path`
  in a `finally` around every `put_if_version`/`delete_if_version`, and
  public `invalidate_index`.
- [ ] T4 — Concurrency. Tests: US5 (deterministic hook tests 5.1, 5.2,
  5.4–5.11, which carry the proof; threaded 5.3 as a smoke test). Expected
  to pass on T2+T3; fix implementation if not.
- [ ] T5 — Conformance with cache. Test: US8.4.
- [ ] T6 — Docs: ADR 0040, ARCHITECTURE.md, review-pr.md. `make check` green.
