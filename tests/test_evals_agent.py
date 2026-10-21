"""The eval agent definitions, the eval session's MCP config, and the runner doc
(AIE-1170, US2).
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

import evals.agent
from evals.__main__ import main
from evals.agent import (
    AGENT_NAME,
    EVAL_AGENT_PREAMBLE,
    agent_tools,
    render_agent_body,
    render_agent_file,
)
from evals.reference_adopter import REFERENCE_SLOTS
from evals.server import HARNESS_TOOL_NAMES
from wenchang.prompts import build_memory_prompt
from wenchang.tools import TOOL_NAMES

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".claude" / "agents"
EVAL_AGENT = AGENTS / "wenchang-eval.md"
JUDGE_AGENT = AGENTS / "wenchang-eval-judge.md"
RUNNER = ROOT / ".claude" / "commands" / "run-evals.md"
_FLAGS = (
    "--mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "
    '"Bash(uv run python -m evals *)" "Edit(evals/runs/**)" '
    "--settings '{\"includeGitInstructions\": false}'"
)
LAUNCH = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk " + _FLAGS
SHARD_LAUNCH = (
    'CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude -p "/run-evals --model sonnet --trials 3 '
    '--judge --shard 1/3" --permission-mode dontAsk ' + _FLAGS
)
PREFLIGHT_PROMPT = (
    "Call get_memory_index first. After it returns, reply with the exact names of every tool "
    "you can call, and finish your reply with this line on its own, as the last line: "
    "WENCHANG-PREFLIGHT-END"
)
LAUNCH_DOCS = (
    "AGENTS.md",
    "README.md",
    ".claude/commands/run-evals.md",
    "docs/adr/0028-behavioral-eval-harness.md",
)
GUARDED_AGENT_TYPES = {"test-writer", "implementer", "doc-updater", "explorer", "spec-reviewer"}


def _split(text: str) -> tuple[dict[str, Any], str]:
    assert text.startswith("---\n")
    front, body = text[len("---\n") :].split("\n---\n", 1)
    meta: object = yaml.safe_load(front)
    assert isinstance(meta, dict)
    return cast(dict[str, Any], meta), body


def _tools(meta: dict[str, Any]) -> list[str]:
    return [t.strip() for t in str(meta["tools"]).split(",")]


def test_eval_agent_frontmatter() -> None:
    """The eval agent can reach only the seven memory tools, inherits the model,
    and omits CLAUDE.md (AIE-1170, US2.1).
    """
    meta, _ = _split(EVAL_AGENT.read_text())

    assert meta["name"] == AGENT_NAME == "wenchang-eval"
    assert _tools(meta) == [f"mcp__wenchang__{name}" for name in TOOL_NAMES]
    assert _tools(meta) == list(agent_tools())
    assert not any(name in tool for tool in _tools(meta) for name in HARNESS_TOOL_NAMES)
    assert meta["model"] == "inherit"
    assert meta["omitClaudeMd"] is True


def test_eval_agent_body_is_preamble_plus_prompt() -> None:
    """The checked-in file equals the rendered one, whose body is the preamble
    and the reference memory prompt (AIE-1170, US2.2).
    """
    text = EVAL_AGENT.read_text()
    _, body = _split(text)

    assert text == render_agent_file()
    assert render_agent_body() == EVAL_AGENT_PREAMBLE + "\n\n" + build_memory_prompt(
        REFERENCE_SLOTS
    )
    assert body.strip("\n") == render_agent_body().strip("\n")


def test_preamble_frames_each_message_as_the_users_turn() -> None:
    """Each message is the user's turn and may carry earlier turns, and the
    reply addresses the user as "you", never as "the user" (AIE-1184, US2.1).
    """
    assert EVAL_AGENT_PREAMBLE == (
        "You are an assistant helping a Mixpanel user. Each message you receive is that "
        "user's own turn. Your reply goes to that user word for word, so in your reply "
        'address them as "you" and never call them "the user". Earlier turns of this '
        "conversation may be included above the newest one."
    )
    assert EVAL_AGENT_PREAMBLE in EVAL_AGENT.read_text()


def test_render_agent_writes_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """render-agent writes the rendered file to --out, or to the agent path by
    default (AIE-1170, US2.3).
    """
    out = tmp_path / "out.md"
    assert main(["render-agent", "--out", str(out)]) == 0
    assert out.read_text() == render_agent_file()

    default = tmp_path / "default.md"
    monkeypatch.setattr(evals.agent, "AGENT_PATH", default)
    assert main(["render-agent"]) == 0
    assert default.read_text() == render_agent_file()


def test_eval_agent_is_not_guard_routed() -> None:
    """The agent name is none the guard hook routes (AIE-1170, US2.4)."""
    assert AGENT_NAME not in GUARDED_AGENT_TYPES
    assert "wenchang-eval-judge" not in GUARDED_AGENT_TYPES


def test_eval_mcp_config() -> None:
    """evals/mcp.json defines only the wenchang server, run from the repo root
    without variable expansion; no root .mcp.json exists (AIE-1170, US2.5).
    """
    config = json.loads((ROOT / "evals" / "mcp.json").read_text())

    assert config == {
        "mcpServers": {
            "wenchang": {
                "command": "uv",
                "args": ["run", "--directory", ".", "python", "-m", "evals.server"],
            }
        }
    }
    assert not (ROOT / ".mcp.json").exists()


def test_judge_agent() -> None:
    """The judge reads and writes files only, omits CLAUDE.md, and names its
    inputs and output (AIE-1170, US2.6).
    """
    meta, body = _split(JUDGE_AGENT.read_text())

    assert meta["name"] == "wenchang-eval-judge"
    assert _tools(meta) == ["Read", "Write"]
    assert meta["omitClaudeMd"] is True
    for needle in ("transcript.json", "store.json", "judge", "judge.json"):
        assert needle in body
    for needle in (
        "turn N",
        "session S turn N",
        "defaults to 1",
        "If that reply is missing from the transcript, the verdict is `fail`.",
    ):
        assert needle in body, needle


def test_runner_doc_describes_parallel_shards() -> None:
    """Parallelism is across sessions: one launch per shard, then a merge; the
    runner stays serial inside a session (AIE-1170, parallel shards).
    """
    doc = RUNNER.read_text()
    required = [
        "## Parallel shards",
        "--shard k/n",
        "uv run python -m evals merge-runs",
        "Trials inside one session stay serial",
        "evals/runs/preflight-<k>of<n>/",
    ]
    missing = [needle for needle in required if needle not in doc]
    assert missing == []


def test_runner_doc_names_everything_the_runner_needs() -> None:
    """The runner doc has the launch command, the preflight, the harness tools,
    the CLI subcommands, the subagent type, and the turn rules (AIE-1170, US2.7).
    """
    doc = RUNNER.read_text()

    required = [
        LAUNCH,
        "Preflight",
        "evals/runs/preflight/",
        *HARNESS_TOOL_NAMES,
        "python -m evals new-run",
        "python -m evals grade",
        "python -m evals report",
        'subagent_type="wenchang-eval"',
        "verbatim",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1",
        "uv run python -m evals turn-prompt",
        "Every `Agent` call, including every later turn, passes `model=<model>`",
        "A turn run on the wrong model invalidates the trial",
        "Never stop, pause, skip, or reorder trials because of their results",
        "Never edit any file outside `evals/runs/`",
        "--settings '{\"includeGitInstructions\": false}'",
        "background task",
        "completion notification",
        "before the next turn",
    ]
    missing = [needle for needle in required if needle not in doc]
    assert missing == []
    assert "SendMessage" not in doc


def test_runner_doc_passes_context_blocks_unchanged_and_records_the_bare_turn() -> None:
    """The runner passes the turn-prompt output to the Agent call unchanged,
    context blocks included, and records only the scenario's turn text as the
    user argument (AIE-1185, US2.4).
    """
    doc = " ".join(RUNNER.read_text().split())

    needles = (
        "passed unchanged",
        "context blocks",
        "turn text alone",
        "For turn 1 it is the scripted text, after any context blocks.",
    )
    for needle in needles:
        assert needle in doc, needle


def _normalized() -> str:
    return " ".join(RUNNER.read_text().split())


def test_launch_constants_match_the_spec() -> None:
    """The expected launch strings are the ones AIE-1208 specifies."""
    assert LAUNCH == (
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 claude --permission-mode dontAsk "
        "--mcp-config evals/mcp.json --strict-mcp-config --allowedTools mcp__wenchang "
        '"Bash(uv run python -m evals *)" "Edit(evals/runs/**)" '
        "--settings '{\"includeGitInstructions\": false}'"
    )


def test_runner_doc_has_both_launch_commands() -> None:
    """The runner doc carries the interactive and the shard launch commands
    verbatim (AIE-1208, AC1, AC2).
    """
    doc = RUNNER.read_text()
    assert LAUNCH in doc
    assert SHARD_LAUNCH in doc


@pytest.mark.parametrize("relative", LAUNCH_DOCS)
def test_every_launch_line_has_permission_mode_and_edit_rule(relative: str) -> None:
    """Every documented claude launch line sets dontAsk and allows Edit on
    evals/runs (AIE-1208, AC3).
    """
    lines = [
        line
        for line in (ROOT / relative).read_text().splitlines()
        if "claude " in line and "--mcp-config evals/mcp.json" in line
    ]
    assert len(lines) >= 1
    for line in lines:
        assert "--permission-mode dontAsk" in line, line
        assert '"Edit(evals/runs/**)"' in line, line


def test_runner_doc_has_the_exact_preflight_prompt() -> None:
    """The preflight prompt is exact and ordered: index first, tool names, then
    the end marker (AIE-1208, AC4, AC17).
    """
    doc = _normalized()
    assert PREFLIGHT_PROMPT in doc
    first = PREFLIGHT_PROMPT.index("get_memory_index first")
    names = PREFLIGHT_PROMPT.index("exact names of every tool")
    end = PREFLIGHT_PROMPT.index("WENCHANG-PREFLIGHT-END")
    assert first < names < end


def test_runner_doc_preflight_checks_the_agent_result() -> None:
    """The preflight verifies seven tools, the end marker on the last non-empty
    line, and a clean tool result (AIE-1208, AC5).
    """
    doc = _normalized()
    for needle in (
        "all seven memory tools",
        "SubagentHandback",
        '"is_error": false',
        "WENCHANG-PREFLIGHT-END",
        "last non-empty line",
        "transcript.json",
    ):
        assert needle in doc, needle


def test_runner_doc_tells_a_wrong_session_to_relaunch() -> None:
    """A session without the right permissions is relaunched (AIE-1208, AC6)."""
    assert "relaunch with the step 0 command" in _normalized()


def test_runner_doc_launch_section_explains_each_part() -> None:
    """The launch explanation covers the permission mode, SubagentHandback, the
    Edit rule, and judge.json (AIE-1208, AC7).
    """
    doc = RUNNER.read_text()
    start = doc.index("What each part does")
    end = doc.index("## 1. Preflight")
    section = doc[start:end]
    for needle in (
        "--permission-mode dontAsk",
        "SubagentHandback",
        "Edit(evals/runs/**)",
        "judge.json",
    ):
        assert needle in section, needle


def test_runner_doc_stops_on_denials_and_missing_judge_output() -> None:
    """A denied tool call stops the run, as does a missing judge.json
    (AIE-1208, AC10).
    """
    doc = _normalized()
    assert "If any tool call is denied, stop" in doc
    assert "If it is missing, stop" in doc


def test_runner_doc_requires_agent_id_for_the_full_reply() -> None:
    """The turn's agent id is required because the server reads the full reply
    from the subagent's transcript (AIE-1208, AC17b).
    """
    doc = _normalized()
    assert "agent_id" in doc
    assert "is required" in doc
    assert "subagent's transcript" in doc
