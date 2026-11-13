"""Eval arms: which name the index tool has and whether the agent gets the memory prompt."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from wenchang.tools import TOOL_NAMES

__all__ = [
    "ARM_PATH",
    "DEFAULT_INDEX_TOOL",
    "HARNESS_TOOL_NAMES",
    "Arm",
    "ArmError",
    "load_arm",
    "rename_index_tool",
    "save_arm",
]

DEFAULT_INDEX_TOOL: Final = "get_memory_index"
ARM_PATH: Path = Path(__file__).resolve().parent / "arm.json"
# Defined here because evals.server is heavy to import.
HARNESS_TOOL_NAMES: Final[tuple[str, ...]] = ("eval_reset", "eval_record_turn", "eval_dump")
_NAME_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")
_RESERVED: Final = frozenset(n for n in TOOL_NAMES if n != DEFAULT_INDEX_TOOL) | frozenset(
    HARNESS_TOOL_NAMES
)
_KEYS: Final = frozenset({"index_tool", "agent_prompt"})


class ArmError(ValueError):
    """An arm is invalid or its file is unreadable."""


@dataclass(frozen=True)
class Arm:
    index_tool: str = DEFAULT_INDEX_TOOL
    agent_prompt: bool = True

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.fullmatch(self.index_tool):
            raise ArmError(
                f"invalid index tool name {self.index_tool!r}: must match [a-z][a-z0-9_]{{0,63}}"
            )
        if self.index_tool in _RESERVED:
            raise ArmError(f"index tool name {self.index_tool!r} is already a tool name")

    @property
    def is_default(self) -> bool:
        return self == Arm()

    def to_json(self) -> dict[str, object]:
        return {"index_tool": self.index_tool, "agent_prompt": self.agent_prompt}

    @classmethod
    def from_json(cls, data: object) -> "Arm":
        if not isinstance(data, dict):
            raise ArmError("arm must be a JSON object")
        fields: dict[str, object] = {str(k): v for k, v in data.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        unknown = sorted(set(fields) - _KEYS)
        if unknown:
            raise ArmError(f"unknown arm key(s): {', '.join(unknown)}")
        index_tool = fields.get("index_tool", DEFAULT_INDEX_TOOL)
        agent_prompt = fields.get("agent_prompt", True)
        if not isinstance(index_tool, str):
            raise ArmError("index_tool must be a string")
        if not isinstance(agent_prompt, bool):
            raise ArmError("agent_prompt must be a boolean")
        return cls(index_tool=index_tool, agent_prompt=agent_prompt)


def load_arm(path: Path = ARM_PATH) -> Arm:
    """The arm at path; the default arm when the file is absent."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return Arm()
    try:
        data: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArmError(f"{path}: invalid JSON: {exc}") from exc
    try:
        return Arm.from_json(data)
    except ArmError as exc:
        raise ArmError(f"{path}: {exc}") from exc


def save_arm(arm: Arm, path: Path = ARM_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(arm.to_json(), indent=2) + "\n")


def rename_index_tool(text: str, arm: Arm) -> str:
    """Replace every canonical index tool name in text with the arm's."""
    return text.replace(DEFAULT_INDEX_TOOL, arm.index_tool)
