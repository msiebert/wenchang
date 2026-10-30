"""Tests for the shared tool-call observer in wenchang.observer.

Covers AIE-1296, US4.3 (ToolCallRecord shape) and US4.6 (check_observer and
notify_observer).
"""

import logging
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, is_dataclass
from typing import cast

import pytest

from wenchang.observer import ToolCallRecord, check_observer, notify_observer

pytestmark = pytest.mark.unit

LOGGER_NAME = "test.wenchang.observer"


class _Uncopyable:
    """A value whose deep copy fails."""

    def __deepcopy__(self, memo: dict[int, object]) -> "_Uncopyable":
        raise RuntimeError("cannot copy")


def _notify(
    on_call: Callable[[ToolCallRecord], None],
    *,
    arguments: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> None:
    notify_observer(
        on_call,
        logging.getLogger(LOGGER_NAME),
        tool="read_file",
        arguments={"scope": "user", "aliases": ["tea"]} if arguments is None else arguments,
        result={"ok": True, "aliases": ["tea"]} if result is None else result,
        is_error=False,
        request_id=None,
        duration_s=0.25,
    )


def test_record_is_a_frozen_dataclass_with_ordered_fields() -> None:
    """ToolCallRecord is a frozen dataclass whose fields are, in order, tool,
    arguments, result, is_error, request_id, duration_s (AIE-1296, US4.3).
    """
    assert is_dataclass(ToolCallRecord)
    assert [f.name for f in fields(ToolCallRecord)] == [
        "tool",
        "arguments",
        "result",
        "is_error",
        "request_id",
        "duration_s",
    ]
    record = ToolCallRecord("t", {}, {}, False, "1", 0.0)
    with pytest.raises(FrozenInstanceError):
        record.tool = "u"  # pyright: ignore[reportAttributeAccessIssue]


def test_record_request_id_accepts_none() -> None:
    """ToolCallRecord accepts request_id=None, as bind_tools records carry
    (AIE-1296, US4.3).
    """
    record = ToolCallRecord("read_file", {}, {"ok": True}, False, None, 0.0)

    assert record.request_id is None


def test_check_observer_accepts_none_and_plain_callables() -> None:
    """check_observer accepts None, a plain function, and a bound method
    (AIE-1296, US4.6).
    """
    records: list[ToolCallRecord] = []

    def observer(record: ToolCallRecord) -> None:
        pass

    check_observer(None)
    check_observer(observer)
    check_observer(records.append)


@pytest.mark.parametrize("value", ["x", 1, object()])
def test_check_observer_rejects_non_callables(value: object) -> None:
    """A non-callable observer raises TypeError("on_call must be callable or
    None") (AIE-1296, US4.6).
    """
    with pytest.raises(TypeError) as excinfo:
        check_observer(value)

    assert str(excinfo.value) == "on_call must be callable or None"


def test_check_observer_rejects_async_functions() -> None:
    """An async def observer raises TypeError("on_call must be a plain
    function, not async") (AIE-1296, US4.6).
    """

    async def observer(record: ToolCallRecord) -> None:
        pass

    with pytest.raises(TypeError) as excinfo:
        check_observer(observer)

    assert str(excinfo.value) == "on_call must be a plain function, not async"


def test_notify_delivers_one_record() -> None:
    """notify_observer calls on_call once with a record of the given fields
    (AIE-1296, US4.6).
    """
    records: list[ToolCallRecord] = []

    _notify(records.append)

    assert len(records) == 1
    record = records[0]
    assert record.tool == "read_file"
    assert dict(record.arguments) == {"scope": "user", "aliases": ["tea"]}
    assert dict(record.result) == {"ok": True, "aliases": ["tea"]}
    assert record.is_error is False
    assert record.request_id is None
    assert record.duration_s == 0.25


def test_notify_record_holds_read_only_deep_copies() -> None:
    """The record's arguments and result are deep copies the caller's later
    mutations don't reach, and assigning into them raises TypeError
    (AIE-1296, US4.6).
    """
    records: list[ToolCallRecord] = []
    aliases = ["tea"]
    arguments: dict[str, object] = {"scope": "user", "aliases": aliases}
    payload_aliases = ["tea"]
    result: dict[str, object] = {"ok": True, "aliases": payload_aliases}

    _notify(records.append, arguments=arguments, result=result)
    aliases.append("coffee")
    payload_aliases.append("coffee")
    arguments["scope"] = "org"
    result["ok"] = False

    record = records[0]
    assert dict(record.arguments) == {"scope": "user", "aliases": ["tea"]}
    assert dict(record.result) == {"ok": True, "aliases": ["tea"]}
    with pytest.raises(TypeError):
        cast(dict[str, object], record.arguments)["scope"] = "team"
    with pytest.raises(TypeError):
        cast(dict[str, object], record.result)["ok"] = False


def test_notify_logs_and_swallows_observer_failure(caplog: pytest.LogCaptureFixture) -> None:
    """An observer that raises is logged at ERROR on the given logger, naming
    the tool, with exc_info; notify_observer returns normally (AIE-1296, US4.6).
    """
    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    def observer(record: ToolCallRecord) -> None:
        raise RuntimeError("observer broke")

    _notify(observer)

    errors = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert "read_file" in errors[0].getMessage()
    assert errors[0].exc_info is not None


def test_notify_logs_and_swallows_copy_failure(caplog: pytest.LogCaptureFixture) -> None:
    """When the arguments cannot be deep-copied, no record is delivered, the
    failure is logged at ERROR on the given logger naming the tool, and
    notify_observer returns normally (AIE-1296, US4.6).
    """
    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)
    records: list[ToolCallRecord] = []

    _notify(records.append, arguments={"scope": "user", "aliases": _Uncopyable()})

    assert records == []
    errors = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert "read_file" in errors[0].getMessage()
    assert errors[0].exc_info is not None
