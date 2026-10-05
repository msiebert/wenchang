# Tasks: Optional aliases and description on append_line and replace_fact

**Linear issue**: AIE-1151 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Core and transport (US1, US2, US3)

test-writer: failing tests in `tests/test_core_append_line.py` (US1.1–1.15),
`tests/test_core_replace_fact.py` (US2.1–2.9), `tests/test_transport_inprocess.py`
(US3.2–3.5; a separate keyword-identity test; pass the new keywords explicitly in the forwarding table, add an
omission test). Update every `TransportClient` test double under `tests/` to
the new `append_line` / `replace_fact` signatures, forwarding the new keywords
where the double forwards. US3.1 is the existing parity test.
implementer: `core.py`, `transport.py` per plan.md (including the US3.6 docstring line). `make check` green.

## T2 — Tools (US4, US5)

test-writer: failing tests in `tests/test_tools.py` (US4.1–4.14, and US4.15 in `tests/test_tools_end_to_end.py`; extend the
`_base` / `_expected` helpers so existing parametrized cases cover the new
parameters) and `tests/test_tools_descriptions.py` (US5.1 phrase pins).
implementer: `tools.py` per plan.md (`_description` helper, signatures,
check order, docstring paragraph). `make check` green.

## T3 — Transport conformance (US6)

test-writer: add `ALIASES_DESCRIPTION_CASES` to
`tests/test_transport_conformance_reference.py` and the method-name pin;
reference-passes parametrized test and one broken client per case in
`tests/test_transport_conformance_cases_self.py`; `MSG_DESCRIPTION_NEWLINE`
parity test in `tests/test_transport_conformance_messages.py`.
implementer: the six cases and the constant in
`src/wenchang/testing/transport_conformance.py`. `make check` green.

## T4 — Docs (US7)

doc-updater: ADR 0024, ARCHITECTURE.md entries, glossary "Aliases" entry,
`review-pr.md` with the criteria -> test mapping.
