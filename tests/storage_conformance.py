"""Shared conformance suite for `Storage` implementations (AIE-1032).

`StorageConformance` is NOT collected by pytest directly (its name doesn't
start with "Test"). Each concrete backend gets its own `Test...` subclass in
its own test module, supplying a `storage` fixture and its own `pytestmark`
(e.g. `pytest.mark.unit` or `pytest.mark.integration`).

Import this module with a bare `from storage_conformance import ...` (not
`from tests.storage_conformance import ...`): `tests/` has no `__init__.py`,
but `tests/conftest.py` causes pytest to add `tests/` to `sys.path`, which
makes the bare import resolve from both `tests/test_storage_memory.py` and
`tests/integration/test_storage_gcs.py`.
"""

import pytest

from wenchang.storage import ListedObject, PreconditionFailedError, Storage
from wenchang.version_token import VersionToken


class StorageConformance:
    """Behavior every `Storage` implementation must satisfy."""

    def test_get_of_missing_key_returns_none(self, storage: Storage) -> None:
        """Fetching a key with no object returns None, not an error
        (AIE-1032, US4-1).
        """
        assert storage.get("does/not/exist") is None

    def test_put_then_get_round_trips_bytes_and_metadata(self, storage: Storage) -> None:
        """The bytes and metadata map from get() match what was put, including
        non-ASCII bytes and unicode metadata values (AIE-1032, US4-2).
        """
        data = "café ✓\r\n".encode()
        metadata = {"lang": "français", "note": "café ✓"}
        storage.put("k", data, metadata)
        result = storage.get("k")
        assert result is not None
        assert result.data == data
        assert dict(result.metadata) == metadata

    def test_put_then_get_round_trips_empty_bytes_and_empty_metadata(
        self, storage: Storage
    ) -> None:
        """Empty bytes and an empty metadata map round-trip through put/get
        (AIE-1032, US4-2).
        """
        storage.put("empty", b"", {})
        result = storage.get("empty")
        assert result is not None
        assert result.data == b""
        assert dict(result.metadata) == {}

    def test_put_returns_token_and_get_reports_same_token(self, storage: Storage) -> None:
        """put() returns a str version token, and a subsequent get() reports
        that same token (AIE-1032, US4-3).
        """
        token = storage.put("k", b"data", {})
        assert isinstance(token, str)
        result = storage.get("k")
        assert result is not None
        assert result.version == token

    def test_second_put_to_same_key_yields_different_token_and_new_data(
        self, storage: Storage
    ) -> None:
        """Two successive puts to one key produce different tokens, and a
        subsequent get returns the second put's bytes AND metadata together
        (AIE-1032, US4-4).
        """
        first_token = storage.put("k", b"first", {"which": "first"})
        second_token = storage.put("k", b"second", {"which": "second"})
        assert second_token != first_token
        result = storage.get("k")
        assert result is not None
        assert result.data == b"second"
        assert dict(result.metadata) == {"which": "second"}
        assert result.version == second_token

    def test_puts_to_different_keys_are_independent(self, storage: Storage) -> None:
        """Puts to two different keys each round-trip independently
        (AIE-1032, US4-5).
        """
        storage.put("key-a", b"data-a", {"who": "a"})
        storage.put("key-b", b"data-b", {"who": "b"})
        result_a = storage.get("key-a")
        result_b = storage.get("key-b")
        assert result_a is not None
        assert result_b is not None
        assert result_a.data == b"data-a"
        assert dict(result_a.metadata) == {"who": "a"}
        assert result_b.data == b"data-b"
        assert dict(result_b.metadata) == {"who": "b"}

    def test_key_is_not_a_prefix_match_bak_suffix(self, storage: Storage) -> None:
        """Putting `a/b.md.bak` does not make `a/b.md` resolve; keys are exact,
        not prefix matches (AIE-1032, US4-5).
        """
        storage.put("a/b.md.bak", b"backup", {})
        assert storage.get("a/b.md") is None

    def test_key_is_not_a_prefix_match_truncated_key(self, storage: Storage) -> None:
        """Putting `a/b.md` does not make the truncated key `a/b` resolve
        (AIE-1032, US4-5).
        """
        storage.put("a/b.md", b"content", {})
        assert storage.get("a/b") is None

    def test_five_successive_puts_yield_five_distinct_tokens(self, storage: Storage) -> None:
        """Five successive puts to the same key produce five pairwise distinct
        tokens (AIE-1032, FR-003).
        """
        tokens = [storage.put("k", f"v{i}".encode(), {}) for i in range(5)]
        assert len(set(tokens)) == 5

    def test_mutating_callers_metadata_dict_after_put_does_not_affect_storage(
        self, storage: Storage
    ) -> None:
        """The caller's metadata mapping is copied on put: mutating the dict
        passed to put afterwards does not affect a later get (AIE-1032).
        """
        metadata: dict[str, str] = {"a": "1"}
        storage.put("k", b"data", metadata)
        metadata["a"] = "mutated"
        metadata["b"] = "new"
        result = storage.get("k")
        assert result is not None
        assert dict(result.metadata) == {"a": "1"}

    def test_tokens_are_compared_only_for_equality(self, storage: Storage) -> None:
        """Tokens are opaque: equal on repeated get of the same write, and
        distinguishable with `!=` from a token of a different write — never
        parsed or ordered (AIE-1032, US4-3).
        """
        first_token = storage.put("k", b"data", {})
        result = storage.get("k")
        assert result is not None
        assert result.version == first_token
        second_token = storage.put("k", b"other", {})
        assert second_token != first_token

    def test_put_if_version_none_on_missing_key_creates_object(self, storage: Storage) -> None:
        """With no object at a key, put_if_version(expected=None) returns a
        token and get() returns the object with that same bytes, metadata,
        and token (AIE-1033, US7).
        """
        token = storage.put_if_version("k", b"data", {"a": "1"}, None)
        result = storage.get("k")
        assert result is not None
        assert result.data == b"data"
        assert dict(result.metadata) == {"a": "1"}
        assert result.version == token

    def test_put_if_version_none_on_existing_key_raises_and_leaves_object_unchanged(
        self, storage: Storage
    ) -> None:
        """With an object already at a key, put_if_version(expected=None)
        raises PreconditionFailedError(key) and leaves the existing bytes,
        metadata, and version unchanged (AIE-1033, US7).
        """
        original_token = storage.put("k", b"original", {"a": "1"})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.put_if_version("k", b"new", {"a": "2"}, None)
        assert excinfo.value.key == "k"
        result = storage.get("k")
        assert result is not None
        assert result.data == b"original"
        assert dict(result.metadata) == {"a": "1"}
        assert result.version == original_token

    def test_put_if_version_with_current_token_succeeds_and_returns_new_token(
        self, storage: Storage
    ) -> None:
        """With an object at version V, put_if_version(expected=V) succeeds,
        returning a new token != V, and get() returns the new bytes and
        metadata together (AIE-1033, US7).
        """
        v1 = storage.put("k", b"v1", {"which": "v1"})
        v2 = storage.put_if_version("k", b"v2", {"which": "v2"}, v1)
        assert v2 != v1
        result = storage.get("k")
        assert result is not None
        assert result.data == b"v2"
        assert dict(result.metadata) == {"which": "v2"}
        assert result.version == v2

    def test_put_if_version_with_stale_token_raises_and_leaves_object_unchanged(
        self, storage: Storage
    ) -> None:
        """With an object at version V2 (written after V1), put_if_version
        using the stale V1 raises PreconditionFailedError and leaves the
        object unchanged (AIE-1033, US7).
        """
        v1 = storage.put("k", b"v1", {"which": "v1"})
        v2 = storage.put("k", b"v2", {"which": "v2"})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.put_if_version("k", b"v3", {"which": "v3"}, v1)
        assert excinfo.value.key == "k"
        result = storage.get("k")
        assert result is not None
        assert result.data == b"v2"
        assert dict(result.metadata) == {"which": "v2"}
        assert result.version == v2

    def test_put_if_version_with_foreign_token_on_missing_key_raises_and_stays_missing(
        self, storage: Storage
    ) -> None:
        """With no object at a key, put_if_version with a non-None token
        (obtained from a different key) raises PreconditionFailedError and
        the key remains absent afterwards (AIE-1033, US7).
        """
        other_token = storage.put("other-key", b"data", {})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.put_if_version("k", b"data", {}, other_token)
        assert excinfo.value.key == "k"
        assert storage.get("k") is None

    @pytest.mark.parametrize("bogus_token", ["abc", "0", "-1", "007", "", "999999999999"])
    def test_put_if_version_with_token_no_put_produced_raises_and_leaves_object_unchanged(
        self, storage: Storage, bogus_token: str
    ) -> None:
        """Using a token string that no put() ever produced against an
        existing object raises PreconditionFailedError and leaves the object
        unchanged (AIE-1033, US7).
        """
        original_token = storage.put("k", b"original", {"a": "1"})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.put_if_version("k", b"new", {"a": "2"}, VersionToken(bogus_token))
        assert excinfo.value.key == "k"
        result = storage.get("k")
        assert result is not None
        assert result.data == b"original"
        assert dict(result.metadata) == {"a": "1"}
        assert result.version == original_token

    def test_put_if_version_with_trailing_newline_on_valid_token_raises_and_leaves_object_unchanged(
        self, storage: Storage
    ) -> None:
        """A token equal to the current version's digits plus a trailing
        newline is not the canonical decimal form of a positive integer, so
        put_if_version must raise PreconditionFailedError(key) and leave the
        object unchanged — even though `int()` would parse it and it targets
        the matching generation (AIE-1033).
        """
        original_token = storage.put("k", b"original", {"a": "1"})
        bad_token = VersionToken(f"{original_token}\n")
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.put_if_version("k", b"new", {"a": "2"}, bad_token)
        assert excinfo.value.key == "k"
        result = storage.get("k")
        assert result is not None
        assert result.data == b"original"
        assert dict(result.metadata) == {"a": "1"}
        assert result.version == original_token

    def test_put_if_version_mutating_callers_metadata_dict_after_put_does_not_affect_storage(
        self, storage: Storage
    ) -> None:
        """The caller's metadata mapping passed to a successful
        put_if_version is copied: mutating the dict afterwards does not
        affect a later get() (AIE-1033, US7).
        """
        metadata: dict[str, str] = {"a": "1"}
        storage.put_if_version("k", b"data", metadata, None)
        metadata["a"] = "mutated"
        metadata["b"] = "new"
        result = storage.get("k")
        assert result is not None
        assert dict(result.metadata) == {"a": "1"}

    def test_precondition_failed_error_is_not_a_wenchang_error(self, storage: Storage) -> None:
        """PreconditionFailedError subclasses Exception directly, not
        WenchangError (AIE-1033, US7).
        """
        from wenchang.errors import WenchangError

        storage.put("k", b"data", {})
        try:
            storage.put_if_version("k", b"new", {}, None)
        except PreconditionFailedError as error:
            assert not isinstance(error, WenchangError)
        else:
            pytest.fail("expected PreconditionFailedError")

    def test_list_page_returns_matching_keys_ascending_with_metadata_and_version(
        self, storage: Storage
    ) -> None:
        """list_page(prefix, None, limit) returns ListedObject(key, metadata,
        version) for every key starting with `prefix` (plain string prefix
        match, including a key like `a/e/xy/1.md` under prefix `a/e/x`),
        ascending by key, with metadata and version matching what get()
        reports for that key (AIE-1035, US4).
        """
        storage.put("a/e/x", b"x-body", {"which": "x"})
        storage.put("a/e/xy/1.md", b"xy-body", {"which": "xy"})
        storage.put("a/e/y", b"y-body", {"which": "y"})
        storage.put("a/f/z", b"z-body", {"which": "z"})

        page = storage.list_page("a/e/x", None, 10)

        assert [obj.key for obj in page] == ["a/e/x", "a/e/xy/1.md"]
        for obj in page:
            assert isinstance(obj, ListedObject)
            expected = storage.get(obj.key)
            assert expected is not None
            assert dict(obj.metadata) == dict(expected.metadata)
            assert obj.version == expected.version

    def test_list_page_excludes_keys_at_or_before_start_after(self, storage: Storage) -> None:
        """With start_after=k, only keys strictly greater than k are
        returned; k itself is excluded whether or not an object exists there
        (AIE-1035, US4).
        """
        storage.put("p/a", b"a", {})
        storage.put("p/b", b"b", {})
        storage.put("p/c", b"c", {})

        page = storage.list_page("p/", "p/b", 10)
        assert [obj.key for obj in page] == ["p/c"]

        page_missing_start = storage.list_page("p/", "p/aa", 10)
        assert [obj.key for obj in page_missing_start] == ["p/b", "p/c"]

    def test_list_page_with_no_matching_keys_returns_empty_sequence(self, storage: Storage) -> None:
        """When no key starts with `prefix`, list_page returns an empty
        sequence (AIE-1035, US4).
        """
        storage.put("other/key", b"data", {})
        assert list(storage.list_page("nope/", None, 10)) == []

    def test_list_page_mutating_returned_metadata_dict_does_not_affect_storage(
        self, storage: Storage
    ) -> None:
        """If a returned ListedObject's metadata mapping is mutable (e.g.
        cast to dict), mutating it afterwards does not affect a subsequent
        get() or list_page() (AIE-1035, US4).
        """
        storage.put("m/k", b"data", {"a": "1"})
        page = storage.list_page("m/", None, 10)
        assert len(page) == 1
        metadata = page[0].metadata
        if isinstance(metadata, dict):
            metadata["a"] = "mutated"
            metadata["b"] = "new"

        result = storage.get("m/k")
        assert result is not None
        assert dict(result.metadata) == {"a": "1"}
        reread = storage.list_page("m/", None, 10)
        assert dict(reread[0].metadata) == {"a": "1"}

    def test_list_page_limit_smaller_than_matches_truncates_to_first_n_in_order(
        self, storage: Storage
    ) -> None:
        """When more keys match than `limit`, list_page returns only the
        first `limit` keys in ascending order (AIE-1035, US4).
        """
        for key in ("q/1", "q/2", "q/3", "q/4"):
            storage.put(key, b"data", {})

        page = storage.list_page("q/", None, 2)
        assert [obj.key for obj in page] == ["q/1", "q/2"]

    def test_list_page_excludes_keys_outside_the_prefix_before_and_after(
        self, storage: Storage
    ) -> None:
        """Keys that sort before the prefix range and keys that sort after
        it, but do not start with it, are excluded (AIE-1035, US4).
        """
        storage.put("r-before", b"data", {})
        storage.put("r/inside", b"data", {})
        storage.put("r0after", b"data", {})

        page = storage.list_page("r/", None, 10)
        assert [obj.key for obj in page] == ["r/inside"]

    def test_list_page_orders_multi_byte_unicode_keys_by_code_point(self, storage: Storage) -> None:
        """A key containing a multi-byte unicode character sorts among other
        matching keys by Python str (code point) comparison (AIE-1035, US4).
        """
        storage.put("u/a", b"data", {})
        storage.put("u/café", b"data", {})
        storage.put("u/z", b"data", {})

        page = storage.list_page("u/", None, 10)
        assert [obj.key for obj in page] == sorted(["u/a", "u/café", "u/z"])

    def test_delete_if_version_with_current_token_deletes_object(self, storage: Storage) -> None:
        """Given an object at token T, delete_if_version(key, T) returns None
        and a subsequent get(key) is None (AIE-1037, US4.1).
        """
        token = storage.put("k", b"data", {"a": "1"})
        result = storage.delete_if_version("k", token)
        assert result is None
        assert storage.get("k") is None

    def test_delete_if_version_with_stale_token_raises_and_leaves_object_unchanged(
        self, storage: Storage
    ) -> None:
        """Given an object at token T2 (written after T1), delete_if_version
        using the stale T1 raises PreconditionFailedError and leaves the
        object's data, metadata, and version unchanged (AIE-1037, US4.2).
        """
        t1 = storage.put("k", b"v1", {"which": "v1"})
        t2 = storage.put("k", b"v2", {"which": "v2"})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.delete_if_version("k", t1)
        assert excinfo.value.key == "k"
        result = storage.get("k")
        assert result is not None
        assert result.data == b"v2"
        assert dict(result.metadata) == {"which": "v2"}
        assert result.version == t2

    def test_delete_if_version_on_missing_key_raises(self, storage: Storage) -> None:
        """Given no object at a key, delete_if_version(key, T) raises
        PreconditionFailedError (AIE-1037, US4.3).
        """
        other_token = storage.put("other-key", b"data", {})
        with pytest.raises(PreconditionFailedError) as excinfo:
            storage.delete_if_version("k", other_token)
        assert excinfo.value.key == "k"
        assert storage.get("k") is None

    def test_put_if_version_none_succeeds_after_delete(self, storage: Storage) -> None:
        """Given a key that was deleted, put_if_version(key, ..., None)
        (create-if-absent) succeeds afterwards (AIE-1037, US4.4).
        """
        token = storage.put("k", b"original", {"a": "1"})
        storage.delete_if_version("k", token)

        new_token = storage.put_if_version("k", b"recreated", {"a": "2"}, None)

        result = storage.get("k")
        assert result is not None
        assert result.data == b"recreated"
        assert dict(result.metadata) == {"a": "2"}
        assert result.version == new_token

    def test_delete_if_version_leaves_other_keys_visible_in_get_and_list_page(
        self, storage: Storage
    ) -> None:
        """Given two keys, deleting one leaves get() and list_page() still
        reporting the other, and list_page() no longer lists the deleted key
        (AIE-1037, US4.5).
        """
        token_a = storage.put("del/a", b"data-a", {"who": "a"})
        storage.put("del/b", b"data-b", {"who": "b"})

        storage.delete_if_version("del/a", token_a)

        assert storage.get("del/a") is None
        remaining = storage.get("del/b")
        assert remaining is not None
        assert remaining.data == b"data-b"

        page = storage.list_page("del/", None, 10)
        assert [obj.key for obj in page] == ["del/b"]

    def test_list_page_version_reflects_the_latest_put(self, storage: Storage) -> None:
        """When a key has been put more than once, the version in its
        ListedObject equals the token from the most recent put, matching
        get() (AIE-1035, US4).
        """
        storage.put("v/k", b"first", {"which": "first"})
        latest_token = storage.put("v/k", b"second", {"which": "second"})

        page = storage.list_page("v/", None, 10)
        assert len(page) == 1
        assert page[0].version == latest_token
        result = storage.get("v/k")
        assert result is not None
        assert result.version == latest_token
