# Implementation Plan: Product identity in the prompt and tool descriptions

**Linear issue**: AIE-1164 | **Branch**: `AIE-1164-product-identity` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

## Summary

Two modules change: `src/wenchang/prompts/slots.py` + `assemble.py` (purpose
slot and splice) and `src/wenchang/tools.py` (`product`, `descriptions()`).
Tests: `tests/test_prompts_slots.py`, `tests/test_prompts_assembly.py`,
`tests/prompts_reference_adopter.py`, `tests/test_prompts_filing.py` and
`tests/test_prompts_forgetting.py` (construction sites only),
`tests/test_tools.py`, `tests/test_tools_descriptions.py`. Docs: ADR 0026,
ADR 0022/0025 dated notes, ARCHITECTURE.md, README.md, glossary.

## Technical Context

Python ≥ 3.12; pyright strict; ruff 100 columns. Stdlib only (`inspect`
added to `tools.py` imports). No import-graph change within `wenchang`.

## Constitution Check

| Principle | Status |
| --------- | ------ |
| I. Tests-first | T1, T2 each test-writer → implementer |
| II. Tests not negotiable | Existing tests change only where the issue requires (see "Existing tests that change"). `tests/test_prompts_invariants.py` unchanged. No tool docstring test changes. |
| Storage via interface only | Unchanged |
| Architecture changes documented | ADR 0026, ARCHITECTURE.md, README, glossary |

## Existing tests that change

- Every `PromptSlots(...)` call gains `purpose` (slots, assembly, filing,
  forgetting, reference adopter).
- `tests/test_prompts_slots.py` helpers: `FIELDS`, `REQUIRED_FIELDS`, `VALID`,
  `_make`, `_make_with` gain `purpose`, first in order, so the existing
  parametrized type / lying-subclass / strip / blank / surrogate / frozen
  tests cover `purpose` (US1.5-1.8, US1.11) rather than duplicating them;
  the order tests gain `purpose`-first cases (US1.9, US1.10).
- `tests/test_prompts_assembly.py`:
  - `test_build_returns_exact_str`: expected section 1 becomes
    `"## Memory\n\n" + purpose + "\n\nOverview text.\n\n"`.
  - `test_build_full_output_format`: expected `bodies["overview"]` becomes
    `SLOTS.purpose + "\n\n" + bodies["overview"]`.
  - `test_build_reads_bodies_at_call_time`: expected `sections["Memory"]`
    becomes `SLOTS.purpose + "\n\nReplacement overview."`.
  - `test_build_omits_blank_section`: parametrize over `BODY_IDS` minus
    `overview`; a new test covers blank overview (US2.3).
  - `test_reference_slots_build_and_appear_under_headings`: add
    `REFERENCE_PURPOSE` to its stripped-blob tuple and check it opens section 1.

## Interface: `wenchang.prompts`

```python
@dataclass(frozen=True)
class PromptSlots:
    purpose: str
    scope_guidance: str
    seed_areas: str
    systems_of_record: str | None = None
```

- `purpose` is the first field, required, no default. Breaking change: every
  construction site passes it.
- `__post_init__`, unchanged structure with `purpose` added first:
  1. Type pass, in field order `purpose`, `scope_guidance`, `seed_areas`
     (required: `issubclass(type(v), str)` else
     `TypeError(f"{field} must be str, not {type_name}")`), then
     `systems_of_record` (`None` or str, else
     `TypeError(f"systems_of_record must be str or None, not {type_name}")`).
  2. Value pass, in field order `purpose`, `scope_guidance`, `seed_areas`,
     `systems_of_record` (skip `None`): `str.strip(str.__str__(v))`; empty →
     `ValueError(f"{field} must not be empty or whitespace-only")`;
     `.encode("utf-8")` failure → `ValueError(f"{field} must be encodable as
     UTF-8")` from the `UnicodeEncodeError`; store with `object.__setattr__`.
- Docstring: a ``purpose`` bullet placed first:
  "``purpose``: one or two sentences naming the product and when to use
  memory." The "Slots state only deployment facts" sentence stays.

`build_memory_prompt(slots, /)`: the `overview` entry of `_SECTIONS` returns
`(overview.HEADING, body)` where `body` is the `"\n\n"` join of the non-empty
parts `[slots.purpose, overview.BODY.strip()]` (purpose is already stripped).
So with a non-blank BODY, section 1 is
`"## Memory\n\n" + purpose + "\n\n" + BODY.strip()`; with a blank BODY it is
`"## Memory\n\n" + purpose`. `overview.BODY` is still read at call time.
`SECTION_ORDER`, headings, and every other section are unchanged.

## Interface: `wenchang.tools`

```python
class MemoryTools:
    def __init__(
        self,
        client: TransportClient,
        identity: Identity,
        policy: ScopePolicy,
        *,
        source: str,
        product: str | None = None,
    ) -> None: ...
    @property
    def product(self) -> str | None: ...  # read-only
    def descriptions(self) -> Mapping[str, str]: ...


def bind_tools[C](
    client, resolver, credentials, policy, *, source: str, product: str | None = None
) -> MemoryTools: ...
```

Constructor check order (argument order; existing checks unchanged): client,
identity, policy, source type, source empty, then product:

1. `product is None` → stored `None`.
2. `not issubclass(type(product), str)` →
   `TypeError(f"product must be a str or None, not {type_name}")` (same
   `_type_name` helper as the other arguments).
3. `value = str.strip(str.__str__(product))`.
4. `value == ""` → `ValueError("product must be non-empty")`.
5. `len(value.splitlines()) != 1` → `ValueError("product must be one line")`
   (equivalently, any `str.splitlines` boundary remains after the strip).
6. `value.encode("utf-8")` raises → `ValueError("product must be encodable as
   UTF-8")` raised `from` the `UnicodeEncodeError`.

These are adopter-side constructor errors (ADR 0022 decision 2): plain
`TypeError`/`ValueError`, never `InvalidArgumentError`. `bind_tools` forwards
`product` to `MemoryTools` unchanged; identity resolution still happens
first, so a resolver error wins over a bad `product` (stated in ADR 0026). No tool method takes `product`; `tools()` is unchanged.

`descriptions()` returns a new `types.MappingProxyType` over a dict built in
`TOOL_NAMES` order. For each name, `doc = inspect.cleandoc(getattr(MemoryTools,
name).__doc__)`. With `product is None`, the value is `doc`. Otherwise the
value is `doc` with its first line (up to the first `"\n"`) replaced by
`_FIRST_LINE_TEMPLATES[name].replace("{product}", product)` (plain
replacement, so braces in a product are verbatim). Lines after the first are
unchanged.

Module constant (private; tests reach it only through `descriptions()`):

Every source line stays ≤100 columns (ruff E501); the two long templates use
implicit string concatenation:

```python
_FIRST_LINE_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "get_memory_index": (
            "Load the metadata index of every {product} memory scope available in this session."
        ),
        "read_file": "Read one {product} memory file: its content, metadata, and version.",
        "list_prefix": (
            "List the files in a {product} memory scope or area, "
            "one page at a time, without content."
        ),
        "write_file": "Create a {product} memory file or replace one whole.",
        "append_line": "Add one fact line to the end of an existing {product} memory file.",
        "replace_fact": "Change one fact in a {product} memory file by quoting the text to replace.",
        "delete_file": "Delete a {product} memory file.",
    }
)
```

An import-time guard (like `assemble._SECTIONS`) raises `RuntimeError` if
`tuple(_FIRST_LINE_TEMPLATES) != TOOL_NAMES`.

Module docstring: the "their docstrings are the descriptions a host shows the
agent" sentence becomes a present-state statement that `descriptions()` gives
the descriptions a host shows the agent: the docstrings, with the product
named in each first line when one is set.

### Template fidelity check (chosen: strict single insertion)

The brief offered two checks. "Remove `{product}` and compare" holds for five
tools but not `get_memory_index` (docstring says "every memory scope") or
`list_prefix` (docstring says "a scope or area", with no "memory"). The
templates above are chosen so the strict check holds: for every tool, the
rendered first line with product `P` equals the docstring's first line with
exactly one string inserted at a word boundary, that string being `"P "` for
six tools and `"P memory "` for `list_prefix` alone. Precisely, the test
computes `first = inspect.cleandoc(getattr(MemoryTools, name).__doc__).split("\n",
1)[0]` at test time (never hardcoded), `boundaries = {0} | {j + 1 for j, c in
enumerate(first) if c == " "}`, `ins = f"{P} memory " if name == "list_prefix"
else f"{P} "`, and asserts the rendered first line is in `{first[:i] + ins +
first[i:] for i in boundaries}`. It runs for at least two products,
`"Mixpanel"` and `"Acme Analytics"`. (For six tools the insertion lands before
"memory"; for `list_prefix` before "scope".) `list_prefix` adds "memory" because "a Mixpanel scope or area"
would not say the tool is about memory.

## Reference fixture

`tests/prompts_reference_adopter.py` gains, before `REFERENCE_SCOPE_GUIDANCE`:

```python
REFERENCE_PURPOSE: Final[str] = """\
You have persistent memory of your work in Mixpanel: reference it and save to it with these
tools whenever you work with Mixpanel."""
```

`REFERENCE_SLOTS = PromptSlots(purpose=REFERENCE_PURPOSE, scope_guidance=...,
seed_areas=..., systems_of_record=...)`. The module docstring says four blobs.

## Files

- `src/wenchang/prompts/slots.py`, `src/wenchang/prompts/assemble.py`
- `src/wenchang/tools.py`
- `tests/test_prompts_slots.py`, `tests/test_prompts_assembly.py`,
  `tests/prompts_reference_adopter.py`, `tests/test_prompts_filing.py`,
  `tests/test_prompts_forgetting.py`, `tests/test_tools.py`,
  `tests/test_tools_descriptions.py`
- `docs/adr/0026-product-identity.md`, `docs/adr/0022-tool-layer.md`,
  `docs/adr/0025-prompt-layer-sections-and-slots.md`, `ARCHITECTURE.md`,
  `README.md`, `docs/product/glossary.md`
