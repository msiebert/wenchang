# Implementation Plan: Cover FileQuotaExceededError in the transport conformance suite

**Linear**: AIE-1322 | **Spec**: `specs/AIE-1322-conformance-file-quota/spec.md`

## Public interface (all in `src/wenchang/testing/transport_conformance.py`)

```python
MIN_FILES_PER_ENTITY: Final = 32  # beside MIN_FILE_BYTES / MIN_INDEX_BYTES

def check_files_per_entity(name: str, value: object) -> int | None:
    """Return None, or value if it is an exact int (not bool) of at least
    MIN_FILES_PER_ENTITY; else fail with check_positive_int's messages:
      "<name>: fixture max_files_per_entity must be an int, got <Type>"
      "<name>: fixture max_files_per_entity must be at least 32, got <n>"
    None is checked first (returns None before any int check)."""

class TransportConformance:
    @pytest.fixture(name="max_files_per_entity")
    def _max_files_per_entity(self) -> int | None:
        """The store's max_files_per_entity, or None (default) to skip the file-cap case."""
        return None

    def test_client_satisfies_protocol(
        self, client, source, scope_map, max_file_bytes, index_max_bytes,
        scope_priority, list_page_size, max_files_per_entity: int | None,
    ) -> None:
        # existing seven checks unchanged and in order, then:
        # cap = check_files_per_entity(name, max_files_per_entity)
        # if cap is not None and cap < page_size + 2:
        #     pytest.fail(f"{name}: fixture max_files_per_entity must be at least "
        #                 f"list_page_size + 2 ({page_size + 2}), got {cap}")

    def test_create_at_file_cap_is_quota_exceeded(
        self,
        client: TransportClient,
        source: str,
        scope_map: Mapping[str, str],
        max_files_per_entity: int | None,
    ) -> None:
        """At max_files_per_entity, a create raises FileQuotaExceededError and stores nothing."""
```

The default fixture's underscore name keeps it out of the public-methods
listing test; pytest resolves it by `name=`, so subclass fixtures named
`max_files_per_entity` override it. `check_files_per_entity` and
`MIN_FILES_PER_ENTITY` are module-level public names like the other `check_*`
helpers and `MIN_*` constants; `wenchang.testing.__all__` is
`["ResolverConformance", "TransportConformance"]` and stays unchanged, so
`tests/test_testing_package.py` needs no change. The US3.5 self-test asserts
the exact page-size floor message.

### Case algorithm

1. `name = _name(type(client))`; `check_client`; `src = check_source`;
   `scopes = check_scope_map`; `limit = check_files_per_entity(name, max_files_per_entity)`.
2. If `limit is None`: `pytest.skip(...)` with a reason containing
   `max_files_per_entity` and how to enable it. Before `require_fresh`: a skipped
   run makes no store call.
3. `require_fresh(name, client, scopes)`.
4. `second = sorted(scopes)[1]`; `metadata = _meta(sources=frozenset({_seed(src)}))`.
5. For `i in range(limit)`: `path = probe_path(name, _PROBE_LABEL, scopes, second,
   PROBE_AREA, f"{PROBE_STEM}-{i}")`, label `f"write_file({path})"`; call
   `client.write_file(path, "- [stated] a\n", metadata, None, source=src)` in
   `try/except Exception as exc`: if `type(exc) is FileQuotaExceededError` →
   `_fail(name, label, "unexpected error: FileQuotaExceededError; check the
   max_files_per_entity fixture")`; else `_fail(name, label, f"unexpected error:
   {_name(type(exc))}")`. Both inside the except block (chained context, as
   `_call`). Results are not validated.
6. `p = probe_path(..., second, PROBE_AREA, f"{PROBE_STEM}-{limit}")`;
   `expect_error(name, f"write_file({p})", lambda: client.write_file(p,
   "- [stated] a\n", metadata, None, source=src), FileQuotaExceededError,
   _RECOVERABLE, message=str(FileQuotaExceededError(p, limit)), path=p, limit=limit)`.
7. `_expect_absent(name, client, p)` (label `read_file(<p>)`).

### expect_error hint

When `expected is FileQuotaExceededError` and the call returned, append
`"; check the max_files_per_entity fixture"`. The `OversizeWriteError` hint is
unchanged; other types get no hint.

### Placement and docstring

New case in the "Error parity" section after
`test_error_messages_carry_category_guidance`. Module docstring fixture list
gains an entry: `max_files_per_entity` optional; the store's
max_files_per_entity (None, the default, or an int of at least
max(32, list_page_size + 2)); None skips the file-cap case.

## Tests (test-writer, `tests/**`)

New tests (docstrings carry AIE-1322 and the US number):
- Self-tests for US1.3–US1.9 using broken clients wrapping a real
  `InProcessClient` over a capped store (follow `_StoresThenRejectsOversize`
  and the `_case_fails` helpers), asserting `Name: label: phrase`.
- `expect_error`-level test for the quota hint, mirroring
  `test_expect_error_oversize_did_not_raise_hints_fixture`.
- US2.1: subclass without the fixture → new case skipped with reason containing
  `max_files_per_entity`, no write calls recorded (`_RecordsWrites`), protocol
  case passes. US2.3: subclass override is picked up; base default is `None`;
  `_max_files_per_entity` is not public.
- US3: `None`/32 pass; `True`, `"32"`, `32.0`, `0`, `31` fail with
  `fixture max_files_per_entity` in both the protocol case and the new case
  (the new case needs its own bad-fixture test; `USED_BAD_FIXTURES` iterates
  only `STATEFUL_CASES`); bad value fails rather than skips. US3.5: cap 40 with
  page size 40 fails the protocol case with the stated message; cap 32 with
  page size 30 passes.

Existing-test edits (per spec Allow-test-changes):
- `tests/test_transport_conformance_reference.py`: store
  `max_files_per_entity=MAX_FILES_PER_ENTITY` (32), fixture override, add
  the case to `ERROR_PARITY_CASES`, docstrings cite AIE-1322.
- `tests/test_transport_conformance_cached.py`: same store config + override.
- `tests/test_transport_conformance_self.py`: `FIXTURE_ORDER` eighth entry,
  `_fixtures` key, capped reference store, `BAD_FIXTURE_VALUES`,
  `FIXTURE_PAIRS`, `BAD_FIXTURES` rows, rename
  `test_every_case_takes_only_the_seven_fixtures` → `..._eight_fixtures`.
- `tests/test_transport_conformance_cases_self.py`: `_fixtures` key and capped
  `_reference()` so the new case counts as unskipped.

## Docs

- doc-updater: ARCHITECTURE.md testing entry (≈ lines 718-760, 790, 944):
  "seven required fixtures" → seven required plus one optional, explicitly
  naming the departure from "every fixture required from the first run";
  validation order; floor `max(32, list_page_size + 2)`; case count 43 → 44;
  the new case. New ADR `docs/adr/0045-conformance-file-cap-case.md`
  (renumber at PR time if taken): optional fixture with `None` default + skip;
  supersedes in part ADR 0039 decision 8 and its consequence; amends ADR 0021
  decision 7a and ADR 0023's "seven fixtures"; rejected: required fixture
  (breaks adopters), default 500 (500 writes per run, fails adopters with other
  caps), separate capped-client fixture (more adopter surface). One-line
  "Amended by ADR 0045" notes on ADR 0021, 0023, 0039. review-pr.md.
- general-purpose: `site-src/reference.md` conformance bullet mentions the
  optional fixture; regenerate `site/` with `uv run scripts/build_site.py`.

## Constitution / risk

- No runtime, core, or storage change. Public testing API gains an optional
  fixture, a constant, a helper, and a case (constitution VII → ADR +
  ARCHITECTURE). Existing adopter subclasses keep passing with one new skipped
  test.
- No test deleted or weakened; existing-test edits listed in spec.
