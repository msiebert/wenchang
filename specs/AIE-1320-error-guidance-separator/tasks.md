# Tasks: Separate error detail from guidance

**Linear issue**: AIE-1320 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## T1 — Terminate details before following text

test-writer adds failing tests for spec US1.1–1.10, US2.1–2.4, US3.1–3.6,
US4.1–4.5 and updates the expected values of
`tests/test_errors.py::test_error_message_format` and
`tests/test_errors_invalid_argument.py::test_invalid_argument_error_str_is_detail_then_guidance`
(spec Allow-test-changes). US5.1 needs no new test. implementer adds
`_sentence` to `src/wenchang/errors.py`, applies it in
`WenchangError.message`, `ResolverFailureError`, and
`BackendUnavailableError`, and drops the `: {detail}` suffix for a blank
`InvalidArgumentError` detail, per plan.md.
`make check` green.

## T2 — Docs

doc-updater: ARCHITECTURE.md errors entry, ADR 0005 decision, CHANGELOG
`[Unreleased]` `Fixed` entry, and a check of `site-src/reference.md` and
other docs quoting rendered messages (US6.1–6.4).
