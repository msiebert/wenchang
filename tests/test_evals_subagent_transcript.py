"""Reading a subagent's full reply from its Claude Code transcript (AIE-1208)."""

import json
from pathlib import Path

import pytest

from evals.subagent_transcript import (
    SubagentTranscriptError,
    default_projects_root,
    find_subagent_transcript,
    read_subagent_reply,
    reply_from_transcript,
)

pytestmark = pytest.mark.unit

AGENT_ID = "a2d570cdfd6af0fa2"
EXPECTED = "I'll check my memory first.\n\nI found nothing.\n\nPROBE-END"


def _text(uuid: str, text: str) -> dict[str, object]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "isSidechain": True,
        "message": {
            "role": "assistant",
            "id": f"msg_{uuid}",
            "content": [{"type": "text", "text": text}],
        },
    }


LINES: list[dict[str, object]] = [
    _text("u1", "I'll check my memory first."),
    {
        "type": "assistant",
        "uuid": "u2",
        "isSidechain": True,
        "message": {
            "role": "assistant",
            "id": "msg_2",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "mcp__wenchang__get_memory_index",
                    "input": {},
                }
            ],
        },
    },
    {
        "type": "user",
        "uuid": "u3",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": ""}],
        },
    },
    {"type": "attachment", "uuid": "att1", "attachment": {"type": "note"}},
    {
        "type": "api-request-blob",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "SHOULD NOT APPEAR"}],
        },
    },
    _text("u4", "I found nothing.\n\nPROBE-END"),
]


def _write(path: Path, entries: list[dict[str, object]], extra: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n" + extra)
    return path


def _fixture(root: Path, session: str = "sess-1", agent_id: str = AGENT_ID) -> Path:
    return _write(root / "-some-cwd" / session / "subagents" / f"agent-{agent_id}.jsonl", LINES)


def test_reply_is_the_assistant_text_in_order(tmp_path: Path) -> None:
    """Only assistant text blocks count, stripped and joined by blank lines;
    other entry types and tool blocks are ignored (AIE-1208, AC11).
    """
    path = _fixture(tmp_path / "projects")
    assert reply_from_transcript(path) == EXPECTED


def test_reply_skips_blank_lines_and_plain_string_content(tmp_path: Path) -> None:
    """Blank lines are skipped and string content on a non-assistant entry is
    ignored (AIE-1208, AC11).
    """
    entries: list[dict[str, object]] = [
        {"type": "user", "uuid": "x", "message": {"role": "user", "content": "plain"}},
        *LINES,
    ]
    path = _write(tmp_path / "t.jsonl", entries, extra="\n   \n")
    assert reply_from_transcript(path) == EXPECTED


def test_reply_dedupes_entries_by_uuid_first_wins(tmp_path: Path) -> None:
    """A repeated uuid contributes once, using its first occurrence
    (AIE-1208, AC11).
    """
    entries = [LINES[0], _text("u1", "DUPLICATE"), *LINES[1:]]
    path = _write(tmp_path / "t.jsonl", entries)
    assert reply_from_transcript(path) == EXPECTED


def test_reply_drops_empty_text_blocks(tmp_path: Path) -> None:
    """Whitespace-only text is dropped before joining (AIE-1208, AC11)."""
    path = _write(
        tmp_path / "t.jsonl", [_text("a", "  one  "), _text("b", "  \n"), _text("c", "two")]
    )
    assert reply_from_transcript(path) == "one\n\ntwo"


def test_malformed_line_is_an_error(tmp_path: Path) -> None:
    """A line that is not JSON raises SubagentTranscriptError (AIE-1208)."""
    path = _write(tmp_path / "t.jsonl", LINES, extra="{not json\n")
    with pytest.raises(SubagentTranscriptError):
        reply_from_transcript(path)


def test_no_text_is_an_error(tmp_path: Path) -> None:
    """A transcript without any assistant text raises (AIE-1208)."""
    path = _write(tmp_path / "t.jsonl", [LINES[1], LINES[2]])
    with pytest.raises(SubagentTranscriptError):
        reply_from_transcript(path)


def test_find_returns_the_single_match(tmp_path: Path) -> None:
    """Exactly one projects/*/*/subagents/agent-<id>.jsonl is returned
    (AIE-1208, AC12).
    """
    root = tmp_path / "projects"
    expected = _fixture(root)
    _fixture(root, agent_id="other")
    assert find_subagent_transcript(root, AGENT_ID) == expected


def test_find_with_no_match_names_the_id(tmp_path: Path) -> None:
    """No match raises with the agent id in the message (AIE-1208, AC12)."""
    root = tmp_path / "projects"
    root.mkdir()
    with pytest.raises(SubagentTranscriptError, match=AGENT_ID):
        find_subagent_transcript(root, AGENT_ID)


def test_find_with_two_matches_names_the_id(tmp_path: Path) -> None:
    """The id in two sessions is ambiguous and raises (AIE-1208, AC12)."""
    root = tmp_path / "projects"
    _fixture(root, session="sess-1")
    _fixture(root, session="sess-2")
    with pytest.raises(SubagentTranscriptError, match=AGENT_ID):
        find_subagent_transcript(root, AGENT_ID)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "a b", "a.b"])
def test_find_rejects_unsafe_ids(tmp_path: Path, bad: str) -> None:
    """Ids outside [A-Za-z0-9_-]+ raise (AIE-1208, AC12)."""
    root = tmp_path / "projects"
    _fixture(root)
    with pytest.raises(SubagentTranscriptError):
        find_subagent_transcript(root, bad)


def test_read_subagent_reply_finds_then_reconstructs(tmp_path: Path) -> None:
    """read_subagent_reply composes the lookup and the reconstruction
    (AIE-1208, AC11, AC12).
    """
    root = tmp_path / "projects"
    _fixture(root)
    assert read_subagent_reply(root, AGENT_ID) == EXPECTED


def test_default_root_uses_claude_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE_CONFIG_DIR, when set, locates the projects directory
    (AIE-1208, AC13).
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert default_projects_root() == tmp_path / "cfg" / "projects"


@pytest.mark.parametrize("value", [None, ""])
def test_default_root_falls_back_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    """Unset or empty CLAUDE_CONFIG_DIR falls back to ~/.claude/projects
    (AIE-1208, AC13).
    """
    if value is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", value)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_projects_root() == tmp_path / ".claude" / "projects"


def test_reply_ignores_thinking_blocks(tmp_path: Path) -> None:
    """Only text blocks count; thinking blocks are ignored (AIE-1208, D6 refinement 1)."""
    entry: dict[str, object] = {
        "type": "assistant",
        "uuid": "t1",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "SECRET"},
                {"type": "text", "text": "visible"},
            ],
        },
    }
    assert reply_from_transcript(_write(tmp_path / "t.jsonl", [entry])) == "visible"


def _error_entry(uuid: str, **extra: object) -> dict[str, object]:
    entry = _text(uuid, "API Error: overloaded")
    entry.update(extra)
    return entry


def test_reply_skips_api_error_and_synthetic_entries(tmp_path: Path) -> None:
    """Assistant entries flagged isApiErrorMessage or with model <synthetic>
    are skipped (AIE-1208, D6 refinement 1).
    """
    synthetic = _text("s1", "No response requested.")
    message = synthetic["message"]
    assert isinstance(message, dict)
    message["model"] = "<synthetic>"
    entries = [_error_entry("e1", isApiErrorMessage=True), synthetic, *LINES]
    assert reply_from_transcript(_write(tmp_path / "t.jsonl", entries)) == EXPECTED


def test_reply_with_only_error_entries_is_an_error(tmp_path: Path) -> None:
    """If only skipped entries carry text, there is no reply and it raises
    (AIE-1208, D6 refinement 1).
    """
    path = _write(tmp_path / "t.jsonl", [_error_entry("e1", isApiErrorMessage=True)])
    with pytest.raises(SubagentTranscriptError):
        reply_from_transcript(path)


def test_not_found_error_names_the_root_and_the_flag(tmp_path: Path) -> None:
    """The error shows the searched root and the --transcripts-root flag
    (AIE-1208, D6 refinement 4).
    """
    root = tmp_path / "projects"
    root.mkdir()
    with pytest.raises(SubagentTranscriptError) as info:
        find_subagent_transcript(root, AGENT_ID)
    assert str(root) in str(info.value)
    assert "--transcripts-root" in str(info.value)


def test_non_utf8_file_is_an_error(tmp_path: Path) -> None:
    """A file that is not UTF-8 raises SubagentTranscriptError, not
    UnicodeDecodeError (AIE-1208, review follow-up 3).
    """
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SubagentTranscriptError):
        reply_from_transcript(path)


def test_non_string_uuid_counts_as_no_uuid(tmp_path: Path) -> None:
    """A non-str uuid does not raise and the entry's text still counts
    (AIE-1208, review follow-up 4).
    """
    entry = _text("x", "kept")
    entry["uuid"] = ["not", "a", "string"]
    other = _text("y", "also kept")
    other["uuid"] = ["not", "a", "string"]
    path = _write(tmp_path / "t.jsonl", [entry, other])
    assert reply_from_transcript(path) == "kept\n\nalso kept"


def test_non_dict_lines_and_non_string_text_are_skipped(tmp_path: Path) -> None:
    """JSON lines that are not objects, and text blocks whose text is not a
    string, are skipped (AIE-1208, review follow-up 4).
    """
    bad_text: dict[str, object] = {
        "type": "assistant",
        "uuid": "b",
        "message": {"role": "assistant", "content": [{"type": "text", "text": 5}]},
    }
    path = _write(tmp_path / "t.jsonl", LINES, extra='[1,2]\n"x"\n' + json.dumps(bad_text) + "\n")
    assert reply_from_transcript(path) == EXPECTED
