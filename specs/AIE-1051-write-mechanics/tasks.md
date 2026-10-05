# Tasks: Write mechanics prose

**Linear issue**: AIE-1051 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Write mechanics body

test-writer adds `tests/test_prompts_write_mechanics.py` covering spec
US1.1-1.3, US2.1-2.5, US3.1-3.4, US4.1-4.4, and US5.1-5.3, with docstrings
citing AIE-1051; the US1.1 and phrase pins fail against the empty `BODY`.
implementer sets `write_mechanics.BODY` to the exact text in plan.md.
`make check` green.

## T2 — Review artifact

doc-updater drafts `review-pr.md` from the template with the criteria ->
test mapping (file:line). No ARCHITECTURE, ADR, or glossary change.
