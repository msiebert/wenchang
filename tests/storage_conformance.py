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

from wenchang.storage import Storage


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
