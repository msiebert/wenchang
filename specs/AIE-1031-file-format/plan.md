# Implementation Plan: File format and metadata — parse and serialize

**Linear issue**: AIE-1031 | **Branch**: `AIE-1031-file-format` | **Date**: 2026-09-25 | **Spec**: [spec.md](spec.md)

## Summary

Add `wenchang.file_format`, a pure module with no I/O:

- `ConfidenceLabel` and a frozen `Fact` value type, plus `parse_fact` /
  `format_fact` for single lines.
- `parse_body` / `serialize_body`: body string ↔ tuple of lines, each a
  `Fact` or a verbatim `str`. Lossless for every input string.
- A frozen `FileMetadata` value type and `metadata_to_map` /
  `metadata_from_map`: the four fields ↔ a flat `dict[str, str]` (the shape
  of GCS custom object metadata). Malformed maps raise `MetadataFormatError`.

## Technical Context

**Language/Version**: Python ≥ 3.12

**Primary Dependencies**: standard library only (`dataclasses`, `datetime`,
`enum.StrEnum`, `json`, `re`)

**Storage**: N/A — pure conversion; the storage layer calls this later

**Testing**: pytest, `@pytest.mark.unit`; pyright strict; ruff

**Project Type**: library

**Constraints**: no imports from storage, transport, scope, or any agent
framework (FR-007); does not import `wenchang.errors` (malformed metadata is
a data-integrity `ValueError`, not an agent-facing taxonomy error)

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | Each task is test-writer → implementer |
| IV. Strict typing | All public types and functions fully annotated |
| V. Storage only through interface | N/A — no storage |
| VI. Spec fidelity | Decisions below go in an ADR |
| VII. Architecture documented | New public module `wenchang.file_format` → ARCHITECTURE.md update + ADR |
| VIII. Traceability | Test docstrings reference AIE-1031 |

**Decisions to record in an ADR (interpretations of the Notion spec):**

1. Metadata lives beside the body in object custom metadata, not as
   frontmatter inside the markdown.
2. The body parser is lenient and lossless: non-fact lines are kept
   verbatim, not rejected. This is robustness only: the intended format is
   facts only, and the prompt layer and agent-facing tool descriptions
   present files as fact lines only, never mentioning other line kinds.
   Whether `write_file` rejects non-fact lines is decided in that issue.
3. Map encoding: `aliases`/`sources` as JSON arrays, `last-updated` as
   ISO 8601 UTC with `Z`.
4. `file_format` is its own top-level module rather than living inside the
   planned `core` package, because storage and core both depend on it.

## Public interface

Module `src/wenchang/file_format.py`. Everything below is importable from
`wenchang.file_format`; nothing is re-exported from `wenchang` top level.

### Fact lines

```python
from dataclasses import dataclass
from enum import StrEnum


class ConfidenceLabel(StrEnum):
    STATED = "stated"
    OBSERVED = "observed"
    INFERRED = "inferred"
    SYSTEM = "system"


@dataclass(frozen=True)
class Fact:
    label: ConfidenceLabel
    text: str
    # __post_init__ raises ValueError if text contains "\n", or if text is
    # empty or whitespace-only (text.strip() == "").


def format_fact(fact: Fact) -> str: ...


# Returns f"- [{fact.label}] {fact.text}", e.g. "- [stated] x".


def parse_fact(line: str) -> Fact | None: ...


# Returns a Fact iff line is exactly: "- [" + one of the four lowercase
# labels + "] " + text, where text is the rest of the line (may contain
# anything except "\n", including leading spaces, brackets, and "\r") and
# text.strip() != "". Otherwise returns None. Never raises for any str
# without "\n". Invariant: parse_fact(format_fact(f)) == f.
```

Examples:

| line | result |
| ---- | ------ |
| `- [stated] a` | `Fact(STATED, "a")` |
| `- [stated]   a` | `Fact(STATED, "  a")` |
| `- [stated] [observed] a` | `Fact(STATED, "[observed] a")` |
| `- [stated] a\r` | `Fact(STATED, "a\r")` |
| `- [Stated] a`, `- [guessed] a`, `[stated] a`, `- [stated]a`, `- [stated]`, `- [stated] `, `- [stated]    `, `  - [stated] a`, `* [stated] a`, `# Heading`, `` | `None` |

### Body

```python
type BodyLine = Fact | str  # str = a non-fact line, kept verbatim


def parse_body(body: str) -> tuple[BodyLine, ...]: ...


# Splits on "\n" only (never str.splitlines). Each piece becomes
# parse_fact(piece) if that is not None, else the piece itself.
# Always returns at least one element: parse_body("") == ("",),
# parse_body("a\n") == ("a", "").


def serialize_body(lines: Sequence[BodyLine]) -> str: ...


# "\n".join(format_fact(l) if Fact else l). Raises ValueError if lines is
# empty, if any str element contains "\n", or if any str element would
# parse as a fact (parse_fact(s) is not None).
# Invariants: serialize_body(parse_body(s)) == s for every str s;
# parse_body(serialize_body(ls)) == tuple(ls) for every ls it accepts.
```

(`Sequence` from `collections.abc`.)

### Metadata

```python
from collections.abc import Mapping
from datetime import datetime

DESCRIPTION_KEY = "description"
ALIASES_KEY = "aliases"
SOURCES_KEY = "sources"
LAST_UPDATED_KEY = "last-updated"


@dataclass(frozen=True)
class FileMetadata:
    description: str
    aliases: tuple[str, ...]
    sources: frozenset[str]
    last_updated: datetime
    # __post_init__ raises ValueError if description contains "\n" or "\r",
    # or if last_updated is naive (tzinfo is None or utcoffset() is None).
    # Empty description, aliases, and sources are allowed; alias/source
    # strings are not validated. Equality compares last_updated as an
    # instant (standard aware-datetime equality).


class MetadataFormatError(ValueError):
    key: str  # the offending map key

    def __init__(self, key: str, detail: str) -> None: ...

    # str(err) names the key.


def metadata_to_map(metadata: FileMetadata) -> dict[str, str]: ...


# Exactly the four keys:
#   description  → the description as-is
#   aliases      → json.dumps(list(aliases))            (order preserved)
#   sources      → json.dumps(sorted(sources))          (deterministic)
#   last-updated → UTC ISO 8601 with "Z" suffix, e.g.
#                  "2026-09-25T19:21:38Z" or "2026-09-25T19:21:38.123456Z"
#                  (fractional seconds only when microsecond != 0)


def metadata_from_map(values: Mapping[str, str]) -> FileMetadata: ...


# Ignores keys other than the four. Raises MetadataFormatError(key, ...)
# when a key is missing; when aliases/sources is not valid JSON or not a
# JSON array of strings; when last-updated is not an ISO 8601 timestamp
# accepted by datetime.fromisoformat, or has no UTC offset; or when the
# decoded description fails FileMetadata validation (key="description").
# Invariant: metadata_from_map(metadata_to_map(m)) == m.
```

## Project Structure

```text
specs/AIE-1031-file-format/
├── spec.md
├── plan.md
├── tasks.md
└── review-spec.md

src/wenchang/
└── file_format.py        # new

tests/
└── test_file_format.py   # new
```

## Complexity Tracking

None.
