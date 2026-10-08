# Tasks: Product identity in the prompt and tool descriptions

**Linear issue**: AIE-1164 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — `purpose` slot and overview splice

test-writer: failing tests for US1.1-1.13 in `tests/test_prompts_slots.py`,
US2.1-2.5 and US3.1-3.3 in `tests/test_prompts_assembly.py`; add
`REFERENCE_PURPOSE` and pass it in `REFERENCE_SLOTS`
(`tests/prompts_reference_adopter.py`); add `purpose` to every other
`PromptSlots(...)` call (`test_prompts_assembly.py`, `test_prompts_filing.py`,
`test_prompts_forgetting.py`). Update the existing expectations the splice
changes (plan.md, Constitution Check). implementer: `slots.py`,
`assemble.py` per plan.md. `make check` green.

## T2 — `product` and `descriptions()`

test-writer: failing tests for US4.1-4.11 in `tests/test_tools.py` and
US5.1-5.7 in `tests/test_tools_descriptions.py`. implementer: `tools.py`
per plan.md. `make check` green.

## T3 — Docs

doc-updater: ADR 0026, dated notes in ADRs 0022 and 0025, ARCHITECTURE.md
`prompts` and `tools` entries, README adopter example, glossary "Prompt
slots" (US6.1-6.5); review-pr.md.
