"""Tests for the on_call observer on MemoryTools and bind_tools.

Covers AIE-1296, US1 (observing direct tool calls), US2 (a failing observer
never breaks the call), US3 (configuring the observer), and US4.1 (no mcp
dependency).
"""

import copy
import inspect
import logging
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import cast

import pytest

from wenchang.core import MemoryFile, MemoryStore
from wenchang.errors import NotFoundError
from wenchang.identity import Identity, ResolutionFailure, SandboxResolver, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import (
    TOOL_NAMES,
    MemoryTools,
    bind_tools,
    render_error,
    render_result,
    tool_descriptions,
)
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit

TIMEOUT = 60
SOURCE = "observer-test"
POLICY = ScopePolicy({})
IDENTITY = Identity({"user": ScopeGrant("u-1", "owner")})
CONTENT = "- [stated] Likes tea\n"
DESCRIPTION = "Tea preferences"
LINE = "- [observed] Drinks it black"
OLD = "Likes tea"
NEW = "Likes green tea"
LOGGER = "wenchang.tools"

_ExcInfo = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]


class _StubClient(InProcessClient):
    """An in-process client whose read_file can return or raise a preset, and
    which records what it returned or raised."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        read_raises: BaseException | None = None,
        read_returns: object = None,
    ) -> None:
        super().__init__(store)
        self.read_raises = read_raises
        self.read_returns = read_returns
        self.returned: list[object] = []
        self.raised: list[BaseException] = []

    def read_file(self, path: str) -> MemoryFile:
        if self.read_raises is not None:
            self.raised.append(self.read_raises)
            raise self.read_raises
        if self.read_returns is not None:
            self.returned.append(self.read_returns)
            return cast(MemoryFile, self.read_returns)
        try:
            value = super().read_file(path)
        except Exception as exc:
            self.raised.append(exc)
            raise
        self.returned.append(value)
        return value


class _UncopyableAliases(list[str]):
    """An aliases list whose deep copy fails."""

    def __deepcopy__(self, memo: dict[int, object]) -> "_UncopyableAliases":
        raise RuntimeError("cannot deep-copy aliases")


class _RecordingResolver:
    """Resolves to IDENTITY and records each call."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def resolve(self, credentials: object) -> Identity | ResolutionFailure:
        self.calls.append(credentials)
        return IDENTITY


def _store() -> MemoryStore:
    return MemoryStore(InMemoryStorage())


def _client(
    *, read_raises: BaseException | None = None, read_returns: object = None
) -> _StubClient:
    return _StubClient(_store(), read_raises=read_raises, read_returns=read_returns)


def _bind(client: InProcessClient, on_call: Callable[[ToolCallRecord], None]) -> MemoryTools:
    return bind_tools(
        client, SandboxResolver(IDENTITY), None, POLICY, source=SOURCE, on_call=on_call
    )


def _seed(client: InProcessClient, name: str = "a") -> MemoryFile:
    """Write a file through tools with no observer."""
    plain = MemoryTools(client, IDENTITY, POLICY, source=SOURCE)
    return plain.write_file("user", "notes", name, CONTENT, DESCRIPTION, ["tea"], None)


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


def _loose(tools: MemoryTools, name: str) -> Callable[..., object]:
    """A tool method typed loosely, for calls Python itself rejects."""
    return cast(Callable[..., object], getattr(tools, name))


# --- US1: observing direct tool calls ---------------------------------------------


def test_successful_call_produces_one_record() -> None:
    """A successful read_file appends one record with the bare name, arguments,
    rendered result, is_error False, request_id None, and a non-negative float
    duration; the call returns the tool's own object (AIE-1296, US1.1).
    """
    client = _client()
    _seed(client)
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    returned = tools.read_file("user", "notes", "a")

    assert returned is client.returned[-1]
    assert len(records) == 1
    record = records[0]
    assert record.tool == "read_file"
    assert dict(record.arguments) == {"scope": "user", "area": "notes", "name": "a"}
    assert dict(record.result) == render_result(returned)
    assert record.is_error is False
    assert record.request_id is None
    assert isinstance(record.duration_s, float)
    assert record.duration_s >= 0


def test_contract_error_produces_one_error_record() -> None:
    """A read_file of a missing file appends one record with is_error True and
    render_error of the exception; the caller gets the identical exception
    (AIE-1296, US1.2).
    """
    client = _client()
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    with pytest.raises(NotFoundError) as excinfo:
        tools.read_file("user", "notes", "missing")

    assert excinfo.value is client.raised[-1]
    assert len(records) == 1
    assert records[0].tool == "read_file"
    assert records[0].is_error is True
    assert dict(records[0].result) == render_error(excinfo.value)
    assert records[0].request_id is None


def test_off_contract_error_is_recorded_as_internal() -> None:
    """An off-contract RuntimeError from the client is recorded with render_error's
    internal payload, without its message, and propagates unchanged
    (AIE-1296, US1.3).
    """
    boom = RuntimeError("secret")
    client = _client(read_raises=boom)
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    with pytest.raises(RuntimeError) as excinfo:
        tools.read_file("user", "notes", "a")

    assert excinfo.value is boom
    assert len(records) == 1
    assert records[0].is_error is True
    assert dict(records[0].result) == render_error(boom)
    assert records[0].result["category"] == "internal"
    assert "secret" not in repr(dict(records[0].result))


def _exercise_all(call: Callable[[str], Callable[..., object]], name: str) -> None:
    """Call each of the seven tools once, in TOOL_NAMES order, on file `name`."""
    call("get_memory_index")()
    call("read_file")("user", "notes", "seed")
    call("list_prefix")("user")
    written = cast(
        MemoryFile,
        call("write_file")("user", "notes", name, CONTENT, DESCRIPTION, ["tea"], None),
    )
    appended = cast(MemoryFile, call("append_line")("user", "notes", name, LINE, written.version))
    replaced = cast(
        MemoryFile,
        call("replace_fact")("user", "notes", name, OLD, NEW, appended.version),
    )
    call("delete_file")("user", "notes", name, replaced.version)


def test_each_tool_produces_one_record_by_attribute_and_by_name() -> None:
    """Each of the seven tools, called by attribute and again through tools(),
    appends exactly one record with its bare name, in call order
    (AIE-1296, US1.4).
    """
    client = _client()
    _seed(client, "seed")
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    _exercise_all(lambda tool: _loose(tools, tool), "by-attribute")
    _exercise_all(lambda tool: tools.tools()[tool], "by-name")

    assert [r.tool for r in records] == [*TOOL_NAMES, *TOOL_NAMES]
    assert all(r.is_error is False for r in records)


def test_arguments_have_defaults_filled() -> None:
    """list_prefix(scope) records every parameter by name with defaults filled
    (AIE-1296, US1.5).
    """
    records: list[ToolCallRecord] = []
    tools = _bind(_client(), records.append)

    tools.list_prefix("user")

    assert dict(records[0].arguments) == {"scope": "user", "area": None, "cursor": None}


def test_positional_and_keyword_calls_give_equal_arguments() -> None:
    """Positional, keyword, and mixed calls record equal argument mappings
    (AIE-1296, US1.5).
    """
    client = _client()
    first = _seed(client)
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    tools.read_file("user", "notes", "a")
    tools.read_file(scope="user", area="notes", name="a")
    tools.read_file("user", name="a", area="notes")
    appended = tools.append_line("user", "notes", "a", LINE, first.version)
    tools.append_line(
        scope="user",
        area="notes",
        name="a",
        line="- [observed] Adds honey",
        expected_version=appended.version,
    )

    reads = [dict(r.arguments) for r in records[:3]]
    assert reads == [{"scope": "user", "area": "notes", "name": "a"}] * 3
    appends = [dict(r.arguments) for r in records[3:]]
    assert appends == [
        {
            "scope": "user",
            "area": "notes",
            "name": "a",
            "line": LINE,
            "expected_version": first.version,
            "aliases": None,
            "description": None,
        },
        {
            "scope": "user",
            "area": "notes",
            "name": "a",
            "line": "- [observed] Adds honey",
            "expected_version": appended.version,
            "aliases": None,
            "description": None,
        },
    ]


def test_record_is_a_read_only_deep_copy() -> None:
    """Mutating the caller's aliases list after the call leaves the record
    unchanged, and assigning into record.arguments or record.result raises
    TypeError (AIE-1296, US1.6).
    """
    records: list[ToolCallRecord] = []
    tools = _bind(_client(), records.append)
    aliases = ["tea"]

    tools.write_file("user", "notes", "a", CONTENT, DESCRIPTION, aliases, None)
    aliases.append("coffee")

    record = records[0]
    assert record.arguments["aliases"] == ["tea"]
    with pytest.raises(TypeError):
        cast(dict[str, object], record.arguments)["scope"] = "org"
    with pytest.raises(TypeError):
        cast(dict[str, object], record.result)["name"] = "b"


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        (("user",), {}),
        (("user", "notes", "a", "extra"), {}),
        (("user", "notes", "a"), {"bogus": 1}),
    ],
)
def test_rejected_call_produces_no_record(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> None:
    """A call Python rejects (wrong arity or unknown keyword) raises TypeError
    and appends no record (AIE-1296, US1.7).
    """
    client = _client()
    _seed(client)
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    with pytest.raises(TypeError):
        _loose(tools, "read_file")(*args, **kwargs)

    assert records == []


def test_observer_runs_on_calling_thread_before_return() -> None:
    """The observer runs on the calling thread before the call returns or
    raises (AIE-1296, US1.8).
    """
    client = _client()
    _seed(client)
    threads: list[int] = []
    tools = _bind(client, lambda record: threads.append(threading.get_ident()))

    tools.read_file("user", "notes", "a")
    after_success = len(threads)
    with pytest.raises(NotFoundError):
        tools.read_file("user", "notes", "missing")
    after_failure = len(threads)

    assert after_success == 1
    assert after_failure == 2
    assert threads == [threading.get_ident()] * 2


@pytest.mark.parametrize(
    ("off_contract", "expected"), [(False, NotFoundError), (True, RuntimeError)]
)
def test_observer_sees_no_active_exception(off_contract: bool, expected: type[Exception]) -> None:
    """An observer capturing sys.exc_info() when a tool raises (contract or
    off-contract) sees (None, None, None) (AIE-1296, US1.9).
    """
    client = _client(read_raises=RuntimeError("boom")) if off_contract else _client()
    seen: list[_ExcInfo] = []
    tools = _bind(client, lambda record: seen.append(sys.exc_info()))

    # Called outside any except block, so only the wrapper could leak an exception.
    with pytest.raises(expected):
        tools.read_file("user", "notes", "missing")

    assert seen == [(None, None, None)]


def test_render_failure_is_recorded_as_error() -> None:
    """When render_result cannot render the tool's return value, one record is
    delivered with is_error True and render_error of the TypeError; the caller
    gets the raw value (AIE-1296, US1.10).
    """
    raw = object()
    client = _client(read_returns=raw)
    records: list[ToolCallRecord] = []
    tools = _bind(client, records.append)

    returned = tools.read_file("user", "notes", "a")

    assert cast(object, returned) is raw
    with pytest.raises(TypeError) as render_failure:
        render_result(cast(MemoryFile, raw))
    assert len(records) == 1
    assert records[0].is_error is True
    assert dict(records[0].result) == render_error(render_failure.value)
    assert records[0].result["error"] == "TypeError"
    assert records[0].result["category"] == "internal"


# --- US2: a failing observer never breaks the call --------------------------------


def _raising_observer(record: ToolCallRecord) -> None:
    raise RuntimeError("observer broke")


def test_failing_observer_on_success_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """An observer raising RuntimeError leaves a successful call's return value
    intact and logs one ERROR on wenchang.tools naming the tool, with exc_info
    (AIE-1296, US2.1).
    """
    caplog.set_level(logging.ERROR, logger=LOGGER)
    client = _client()
    _seed(client)
    tools = _bind(client, _raising_observer)

    returned = tools.read_file("user", "notes", "a")

    assert returned is client.returned[-1]
    errors = _errors(caplog)
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert "read_file" in errors[0].getMessage()
    assert errors[0].exc_info is not None


def test_failing_observer_on_failure_keeps_tool_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When both the tool and the observer raise, the caller gets the tool's own
    exception object and the observer failure is logged (AIE-1296, US2.2).
    """
    caplog.set_level(logging.ERROR, logger=LOGGER)
    client = _client()
    tools = _bind(client, _raising_observer)

    with pytest.raises(NotFoundError) as excinfo:
        tools.read_file("user", "notes", "missing")

    assert excinfo.value is client.raised[-1]
    errors = _errors(caplog)
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert "read_file" in errors[0].getMessage()
    assert errors[0].exc_info is not None


def test_uncopyable_arguments_are_logged_not_delivered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Arguments that cannot be deep-copied leave the tool's outcome unchanged,
    deliver no record, and log at ERROR on wenchang.tools (AIE-1296, US2.3).
    """
    caplog.set_level(logging.ERROR, logger=LOGGER)
    aliases = _UncopyableAliases(["tea"])
    with pytest.raises(RuntimeError):
        copy.deepcopy(aliases)
    records: list[ToolCallRecord] = []
    tools = _bind(_client(), records.append)

    written = tools.write_file("user", "notes", "a", CONTENT, DESCRIPTION, aliases, None)

    assert records == []
    assert written.metadata.aliases == ("tea",)
    plain = MemoryTools(tools.client, IDENTITY, POLICY, source=SOURCE)
    assert plain.read_file("user", "notes", "a") == written
    errors = _errors(caplog)
    assert len(errors) == 1
    assert errors[0].levelno == logging.ERROR
    assert "write_file" in errors[0].getMessage()


def _chain(exc: BaseException | None) -> list[BaseException]:
    seen: list[BaseException] = []
    pending: list[BaseException] = [] if exc is None else [exc]
    while pending:
        current = pending.pop()
        if any(current is s for s in seen):
            continue
        seen.append(current)
        pending.extend(e for e in (current.__context__, current.__cause__) if e is not None)
    return seen


def test_observer_failure_log_does_not_leak_tool_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With an off-contract client error and a raising observer, no wenchang.tools
    log record carries the client's message in its message, formatted traceback,
    or chained exceptions; the client's error still reaches the caller
    (AIE-1296, US2.4).
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    boom = RuntimeError("secret")
    tools = _bind(_client(read_raises=boom), _raising_observer)

    with pytest.raises(RuntimeError) as excinfo:
        tools.read_file("user", "notes", "a")

    assert excinfo.value is boom
    records = _errors(caplog)
    assert len([r for r in records if r.levelno == logging.ERROR]) == 1
    formatter = logging.Formatter()
    for record in records:
        assert "secret" not in record.getMessage()
        if record.exc_info is not None:
            assert "secret" not in formatter.formatException(record.exc_info)
            for chained in _chain(record.exc_info[1]):
                assert chained is not boom
                assert "secret" not in str(chained)


# --- US3: configuring the observer ------------------------------------------------


@pytest.mark.parametrize("target", [bind_tools, MemoryTools])
def test_on_call_is_keyword_only_defaulting_to_none(target: Callable[..., object]) -> None:
    """bind_tools and MemoryTools take a keyword-only on_call defaulting to None
    (AIE-1296, US3.1).
    """
    parameter = inspect.signature(target).parameters["on_call"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


def test_on_call_property_returns_the_observer() -> None:
    """MemoryTools.on_call returns the observer passed, or None (AIE-1296, US3.1)."""
    client = _client()
    records: list[ToolCallRecord] = []
    observer = records.append

    assert MemoryTools(client, IDENTITY, POLICY, source=SOURCE).on_call is None
    assert MemoryTools(client, IDENTITY, POLICY, source=SOURCE, on_call=None).on_call is None
    assert (
        MemoryTools(client, IDENTITY, POLICY, source=SOURCE, on_call=observer).on_call == observer
    )
    assert _bind(client, observer).on_call == observer


def test_no_observer_by_default() -> None:
    """With on_call omitted, tools behave as before (AIE-1296, US3.2)."""
    client = _client()
    _seed(client)
    tools = bind_tools(client, SandboxResolver(IDENTITY), None, POLICY, source=SOURCE)

    assert tools.on_call is None
    assert tools.read_file("user", "notes", "a") is client.returned[-1]


async def _async_observer(record: ToolCallRecord) -> None:
    pass


_BAD_OBSERVERS = [
    ("x", "on_call must be callable or None"),
    (_async_observer, "on_call must be a plain function, not async"),
]


@pytest.mark.parametrize(("on_call", "message"), _BAD_OBSERVERS)
def test_memory_tools_rejects_bad_observer(on_call: object, message: str) -> None:
    """MemoryTools rejects a non-callable or async on_call with TypeError
    (AIE-1296, US3.3).
    """
    with pytest.raises(TypeError) as excinfo:
        MemoryTools(
            _client(),
            IDENTITY,
            POLICY,
            source=SOURCE,
            on_call=cast(Callable[[ToolCallRecord], None], on_call),
        )

    assert str(excinfo.value) == message


@pytest.mark.parametrize(("on_call", "message"), _BAD_OBSERVERS)
def test_bind_tools_rejects_bad_observer_before_resolving(on_call: object, message: str) -> None:
    """bind_tools rejects a non-callable or async on_call with TypeError before
    calling the resolver (AIE-1296, US3.3).
    """
    resolver = _RecordingResolver()

    with pytest.raises(TypeError) as excinfo:
        bind_tools(
            _client(),
            resolver,
            "creds",
            POLICY,
            source=SOURCE,
            on_call=cast(Callable[[ToolCallRecord], None], on_call),
        )

    assert str(excinfo.value) == message
    assert resolver.calls == []


_EXPECTED_PARAMETERS: dict[str, list[str]] = {
    "get_memory_index": [],
    "read_file": ["scope", "area", "name"],
    "list_prefix": ["scope", "area", "cursor"],
    "write_file": [
        "scope",
        "area",
        "name",
        "content",
        "description",
        "aliases",
        "expected_version",
    ],
    "append_line": [
        "scope",
        "area",
        "name",
        "line",
        "expected_version",
        "aliases",
        "description",
    ],
    "replace_fact": [
        "scope",
        "area",
        "name",
        "old_string",
        "new_string",
        "expected_version",
        "aliases",
        "description",
    ],
    "delete_file": ["scope", "area", "name", "expected_version"],
}


def test_descriptions_and_signatures_are_unchanged_by_observer() -> None:
    """descriptions(), tool_descriptions(), and each tool method's signature are
    identical with and without an observer (AIE-1296, US3.4).
    """
    client = _client()
    before = dict(tool_descriptions())
    plain = MemoryTools(client, IDENTITY, POLICY, source=SOURCE)
    records: list[ToolCallRecord] = []
    observed = MemoryTools(client, IDENTITY, POLICY, source=SOURCE, on_call=records.append)

    assert dict(observed.descriptions()) == dict(plain.descriptions())
    assert dict(tool_descriptions()) == before
    for name in TOOL_NAMES:
        observed_method = _loose(observed, name)
        plain_method = _loose(plain, name)
        assert inspect.signature(observed_method) == inspect.signature(plain_method)
        assert list(inspect.signature(observed_method).parameters) == _EXPECTED_PARAMETERS[name]
        assert observed_method.__name__ == name
        assert observed_method.__doc__ == plain_method.__doc__
    assert records == []


# --- Edge cases -------------------------------------------------------------------


def test_base_exception_from_tool_propagates_without_record() -> None:
    """A KeyboardInterrupt raised by the tool is not caught: it propagates
    unchanged and produces no record (AIE-1296, edge case: non-Exception
    BaseExceptions).
    """
    interrupt = KeyboardInterrupt()
    records: list[ToolCallRecord] = []
    tools = _bind(_client(read_raises=interrupt), records.append)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        tools.read_file("user", "notes", "a")

    assert excinfo.value is interrupt
    assert records == []


def test_base_exception_from_observer_propagates() -> None:
    """A KeyboardInterrupt raised by the observer is not swallowed
    (AIE-1296, edge case: non-Exception BaseExceptions).
    """
    interrupt = KeyboardInterrupt()
    client = _client()
    _seed(client)

    def observer(record: ToolCallRecord) -> None:
        raise interrupt

    tools = _bind(client, observer)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        tools.read_file("user", "notes", "a")

    assert excinfo.value is interrupt


def test_duration_excludes_observer_time() -> None:
    """duration_s covers the tool method only, not the observer: a slow observer
    does not inflate it (AIE-1296, edge case: duration_s boundary).
    """
    client = _client()
    _seed(client)
    records: list[ToolCallRecord] = []

    def slow_observer(record: ToolCallRecord) -> None:
        time.sleep(0.2)
        records.append(record)

    tools = _bind(client, slow_observer)

    tools.read_file("user", "notes", "a")

    assert len(records) == 1
    assert records[0].duration_s < 0.04


# --- US4.1: no mcp dependency -----------------------------------------------------


def test_observer_works_without_mcp() -> None:
    """With mcp unimportable, wenchang.observer and wenchang.tools import and
    bind_tools(..., on_call=...) delivers records (AIE-1296, US4.1).
    """
    code = """
import sys
sys.modules["mcp"] = None
import wenchang.observer
import wenchang.tools
from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient
records = []
tools = wenchang.tools.bind_tools(
    InProcessClient(MemoryStore(InMemoryStorage())),
    SandboxResolver(Identity({"user": ScopeGrant("u-1", "owner")})),
    None,
    ScopePolicy({}),
    source="no-mcp",
    on_call=records.append,
)
tools.get_memory_index()
assert all(isinstance(r, wenchang.observer.ToolCallRecord) for r in records)
assert not [m for m in sys.modules if m.startswith("mcp.")]
print(",".join(r.tool for r in records))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "get_memory_index"
