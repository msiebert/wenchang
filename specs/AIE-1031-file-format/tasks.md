# Tasks: File format and metadata — parse and serialize (AIE-1031)

**Input**: [spec.md](spec.md), [plan.md](plan.md)

Tasks run in order. Each is test-writer (tests in
`tests/test_file_format.py`) then implementer (`src/wenchang/file_format.py`).
`make check` green after each.

## T1 — Confidence labels and fact lines

Build `ConfidenceLabel`, `Fact`, `format_fact`, `parse_fact` per plan.md.

Acceptance: spec US1 scenarios 1–6; edge cases on whitespace-only text,
leading spaces in text, nested bracketed label, `\r` kept in text, leading
indentation; every row of plan.md's `parse_fact` examples table;
`parse_fact(format_fact(f)) == f`.

## T2 — Body parse and serialize

Build `BodyLine`, `parse_body`, `serialize_body`.

Acceptance: spec US1 scenario 3 (other lines kept in position), US2
scenarios 1–6; edge cases `parse_body("") == ("",)`, `parse_body("\n") ==
("", "")`, empty sequence rejected by `serialize_body`, `\r\n` bodies
round-trip.

## T3 — File metadata and map conversion

Build `FileMetadata`, the four key constants, `MetadataFormatError`,
`metadata_to_map`, `metadata_from_map`.

Acceptance: spec US3 scenarios 1–11; `last-updated` encoding with and
without microseconds; a non-UTC aware timestamp encodes as the same instant
in UTC; `MetadataFormatError` is a `ValueError` and exposes `key`.

## T4 — Docs (doc-updater)

ARCHITECTURE.md: add `file_format` to the module map and narrow the planned
`core` entry to the API functions. ADR for the four decisions in plan.md, including that non-fact lines are
tolerated by the parser but never presented to the agent (prompts and tool
descriptions say files are facts only).
Glossary: "body line" / "metadata map" if useful. Draft `review-pr.md`.
