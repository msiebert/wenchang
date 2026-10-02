"""Reference run of the transport conformance suite against InProcessClient.

Covers AIE-1047, US1.1 and US1.5, and through the inherited suite methods
US3.1 through US3.5, and AIE-1045, US11.1. pytest itself checks that the
reference subclass collects every listed case and skips none; a missing
fixture surfaces as a collection error (US1.5).
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from wenchang.core import MemoryStore
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing import TransportConformance
from wenchang.transport import InProcessClient, TransportClient

pytestmark = pytest.mark.unit

MAX_FILE_BYTES = 256
INDEX_MAX_BYTES = 4096
SCOPE_PRIORITY = ("user", "org")
LIST_PAGE_SIZE = 2

BASELINE_CASES = frozenset(
    {
        "test_client_satisfies_protocol",
        "test_write_then_read_round_trips",
        "test_returned_token_is_accepted",
        "test_read_absent_is_not_found",
        "test_oversize_write_is_rejected",
    }
)

ROUND_TRIP_ATOMICITY_TOKEN_CASES = frozenset(
    {
        "test_round_trip_unicode_content_and_metadata",
        "test_round_trip_markdown_resembling_fact_syntax",
        "test_round_trip_content_without_trailing_newline",
        "test_round_trip_empty_content",
        "test_round_trip_empty_aliases_and_many_sources",
        "test_write_replace_round_trips",
        "test_failed_replace_leaves_content_and_metadata_together",
        "test_delete_removes_content_and_metadata_together",
        "test_append_updates_content_and_last_updated_together",
        "test_tokens_from_every_operation_are_accepted",
        "test_index_entry_tokens_are_accepted",
    }
)

CONFLICT_REPLACE_APPEND_CASES = frozenset(
    {
        "test_stale_write_conflicts_with_current_content",
        "test_create_on_existing_path_conflicts",
        "test_write_with_token_on_absent_path_is_not_found",
        "test_stale_delete_conflicts",
        "test_delete_absent_is_not_found",
        "test_replace_fact_unique_match_succeeds",
        "test_replace_fact_zero_matches_rejected",
        "test_replace_fact_multiple_matches_rejected",
        "test_replace_fact_stale_token_unique_match_reapplies",
        "test_replace_fact_stale_token_non_unique_conflicts",
        "test_replace_fact_empty_old_string_is_value_error",
        "test_concurrent_appends_one_lands_one_conflicts",
        "test_retried_append_does_not_duplicate",
        "test_append_inserts_separator_when_needed",
        "test_append_to_absent_file_is_not_found_and_creates_nothing",
        "test_append_non_fact_line_is_value_error",
    }
)

ENFORCEMENT_INDEX_LISTING_CASES = frozenset(
    {
        "test_oversize_append_is_rejected",
        "test_oversize_replace_fact_is_rejected",
        "test_system_area_write_is_accepted_at_transport",
        "test_index_fans_out_over_every_scope",
        "test_index_orders_system_first_then_priority_then_recency",
        "test_index_byte_cap_degrades_with_capped_prefixes",
        "test_index_of_empty_scope_map_is_empty",
        "test_list_prefix_paginates_with_stable_cursors",
        "test_list_prefix_levels",
        "test_list_prefix_invalid_prefix_is_not_found",
        "test_list_prefix_malformed_cursor_is_value_error",
    }
)

ERROR_PARITY_CASES = frozenset(
    {
        "test_invalid_path_is_not_found_for_every_operation",
        "test_absent_file_is_not_found_for_every_mutating_read",
        "test_empty_source_is_value_error",
        "test_error_messages_carry_category_guidance",
        "test_get_memory_index_argument_errors_match_core",
    }
)


class _Ticking:
    """A clock returning a strictly later aware datetime on each call."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(microseconds=self._n)


class TestInProcessClient(TransportConformance):
    """InProcessClient over a fresh MemoryStore passes every suite case, none skipped.

    AIE-1047, US1.1, US3.1-US3.5; AIE-1045, US1-US10, US11.1.
    """

    @pytest.fixture
    def client(self) -> TransportClient:
        return InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=MAX_FILE_BYTES,
                index_max_bytes=INDEX_MAX_BYTES,
                scope_priority=SCOPE_PRIORITY,
                list_page_size=LIST_PAGE_SIZE,
            )
        )

    @pytest.fixture
    def source(self) -> str:
        return "conformance"

    @pytest.fixture
    def scope_map(self) -> Mapping[str, str]:
        return {"user": "u-1", "org": "o-9"}

    @pytest.fixture
    def max_file_bytes(self) -> int:
        return MAX_FILE_BYTES

    @pytest.fixture
    def index_max_bytes(self) -> int:
        return INDEX_MAX_BYTES

    @pytest.fixture
    def scope_priority(self) -> tuple[str, ...]:
        return SCOPE_PRIORITY

    @pytest.fixture
    def list_page_size(self) -> int:
        return LIST_PAGE_SIZE


def test_ticking_clock_strictly_increases() -> None:
    """The reference clock stamps strictly increasing aware datetimes (AIE-1047, US1.1)."""
    clock = _Ticking()
    first, second = clock(), clock()

    assert first.utcoffset() is not None
    assert first < second


def test_suite_public_methods_are_exactly_the_listed_cases() -> None:
    """The suite's public callables are exactly the listed cases.

    AIE-1047, US5.3; AIE-1045, US11.1 (adds the round-trip, atomicity, token,
    conflict, replace-fact, append, enforcement, index, listing, and US10
    error-parity cases).
    """
    public = {
        name
        for name, value in vars(TransportConformance).items()
        if callable(value) and not name.startswith("_")
    }

    assert public == (
        BASELINE_CASES
        | ROUND_TRIP_ATOMICITY_TOKEN_CASES
        | CONFLICT_REPLACE_APPEND_CASES
        | ENFORCEMENT_INDEX_LISTING_CASES
        | ERROR_PARITY_CASES
    )
