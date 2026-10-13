"""The eval MCP server: memory tools plus harness tools over an in-memory store
(AIE-1170, US1 and US4.16(c)).
"""

import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import anyio
import pytest
from mcp import StdioServerParameters
from mcp.client import Client
from mcp.types import CallToolResult

from evals.graders import load_store_dump, load_trace, load_transcript, order_key
from evals.reference_adopter import (
    REFERENCE_PRODUCT,
    REFERENCE_SLOTS,
    bind_reference_tools,
)
from evals.scenario import load_scenario
from evals.server import (
    EVAL_SERVER_INSTRUCTIONS,
    HARNESS_TOOL_NAMES,
    EvalState,
    build_eval_server,
)
from wenchang.core import MemoryStore
from wenchang.mcp import PROMPT_RESOURCE_URI, ToolCallRecord
from wenchang.prompts import build_memory_prompt
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import TOOL_NAMES, tool_descriptions
from wenchang.transport import InProcessClient

pytestmark = pytest.mark.unit

SEEDED = """\
id: seeded
title: Seeded
category: filing
source: AIE-1170
identity: {identity}
seed:
  - scope: user
    area: preferences
    name: editor
    content: "- [stated] Prefers tabs.\\n"
    description: Editor preferences
    aliases: [editor]
  - scope: project
    area: metrics
    name: activation
    content: "- [stated] Activation is the second purchase.\\n"
    description: Activation
    aliases: []
sessions:
  - turns: [one, two]
  - turns: [three]
assertions:
  - kind: index_read_first
"""

OTHER = """\
id: other
title: Other
category: privacy
source: AIE-1170
seed:
  - scope: user
    area: notes
    name: fresh
    content: "- [stated] Fresh.\\n"
    description: Fresh
    aliases: []
sessions:
  - turns: [hi]
assertions:
  - kind: index_read_first
"""


def _scenario(tmp_path: Path, text: str, stem: str, **fmt: str) -> Path:
    path = tmp_path / "scenarios" / f"{stem}.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text.format(**fmt) if fmt else text)
    return path


def _run[T](state: EvalState, body: Callable[[Client], Awaitable[T]]) -> T:
    async def main() -> T:
        with anyio.fail_after(30):
            async with Client(build_eval_server(state)) as client:
                return await body(client)

    return anyio.run(main)


def _payload(result: CallToolResult) -> dict[str, Any]:
    payload = result.structured_content
    assert payload is not None
    return payload


def _error_text(result: CallToolResult) -> str:
    assert result.is_error
    return json.dumps([c.model_dump() for c in result.content])


async def _reset(client: Client, scenario: Path, trial_dir: Path) -> CallToolResult:
    return await client.call_tool(
        "eval_reset", {"scenario_path": str(scenario), "trial_dir": str(trial_dir)}
    )


async def _write(client: Client, scope: str, area: str, name: str, line: str) -> CallToolResult:
    return await client.call_tool(
        "write_file",
        {
            "scope": scope,
            "area": area,
            "name": name,
            "content": f"{line}\n",
            "description": f"About {name}",
            "aliases": [],
            "expected_version": None,
        },
    )


async def _turn(client: Client, session: int, turn: int, reply: str = "ok") -> CallToolResult:
    return await client.call_tool(
        "eval_record_turn",
        {"session": session, "turn": turn, "user": f"u{session}.{turn}", "reply": reply},
    )


@pytest.fixture
def state(tmp_path: Path) -> EvalState:
    return EvalState(runs_root=tmp_path / "runs")


def test_tool_surface_is_memory_tools_plus_harness(state: EvalState) -> None:
    """The server lists TOOL_NAMES plus the harness tools, with the reference
    product's descriptions (AIE-1170, US1.1).
    """

    async def body(client: Client) -> dict[str, str | None]:
        return {t.name: t.description for t in (await client.list_tools()).tools}

    tools = _run(state, body)
    bound = bind_reference_tools(InProcessClient(MemoryStore(InMemoryStorage())))

    assert set(tools) == {*TOOL_NAMES, *HARNESS_TOOL_NAMES}
    assert HARNESS_TOOL_NAMES == ("eval_reset", "eval_record_turn", "eval_dump")
    for name in TOOL_NAMES:
        assert tools[name] == tool_descriptions(REFERENCE_PRODUCT)[name]
        assert tools[name] == bound.descriptions()[name]


def test_instructions_are_neutral_and_prompt_is_a_resource(state: EvalState) -> None:
    """Instructions do not carry the prompt; the prompt resource does
    (AIE-1170, US1.2).
    """
    prompt = build_memory_prompt(REFERENCE_SLOTS)

    async def body(client: Client) -> tuple[str | None, str]:
        read = await client.read_resource(PROMPT_RESOURCE_URI)
        return client.instructions, cast(Any, read.contents[0]).text

    instructions, resource = _run(state, body)

    assert instructions == EVAL_SERVER_INSTRUCTIONS == "Memory tools for this workspace."
    assert "eval" not in (instructions or "").lower()
    assert prompt not in (instructions or "")
    assert resource == prompt


def test_reset_seeds_the_store(tmp_path: Path, state: EvalState) -> None:
    """eval_reset seeds the scenario's files under the identity's entities
    (AIE-1170, US1.3).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")

    async def body(client: Client) -> dict[str, Any]:
        reset = await _reset(client, scenario, state.runs_root / "t1")
        assert not reset.is_error, reset
        return _payload(await client.call_tool("get_memory_index", {}))

    index = _run(state, body)

    entries = {e["path"]: e for e in index["entries"]}
    assert set(entries) == {
        "user/u-ada/preferences/editor.md",
        "project/p-checkout/metrics/activation.md",
    }
    assert all(e["sources"] == ["seed-job"] for e in entries.values())


def test_reset_replaces_store_trace_and_transcript(tmp_path: Path, state: EvalState) -> None:
    """A second reset leaves only the new seeds and an empty trace and
    transcript; seq restarts (AIE-1170, US1.4).
    """
    first = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    second = _scenario(tmp_path, OTHER, "other")
    trial = state.runs_root / "t2"

    async def body(client: Client) -> None:
        await _reset(client, first, state.runs_root / "t1")
        await _write(client, "user", "notes", "x", "- [stated] x")
        await _turn(client, 1, 1)
        await _reset(client, second, trial)
        await client.call_tool("get_memory_index", {})
        await client.call_tool("eval_dump", {})

    _run(state, body)

    store = load_store_dump(trial / "store.json")
    trace = load_trace(trial / "trace.json")
    assert [f.path for f in store.files] == ["user/u-ada/notes/fresh.md"]
    assert [(c.seq, c.tool) for c in trace] == [(1, "get_memory_index")]
    assert load_transcript(trial / "transcript.json") == ()


def test_identity_comes_from_the_scenario(tmp_path: Path, state: EvalState) -> None:
    """admin may write organization; member gets role_required (AIE-1170, US1.5)."""
    results: dict[str, CallToolResult] = {}
    for identity in ("admin", "member"):
        scenario = _scenario(tmp_path, SEEDED, f"seeded-{identity}", identity=identity)
        scenario.write_text(scenario.read_text().replace("id: seeded", f"id: seeded-{identity}"))

        async def body(client: Client, scenario: Path = scenario) -> CallToolResult:
            await _reset(client, scenario, state.runs_root / "t")
            return await _write(client, "organization", "vocabulary", "x", "- [stated] x")

        results[identity] = _run(state, body)

    assert not results["admin"].is_error
    assert results["member"].is_error
    assert _payload(results["member"])["reason"] == "role_required"


def test_trace_records_carry_timing_and_correlation(tmp_path: Path, state: EvalState) -> None:
    """Records carry seq, request_id, duration_s, started_ms, completed_ms,
    tool, arguments, result, and is_error; harness calls are not traced
    (AIE-1170, US1.6).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"

    async def body(client: Client) -> None:
        await _reset(client, scenario, trial)
        await client.call_tool("get_memory_index", {})
        await client.call_tool(
            "read_file", {"scope": "user", "area": "preferences", "name": "missing"}
        )
        await _turn(client, 1, 1)
        await client.call_tool("eval_dump", {})

    _run(state, body)

    trace = load_trace(trial / "trace.json")
    assert [(c.seq, c.tool, c.is_error) for c in trace] == [
        (1, "get_memory_index", False),
        (2, "read_file", True),
    ]
    first, second = trace
    assert first.request_id and second.request_id and first.request_id != second.request_id
    for call in trace:
        assert call.duration_s >= 0
        assert call.started_ms <= call.completed_ms
        assert call.completed_ms - call.started_ms == pytest.approx(call.duration_s * 1000)
    assert first.completed_ms <= second.started_ms
    assert second.arguments == {"scope": "user", "area": "preferences", "name": "missing"}
    assert second.result["reason"] == "file_absent"


def test_turns_tag_calls_by_time_window(tmp_path: Path, state: EvalState) -> None:
    """Each eval_record_turn closes a window; calls before its boundary belong
    to that turn; the transcript keeps both turns (AIE-1170, US1.7, US1.8).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"

    async def body(client: Client) -> None:
        await _reset(client, scenario, trial)
        for _ in range(3):
            await client.call_tool("get_memory_index", {})
        await _turn(client, 1, 1, reply="first")
        await client.call_tool("get_memory_index", {})
        await client.call_tool(
            "eval_record_turn",
            {"session": 1, "turn": 2, "user": "u1.2", "reply": "second", "agent_id": "a-1"},
        )
        await client.call_tool("eval_dump", {})

    _run(state, body)

    trace = load_trace(trial / "trace.json")
    assert [(c.session, c.turn) for c in trace] == [(1, 1), (1, 1), (1, 1), (1, 2)]
    transcript = load_transcript(trial / "transcript.json")
    assert [(t.session, t.turn, t.user, t.reply, t.agent_id) for t in transcript] == [
        (1, 1, "u1.1", "first", None),
        (1, 2, "u1.2", "second", "a-1"),
    ]


def test_dump_writes_the_store_and_tags_trailing_calls(tmp_path: Path, state: EvalState) -> None:
    """eval_dump writes all three files; the store has seeded and written
    files and not deleted ones; calls after the last boundary are 0/0
    (AIE-1170, US1.9).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "nested" / "t"

    async def body(client: Client) -> dict[str, Any]:
        await _reset(client, scenario, trial)
        await _write(client, "user", "notes", "new", "- [stated] New.")
        await _turn(client, 1, 1)
        index = _payload(await client.call_tool("get_memory_index", {}))
        version = next(
            e["version"] for e in index["entries"] if e["path"].endswith("metrics/activation.md")
        )
        await client.call_tool(
            "delete_file",
            {
                "scope": "project",
                "area": "metrics",
                "name": "activation",
                "expected_version": version,
            },
        )
        return _payload(await client.call_tool("eval_dump", {}))

    result = _run(state, body)

    store = load_store_dump(trial / "store.json")
    assert [f.path for f in store.files] == [
        "user/u-ada/notes/new.md",
        "user/u-ada/preferences/editor.md",
    ]
    new = store.get("user", "notes", "new")
    assert new is not None
    assert (new.content, new.description, new.sources) == (
        "- [stated] New.\n",
        "About new",
        ("reference-agent",),
    )
    trace = load_trace(trial / "trace.json")
    assert [(c.tool, c.session, c.turn) for c in trace] == [
        ("write_file", 1, 1),
        ("get_memory_index", 0, 0),
        ("delete_file", 0, 0),
    ]
    assert result == {
        "store": str(trial / "store.json"),
        "trace": str(trial / "trace.json"),
        "transcript": str(trial / "transcript.json"),
        "files": 2,
        "calls": 3,
    }


def test_dump_before_reset_is_an_error(state: EvalState) -> None:
    """Without eval_reset, eval_dump errors and memory tools use an empty
    member store (AIE-1170, US1.10).
    """

    async def body(client: Client) -> tuple[CallToolResult, CallToolResult]:
        dump = await client.call_tool("eval_dump", {})
        write = await _write(client, "user", "notes", "x", "- [stated] x")
        return dump, write

    dump, write = _run(state, body)

    assert "eval_reset" in _error_text(dump)
    assert not write.is_error
    assert _payload(write)["path"] == "user/u-ada/notes/x.md"


@pytest.mark.parametrize("problem", ["missing", "invalid", "outside"])
def test_bad_reset_leaves_state_unchanged(tmp_path: Path, state: EvalState, problem: str) -> None:
    """A missing or invalid scenario, or a trial dir outside the runs root, is
    an error naming it, and the trial in progress is untouched (AIE-1170, US1.11).
    """
    good = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"
    bad_scenario = good
    bad_trial = trial
    needle = ""
    if problem == "missing":
        bad_scenario = tmp_path / "scenarios" / "absent.yaml"
        needle = "absent.yaml"
    elif problem == "invalid":
        bad_scenario = _scenario(tmp_path, "id: broken\n", "broken")
        needle = "broken.yaml"
    else:
        bad_trial = tmp_path / "elsewhere"
        needle = "elsewhere"

    async def body(client: Client) -> CallToolResult:
        await _reset(client, good, trial)
        await _write(client, "user", "notes", "kept", "- [stated] Kept.")
        bad = await _reset(client, bad_scenario, bad_trial)
        await client.call_tool("eval_dump", {})
        return bad

    bad = _run(state, body)

    assert needle in _error_text(bad)
    store = load_store_dump(trial / "store.json")
    assert store.get("user", "notes", "kept") is not None
    assert [c.tool for c in load_trace(trial / "trace.json")] == ["write_file"]
    assert not (tmp_path / "elsewhere").exists()


def test_concurrent_calls_are_all_traced(tmp_path: Path, state: EvalState) -> None:
    """20 concurrent calls give 20 records with distinct seq and request ids
    (AIE-1170, US1.12).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"

    async def body(client: Client) -> None:
        await _reset(client, scenario, trial)
        async with anyio.create_task_group() as group:
            for i in range(20):
                group.start_soon(_write, client, "user", "notes", f"n{i}", f"- [stated] {i}")
        await client.call_tool("eval_dump", {})

    _run(state, body)

    trace = load_trace(trial / "trace.json")
    assert sorted(c.seq for c in trace) == list(range(1, 21))
    assert len({c.request_id for c in trace}) == 20


def test_late_record_is_tagged_by_start_time(tmp_path: Path) -> None:
    """A record that arrives after a turn boundary but started before it
    belongs to that turn; untagged calls sort last (AIE-1170, US4.16(c)).
    """
    now = [0.0]
    state = EvalState(runs_root=tmp_path / "runs", clock=lambda: now[0])
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")

    state.reset(load_scenario(scenario), state.runs_root / "t")

    def record(tool: str, at: float, duration_s: float) -> None:
        now[0] = at
        state.record_call(
            ToolCallRecord(
                tool, MappingProxyType({}), MappingProxyType({}), False, tool, duration_s
            )
        )

    record("get_memory_index", at=0.010, duration_s=0.005)
    now[0] = 0.020
    state.record_turn(1, 1, "u", "r")
    record("read_file", at=0.025, duration_s=0.010)  # started at 15 ms, before the boundary
    record("append_line", at=0.040, duration_s=0.002)
    now[0] = 0.050
    state.record_turn(1, 2, "u", "r")
    record("delete_file", at=0.060, duration_s=0.001)
    state.dump()

    trace = sorted(load_trace(state.runs_root / "t" / "trace.json"), key=order_key)
    assert [(c.tool, c.session, c.turn) for c in trace] == [
        ("get_memory_index", 1, 1),
        ("read_file", 1, 1),
        ("append_line", 1, 2),
        ("delete_file", 0, 0),
    ]
    read = next(c for c in trace if c.tool == "read_file")
    assert read.seq == 2
    assert read.started_ms == pytest.approx(15.0)


def test_server_runs_over_stdio(tmp_path: Path) -> None:
    """python -m evals.server serves the tool surface and a reset, write, dump
    round trip over stdio from any working directory (AIE-1170, US1.13).
    """
    runs = tmp_path / "runs"
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = runs / "t"
    work = tmp_path / "cwd"
    work.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evals.server", "--runs-root", str(runs)],
        cwd=str(work),
    )

    async def main() -> tuple[set[str], bool, bool]:
        with anyio.fail_after(30):
            async with Client(params) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                reset = await _reset(client, scenario, trial)
                write = await _write(client, "user", "notes", "x", "- [stated] x")
                await client.call_tool("eval_dump", {})
                return names, reset.is_error, write.is_error

    names, reset_error, write_error = anyio.run(main)

    assert names == {*TOOL_NAMES, *HARNESS_TOOL_NAMES}
    assert (reset_error, write_error) == (False, False)
    assert load_store_dump(trial / "store.json").get("user", "notes", "x") is not None


def test_reset_does_not_move_the_time_baseline(tmp_path: Path) -> None:
    """Times are measured from server start; eval_reset never rebases them
    (AIE-1170, US1.6).
    """
    now = [100.0]
    state = EvalState(runs_root=tmp_path / "runs", clock=lambda: now[0])
    scenario = load_scenario(_scenario(tmp_path, SEEDED, "seeded", identity="member"))

    now[0] = 102.0
    state.reset(scenario, state.runs_root / "t")
    now[0] = 103.0
    state.record_call(
        ToolCallRecord(
            "get_memory_index", MappingProxyType({}), MappingProxyType({}), False, "1", 0.5
        )
    )

    (call,) = state.trace()
    assert call.completed_ms == pytest.approx(3000.0)
    assert call.started_ms == pytest.approx(2500.0)
