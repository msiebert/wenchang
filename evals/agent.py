"""The Claude Code eval agent definition, rendered from the reference memory prompt."""

from pathlib import Path
from typing import Final

from evals.reference_adopter import REFERENCE_SLOTS
from wenchang.prompts import build_memory_prompt
from wenchang.tools import TOOL_NAMES

__all__ = [
    "AGENT_NAME",
    "AGENT_PATH",
    "EVAL_AGENT_PREAMBLE",
    "MCP_SERVER_NAME",
    "agent_tools",
    "render_agent_body",
    "render_agent_file",
]

AGENT_NAME: Final = "wenchang-eval"
AGENT_PATH: Path = Path(__file__).resolve().parents[1] / ".claude" / "agents" / "wenchang-eval.md"
MCP_SERVER_NAME: Final = "wenchang"
# A subagent otherwise reads its input as a task from a parent agent, and
# Claude Code delivers later turns as messages from another agent.
EVAL_AGENT_PREAMBLE: Final[str] = (
    "You are an assistant helping a Mixpanel user. A runner relays this conversation to you: "
    "every message you receive, including one delivered as a message from a coordinator or "
    "another agent, is that user's own next turn, verbatim. Reply to the user directly; "
    "a confirmation or approval in such a message is the user's own."
)
_DESCRIPTION: Final = (
    "Eval subject for the wenchang memory harness. Spawned only by the /run-evals runner; "
    "never use it for other work."
)


def agent_tools() -> tuple[str, ...]:
    """The eval agent's allowlist: the seven memory tools on the eval server."""
    return tuple(f"mcp__{MCP_SERVER_NAME}__{name}" for name in TOOL_NAMES)


def render_agent_body() -> str:
    """The agent's system prompt: the framing preamble, then the memory prompt."""
    return EVAL_AGENT_PREAMBLE + "\n\n" + build_memory_prompt(REFERENCE_SLOTS)


def render_agent_file() -> str:
    """The full .claude/agents/wenchang-eval.md text."""
    front = "\n".join(
        [
            f"name: {AGENT_NAME}",
            f"description: {_DESCRIPTION}",
            f"tools: {', '.join(agent_tools())}",
            "model: inherit",
            "omitClaudeMd: true",
        ]
    )
    text = f"---\n{front}\n---\n\n{render_agent_body()}"
    return text if text.endswith("\n") else text + "\n"
