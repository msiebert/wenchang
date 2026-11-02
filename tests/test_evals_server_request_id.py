"""Tests that the eval server's trace rejects a record with no request_id."""

from types import MappingProxyType

import pytest

from evals.server import _Record, _Snapshot  # pyright: ignore[reportPrivateUsage]
from wenchang.core import MemoryStore
from wenchang.identity import Identity, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit


def test_trace_rejects_record_without_request_id() -> None:
    """Building the trace from a record whose request_id is None raises
    RuntimeError naming the tool (AIE-1296, FR-007).
    """
    record = ToolCallRecord(
        "read_file", MappingProxyType({}), MappingProxyType({}), False, None, 0.001
    )
    snapshot = _Snapshot(
        client=InProcessClient(MemoryStore(InMemoryStorage())),
        identity=Identity({"user": ScopeGrant("u-1", "owner")}),
        trial_dir=None,
        records=(_Record(seq=1, record=record, started_ms=0.0, completed_ms=1.0),),
        boundaries=(),
        turns=(),
    )

    with pytest.raises(RuntimeError, match="read_file"):
        snapshot.trace()
