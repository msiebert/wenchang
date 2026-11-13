"""Eval arms: an alternative index tool name and an optional memory prompt (AIE-1384)."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from evals.__main__ import main
from evals.agent import (
    EVAL_AGENT_PREAMBLE,
    agent_tools,
    render_agent_body,
    render_agent_file,
)
from evals.arm import Arm, ArmError, load_arm, rename_index_tool, save_arm
from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
EVAL_AGENT = ROOT / ".claude" / "agents" / "wenchang-eval.md"
DEFAULT_TOOL = "get_memory_index"
INVALID_NAMES = [
    "Load",
    "1abc",
    "has-dash",
    "a" * 65,
    "read_file",
    "eval_dump",
    "",
]


def _split(text: str) -> tuple[dict[str, Any], str]:
    assert text.startswith("---\n")
    front, body = text[len("---\n") :].split("\n---\n", 1)
    meta: object = yaml.safe_load(front)
    assert isinstance(meta, dict)
    return cast(dict[str, Any], meta), body


def _tools(meta: dict[str, Any]) -> list[str]:
    return [t.strip() for t in str(meta["tools"]).split(",")]


def _run(argv: list[str]) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def test_default_arm_matches_current_output() -> None:
    """The default arm reproduces today's tools, body, and checked-in agent file
    (AIE-1384, AC1).
    """
    default_tools = tuple(f"mcp__wenchang__{name}" for name in TOOL_NAMES)
    assert agent_tools() == default_tools
    assert agent_tools(Arm()) == default_tools
    expected_body = EVAL_AGENT_PREAMBLE + "\n\n" + build_memory_prompt(REFERENCE_SLOTS)
    assert render_agent_body() == expected_body
    assert render_agent_body(Arm()) == expected_body
    assert render_agent_file() == EVAL_AGENT.read_text()
    assert render_agent_file(Arm()) == EVAL_AGENT.read_text()


def test_renamed_arm_replaces_tool_in_place_and_renames_body() -> None:
    """A renamed arm swaps the tool in the same position and renames it in the
    prompt (AIE-1384, AC3).
    """
    arm = Arm("load_memory")
    default = agent_tools()
    renamed = agent_tools(arm)
    index = default.index(f"mcp__wenchang__{DEFAULT_TOOL}")
    assert renamed[index] == "mcp__wenchang__load_memory"
    assert renamed[:index] == default[:index]
    assert renamed[index + 1 :] == default[index + 1 :]

    body = render_agent_body(arm)
    assert DEFAULT_TOOL not in body
    assert "load_memory" in body
    assert body == render_agent_body().replace(DEFAULT_TOOL, "load_memory")
    assert body == rename_index_tool(render_agent_body(), arm)
    _, file_body = _split(render_agent_file(arm))
    assert file_body.strip("\n") == body.strip("\n")


def test_no_agent_prompt_body_is_preamble_only() -> None:
    """Without the agent prompt the body is the preamble alone (AIE-1384, AC2)."""
    body = render_agent_body(Arm("load_memory", agent_prompt=False))
    assert body == EVAL_AGENT_PREAMBLE
    assert DEFAULT_TOOL not in body
    assert "load_memory" not in body


def test_rename_index_tool() -> None:
    """rename_index_tool replaces every occurrence; the default arm is a no-op
    (AIE-1384, AC3).
    """
    text = f"call {DEFAULT_TOOL} then {DEFAULT_TOOL}"
    assert rename_index_tool(text, Arm("load_memory")) == "call load_memory then load_memory"
    assert rename_index_tool(text, Arm()) == text


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_invalid_index_tool_raises(name: str) -> None:
    """An invalid index tool name is rejected (AIE-1384, AC4)."""
    with pytest.raises(ArmError):
        Arm(name)


def test_default_name_is_valid_and_is_default_only_for_default() -> None:
    """get_memory_index is a valid name; only Arm() is the default (AIE-1384, AC4b)."""
    assert Arm(DEFAULT_TOOL).is_default
    assert Arm().is_default
    assert not Arm("load_memory").is_default
    assert not Arm(agent_prompt=False).is_default


def test_arm_json_round_trip(tmp_path: Path) -> None:
    """to_json/from_json and save_arm/load_arm round-trip (AIE-1384, AC4b)."""
    arm = Arm("load_memory", agent_prompt=False)
    assert arm.to_json() == {"index_tool": "load_memory", "agent_prompt": False}
    assert Arm.from_json(arm.to_json()) == arm
    path = tmp_path / "arm.json"
    save_arm(arm, path)
    assert load_arm(path) == arm


def test_load_arm_missing_file_is_default(tmp_path: Path) -> None:
    """A missing arm file loads as the default arm (AIE-1384, AC4b)."""
    assert load_arm(tmp_path / "absent.json") == Arm()


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '"load_memory"',
        '{"index_tool": "load_memory", "extra": 1}',
        '{"index_tool": "load_memory", "agent_prompt": "no"}',
        '{"index_tool": 5}',
        '{"index_tool": "Bad-Name"}',
    ],
)
def test_load_arm_rejects_bad_content(tmp_path: Path, content: str) -> None:
    """Malformed, non-object, unknown-key, wrong-type, or invalid-name arm files
    raise ArmError (AIE-1384, AC4b).
    """
    path = tmp_path / "arm.json"
    path.write_text(content)
    with pytest.raises(ArmError):
        load_arm(path)


def test_set_arm_writes_arm_and_agent_file(tmp_path: Path) -> None:
    """set-arm writes arm.json and rewrites the agent file with the renamed tool
    and a preamble-only body (AIE-1384, AC2).
    """
    arm_path = tmp_path / "arm.json"
    agent_out = tmp_path / "agent.md"
    code = _run(
        [
            "set-arm",
            "--index-tool",
            "load_memory",
            "--no-agent-prompt",
            "--arm-path",
            str(arm_path),
            "--agent-out",
            str(agent_out),
        ]
    )
    assert code == 0
    assert json.loads(arm_path.read_text()) == {"index_tool": "load_memory", "agent_prompt": False}
    meta, body = _split(agent_out.read_text())
    default_tools = [f"mcp__wenchang__{name}" for name in TOOL_NAMES]
    expected = [t.replace(DEFAULT_TOOL, "load_memory") for t in default_tools]
    assert _tools(meta) == expected
    assert body.strip("\n") == EVAL_AGENT_PREAMBLE
    assert DEFAULT_TOOL not in body
    assert "load_memory" not in body


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_set_arm_invalid_name_exits_2_and_writes_nothing(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """An invalid name exits 2 with a message on stderr and writes neither file
    (AIE-1384, AC4).
    """
    arm_path = tmp_path / "arm.json"
    agent_out = tmp_path / "agent.md"
    code = _run(
        [
            "set-arm",
            "--index-tool",
            name,
            "--arm-path",
            str(arm_path),
            "--agent-out",
            str(agent_out),
        ]
    )
    assert code == 2
    assert capsys.readouterr().err.strip() != ""
    assert not arm_path.exists()
    assert not agent_out.exists()


def test_set_arm_reset_deletes_arm_and_restores_default_agent(tmp_path: Path) -> None:
    """--reset deletes arm.json and rewrites the default agent file (AIE-1384, AC4b)."""
    arm_path = tmp_path / "arm.json"
    agent_out = tmp_path / "agent.md"
    save_arm(Arm("load_memory", agent_prompt=False), arm_path)
    agent_out.write_text("stale")
    code = _run(["set-arm", "--reset", "--arm-path", str(arm_path), "--agent-out", str(agent_out)])
    assert code == 0
    assert not arm_path.exists()
    assert agent_out.read_text() == render_agent_file()

    again = _run(["set-arm", "--reset", "--arm-path", str(arm_path), "--agent-out", str(agent_out)])
    assert again == 0
