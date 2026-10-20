"""The transcript's optional agent_result field (AIE-1208, AC16)."""

import json
from pathlib import Path

import pytest

from evals.graders import (
    GradeInputError,
    TranscriptTurn,
    load_transcript,
    transcript_to_json,
)

pytestmark = pytest.mark.unit


def _load(tmp_path: Path, body: object) -> tuple[TranscriptTurn, ...]:
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps(body))
    return load_transcript(path)


def test_agent_result_defaults_to_none() -> None:
    """agent_result is the last field and defaults to None (AIE-1208, AC16)."""
    assert TranscriptTurn(1, 1, "u", "r", None).agent_result is None
    assert TranscriptTurn(1, 1, "u", "r", "a", "result").agent_result == "result"


def test_agent_result_round_trips_when_present(tmp_path: Path) -> None:
    """A set agent_result is written and loaded back (AIE-1208, AC16)."""
    turns = (TranscriptTurn(1, 1, "hi", "full reply", "a-1", "handback text"),)
    payload = transcript_to_json(turns)
    assert "agent_result" in json.dumps(payload)
    assert _load(tmp_path, payload) == turns


def test_agent_result_is_omitted_when_none(tmp_path: Path) -> None:
    """A None agent_result writes no key and loads as None (AIE-1208, AC16)."""
    turns = (TranscriptTurn(1, 1, "hi", "reply", "a-1"),)
    payload = transcript_to_json(turns)
    assert "agent_result" not in json.dumps(payload)
    assert _load(tmp_path, payload) == turns


def test_existing_json_without_the_key_still_loads(tmp_path: Path) -> None:
    """Older transcripts load with agent_result None (AIE-1208, AC16)."""
    body = {"turns": [{"session": 1, "turn": 1, "user": "u", "reply": "r", "agent_id": None}]}
    (turn,) = _load(tmp_path, body)
    assert turn.agent_result is None


def test_agent_result_null_loads_as_none(tmp_path: Path) -> None:
    """An explicit null agent_result is accepted (AIE-1208, AC16)."""
    body = {
        "turns": [
            {
                "session": 1,
                "turn": 1,
                "user": "u",
                "reply": "r",
                "agent_id": None,
                "agent_result": None,
            }
        ]
    }
    (turn,) = _load(tmp_path, body)
    assert turn.agent_result is None


def test_agent_result_of_another_type_is_rejected(tmp_path: Path) -> None:
    """A non-string agent_result raises GradeInputError naming the field
    (AIE-1208, AC16).
    """
    body = {
        "turns": [
            {
                "session": 1,
                "turn": 1,
                "user": "u",
                "reply": "r",
                "agent_id": None,
                "agent_result": 5,
            }
        ]
    }
    with pytest.raises(GradeInputError, match="agent_result"):
        _load(tmp_path, body)
