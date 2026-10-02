"""Broken-client self-tests for the round-trip through listing cases.

Covers AIE-1045, US11.2 for the US1-US9 groups: each broken client makes its
case fail with a message "{client type}: {label}: ...{phrase}..." whose label
names the affected probe path, and the unbroken reference client passes the
same case.
"""

import inspect
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from wenchang.core import FileEntry, ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore
from wenchang.errors import (
    NotFoundError,
    NotFoundReason,
    ReplaceFactMatchError,
    RestrictedScopeError,
    RestrictionReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata
from wenchang.paths import parse_path
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing.transport_conformance import TransportConformance
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

SOURCE = "conformance"
SCOPE_MAP: Mapping[str, str] = {"user": "u-1", "org": "o-9"}
P = "org/o-9/notes/conformance-probe.md"
Q = "org/o-9/notes/conformance-probe-2.md"
R = "user/u-1/notes/conformance-probe-3.md"
PROBES = frozenset({P, Q, R})
WHEN = datetime(2024, 1, 1, tzinfo=UTC)

UNICODE_ROUND_TRIP = "test_round_trip_unicode_content_and_metadata"
FAILED_REPLACE = "test_failed_replace_leaves_content_and_metadata_together"
TOKENS_FROM_EVERY_OPERATION = "test_tokens_from_every_operation_are_accepted"
INDEX_ENTRY_TOKENS = "test_index_entry_tokens_are_accepted"

CASES = (
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
)


class _Ticking:
    """Returns an aware datetime one microsecond later on each call."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> datetime:
        self._n += 1
        return WHEN + timedelta(microseconds=self._n)


def _reference() -> InProcessClient:
    return InProcessClient(
        MemoryStore(
            InMemoryStorage(),
            clock=_Ticking(),
            max_file_bytes=256,
            index_max_bytes=4096,
            scope_priority=("user", "org"),
            list_page_size=2,
        )
    )


class _Forwarding:
    """Forwards all seven TransportClient methods to a real InProcessClient."""

    def __init__(self) -> None:
        self.inner = _reference()

    def read_file(self, path: str) -> MemoryFile:
        return self.inner.read_file(path)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        return self.inner.write_file(path, content, metadata, expected_version, source=source)

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        return self.inner.append_line(path, line, expected_version, source=source)

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        return self.inner.replace_fact(
            path, old_string, new_string, expected_version, source=source
        )

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return self.inner.list_prefix(prefix, cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        self.inner.delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        return self.inner.get_memory_index(scope_map)


def _with_meta(file: MemoryFile, **overrides: object) -> MemoryFile:
    """A copy of file with metadata fields replaced, bypassing validation."""
    metadata = object.__new__(FileMetadata)
    for key, value in (vars(file.metadata) | overrides).items():
        object.__setattr__(metadata, key, value)
    copy = object.__new__(MemoryFile)
    for key, value in (vars(file) | {"metadata": metadata}).items():
        object.__setattr__(copy, key, value)
    return copy


# --- Running cases -----------------------------------------------------------

SUITE = TransportConformance()


def _fixtures(client: object) -> dict[str, object]:
    return {
        "client": client,
        "source": SOURCE,
        "scope_map": dict(SCOPE_MAP),
        "max_file_bytes": 256,
        "index_max_bytes": 4096,
        "scope_priority": ("user", "org"),
        "list_page_size": 2,
    }


def _run(case: str, client: object) -> None:
    """Call SUITE.<case> with the fixtures its signature asks for."""
    method = cast(Callable[..., None], getattr(SUITE, case))
    values = _fixtures(client)
    params = [p for p in inspect.signature(method).parameters if p != "self"]
    method(**{p: values[p] for p in params})


def _reference_passes(case: str) -> None:
    """The case passes for the reference client and the forwarding wrapper."""
    _run(case, _reference())
    _run(case, _Forwarding())


def _case_fails(case: str, client: object, path: str, phrase: str) -> str:
    """Run the case; require "{client type}: {label}: {text}" with path in label, phrase in text.

    `phrase` is a regular expression searched in the text after the label.
    """
    with pytest.raises(pytest.fail.Exception) as exc_info:
        _run(case, client)
    message = str(exc_info.value)
    prefix = f"{type(client).__name__}: "
    assert message.startswith(prefix), message
    label, sep, text = message.removeprefix(prefix).partition(": ")
    assert sep, message
    assert path in label, message
    assert re.search(phrase, text, re.DOTALL), message
    return message


@pytest.mark.parametrize("case", CASES)
def test_reference_client_passes_case(case: str) -> None:
    """The reference client and forwarding wrapper pass each US1-US3 case.

    AIE-1045, US1.1-US1.5, US2.1-US2.3, US3.1, US3.2, US11.2.
    """
    _reference_passes(case)


# --- US1: round-trip fidelity -------------------------------------------------


class _DropsUnicodeAlias(_Forwarding):
    """read_file of a probe path drops the last non-ASCII alias."""

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        aliases = result.metadata.aliases
        if path in PROBES and any(not a.isascii() for a in aliases):
            last = max(i for i, a in enumerate(aliases) if not a.isascii())
            return _with_meta(result, aliases=aliases[:last] + aliases[last + 1 :])
        return result


def test_unicode_round_trip_dropped_alias_fails() -> None:
    """A read that drops a unicode alias fails "round trip" naming aliases (AIE-1045, US1.1)."""
    _reference_passes(UNICODE_ROUND_TRIP)

    _case_fails(UNICODE_ROUND_TRIP, _DropsUnicodeAlias(), P, r"round trip.*aliases")


# --- US2: atomicity -----------------------------------------------------------


class _StaleDescriptionAfterConflict(_Forwarding):
    """After a write conflict on a probe path, reads of it carry the previous description.

    The content is the current content; the description is the one from the
    write before the last successful one.
    """

    def __init__(self) -> None:
        super().__init__()
        self.descriptions: dict[str, list[str]] = {}
        self.conflicted: set[str] = set()

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        try:
            result = super().write_file(path, content, metadata, expected_version, source=source)
        except VersionConflictError:
            self.conflicted.add(path)
            raise
        self.descriptions.setdefault(path, []).append(metadata.description)
        return result

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        history = self.descriptions.get(path, [])
        if path in PROBES and path in self.conflicted and len(history) >= 2:
            return _with_meta(result, description=history[-2])
        return result


def test_failed_replace_new_content_old_description_fails() -> None:
    """New content with the old description after a conflict fails (AIE-1045, US2.1)."""
    _reference_passes(FAILED_REPLACE)

    _case_fails(FAILED_REPLACE, _StaleDescriptionAfterConflict(), P, r"round trip|wrong content")


# --- US3: version token opacity ----------------------------------------------


class _IssuesRejectedTokens(_Forwarding):
    """Results of `operation` for probe paths carry tokens the client later rejects.

    A rejected token handed back to any mutating call raises VersionConflictError
    carrying the real current content and version; `rejected_path` records the
    path of that call.
    """

    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation
        self.issued: dict[str, str] = {}
        self.rejected_path: str | None = None

    def _issue(self, path: str) -> VersionToken:
        token = f"rejected-{len(self.issued)}"
        self.issued[token] = path
        return VersionToken(token)

    def _file(self, operation: str, result: MemoryFile) -> MemoryFile:
        if operation != self.operation or result.path not in PROBES:
            return result
        copy = object.__new__(MemoryFile)
        for key, value in (vars(result) | {"version": self._issue(result.path)}).items():
            object.__setattr__(copy, key, value)
        return copy

    def _entries(self, operation: str, entries: tuple[FileEntry, ...]) -> tuple[FileEntry, ...]:
        if operation != self.operation:
            return entries
        return tuple(
            FileEntry(e.path, e.metadata, self._issue(e.path)) if e.path in PROBES else e
            for e in entries
        )

    def _check(self, path: str, expected_version: VersionToken | None) -> None:
        if expected_version is not None and expected_version in self.issued:
            self.rejected_path = path
            current = self.inner.read_file(path)
            raise VersionConflictError(path, current.content, current.version)

    def read_file(self, path: str) -> MemoryFile:
        return self._file("read_file", super().read_file(path))

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        self._check(path, expected_version)
        result = super().write_file(path, content, metadata, expected_version, source=source)
        return self._file("write_file", result)

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        self._check(path, expected_version)
        result = super().append_line(path, line, expected_version, source=source)
        return self._file("append_line", result)

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        self._check(path, expected_version)
        result = super().replace_fact(path, old_string, new_string, expected_version, source=source)
        return self._file("replace_fact", result)

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        return ListPage(self._entries("list_prefix", page.entries), page.next_cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        self._check(path, expected_version)
        super().delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        index = super().get_memory_index(scope_map)
        return MemoryIndex(
            entries=self._entries("get_memory_index", index.entries), capped=index.capped
        )


@pytest.mark.parametrize(
    "operation", ["write_file", "read_file", "append_line", "replace_fact", "list_prefix"]
)
def test_rejected_token_from_operation_fails(operation: str) -> None:
    """A token from `operation` that the client later rejects fails "token not accepted".

    AIE-1045, US3.1.
    """
    _reference_passes(TOKENS_FROM_EVERY_OPERATION)
    client = _IssuesRejectedTokens(operation)

    message = _case_fails(TOKENS_FROM_EVERY_OPERATION, client, "", r"token not accepted")

    assert client.rejected_path is not None, message
    label = message.removeprefix(f"{type(client).__name__}: ").partition(": ")[0]
    assert client.rejected_path in label, message


def test_rejected_index_entry_token_fails() -> None:
    """An index entry token the client later rejects fails "token not accepted".

    AIE-1045, US3.2.
    """
    _reference_passes(INDEX_ENTRY_TOKENS)
    client = _IssuesRejectedTokens("get_memory_index")

    _case_fails(INDEX_ENTRY_TOKENS, client, P, r"token not accepted")

    assert client.rejected_path == P


# --- US4-US6: conflicts, replace-fact matching, append guarding --------------

STALE_WRITE = "test_stale_write_conflicts_with_current_content"
REPLACE_ZERO_MATCHES = "test_replace_fact_zero_matches_rejected"
CONCURRENT_APPENDS = "test_concurrent_appends_one_lands_one_conflicts"

CONFLICT_REPLACE_APPEND_CASES = (
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
)


@pytest.mark.parametrize("case", CONFLICT_REPLACE_APPEND_CASES)
def test_reference_client_passes_conflict_replace_append_case(case: str) -> None:
    """The reference client and forwarding wrapper pass each US4-US6 case.

    AIE-1045, US4.1-US4.5, US5.1-US5.6, US6.1-US6.5, US11.2.
    """
    _reference_passes(case)


class _StaleWriteSucceeds(_Forwarding):
    """A guarded write to a probe path that conflicts is re-applied at the current version."""

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        try:
            return super().write_file(path, content, metadata, expected_version, source=source)
        except VersionConflictError as exc:
            if path not in PROBES or expected_version is None:
                raise
            return super().write_file(path, content, metadata, exc.version, source=source)


def test_stale_write_success_fails() -> None:
    """A stale write that succeeds instead of conflicting fails "did not raise".

    AIE-1045, US4.1.
    """
    _reference_passes(STALE_WRITE)

    _case_fails(STALE_WRITE, _StaleWriteSucceeds(), P, r"did not raise")


class _MisreportsZeroMatches(_Forwarding):
    """A zero-match replace_fact on a probe path reports match_count=2."""

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
    ) -> MemoryFile:
        try:
            return super().replace_fact(
                path, old_string, new_string, expected_version, source=source
            )
        except ReplaceFactMatchError as exc:
            if path not in PROBES or exc.match_count != 0:
                raise
            raise ReplaceFactMatchError(exc.path, exc.content, exc.version, 2) from exc


def test_replace_fact_wrong_match_count_fails() -> None:
    """A zero-match rejection carrying the wrong match_count fails "wrong payload".

    AIE-1045, US5.2.
    """
    _reference_passes(REPLACE_ZERO_MATCHES)

    _case_fails(REPLACE_ZERO_MATCHES, _MisreportsZeroMatches(), P, r"wrong payload.*match_count")


class _LandsStaleAppends(_Forwarding):
    """A conflicting append to a probe path is re-applied at the current version."""

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        try:
            return super().append_line(path, line, expected_version, source=source)
        except VersionConflictError as exc:
            if path not in PROBES:
                raise
            return super().append_line(path, line, exc.version, source=source)


def test_concurrent_appends_both_landing_fails() -> None:
    """A second append at the same stale version that lands fails "did not raise".

    AIE-1045, US6.1.
    """
    _reference_passes(CONCURRENT_APPENDS)

    _case_fails(CONCURRENT_APPENDS, _LandsStaleAppends(), P, r"did not raise")


# --- US7-US9: enforcement, index behavior, listing ---------------------------

OVERSIZE_APPEND = "test_oversize_append_is_rejected"
OVERSIZE_REPLACE_FACT = "test_oversize_replace_fact_is_rejected"
SYSTEM_AREA_WRITE = "test_system_area_write_is_accepted_at_transport"
INDEX_BYTE_CAP = "test_index_byte_cap_degrades_with_capped_prefixes"
LIST_PAGINATES = "test_list_prefix_paginates_with_stable_cursors"
SYSTEM_PATH = "org/o-9/system/conformance-curated.md"

ENFORCEMENT_INDEX_LISTING_CASES = (
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
)


@pytest.mark.parametrize("case", ENFORCEMENT_INDEX_LISTING_CASES)
def test_reference_client_passes_enforcement_index_listing_case(case: str) -> None:
    """The reference client and forwarding wrapper pass each US7-US9 case.

    AIE-1045, US7.1-US7.3, US8.1-US8.4, US9.1-US9.4, US11.1, US11.2.
    """
    _reference_passes(case)


class _AcceptsOversize(_Forwarding):
    """Forwards to a store whose size limit is 1 MiB, far above the fixture's."""

    def __init__(self) -> None:
        super().__init__()
        self.inner = InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=1 << 20,
                index_max_bytes=4096,
                scope_priority=("user", "org"),
                list_page_size=2,
            )
        )


@pytest.mark.parametrize("case", [OVERSIZE_APPEND, OVERSIZE_REPLACE_FACT])
def test_oversize_mutation_accepted_fails(case: str) -> None:
    """An append or replace_fact accepted past max_file_bytes fails "did not raise".

    AIE-1045, US7.1, US7.2.
    """
    _reference_passes(case)

    _case_fails(case, _AcceptsOversize(), P, r"did not raise")


class _RejectsSystemWrites(_Forwarding):
    """write_file to a system/ area raises RestrictedScopeError(SYSTEM_READ_ONLY)."""

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        parts = parse_path(path)
        if parts.area == "system":
            raise RestrictedScopeError(path, parts.scope, RestrictionReason.SYSTEM_READ_ONLY)
        return super().write_file(path, content, metadata, expected_version, source=source)


def test_system_area_write_rejected_fails() -> None:
    """A transport that rejects a system/ write fails "unexpected error" (AIE-1045, US7.3)."""
    _reference_passes(SYSTEM_AREA_WRITE)

    _case_fails(SYSTEM_AREA_WRITE, _RejectsSystemWrites(), SYSTEM_PATH, r"unexpected error")


class _HidesCappedPrefixes(_Forwarding):
    """get_memory_index returns the real entries but always reports capped=()."""

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        index = super().get_memory_index(scope_map)
        return MemoryIndex(entries=index.entries, capped=())


def test_index_omitting_entries_without_capped_fails() -> None:
    """An index that omits entries yet reports capped=() fails "wrong capped".

    AIE-1045, US8.3.
    """
    _reference_passes(INDEX_BYTE_CAP)

    _case_fails(INDEX_BYTE_CAP, _HidesCappedPrefixes(), "get_memory_index", r"wrong capped")


class _DropsFirstPageCursor(_Forwarding):
    """A first page that has more to follow is returned with next_cursor=None."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        if cursor is None and page.next_cursor is not None:
            return ListPage(page.entries, None)
        return page


def test_full_first_page_without_cursor_fails() -> None:
    """A full first page with next_cursor=None fails naming the cursor (AIE-1045, US9.1)."""
    _reference_passes(LIST_PAGINATES)

    _case_fails(LIST_PAGINATES, _DropsFirstPageCursor(), "list_prefix", r"cursor")


# --- US10: error parity -------------------------------------------------------

ABSENT_MUTATING_READ = "test_absent_file_is_not_found_for_every_mutating_read"

ERROR_PARITY_CASES = (
    "test_invalid_path_is_not_found_for_every_operation",
    "test_absent_file_is_not_found_for_every_mutating_read",
    "test_empty_source_is_value_error",
    "test_error_messages_carry_category_guidance",
    "test_get_memory_index_argument_errors_match_core",
)


@pytest.mark.parametrize("case", ERROR_PARITY_CASES)
def test_reference_client_passes_error_parity_case(case: str) -> None:
    """The reference client and forwarding wrapper pass each US10 case.

    AIE-1045, US10.1-US10.5, US11.1, US11.2.
    """
    _reference_passes(case)


class _KeyErrorForAbsentRead(_Forwarding):
    """read_file of an absent probe path raises KeyError instead of NotFoundError."""

    def read_file(self, path: str) -> MemoryFile:
        try:
            return super().read_file(path)
        except NotFoundError as exc:
            if path not in PROBES or exc.reason is not NotFoundReason.FILE_ABSENT:
                raise
            raise KeyError(path) from exc


def test_absent_read_raising_key_error_fails() -> None:
    """An absent read raising KeyError fails "wrong error type" naming KeyError.

    AIE-1045, US10.2, US11.2.
    """
    _reference_passes(ABSENT_MUTATING_READ)

    message = _case_fails(ABSENT_MUTATING_READ, _KeyErrorForAbsentRead(), P, r"wrong error type")

    assert "KeyError" in message, message
