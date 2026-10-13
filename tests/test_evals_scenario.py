"""The eval scenario format and its loader (AIE-1170, US3)."""

import textwrap
from pathlib import Path

import pytest

from evals.reference_adopter import (
    ADMIN_IDENTITY,
    MEMBER_IDENTITY,
    REFERENCE_SEED_FILES,
    SeedFile,
)
from evals.scenario import (
    ASSERTION_KINDS,
    AliasPresent,
    ArgMatcher,
    FileAbsent,
    IndexReadFirst,
    LineAbsent,
    LinePresent,
    NoContentMatching,
    NoDuplicateFact,
    Scenario,
    ScenarioError,
    SeedLinesPreserved,
    ToolCalled,
    ToolNotCalled,
    load_scenario,
)

pytestmark = pytest.mark.unit

FULL = """\
id: full
title: Every field
category: forgetting
source: specs/AIE-1053-forgetting/spec.md
identity: admin
reference_seed: false
seed:
  - scope: user
    area: preferences
    name: editor
    content: |
      - [stated] Prefers tabs.
      - [stated] Uses a dark theme.
    description: Editor preferences
    aliases: [editor, ide]
sessions:
  - turns:
      - "Forget that I prefer tabs."
      - "Yes, just that one."
  - turns:
      - "What do you remember about my editor?"
assertions:
  - kind: index_read_first
    session: 2
  - kind: file_absent
    id: gone
    scope: user
    area: workflows
    name: atlas
  - kind: line_present
    pattern: "(?i)dark"
    scope: user
  - kind: line_absent
    pattern: "(?i)tabs"
    scope: user
    area: preferences
    name: editor
  - kind: no_content_matching
    pattern: "1234"
  - kind: no_duplicate_fact
    pattern: "theme"
  - kind: seed_lines_preserved
    scope: user
    area: preferences
    name: editor
    except: "(?i)tabs"
  - kind: tool_called
    tool: [replace_fact]
    args:
      name: editor
      new_string: ""
      old_string: {matches: "tabs"}
      aliases: {contains: ide}
    session: 1
    turn: 2
    succeeded: true
    min: 1
    max: 2
  - kind: tool_not_called
    tool: delete_file
  - kind: alias_present
    scope: user
    area: preferences
    name: editor
    alias: IDE
judge:
  - id: confirms
    rubric: The reply confirms the fact was removed.
"""


def _write(tmp_path: Path, text: str, stem: str | None = None) -> Path:
    body = textwrap.dedent(text)
    if stem is None:
        stem = next(
            line.split(":", 1)[1].strip() for line in body.splitlines() if line.startswith("id:")
        )
    path = tmp_path / f"{stem}.yaml"
    path.write_text(body)
    return path


def _minimal(**overrides: str) -> str:
    parts = {
        "id": "id: mini\n",
        "title": "title: Minimal\n",
        "category": "category: privacy\n",
        "source": "source: AIE-1170\n",
        "identity": "",
        "seed": "",
        "sessions": "sessions:\n  - turns:\n      - Hello\n",
        "assertions": "assertions:\n  - kind: index_read_first\n",
        "extra": "",
    }
    parts.update(overrides)
    return "".join(parts.values())


def test_full_scenario_parses_every_field(tmp_path: Path) -> None:
    """A scenario using every field loads with every field populated (AIE-1170, US3.1)."""
    path = _write(tmp_path, FULL)

    s = load_scenario(path)

    assert isinstance(s, Scenario)
    assert (s.id, s.title, s.category, s.source) == (
        "full",
        "Every field",
        "forgetting",
        "specs/AIE-1053-forgetting/spec.md",
    )
    assert s.identity_name == "admin"
    assert s.identity == ADMIN_IDENTITY
    assert s.path == path
    assert s.seed_files == (
        SeedFile(
            "user",
            "preferences",
            "editor",
            "- [stated] Prefers tabs.\n- [stated] Uses a dark theme.\n",
            "Editor preferences",
            ("editor", "ide"),
        ),
    )
    assert [session.turns for session in s.sessions] == [
        ("Forget that I prefer tabs.", "Yes, just that one."),
        ("What do you remember about my editor?",),
    ]
    assert [a.id for a in s.assertions] == [
        "index_read_first-1",
        "gone",
        "line_present-3",
        "line_absent-4",
        "no_content_matching-5",
        "no_duplicate_fact-6",
        "seed_lines_preserved-7",
        "tool_called-8",
        "tool_not_called-9",
        "alias_present-10",
    ]
    first, gone, present, absent, nocontent, nodup, preserved, called, notcalled, alias = (
        s.assertions
    )
    assert isinstance(first, IndexReadFirst)
    assert first.session == 2
    assert isinstance(gone, FileAbsent)
    assert (gone.file.scope, gone.file.area, gone.file.name) == ("user", "workflows", "atlas")
    assert isinstance(present, LinePresent)
    assert present.pattern == "(?i)dark"
    assert (present.where.scope, present.where.area, present.where.name) == ("user", None, None)
    assert isinstance(absent, LineAbsent)
    assert (absent.where.scope, absent.where.area, absent.where.name) == (
        "user",
        "preferences",
        "editor",
    )
    assert isinstance(nocontent, NoContentMatching)
    assert nocontent.pattern == "1234"
    assert isinstance(nodup, NoDuplicateFact)
    assert nodup.where.scope is None
    assert isinstance(preserved, SeedLinesPreserved)
    assert preserved.except_pattern == "(?i)tabs"
    assert isinstance(called, ToolCalled)
    assert called.call.tools == frozenset({"replace_fact"})
    assert called.call.args["name"] == ArgMatcher(equals="editor")
    assert called.call.args["new_string"] == ArgMatcher(equals="")
    assert called.call.args["old_string"] == ArgMatcher(matches="tabs")
    assert called.call.args["aliases"] == ArgMatcher(contains="ide")
    assert (called.call.session, called.call.turn, called.call.succeeded) == (1, 2, True)
    assert (called.min, called.max) == (1, 2)
    assert isinstance(notcalled, ToolNotCalled)
    assert notcalled.call.tools == frozenset({"delete_file"})
    assert notcalled.call.args == {}
    assert (notcalled.call.session, notcalled.call.turn, notcalled.call.succeeded) == (
        None,
        None,
        None,
    )
    assert isinstance(alias, AliasPresent)
    assert alias.alias == "IDE"
    assert [(j.id, j.rubric) for j in s.judge] == [
        ("confirms", "The reply confirms the fact was removed.")
    ]


def test_defaults_apply(tmp_path: Path) -> None:
    """Omitted optional fields take their defaults (AIE-1170, US3.1)."""
    text = _minimal(
        assertions="assertions:\n  - kind: tool_called\n    tool: get_memory_index\n",
    )
    s = load_scenario(_write(tmp_path, text))

    assert s.identity_name == "member"
    assert s.identity == MEMBER_IDENTITY
    assert s.seed_files == ()
    assert s.judge == ()
    (called,) = s.assertions
    assert isinstance(called, ToolCalled)
    assert called.id == "tool_called-1"
    assert (called.min, called.max) == (1, None)


def test_reference_seed_comes_first(tmp_path: Path) -> None:
    """reference_seed puts REFERENCE_SEED_FILES before the scenario's seeds (AIE-1170, US3.2)."""
    text = _minimal(
        seed=(
            "reference_seed: true\n"
            "seed:\n"
            '  - {scope: user, area: notes, name: extra, content: "- [stated] x\\n",'
            " description: Extra, aliases: []}\n"
        )
    )
    s = load_scenario(_write(tmp_path, text))

    assert s.seed_files[: len(REFERENCE_SEED_FILES)] == REFERENCE_SEED_FILES
    assert s.seed_files[-1] == SeedFile("user", "notes", "extra", "- [stated] x\n", "Extra", ())


def test_seed_colliding_with_reference_seed_is_rejected(tmp_path: Path) -> None:
    """A scenario seed at a reference seed path is rejected (AIE-1170, US3.2)."""
    text = _minimal(
        seed=(
            "reference_seed: true\n"
            "seed:\n"
            '  - {scope: user, area: preferences, name: charts, content: "- [stated] x\\n",'
            " description: Clash, aliases: []}\n"
        )
    )
    with pytest.raises(ScenarioError, match="charts"):
        load_scenario(_write(tmp_path, text))


_SEED = (
    'seed:\n  - {scope: user, area: notes, name: a, content: "x\\n", description: A, aliases: []}\n'
)

MALFORMED: list[tuple[str, str, str]] = [
    ("unknown-top-level-key", _minimal(extra="colour: blue\n"), "colour"),
    (
        "unknown-kind",
        _minimal(assertions="assertions:\n  - kind: file_exists\n"),
        "file_exists",
    ),
    (
        "unknown-field",
        _minimal(assertions="assertions:\n  - kind: index_read_first\n    turn: 1\n"),
        "turn",
    ),
    (
        "missing-required-field",
        _minimal(assertions="assertions:\n  - kind: no_content_matching\n"),
        "pattern",
    ),
    (
        "bad-regex",
        _minimal(assertions='assertions:\n  - kind: no_content_matching\n    pattern: "("\n'),
        "pattern",
    ),
    (
        "unknown-scope",
        _minimal(
            assertions=(
                "assertions:\n  - kind: file_absent\n    scope: team\n    area: a\n    name: b\n"
            )
        ),
        "team",
    ),
    (
        "bad-segment",
        _minimal(
            assertions=(
                "assertions:\n  - kind: file_absent\n    scope: user\n    area: a/b\n    name: c\n"
            )
        ),
        "a/b",
    ),
    ("no-sessions", _minimal(sessions="sessions: []\n"), "sessions"),
    ("empty-turns", _minimal(sessions="sessions:\n  - turns: []\n"), "turns"),
    (
        "duplicate-assertion-ids",
        _minimal(
            assertions=(
                "assertions:\n  - kind: index_read_first\n    id: same\n"
                "  - kind: no_content_matching\n    id: same\n    pattern: x\n"
            )
        ),
        "same",
    ),
    (
        "duplicate-seed-paths",
        _minimal(
            seed=_SEED + '  - {scope: user, area: notes, name: a, content: "y\\n",'
            " description: A, aliases: []}\n"
        ),
        "notes",
    ),
    (
        "session-out-of-range",
        _minimal(assertions="assertions:\n  - kind: index_read_first\n    session: 2\n"),
        "session",
    ),
    (
        "turn-out-of-range",
        _minimal(
            assertions=(
                "assertions:\n  - kind: tool_not_called\n    tool: write_file\n"
                "    session: 1\n    turn: 2\n"
            )
        ),
        "turn",
    ),
    ("unknown-identity", _minimal(identity="identity: owner\n"), "owner"),
    ("id-not-stem", _minimal(id="id: other\n"), "other"),
    (
        "min-greater-than-max",
        _minimal(
            assertions=(
                "assertions:\n  - kind: tool_called\n    tool: write_file\n    min: 2\n    max: 1\n"
            )
        ),
        "min",
    ),
]


@pytest.mark.parametrize(("case", "text", "needle"), MALFORMED, ids=[m[0] for m in MALFORMED])
def test_malformed_scenarios_are_rejected(
    tmp_path: Path, case: str, text: str, needle: str
) -> None:
    """Each malformed scenario raises ScenarioError naming the file and the
    offending key or value (AIE-1170, US3.3).
    """
    path = _write(tmp_path, text, stem="mini")

    with pytest.raises(ScenarioError) as info:
        load_scenario(path)

    assert str(path) in str(info.value)
    assert needle in str(info.value), case


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    """YAML whose top level is not a mapping is rejected (AIE-1170, US3.3)."""
    path = tmp_path / "mini.yaml"
    path.write_text("- just\n- a list\n")

    with pytest.raises(ScenarioError, match="mapping"):
        load_scenario(path)


def test_unknown_tool_name_is_rejected(tmp_path: Path) -> None:
    """A call matcher naming a tool outside TOOL_NAMES is rejected (AIE-1170, US3.3)."""
    text = _minimal(assertions="assertions:\n  - kind: tool_not_called\n    tool: eval_dump\n")

    with pytest.raises(ScenarioError, match="eval_dump"):
        load_scenario(_write(tmp_path, text))


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    """A missing scenario file raises ScenarioError naming it (AIE-1170, US3.3)."""
    path = tmp_path / "absent.yaml"

    with pytest.raises(ScenarioError, match=r"absent\.yaml"):
        load_scenario(path)


def test_assertion_kinds_are_the_closed_set() -> None:
    """ASSERTION_KINDS is exactly the ten kinds US4 defines (AIE-1170, US3.4)."""
    assert set(ASSERTION_KINDS) == {
        "index_read_first",
        "file_absent",
        "line_present",
        "line_absent",
        "no_content_matching",
        "no_duplicate_fact",
        "seed_lines_preserved",
        "tool_called",
        "tool_not_called",
        "alias_present",
    }
