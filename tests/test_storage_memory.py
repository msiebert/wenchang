"""Conformance and fake-specific tests for InMemoryStorage (AIE-1032)."""

import pytest

from storage_conformance import StorageConformance
from wenchang.storage import Storage
from wenchang.storage.memory import InMemoryStorage

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> Storage:
    return InMemoryStorage()


class TestInMemoryStorage(StorageConformance):
    """Runs the shared conformance suite against InMemoryStorage."""


@pytest.mark.unit
def test_get_returned_metadata_is_a_mutable_dict_but_mutating_it_does_not_affect_storage(
    storage: Storage,
) -> None:
    """If the metadata returned by get() is a plain dict, mutating that dict
    does not affect a later get() — the fake must not hand back its internal
    mapping by reference (AIE-1032, US4-6).
    """
    storage.put("k", b"data", {"a": "1"})
    first = storage.get("k")
    assert first is not None
    if isinstance(first.metadata, dict):
        first.metadata["a"] = "mutated"
        first.metadata["b"] = "new"
    second = storage.get("k")
    assert second is not None
    assert dict(second.metadata) == {"a": "1"}


@pytest.mark.unit
def test_tokens_are_unique_across_different_keys_within_one_instance() -> None:
    """Tokens issued for different keys within one InMemoryStorage instance
    are distinct (AIE-1032).
    """
    storage = InMemoryStorage()
    token_a = storage.put("key-a", b"data-a", {})
    token_b = storage.put("key-b", b"data-b", {})
    assert token_a != token_b


def test_in_memory_storage_satisfies_storage_protocol() -> None:
    """InMemoryStorage structurally satisfies the Storage protocol, so it can
    be assigned to a `Storage`-typed variable without a cast (AIE-1032).
    """
    instance: Storage = InMemoryStorage()
    assert instance.get("anything") is None
