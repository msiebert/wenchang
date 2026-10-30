"""Tests for where entity purge and export are, and are not, exposed.

Covers AIE-1291, US6.
"""

import dataclasses

import pytest

from wenchang.core import PURGE_MAX_PASSES, ExportedObject, MemoryStore, PurgeIncompleteError
from wenchang.errors import WenchangError
from wenchang.identity import Identity, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import TOOL_NAMES, MemoryTools, tool_descriptions
from wenchang.transport import InProcessClient, TransportClient

pytestmark = pytest.mark.unit

OPERATOR_ONLY = ("purge", "export")


def test_purge_and_export_are_not_agent_facing() -> None:
    """TransportClient, InProcessClient, MemoryTools, and the tool
    descriptions expose no purge or export (AIE-1291, US6.1).
    """
    client = InProcessClient(MemoryStore(InMemoryStorage()))
    tools = MemoryTools(
        client,
        Identity({"user": ScopeGrant("u1", "owner")}),
        ScopePolicy({}),
        source="api-surface",
    )

    for name in OPERATOR_ONLY:
        assert not hasattr(TransportClient, name)
        assert not hasattr(InProcessClient, name)
        assert not hasattr(client, name)
        assert not hasattr(MemoryTools, name)
        assert not hasattr(tools, name)
        assert name not in TOOL_NAMES
        for mapping in (tools.descriptions(), tool_descriptions()):
            for tool, text in mapping.items():
                assert name not in tool
                assert name not in text.lower()


def test_public_names_importable() -> None:
    """ExportedObject, PurgeIncompleteError, and PURGE_MAX_PASSES are public
    in wenchang.core; PurgeIncompleteError is outside the WenchangError
    taxonomy (AIE-1291, US6.2).
    """
    assert PURGE_MAX_PASSES == 5
    assert issubclass(PurgeIncompleteError, Exception)
    assert not issubclass(PurgeIncompleteError, WenchangError)
    assert dataclasses.is_dataclass(ExportedObject)
    assert callable(MemoryStore.purge)
    assert callable(MemoryStore.export)
