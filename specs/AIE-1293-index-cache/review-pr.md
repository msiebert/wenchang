# PR Review: AIE-1293 — Optional adopter-injected cache for get_memory_index

## What changed & why

`get_memory_index` listed every granted `{scope}/{entity_id}/` prefix on every
call. Adopters can now pass `MemoryStore(..., index_cache=IndexCache(get=...,
set=..., ttl=...))`, backed by any key-value store. New module
`wenchang.index_cache` (`IndexCache`, `InMemoryIndexCache`,
`DEFAULT_KEY_PREFIX`). `core` caches each entity's listing under a generation
token, invalidates after every `put_if_version`/`delete_if_version`, and adds
`invalidate_index(scope, entity_id)`. Without a cache, behavior is unchanged.

## Acceptance criteria → tests

| Acceptance criterion | Test(s) |
| -------------------- | ------- |
| US1.1–1.4 config defaults, type/value checks, `str` subclass prefix | `tests/test_index_cache.py`: `test_defaults`, `test_wrong_types_raise_type_error`, `test_type_error_precedes_value_error`, `test_non_positive_ttl_raises_value_error`, `test_str_subclass_key_prefix_is_stored_as_exact_str` |
| US1.5–1.6 store rejects non-`IndexCache`; property | `test_store_rejects_non_index_cache`, `test_store_index_cache_property` |
| US2 no cache: lists every call; `invalidate_index` no-op | `test_no_cache_lists_every_call`, `test_no_cache_invalidate_index_is_a_no_op` |
| US3 repeat call: zero `list_page`; cached == uncached (cap, priority, offsets, paging, malformed keys) | `test_second_call_makes_no_list_page_calls`, `test_empty_entity_is_cached`, `test_cached_index_equals_uncached_with_cap_priority_and_offsets`, `test_multi_page_listing_is_cached`, `test_malformed_key_absent_from_cached_index` |
| US4 writes/deletes visible; only that entity re-lists; failed mutation still invalidates; tombstones; arg validation | `test_create_visible_on_next_index`, `test_update_visible_on_next_index`, `test_delete_tombstones_listing_and_omits_file`, `test_mutation_relists_only_its_entity`, `test_failed_mutation_still_invalidates`, `test_replace_fact_retry_reflects_committed_version`, `test_invalidate_index_tombstones_and_relists_only_that_entity` (also asserts the token is replaced, before the tombstone), `test_invalidate_during_listing_is_seen_by_next_call`, `test_invalidate_index_rejects_*` |
| US5 races (deterministic hooks), threads, two hosts, evictions, ttl skew, prefix isolation | `test_write_during_listing_is_seen_by_next_call`, `test_delete_during_listing_is_seen_by_next_call`, `test_threaded_writers_and_reader_converge`, `test_two_hosts_share_cache`, `test_racing_first_readers_*`, `test_index_during_put_does_not_hide_write`, `test_index_during_delete_does_not_hide_delete`, `test_lost_token_key_relists`, `test_lost_listing_key_relists_and_keeps_token`, `test_token_expiring_before_listing_relists`, `test_distinct_key_prefixes_isolate_storage_roots` |
| US6 out-of-band writes stale within `ttl`, fresh after `ttl` or `invalidate_index`; `ttl` passed through | `test_out_of_band_write_*`, `test_every_set_receives_configured_ttl` |
| US7 cache failures/bad values: fallback, logs scope not entity, `invalidate_index` propagates, garbage is a miss | `test_get_failure_falls_back_and_logs_scope_not_entity`, `test_bytes_from_get_is_a_logged_miss`, `test_set_failure_does_not_*`, `test_invalidate_index_propagates_set_failure`, `test_invalid_listing_value_is_a_miss`, `test_tombstone_under_current_token_is_a_miss`, `test_corrupt_metadata_raises_and_stores_nothing`, `test_base_exception_from_*_propagates`, `test_invalid_scope_map_errors_match_uncached_with_no_cache_call` |
| US8.1–8.3 `InMemoryIndexCache` expiry | `test_in_memory_*` in `tests/test_index_cache.py`, including `test_in_memory_overflowing_ttl_never_expires` (`timedelta.max` ttl neither raises nor expires) |
| US8.4 transport conformance on a cached store | `tests/test_transport_conformance_cached.py` (an autouse fixture fails the run on any `pytest.skip`, so no conformance case is silently skipped) |

## Architecture / ADR changes

- New [ADR 0040](../../docs/adr/0040-index-cache.md): decision, rejected
  alternatives, token protocol and proof sketch, failure policy, `ttl`,
  constitution principle V, privacy.
- `ARCHITECTURE.md`: module count/intro, new `index_cache` entry, `core`
  entry (constructor arg, property, cached index, mutation invalidation,
  `invalidate_index`), diagram notes, new key invariant.
- Glossary: "Index cache".

## Deviations from spec

- None.

## Look closely at

- **Proof sketch** (ADR 0040 decision 3) against `_cached_entity_entries`
  and `_put_if_version`/`_delete_if_version` in `core.py`: the token is
  observed before `_drain`, and invalidation is in `finally` after the
  storage call.
- **`ttl=None` is unbounded staleness** after a swallowed invalidation
  failure or an out-of-band write. Docs recommend a finite `ttl`.
- **Timed-out write hole** (documented, not closed): a write that raised
  `BackendUnavailableError` can still commit server-side after the
  `finally` replaced the token; a reader can then cache a pre-commit
  listing under the fresh token, stale until the entity's next write or
  `ttl` (unbounded with `ttl=None`). See ADR 0040 decisions 3, 4, 10.
- **`key_prefix` must be prefix-free** across stores sharing one cache,
  since scope and entity segments may contain `":"`. Not validated at
  runtime; documented in the `IndexCache` docstring, ADR 0040 decision 7,
  and ARCHITECTURE.md.
- **Remaining delete/purge race**: a reader that listed pre-delete can
  store pre-delete metadata after the tombstone. It is never served, but it
  persists until re-index or `ttl`. A finite `ttl` is required for erasure
  obligations.
- **Linearizability**: per-key linearizability is a stated requirement. A
  weaker cache (e.g. replica reads) bounds freshness only by `ttl`.
- **Privacy**: cache values hold descriptions/aliases/sources, and keys hold
  entity IDs. Check that no log line includes an entity ID or key.

## Follow-ups

- AIE-1291 (purge) must call `invalidate_index` after all its deletes finish.
- Seeding/admin writers that bypass the cache should call `invalidate_index`.
