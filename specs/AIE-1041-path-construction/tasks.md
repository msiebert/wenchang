# Tasks: Path construction from scope and entity ID

**Linear issue**: AIE-1041 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

Each task runs test-writer (failing tests), then implementer (make them
pass), then a green `make check`, in order.

## T1 — build_path, build_prefix, parse_path

Add `PathParts`, `build_path`, `build_prefix`, and `parse_path` to
`src/wenchang/paths.py`, following the validation rules, error table, and
algorithm in plan.md. Do not change `is_valid_path` or `is_valid_prefix`.

Precondition: AIE-1043 is merged (or its branch is the base), so
`paths.is_valid_segment` is public and rejects `"/"`. If not, stop and
report. Do not add a local `"/"` check.

Acceptance: spec US1.1–7, US2.1–7, US3.1–4, US4.1–2. New file
`tests/test_paths_build.py`; `tests/test_paths.py` is unchanged. Covers
FR-001–FR-007. Each test docstring cites AIE-1041 and its scenario ID, e.g.
`(AIE-1041, US2.4)`.

## T2 — Docs

doc-updater updates the ARCHITECTURE.md `paths` entry and writes
`docs/adr/0015-path-construction.md` from the decisions listed in plan.md.
