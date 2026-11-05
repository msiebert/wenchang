# Tasks: AIE-1335 filesystem storage backend

Tests first; implementation never edits `tests/`. Run `make check` at the end.

- [x] T1 — test-writer: `tests/test_storage_filesystem.py`. A `storage`
  fixture on `tmp_path`, `TestFilesystemStorage(StorageConformance)` and
  `TestFilesystemEntityPurgeExport(EntityPurgeExportConformance)` (AC1,
  AC17). Tests fail until T2 exists (import error is acceptable red).
- [x] T2 — test-writer: filesystem-specific tests in the same file: layout and
  readability (AC3), coexisting `a` / `a/b` (AC4), key-escape safety (AC5),
  invalid keys (AC6), token non-reuse (AC7), fresh instance on same root
  (AC8), cross-instance threads (AC9), cross-process (AC10), orphan body and
  temp files (AC11), ordering and paging (AC12), no body reads (AC13), missing
  key (AC14), error mapping (AC15), root creation (AC16).
- [x] T3 — test-writer: `tests/test_storage_filesystem_memory_store.py`,
  MemoryStore end to end on `FilesystemStorage` (AC2).
- [x] T4 — implementer: `src/wenchang/storage/filesystem.py` per `plan.md`
  (`FilesystemStorage`, `InvalidStorageKeyError`); make T1 to T3 pass (AC1 to
  AC17).
- [x] T5 — doc-updater: update `ARCHITECTURE.md` storage sections and diagram;
  add the next-numbered ADR (amends ADR 0003: a test/local-dev backend held to
  the conformance suite, not a production provider hedge) and an amendment note
  in ADR 0003; check `docs/product/glossary.md` (no new product term expected);
  draft `review-pr.md` (AC19).
- [ ] T6 — `make check` green (AC18).
