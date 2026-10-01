# PR Review: AIE-1041 — Path construction from scope and entity ID

## What changed & why

`src/wenchang/paths.py` gains `PathParts`, `build_path`, `build_prefix`, and
`parse_path`, so no caller has to format or split
`scope/entity_id/area/name.md` by hand. All four are pure string code on top
of the shared `is_valid_segment` rule from AIE-1043. `build_path` and
`parse_path` are exact inverses over every path `is_valid_path` accepts, and
`parse_path(...).area` gives the upcoming `system/` enforcement the area
without re-splitting. `is_valid_path`, `is_valid_prefix`, and
`tests/test_paths.py` are unchanged. The only test file is the new
`tests/test_paths_build.py`.

## Acceptance criteria → tests

All tests are in `tests/test_paths_build.py`.

| Acceptance criterion (Given/When/Then) | Test(s) |
| --------------------------------------- | ------- |
| US1.1 `"user","u_42","preferences","editor"` → `"user/u_42/preferences/editor.md"` | `test_build_path_formats_four_segments`, `test_build_path_accepts_keyword_arguments` |
| US1.2 every accepted `build_path` result satisfies `is_valid_path` | `test_build_path_result_is_valid_path` |
| US1.3 bad scope/entity_id/area (`""`, `.`, `..`, `/`, `\`, Cc) → `ValueError` naming it; non-Cc accepted | `test_build_path_rejects_invalid_segment_argument`, `test_build_path_accepts_non_cc_characters`, `test_build_path_worked_example_slash_in_scope` |
| US1.4 bad name (`""`, `/`, `\`, Cc) → `ValueError` naming `name`; non-Cc accepted | `test_build_path_rejects_invalid_name`, `test_build_path_accepts_non_cc_characters`, `test_build_path_worked_example_empty_name` |
| US1.5 `"."`, `".."`, names ending `.md` accepted, `.md` appended | `test_build_path_appends_md_unconditionally` |
| US1.6 several bad args → first in parameter order named | `test_build_path_names_first_invalid_argument` |
| US1.7 Unicode, spaces, mixed case used verbatim, no NFC | `test_build_path_uses_inputs_verbatim`, `test_build_path_does_not_nfc_normalize` |
| US2.1 `build_prefix("user")` → `"user/"` | `test_build_prefix_scope_only` |
| US2.2 scope + entity ID → `"user/u_42/"` | `test_build_prefix_scope_and_entity_id` |
| US2.3 scope + entity ID + area → `"user/u_42/preferences/"` | `test_build_prefix_scope_entity_id_and_area`, `test_build_prefix_accepts_keyword_arguments` |
| US2.4 `area` without `entity_id` → `"area requires entity_id"`, before segment checks | `test_build_prefix_area_without_entity_id`, `test_build_prefix_area_without_entity_id_keyword` |
| US2.5 invalid supplied arg (incl. `""`) → `ValueError` naming it | `test_build_prefix_rejects_invalid_supplied_argument`, `test_build_prefix_rejects_invalid_scope_alone`, `test_build_prefix_rejects_invalid_entity_id_without_area`, `test_build_prefix_empty_entity_id_is_not_omitted` |
| US2.6 result satisfies `is_valid_prefix`; every matching `build_path` starts with it | `test_build_prefix_result_is_valid_prefix`, `test_build_path_starts_with_build_prefix` |
| US2.7 several bad supplied args → first in order named | `test_build_prefix_names_first_invalid_argument` |
| US3.1 `parse_path("user/u_42/preferences/editor.md")` → `PathParts(...)` | `test_parse_path_splits_into_parts` |
| US3.2 any string `is_valid_path` rejects → `ValueError` | `test_parse_path_rejects_malformed_paths`, `test_parse_path_worked_example_wrong_extension`, `test_parse_path_raises_only_value_error_iff_invalid` |
| US3.3 `"s/e/system/x.md"` → `.area == "system"` | `test_parse_path_exposes_system_area` |
| US3.4 only the final `.md` stripped (`..md` → `"."`, `b.md.md` → `"b.md"`) | `test_parse_path_strips_only_final_md`, `test_parse_path_worked_example_double_md` |
| US4.1 `parse_path(build_path(s, e, a, n)) == PathParts(s, e, a, n)` | `test_parse_inverts_build` |
| US4.2 `build_path(**asdict(parse_path(p))) == p` for valid `p` | `test_build_inverts_parse`, `test_build_inverts_parse_positionally`, `test_path_parts_field_order` |
| Edge cases: `PathParts` frozen, by-value, unvalidated; `"system"` accepted | `test_path_parts_is_frozen`, `test_path_parts_compares_by_value`, `test_path_parts_does_no_validation`, `test_build_path_accepts_system_segment` |
| FR-006 `paths` imports nothing from `wenchang` | `test_paths_module_has_no_wenchang_import` |
| FR-007 only `ValueError` raised, including for never-raises inputs | `test_build_path_rejects_invalid_segment_argument`, `test_build_path_rejects_invalid_name`, `test_build_prefix_rejects_invalid_supplied_argument`, `test_parse_path_rejects_malformed_paths`, `test_parse_path_raises_only_value_error_iff_invalid` |

## Architecture / ADR changes

- New [ADR 0015](../../docs/adr/0015-path-construction.md) records the
  decisions: relative paths with no `{root}`, always append `.md`, `"."` and
  `".."` allowed as names, `ValueError` rather than `NotFoundError`, no
  identity-aware helper, `""` invalid in `build_prefix`, and validation
  through the shared `is_valid_segment`. The five human decisions from spec
  review on 2026-09-30 are marked as approved.
- `ARCHITECTURE.md`: the **paths** module-map entry describes `PathParts`,
  the three functions, their error messages, and the round-trip laws. The
  planned **scope** entry now says path construction lives in `paths`. The
  diagram's scope node drops "path construction", and the note under the
  diagram says `paths` is omitted as dependency-free.
- `docs/product/glossary.md`: new **Name** entry for the stem without `.md`.
  "Memory path", "Prefix", and "Area" were already accurate.

## Deviations from spec

- None from the Notion spec. `{root}` is omitted from built paths under the
  existing "storage root is the storage instance" invariant (ADR 0007).
- `test_path_parts_is_frozen` assigns through
  `setattr(parts, "scope", "other")  # noqa: B010` instead of
  `parts.scope = ...`. Pyright flags direct assignment to a frozen dataclass
  field, and ruff's B010 flags a constant-name `setattr`. The test still
  exercises `FrozenInstanceError` at runtime.

## Look closely at

- The round-trip laws over odd stems. `ROUND_TRIP_BUILD_ARGS` and
  `ROUND_TRIP_PATHS` add `"."`, `".."`, `".md"`, `"b.md"`, and `"notes.md"`
  to `VALID_PATHS`. Check that the name rule `name != "" and
  is_valid_segment(name + ".md")` is exactly the set under which both laws
  hold. `BAD_NAME_PATHS` (such as a bare `.md` last segment) must stay
  rejected by `parse_path` and must not be producible by `build_path`.
- `build_prefix` precedence. `"area requires entity_id"` is checked before
  any segment validation, so `build_prefix("bad/", None, "a")` and
  `build_prefix("u", None, "")` both report the missing entity ID and not
  the bad segment.
- `is_valid_path` and `is_valid_prefix` must be byte-for-byte unchanged in
  the diff, and `tests/test_paths.py` untouched. The new code only calls
  them.

## Follow-ups

- Lone surrogates (e.g. `"\ud800"`) pass `is_valid_segment` but cannot be
  UTF-8 encoded, so a path built from one fails only at storage. This and
  any other segment-rule tightening belongs in the shared rule, not in the
  builders.
- AIE-1040 (`system/` read-only) and AIE-1042 (write restriction) will use
  `parse_path(...).area` and `build_path` / `build_prefix` rather than
  splitting paths themselves.
