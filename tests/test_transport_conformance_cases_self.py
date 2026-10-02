"""Broken-client self-tests for the round-trip through error-parity cases.

Covers AIE-1045, US11.2 for the US1-US10 groups: each broken client makes its
case fail with a message "{client type}: {label}: ...{phrase}..." whose label
names the affected probe path, and the unbroken reference client passes the
same case without skipping it.
"""

import inspect
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from wenchang.core import (
    CappedPrefix,
    FileEntry,
    ListCursor,
    ListPage,
    MemoryFile,
    MemoryIndex,
    MemoryStore,
)
from wenchang.errors import (
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    ReplaceFactMatchError,
    RestrictedScopeError,
    RestrictionReason,
    VersionConflictError,
)
from wenchang.file_format import FileMetadata
from wenchang.paths import is_valid_path, parse_path
from wenchang.storage.memory import InMemoryStorage
from wenchang.testing.transport_conformance import MIN_INDEX_BYTES, TransportConformance
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit
pytest_plugins = ["pytester"]

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


def _with_content(file: MemoryFile, content: str) -> MemoryFile:
    """A copy of file with its content replaced."""
    copy = object.__new__(MemoryFile)
    for key, value in (vars(file) | {"content": content}).items():
        object.__setattr__(copy, key, value)
    return copy


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


def _run(case: str, client: object, **overrides: object) -> None:
    """Call SUITE.<case> with the fixtures its signature asks for."""
    method = cast(Callable[..., None], getattr(SUITE, case))
    values = _fixtures(client) | overrides
    params = [p for p in inspect.signature(method).parameters if p != "self"]
    method(**{p: values[p] for p in params})


def _run_unskipped(case: str, client: object, **overrides: object) -> None:
    """_run, failing "case skipped" if the case skips instead of passing."""
    try:
        _run(case, client, **overrides)
    except pytest.skip.Exception:
        pytest.fail(f"{case}: case skipped")


def _reference_passes(case: str) -> None:
    """The case passes, unskipped, for the reference client and the forwarding wrapper."""
    _run_unskipped(case, _reference())
    _run_unskipped(case, _Forwarding())


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


# --- Conflict payloads and guarded retries -----------------------------------

CREATE_ON_EXISTING = "test_create_on_existing_path_conflicts"
RETRIED_APPEND = "test_retried_append_does_not_duplicate"
APPEND_SEPARATOR = "test_append_inserts_separator_when_needed"
APPEND_UPDATES = "test_append_updates_content_and_last_updated_together"
DELETE_REMOVES = "test_delete_removes_content_and_metadata_together"


class _StaleConflictContent(_Forwarding):
    """A write conflict on a probe path carries the content from before its last write."""

    def __init__(self) -> None:
        super().__init__()
        self.before: dict[str, str] = {}

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
            prior: str | None = self.inner.read_file(path).content
        except NotFoundError:
            prior = None
        try:
            result = super().write_file(path, content, metadata, expected_version, source=source)
        except VersionConflictError as exc:
            if path not in PROBES or path not in self.before:
                raise
            raise VersionConflictError(path, self.before[path], exc.version) from exc
        if prior is not None:
            self.before[path] = prior
        return result


def test_conflict_carrying_stale_content_fails() -> None:
    """A conflict carrying pre-write content fails "wrong payload" naming content.

    AIE-1045, US4.1.
    """
    _reference_passes(STALE_WRITE)

    _case_fails(STALE_WRITE, _StaleConflictContent(), P, r"wrong payload.*content")


class _CreateOverwrites(_Forwarding):
    """A create (no token) on an existing probe path overwrites it."""

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
            if path not in PROBES or expected_version is not None:
                raise
            return super().write_file(path, content, metadata, exc.version, source=source)


def test_create_on_existing_succeeding_fails() -> None:
    """A create on an existing path that succeeds fails "did not raise" (AIE-1045, US4.2)."""
    _reference_passes(CREATE_ON_EXISTING)

    _case_fails(CREATE_ON_EXISTING, _CreateOverwrites(), P, r"did not raise")


def test_retried_landed_append_succeeding_fails() -> None:
    """A repeated landed append that succeeds fails "did not raise" (AIE-1045, US6.2)."""
    _reference_passes(RETRIED_APPEND)

    _case_fails(RETRIED_APPEND, _LandsStaleAppends(), P, r"did not raise")


class _IgnoresWriteRetry(_Forwarding):
    """The first write to a probe path after it conflicted returns the file unchanged."""

    def __init__(self) -> None:
        super().__init__()
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
        if path in self.conflicted:
            self.conflicted.discard(path)
            return self.inner.read_file(path)
        try:
            return super().write_file(path, content, metadata, expected_version, source=source)
        except VersionConflictError:
            if path in PROBES:
                self.conflicted.add(path)
            raise


def test_stale_write_retry_without_effect_fails() -> None:
    """A retry at the conflict's token that changes nothing fails "wrong content".

    AIE-1045, US4.1.
    """
    _reference_passes(STALE_WRITE)

    _case_fails(STALE_WRITE, _IgnoresWriteRetry(), P, r"wrong content")


class _MutatesBeforeMatchError(_Forwarding):
    """A zero-match replace_fact on a probe path appends a line, then raises the real error."""

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
            if path in PROBES and exc.match_count == 0:
                self.inner.append_line(path, "- [stated] mutated", exc.version, source=source)
            raise


def test_replace_fact_rejection_after_mutating_fails() -> None:
    """A correct zero-match rejection that already changed the file fails "content changed".

    AIE-1045, US5.2.
    """
    _reference_passes(REPLACE_ZERO_MATCHES)

    _case_fails(REPLACE_ZERO_MATCHES, _MutatesBeforeMatchError(), P, r"content changed")


class _AppliesOversizeAppend(_AcceptsOversize):
    """An append to a probe path past 256 bytes is applied, then rejected as oversize."""

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        current = self.inner.read_file(path).content if path in PROBES else ""
        separator = "\n" if current and not current.endswith("\n") else ""
        size = len((current + separator + line + "\n").encode("utf-8"))
        result = super().append_line(path, line, expected_version, source=source)
        if path in PROBES and size > 256:
            raise OversizeWriteError(path, size, 256)
        return result


def test_oversize_append_applied_before_rejection_fails() -> None:
    """An oversize append rejected after landing fails "content changed" (AIE-1045, US7.1)."""
    _reference_passes(OVERSIZE_APPEND)

    _case_fails(OVERSIZE_APPEND, _AppliesOversizeAppend(), P, r"content changed")


class _OnAppendRetry(_Forwarding):
    """The first append to a probe path after it conflicted goes through `retry`."""

    def __init__(self) -> None:
        super().__init__()
        self.conflicted: set[str] = set()

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        if path in self.conflicted:
            self.conflicted.discard(path)
            return self.retry(path, line, expected_version, source)
        try:
            return super().append_line(path, line, expected_version, source=source)
        except VersionConflictError:
            if path in PROBES:
                self.conflicted.add(path)
            raise

    def retry(
        self, path: str, line: str, expected_version: VersionToken, source: str
    ) -> MemoryFile:
        return self.inner.append_line(path, line, expected_version, source=source)


class _DuplicatesRetriedAppend(_OnAppendRetry):
    """A retried append lands its line twice."""

    def retry(
        self, path: str, line: str, expected_version: VersionToken, source: str
    ) -> MemoryFile:
        first = self.inner.append_line(path, line, expected_version, source=source)
        return self.inner.append_line(path, line, first.version, source=source)


class _DropsRetriedAppend(_OnAppendRetry):
    """A retried append reports success without landing its line."""

    def retry(
        self, path: str, line: str, expected_version: VersionToken, source: str
    ) -> MemoryFile:
        return self.inner.read_file(path)


class _MisordersRetriedAppend(_OnAppendRetry):
    """A retried append inserts its line before the last line instead of after it."""

    def retry(
        self, path: str, line: str, expected_version: VersionToken, source: str
    ) -> MemoryFile:
        current = self.inner.read_file(path)
        lines = current.content.splitlines(keepends=True)
        content = "".join([*lines[:-1], line + "\n", *lines[-1:]])
        return self.inner.write_file(
            path, content, current.metadata, expected_version, source=source
        )


@pytest.mark.parametrize(
    ("client_type", "phrase"),
    [
        (_DuplicatesRetriedAppend, r"duplicated line"),
        (_DropsRetriedAppend, r"missing line"),
        (_MisordersRetriedAppend, r"wrong content"),
    ],
)
def test_concurrent_appends_bad_retry_fails(client_type: type[_OnAppendRetry], phrase: str) -> None:
    """A retry that duplicates, drops, or misplaces its line fails with `phrase`.

    AIE-1045, US6.1.
    """
    _reference_passes(CONCURRENT_APPENDS)

    _case_fails(CONCURRENT_APPENDS, client_type(), P, phrase)


class _NoSeparator(_Forwarding):
    """An append to a probe path lacking a trailing newline joins the line without one."""

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        if path in PROBES:
            current = self.inner.read_file(path)
            if current.content and not current.content.endswith("\n"):
                return self.inner.write_file(
                    path,
                    current.content + line + "\n",
                    current.metadata,
                    expected_version,
                    source=source,
                )
        return super().append_line(path, line, expected_version, source=source)


def test_append_without_separator_fails() -> None:
    """An append that omits the separating newline fails "wrong content" (AIE-1045, US6.3)."""
    _reference_passes(APPEND_SEPARATOR)

    _case_fails(APPEND_SEPARATOR, _NoSeparator(), P, r"wrong content")


# --- Atomicity of append and delete ------------------------------------------


class _FrozenAppendClock(_Forwarding):
    """Reads of a probe path after an append carry its pre-append last_updated."""

    def __init__(self) -> None:
        super().__init__()
        self.frozen: dict[str, datetime] = {}

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        if path in PROBES:
            self.frozen[path] = self.inner.read_file(path).metadata.last_updated
        return super().append_line(path, line, expected_version, source=source)

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        if path in self.frozen:
            return _with_meta(result, last_updated=self.frozen[path])
        return result


def test_append_not_advancing_last_updated_fails() -> None:
    """An append that leaves last_updated unchanged fails "not later" (AIE-1045, US2.3)."""
    _reference_passes(APPEND_UPDATES)

    _case_fails(APPEND_UPDATES, _FrozenAppendClock(), P, r"not later")


class _DropsSourceAfterAppend(_Forwarding):
    """Reads of a probe path after an append omit the appending source from sources."""

    def __init__(self) -> None:
        super().__init__()
        self.appended: dict[str, str] = {}

    def append_line(
        self, path: str, line: str, expected_version: VersionToken, *, source: str
    ) -> MemoryFile:
        if path in PROBES:
            self.appended[path] = source
        return super().append_line(path, line, expected_version, source=source)

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        if path in self.appended:
            sources = result.metadata.sources - {self.appended[path]}
            return _with_meta(result, sources=sources)
        return result


def test_append_not_stamping_source_fails() -> None:
    """An appended file whose sources lack the source fails "source not stamped".

    AIE-1045, US2.3.
    """
    _reference_passes(APPEND_UPDATES)

    _case_fails(APPEND_UPDATES, _DropsSourceAfterAppend(), P, r"source not stamped")


class _ListsDeleted(_Forwarding):
    """First-page listings keep showing deleted probe files."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[FileEntry] = []

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        if path in PROBES:
            current = self.inner.read_file(path)
            self.deleted.append(FileEntry(path, current.metadata, current.version))
        super().delete_file(path, expected_version)

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        if cursor is not None:
            return page
        listed = {e.path for e in page.entries}
        ghosts = tuple(
            e for e in self.deleted if e.path.startswith(prefix) and e.path not in listed
        )
        return ListPage(page.entries + ghosts, page.next_cursor)


def test_deleted_file_still_listed_fails() -> None:
    """A listing that still shows a deleted file fails "deleted file still listed".

    AIE-1045, US2.2.
    """
    _reference_passes(DELETE_REMOVES)

    message = _case_fails(DELETE_REMOVES, _ListsDeleted(), "list_prefix(", r"deleted file")

    assert "deleted file still listed" in message, message


class _AltersSystemReads(_Forwarding):
    """Reads of a system/ area file return extra content."""

    def read_file(self, path: str) -> MemoryFile:
        result = super().read_file(path)
        if parse_path(path).area == "system":
            return _with_content(result, result.content + "- [system] extra\n")
        return result


def test_system_area_write_reading_back_different_fails() -> None:
    """An accepted system/ write that reads back different fails "round trip".

    AIE-1045, US7.3.
    """
    _reference_passes(SYSTEM_AREA_WRITE)

    _case_fails(SYSTEM_AREA_WRITE, _AltersSystemReads(), SYSTEM_PATH, r"round trip changed content")


# --- US8: index order, budget, and capped ------------------------------------

INDEX_ORDER = "test_index_orders_system_first_then_priority_then_recency"
INDEX_FANS_OUT = "test_index_fans_out_over_every_scope"
INDEX_AREA_SEGMENT = "/conformance-index/"


def _is_system(entry: FileEntry) -> bool:
    return parse_path(entry.path).area == "system"


class _NonSystemFirst(_Forwarding):
    """get_memory_index puts non-system entries before system/ entries."""

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        index = super().get_memory_index(scope_map)
        rest = tuple(e for e in index.entries if not _is_system(e))
        system = tuple(e for e in index.entries if _is_system(e))
        return MemoryIndex(entries=rest + system, capped=index.capped)


def test_index_system_entries_after_others_fails() -> None:
    """An index listing system/ entries after the rest fails "wrong order" (AIE-1045, US8.2)."""
    _reference_passes(INDEX_ORDER)

    _case_fails(INDEX_ORDER, _NonSystemFirst(), "get_memory_index", r"wrong order")


class _LargeIndexBudget(_Forwarding):
    """Forwards to a store whose index budget is 1 MiB, far above the fixture's."""

    def __init__(self) -> None:
        super().__init__()
        self.inner = InProcessClient(
            MemoryStore(
                InMemoryStorage(),
                clock=_Ticking(),
                max_file_bytes=256,
                index_max_bytes=1 << 20,
                scope_priority=("user", "org"),
                list_page_size=2,
            )
        )


def test_index_over_budget_fails() -> None:
    """An index whose entries exceed index_max_bytes fails "budget exceeded" (AIE-1045, US8.3)."""
    _reference_passes(INDEX_BYTE_CAP)

    _case_fails(INDEX_BYTE_CAP, _LargeIndexBudget(), "get_memory_index", r"budget exceeded")


class _DropsFittingIndexEntry(_Forwarding):
    """get_memory_index omits the first conformance-index entry, leaving capped alone."""

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        index = super().get_memory_index(scope_map)
        entries = list(index.entries)
        for i, entry in enumerate(entries):
            if INDEX_AREA_SEGMENT in entry.path:
                del entries[i]
                break
        return MemoryIndex(entries=tuple(entries), capped=index.capped)


def test_index_dropping_fitting_entry_fails() -> None:
    """An index omitting an entry that fits the budget fails "wrong order" (AIE-1045, US8.3)."""
    _reference_passes(INDEX_BYTE_CAP)

    _case_fails(INDEX_BYTE_CAP, _DropsFittingIndexEntry(), "get_memory_index", r"wrong order")


class _ReportsCapped(_Forwarding):
    """get_memory_index reports a capped prefix even when nothing was omitted."""

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        index = super().get_memory_index(scope_map)
        extra = CappedPrefix("org/o-9/notes/", 1)
        return MemoryIndex(entries=index.entries, capped=(*index.capped, extra))


def test_index_spuriously_capped_fails() -> None:
    """A complete index reporting a capped prefix fails "wrong capped" (AIE-1045, US8.1)."""
    _reference_passes(INDEX_FANS_OUT)

    _case_fails(INDEX_FANS_OUT, _ReportsCapped(), "get_memory_index", r"wrong capped")


def test_skipped_case_counts_as_failure() -> None:
    """A fixture under which US8.3 skips is reported as "case skipped" (AIE-1045, FR-002)."""
    with pytest.raises(pytest.fail.Exception, match="case skipped"):
        _run_unskipped(INDEX_BYTE_CAP, _LargeIndexBudget(), index_max_bytes=1 << 20)


def test_index_byte_cap_rejects_budget_below_minimum() -> None:
    """US8.3 fails "fixture index_max_bytes" below MIN_INDEX_BYTES (AIE-1045, US8.3)."""
    client = _reference()
    expected = (
        f"{type(client).__name__}: fixture index_max_bytes must be at least "
        f"{MIN_INDEX_BYTES}, got {MIN_INDEX_BYTES - 1}"
    )
    with pytest.raises(pytest.fail.Exception, match=f"^{re.escape(expected)}"):
        _run(INDEX_BYTE_CAP, client, index_max_bytes=MIN_INDEX_BYTES - 1)


def test_reference_subclass_runs_every_case_unskipped(pytester: pytest.Pytester) -> None:
    """TestInProcessClient passes every suite case and skips none (AIE-1045, FR-002, US11.1)."""
    cases = [
        name
        for name, value in vars(TransportConformance).items()
        if name.startswith("test_") and callable(value)
    ]
    module = Path(__file__).with_name("test_transport_conformance_reference.py").read_text()
    pytester.makepyfile(test_reference_copy=module)

    result = pytester.runpytest("-p", "no:cacheprovider", "-k", "TestInProcessClient")

    outcomes = result.parseoutcomes()
    assert outcomes.get("skipped", 0) == 0, outcomes
    result.assert_outcomes(passed=len(cases))


# --- US9: listing order and cursors ------------------------------------------


class _DescendingPages(_Forwarding):
    """Each listing page has its entries in descending path order."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        return ListPage(tuple(reversed(page.entries)), page.next_cursor)


class _UnstableCursor(_Forwarding):
    """A cursor handed back a second time lists an empty last page."""

    def __init__(self) -> None:
        super().__init__()
        self.used: set[str] = set()

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        if cursor is None:
            return page
        if cursor in self.used:
            return ListPage((), None)
        self.used.add(cursor)
        return page


class _CursorOnLastPage(_Forwarding):
    """A last page reached through a cursor carries that cursor as next_cursor."""

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        if cursor is not None and page.next_cursor is None:
            return ListPage(page.entries, cursor)
        return page


class _RepeatsBoundaryEntry(_Forwarding):
    """A page reached through a cursor repeats the previous first page's last entry."""

    def __init__(self) -> None:
        super().__init__()
        self.boundary: dict[str, FileEntry] = {}

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        page = super().list_prefix(prefix, cursor)
        if cursor is None:
            if page.entries:
                self.boundary[prefix] = page.entries[-1]
            return page
        if prefix in self.boundary:
            return ListPage((self.boundary[prefix], *page.entries), page.next_cursor)
        return page


@pytest.mark.parametrize(
    ("client_type", "phrase"),
    [
        (_DescendingPages, r"wrong order"),
        (_UnstableCursor, r"unstable cursor"),
        (_CursorOnLastPage, r"expected None on the last page"),
        (_RepeatsBoundaryEntry, r"wrong order|duplicate"),
    ],
)
def test_list_pagination_misbehavior_fails(client_type: type[_Forwarding], phrase: str) -> None:
    """Descending pages, an unstable cursor, a cursor on the last page, or an entry
    repeated across pages each fail with `phrase`.

    AIE-1045, US9.1.
    """
    _reference_passes(LIST_PAGINATES)

    _case_fails(LIST_PAGINATES, client_type(), "list_prefix", phrase)


# --- US10: error parity ------------------------------------------------------

ERROR_GUIDANCE = "test_error_messages_carry_category_guidance"
EMPTY_SOURCE = "test_empty_source_is_value_error"
INVALID_PATH = "test_invalid_path_is_not_found_for_every_operation"


class _ReshapedNotFoundMessage(_Forwarding):
    """NotFoundError for an absent probe path keeps its fields but has a different message."""

    def read_file(self, path: str) -> MemoryFile:
        try:
            return super().read_file(path)
        except NotFoundError as exc:
            if path in PROBES:
                exc.detail = f"No file at {path}."
            raise


def test_reshaped_error_message_fails() -> None:
    """A correctly typed error whose message differs from core's fails "wrong message".

    AIE-1045, US10.4.
    """
    _reference_passes(ERROR_GUIDANCE)

    _case_fails(ERROR_GUIDANCE, _ReshapedNotFoundMessage(), P, r"wrong message")


class _BadSourceMessage(_Forwarding):
    """write_file with an empty source raises ValueError("bad source")."""

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if not source:
            raise ValueError("bad source")
        return super().write_file(path, content, metadata, expected_version, source=source)


def test_empty_source_wrong_message_fails() -> None:
    """An empty-source ValueError with its own message fails "wrong message" (AIE-1045, US10.3)."""
    _reference_passes(EMPTY_SOURCE)

    _case_fails(EMPTY_SOURCE, _BadSourceMessage(), P, r"wrong message")


class _KeyErrorForAbsentDelete(_Forwarding):
    """delete_file of an absent probe path raises KeyError instead of NotFoundError."""

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        try:
            super().delete_file(path, expected_version)
        except NotFoundError as exc:
            if path not in PROBES or exc.reason is not NotFoundReason.FILE_ABSENT:
                raise
            raise KeyError(path) from exc


def test_absent_delete_raising_key_error_fails() -> None:
    """An absent delete raising KeyError fails "wrong error type" (AIE-1045, US10.2)."""
    _reference_passes(ABSENT_MUTATING_READ)

    message = _case_fails(ABSENT_MUTATING_READ, _KeyErrorForAbsentDelete(), P, r"wrong error type")

    assert "KeyError" in message, message


class _StoresInvalidPathWrite(_Forwarding):
    """The first write to an invalid path is stored at P before the INVALID_PATH error."""

    def __init__(self) -> None:
        super().__init__()
        self.stored = False

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        if not is_valid_path(path) and not self.stored:
            self.stored = True
            self.inner.write_file(P, content, metadata, None, source=source)
        return super().write_file(path, content, metadata, expected_version, source=source)


def test_invalid_path_write_stored_fails() -> None:
    """A rejected invalid-path write that still stores a file fails "did not raise".

    AIE-1045, US10.1.
    """
    _reference_passes(INVALID_PATH)

    _case_fails(INVALID_PATH, _StoresInvalidPathWrite(), P, r"did not raise")
