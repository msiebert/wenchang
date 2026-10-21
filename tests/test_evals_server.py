"""The eval MCP server: memory tools plus harness tools over an in-memory store
(AIE-1170, US1 and US4.16(c)).
"""

import json
import sys
import threading
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
from evals.subagent_transcript import SubagentTranscriptError
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


CAPPED = """\
id: capped
title: Capped
category: filing
source: AIE-1170
index_max_bytes: 1
seed:
  - scope: user
    area: preferences
    name: charts
    content: "- [stated] Dark.\\n"
    description: Charts
    aliases: []
  - scope: user
    area: workflows
    name: review
    content: "- [stated] Mondays.\\n"
    description: Review
    aliases: []
sessions:
  - turns: [hi]
assertions:
  - kind: index_read_first
"""


def test_scenario_index_cap_reaches_the_store(tmp_path: Path, state: EvalState) -> None:
    """A scenario's index_max_bytes caps the store's index, so the seeded areas
    are listed under capped and no entry fits (AIE-1170, US9.4).
    """
    capped = _scenario(tmp_path, CAPPED, "capped")
    plain = _scenario(tmp_path, SEEDED, "seeded", identity="member")

    async def body(client: Client) -> tuple[dict[str, Any], dict[str, Any]]:
        await _reset(client, capped, state.runs_root / "t1")
        first = _payload(await client.call_tool("get_memory_index", {}))
        await _reset(client, plain, state.runs_root / "t2")
        second = _payload(await client.call_tool("get_memory_index", {}))
        return first, second

    first, second = _run(state, body)

    assert first["entries"] == []
    assert {row["prefix"] for row in first["capped"]} == {
        "user/u-ada/preferences/",
        "user/u-ada/workflows/",
    }
    assert len(second["entries"]) == 2
    assert second["capped"] == []


def test_record_turn_writes_the_transcript(tmp_path: Path, state: EvalState) -> None:
    """Each eval_record_turn rewrites transcript.json, so the next turn's prompt
    can be built mid-trial (AIE-1170, US1.8).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"

    async def body(client: Client) -> None:
        await _reset(client, scenario, trial)
        await _turn(client, 1, 1, reply="first reply")

    _run(state, body)

    turns = load_transcript(trial / "transcript.json")
    assert [(t.session, t.turn, t.reply) for t in turns] == [(1, 1, "first reply")]


AGENT_ID = "a2d570cdfd6af0fa2"
FULL_REPLY = "I'll check my memory first.\n\nI found nothing.\n\nPROBE-END"
WRAPPED_RESULT = (
    "[Subagent hand-back] The text below is the subagent's reply. The report follows:\n"
    "  I found nothing.\n  \n  PROBE-END\n"
    f"agentId: {AGENT_ID} (use SendMessage with to: '{AGENT_ID}' to continue)\n"
    "<usage>subagent_tokens: 1</usage>"
)


def _subagent_fixture(root: Path) -> None:
    lines = [
        {
            "type": "assistant",
            "uuid": "u1",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I'll check my memory first."}],
            },
        },
        {
            "type": "assistant",
            "uuid": "u4",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "I found nothing.\n\nPROBE-END"}],
            },
        },
    ]
    path = root / "-some-cwd" / "sess-1" / "subagents" / f"agent-{AGENT_ID}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


@pytest.fixture
def transcript_state(tmp_path: Path) -> EvalState:
    _subagent_fixture(tmp_path / "projects")
    state = EvalState(
        runs_root=tmp_path / "runs",
        transcripts_root=tmp_path / "projects",
        transcript_retry_s=0,
    )
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    state.reset(load_scenario(scenario), state.runs_root / "t")
    return state


def test_record_turn_reads_the_reply_from_the_subagent_transcript(
    transcript_state: EvalState,
) -> None:
    """With a transcripts root, the recorded reply is the reconstructed text
    and the passed text is kept as agent_result (AIE-1208, AC14).
    """
    transcript_state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)

    (turn,) = transcript_state.transcript()
    assert (turn.reply, turn.agent_result, turn.agent_id) == (FULL_REPLY, WRAPPED_RESULT, AGENT_ID)
    saved = load_transcript(transcript_state.runs_root / "t" / "transcript.json")
    assert saved == (turn,)


@pytest.mark.parametrize("agent_id", [None, "ffffffffffffffff0"])
def test_record_turn_without_a_findable_transcript_records_nothing(
    transcript_state: EvalState, agent_id: str | None
) -> None:
    """A missing agent id or transcript raises and leaves the transcript
    untouched (AIE-1208, AC14).
    """
    with pytest.raises(SubagentTranscriptError):
        transcript_state.record_turn(1, 1, "hi", WRAPPED_RESULT, agent_id)

    assert transcript_state.transcript() == ()
    assert load_transcript(transcript_state.runs_root / "t" / "transcript.json") == ()


def test_record_turn_tool_errors_when_the_transcript_is_missing(
    tmp_path: Path, transcript_state: EvalState
) -> None:
    """Through MCP, eval_record_turn returns an error result and records
    nothing (AIE-1208, AC14).
    """

    async def body(client: Client) -> CallToolResult:
        return await client.call_tool(
            "eval_record_turn",
            {"session": 1, "turn": 1, "user": "hi", "reply": "r", "agent_id": "nope"},
        )

    result = _run(transcript_state, body)

    assert result.is_error
    assert transcript_state.transcript() == ()


def test_record_turn_is_unchanged_without_a_transcripts_root(
    tmp_path: Path, state: EvalState
) -> None:
    """Without a transcripts root the reply is as passed and no agent_result
    is recorded or written (AIE-1208, AC15).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    state.reset(load_scenario(scenario), state.runs_root / "t")

    state.record_turn(1, 1, "hi", "as passed", "a-1")

    (turn,) = state.transcript()
    assert (turn.reply, turn.agent_result) == ("as passed", None)
    written = json.loads((state.runs_root / "t" / "transcript.json").read_text())
    assert "agent_result" not in json.dumps(written)


def test_record_turn_normalizes_a_decorated_agent_id(transcript_state: EvalState) -> None:
    """The first whitespace-separated token of agent_id is used and recorded
    (AIE-1208, D6 refinement 3).
    """
    decorated = f"{AGENT_ID} (use SendMessage with to: '{AGENT_ID}' to continue)"

    transcript_state.record_turn(1, 1, "hi", WRAPPED_RESULT, decorated)

    (turn,) = transcript_state.transcript()
    assert (turn.agent_id, turn.reply) == (AGENT_ID, FULL_REPLY)


@pytest.mark.parametrize("blank", ["", "   \n"])
def test_record_turn_rejects_a_blank_agent_id(transcript_state: EvalState, blank: str) -> None:
    """An empty or whitespace-only agent_id raises and records nothing
    (AIE-1208, D6 refinement 3).
    """
    with pytest.raises(SubagentTranscriptError):
        transcript_state.record_turn(1, 1, "hi", WRAPPED_RESULT, blank)
    assert transcript_state.transcript() == ()


def test_record_turn_requires_the_final_text_in_the_agent_result(
    transcript_state: EvalState,
) -> None:
    """When the transcript's last text block is not in the agent result, the
    turn raises after retries and records nothing (AIE-1208, D6 refinement 2).
    """
    stale = "[Subagent hand-back]\n  Something else entirely.\nagentId: x\n<usage>t</usage>"

    with pytest.raises(SubagentTranscriptError):
        transcript_state.record_turn(1, 1, "hi", stale, AGENT_ID)

    assert transcript_state.transcript() == ()
    assert load_transcript(transcript_state.runs_root / "t" / "transcript.json") == ()


def test_record_turn_consistency_check_ignores_whitespace_and_framing(
    transcript_state: EvalState,
) -> None:
    """Indentation and line breaks in the wrapped result do not defeat the
    consistency check (AIE-1208, D6 refinement 2).
    """
    transcript_state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)
    assert len(transcript_state.transcript()) == 1


def test_missing_transcript_error_names_the_root_and_the_flag(tmp_path: Path) -> None:
    """The not-found error shows the searched root and how to change it
    (AIE-1208, D6 refinement 4).
    """
    root = tmp_path / "projects"
    state = EvalState(runs_root=tmp_path / "runs", transcripts_root=root, transcript_retry_s=0)
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    state.reset(load_scenario(scenario), state.runs_root / "t")

    with pytest.raises(SubagentTranscriptError) as info:
        state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)

    assert str(root) in str(info.value)
    assert "--transcripts-root" in str(info.value)


def _retry_state(tmp_path: Path, retry_s: float) -> EvalState:
    state = EvalState(
        runs_root=tmp_path / "runs",
        transcripts_root=tmp_path / "projects",
        transcript_retry_s=retry_s,
    )
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    state.reset(load_scenario(scenario), state.runs_root / "t")
    return state


def test_record_turn_retries_until_the_transcript_appears(tmp_path: Path) -> None:
    """A transcript written shortly after the call is picked up by the retry
    (AIE-1208, review follow-up 1).
    """
    state = _retry_state(tmp_path, 1.0)
    timer = threading.Timer(0.2, _subagent_fixture, args=(tmp_path / "projects",))
    timer.start()
    try:
        state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)
    finally:
        timer.join()

    (turn,) = state.transcript()
    assert turn.reply == FULL_REPLY


def test_record_turn_retries_a_transcript_that_is_still_incomplete(tmp_path: Path) -> None:
    """A transcript holding only the pre-tool text is retried until the final
    text lands (AIE-1208, review follow-up 1).
    """
    state = _retry_state(tmp_path, 1.0)
    path = tmp_path / "projects" / "-some-cwd" / "sess-1" / "subagents" / f"agent-{AGENT_ID}.jsonl"
    path.parent.mkdir(parents=True)
    first = {
        "type": "assistant",
        "uuid": "u1",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "I'll check."}]},
    }
    path.write_text(json.dumps(first) + "\n")

    def finish() -> None:
        path.unlink()
        _subagent_fixture(tmp_path / "projects")

    timer = threading.Timer(0.2, finish)
    timer.start()
    try:
        state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)
    finally:
        timer.join()

    (turn,) = state.transcript()
    assert turn.reply == FULL_REPLY


def test_record_turn_raises_on_a_persistently_torn_line(tmp_path: Path) -> None:
    """A torn final JSON line is retried, then raised, recording nothing
    (AIE-1208, review follow-up 2).
    """
    state = _retry_state(tmp_path, 0.3)
    _subagent_fixture(tmp_path / "projects")
    path = tmp_path / "projects" / "-some-cwd" / "sess-1" / "subagents" / f"agent-{AGENT_ID}.jsonl"
    with path.open("a") as handle:
        handle.write('{"type":"assistant","uuid":')

    with pytest.raises(SubagentTranscriptError):
        state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)

    assert state.transcript() == ()


def test_record_turn_raises_on_an_ambiguous_agent_id(tmp_path: Path) -> None:
    """Two transcripts for one id raise and record nothing (AIE-1208, review
    follow-up 2).
    """
    state = _retry_state(tmp_path, 0.0)
    root = tmp_path / "projects"
    _subagent_fixture(root)
    other = root / "-some-cwd" / "sess-2" / "subagents" / f"agent-{AGENT_ID}.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(
        (root / "-some-cwd" / "sess-1" / "subagents" / f"agent-{AGENT_ID}.jsonl").read_text()
    )

    with pytest.raises(SubagentTranscriptError):
        state.record_turn(1, 1, "hi", WRAPPED_RESULT, AGENT_ID)

    assert state.transcript() == ()


def test_reset_writes_an_empty_transcript_file(tmp_path: Path, state: EvalState) -> None:
    """eval_reset writes transcript.json with an empty turns list into the
    trial dir (AIE-1208, review follow-up 5).
    """
    scenario = _scenario(tmp_path, SEEDED, "seeded", identity="member")
    trial = state.runs_root / "t"

    state.reset(load_scenario(scenario), trial)

    assert json.loads((trial / "transcript.json").read_text()) == {"turns": []}
