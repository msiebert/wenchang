"""Reconstruct a subagent's full reply from its Claude Code transcript.

Claude Code writes each subagent's conversation to
<projects>/<project>/<session>/subagents/agent-<agent_id>.jsonl.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, TypeGuard, cast

__all__ = [
    "PermanentTranscriptError",
    "SubagentTranscriptError",
    "default_projects_root",
    "find_subagent_transcript",
    "read_subagent_reply",
    "reply_from_transcript",
    "text_blocks_from_transcript",
]

_AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")


def _is_dict(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


class SubagentTranscriptError(Exception):
    """A subagent transcript could not be found or read."""


class PermanentTranscriptError(SubagentTranscriptError):
    """A failure that waiting cannot fix: an invalid or ambiguous agent_id."""


def default_projects_root() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "projects"
    return Path.home() / ".claude" / "projects"


def find_subagent_transcript(projects_root: Path, agent_id: str) -> Path:
    """The one transcript file for agent_id under projects_root."""
    if _AGENT_ID.fullmatch(agent_id) is None:
        raise PermanentTranscriptError(
            f"agent_id {agent_id!r} must match [A-Za-z0-9_-]+ (the token after agentId:)"
        )
    matches = sorted(projects_root.glob(f"*/*/subagents/agent-{agent_id}.jsonl"))
    if len(matches) != 1:
        error = PermanentTranscriptError if matches else SubagentTranscriptError
        raise error(
            f"expected one transcript for agent_id {agent_id} under {projects_root}, "
            f"found {len(matches)}; point --transcripts-root at the right projects directory"
        )
    return matches[0]


def text_blocks_from_transcript(path: Path) -> list[str]:
    """The subagent's assistant text blocks in file order, stripped and non-empty."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SubagentTranscriptError(f"cannot read {path}: {exc}") from exc
    seen: set[object] = set()
    blocks: list[str] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SubagentTranscriptError(f"{path}:{number}: not valid JSON: {exc}") from exc
        if not _is_dict(entry) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not _is_dict(message):
            continue
        if entry.get("isApiErrorMessage") or message.get("model") == "<synthetic>":
            continue
        uuid = entry.get("uuid")
        if isinstance(uuid, str):
            if uuid in seen:
                continue
            seen.add(uuid)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in cast(list[object], content):
            if _is_dict(block) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    blocks.append(text.strip())
    if not blocks:
        raise SubagentTranscriptError(f"{path} has no assistant text")
    return blocks


def reply_from_transcript(path: Path) -> str:
    """The text blocks joined by blank lines."""
    return "\n\n".join(text_blocks_from_transcript(path))


def read_subagent_reply(projects_root: Path, agent_id: str) -> str:
    return reply_from_transcript(find_subagent_transcript(projects_root, agent_id))
