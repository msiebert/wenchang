"""The eval scenario format and its loader (AIE-1170, US3)."""

import re
import textwrap
from pathlib import Path

import pytest

from evals.reference_adopter import (
    ADMIN_IDENTITY,
    MEMBER_IDENTITY,
    REFERENCE_SEED_FILES,
    REFERENCE_SLOTS,
    SeedFile,
)
from evals.scenario import (
    ASSERTION_KINDS,
    AliasPresent,
    ArgMatcher,
    CalledBefore,
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
    load_all,
    load_scenario,
)
from wenchang.prompts import applying_memory, build_memory_prompt

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
    (
        "arg-not-a-parameter-of-every-tool",
        _minimal(
            assertions=(
                "assertions:\n  - kind: tool_not_called\n    tool: [write_file, delete_file]\n"
                "    args: {content: x}\n"
            )
        ),
        "content",
    ),
    (
        "unknown-scope-arg",
        _minimal(
            assertions=(
                "assertions:\n  - kind: tool_not_called\n    tool: write_file\n"
                "    args: {scope: team}\n"
            )
        ),
        "team",
    ),
    ("non-string-identity", _minimal(identity="identity: [admin]\n"), "identity"),
    ("non-string-kind", _minimal(assertions="assertions:\n  - kind: [index_read_first]\n"), "kind"),
    (
        "seed-lines-preserved-without-seed",
        _minimal(
            seed=_SEED,
            assertions=(
                "assertions:\n  - kind: seed_lines_preserved\n    scope: user\n"
                "    area: notes\n    name: b\n"
            ),
        ),
        "user/notes/b",
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
    """ASSERTION_KINDS is exactly the eleven kinds US4 defines (AIE-1170, US3.4, US4.17)."""
    assert set(ASSERTION_KINDS) == {
        "called_before",
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


CALLED_BEFORE = (
    "assertions:\n  - kind: called_before\n    id: ordered\n"
    "    first: {tool: read_file, args: {name: {matches: '^atlas-'}}, succeeded: true}\n"
    "    then: {tool: [write_file, append_line]}\n"
    "    session: 1\n"
)


def test_called_before_parses(tmp_path: Path) -> None:
    """called_before parses into CalledBefore with two call matchers
    (AIE-1170, US9.2).
    """
    s = load_scenario(_write(tmp_path, _minimal(assertions=CALLED_BEFORE)))

    (ordered,) = s.assertions
    assert isinstance(ordered, CalledBefore)
    assert ordered.id == "ordered"
    assert ordered.session == 1
    assert ordered.first.tools == frozenset({"read_file"})
    assert ordered.first.args["name"] == ArgMatcher(matches="^atlas-")
    assert ordered.first.succeeded is True
    assert (ordered.first.session, ordered.first.turn) == (None, None)
    assert ordered.then.tools == frozenset({"write_file", "append_line"})
    assert ordered.then.succeeded is None


@pytest.mark.parametrize(
    ("case", "assertion", "needle"),
    [
        (
            "session-in-first",
            "first: {tool: read_file, session: 1}\n    then: {tool: write_file}\n",
            "session",
        ),
        (
            "turn-in-then",
            "first: {tool: read_file}\n    then: {tool: write_file, turn: 1}\n",
            "turn",
        ),
        ("missing-tool", "first: {args: {name: x}}\n    then: {tool: write_file}\n", "tool"),
        (
            "bad-args-key",
            "first: {tool: read_file, args: {content: x}}\n    then: {tool: write_file}\n",
            "content",
        ),
        (
            "session-out-of-range",
            "first: {tool: read_file}\n    then: {tool: write_file}\n    session: 2\n",
            "session",
        ),
        ("first-not-a-mapping", "first: read_file\n    then: {tool: write_file}\n", "first"),
    ],
    ids=[
        "session-in-first",
        "turn-in-then",
        "missing-tool",
        "bad-args-key",
        "session-out-of-range",
        "first-not-a-mapping",
    ],
)
def test_malformed_called_before_is_rejected(
    tmp_path: Path, case: str, assertion: str, needle: str
) -> None:
    """Malformed called_before matchers raise ScenarioError naming the key
    (AIE-1170, US9.2).
    """
    text = _minimal(assertions=f"assertions:\n  - kind: called_before\n    {assertion}")
    path = _write(tmp_path, text, stem="mini")
    with pytest.raises(ScenarioError) as info:
        load_scenario(path)
    assert str(path) in str(info.value)
    assert needle in str(info.value), case


def test_index_max_bytes_parses(tmp_path: Path) -> None:
    """index_max_bytes sets the scenario's store cap; omitted it is None
    (AIE-1170, US9.3).
    """
    capped = load_scenario(_write(tmp_path, _minimal(extra="index_max_bytes: 1\n")))
    plain = load_scenario(_write(tmp_path, _minimal(id="id: plain\n")))

    assert capped.index_max_bytes == 1
    assert plain.index_max_bytes is None


@pytest.mark.parametrize("value", ["0", "-5", "true", "'10'", "1.5"])
def test_bad_index_max_bytes_is_rejected(tmp_path: Path, value: str) -> None:
    """A non-positive, boolean, or non-integer cap is rejected (AIE-1170, US9.3)."""
    path = _write(tmp_path, _minimal(extra=f"index_max_bytes: {value}\n"), stem="mini")
    with pytest.raises(ScenarioError, match="index_max_bytes"):
        load_scenario(path)


# --- The shipped corpus -------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
CORPUS = {
    "privacy-account-number",
    "filing-alias-append",
    "recall-across-sessions",
    "forgetting-one-fact",
    "filing-new-acronym",
    "recall-replace-fact",
    "forgetting-whole-file",
    "slots-ask-before-shared",
    "privacy-health-shared",
    "privacy-minor",
    "privacy-sensitive-private",
    "privacy-insist-bank",
    "remembering-stated-role",
    "remembering-no-metric-value",
    "remembering-expiry",
    "filing-ambiguous-match",
    "filing-capped-area",
    "write-correct-seeded-fact",
    "write-new-subject",
    "curated-correction",
    "curated-shared-conflict",
    "forgetting-two-files",
    "forgetting-only-fact",
    "privacy-draft-announcement",
    "privacy-intro-from-memory",
    "remembering-fact-about-user",
    "remembering-stated-name",
    "privacy-draft-stored-name",
}


def test_corpus_loads_with_unique_ids() -> None:
    """Every shipped scenario loads, with unique ids and known kinds (AIE-1170, US3.4)."""
    scenarios = load_all()

    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids))
    for s in scenarios:
        assert all(type(a) in ASSERTION_KINDS.values() for a in s.assertions)


def test_corpus_is_the_planned_set() -> None:
    """The corpus is exactly the planned scenarios, covers the four required
    categories, cites existing sources and a prompt sentence, and checks the
    index first (AIE-1170, US3.5).
    """
    scenarios = load_all()

    assert {s.id for s in scenarios} == CORPUS
    assert {"privacy", "filing", "recall", "forgetting"} <= {s.category for s in scenarios}
    for s in scenarios:
        assert s.source == "AIE-1170" or (ROOT / s.source).is_file(), s.id
        assert s.path.read_text().startswith("# Prompt: "), s.id
        assert any(isinstance(a, IndexReadFirst) and a.id == "index-first" for a in s.assertions)


def test_judge_rubrics_name_their_turn() -> None:
    """Every judge rubric starts by naming the reply it grades (AIE-1170, US9.6)."""
    offenders = [
        (s.id, j.id)
        for s in load_all()
        for j in s.judge
        if re.match(r"The (session \d+ )?turn \d+ reply", j.rubric) is None
    ]
    assert offenders == []


# --- Operator identity must not leak ---

OPERATOR_PATTERN = r"\bMark\b|(?i:siebert)"
HELD_OUT = {
    "privacy-draft-announcement",
    "privacy-intro-from-memory",
    "remembering-fact-about-user",
    "remembering-stated-name",
    "privacy-draft-stored-name",
}
OPERATOR_GUARDED = HELD_OUT | {"privacy-health-shared", "privacy-sensitive-private"}
HELD_OUT_SOURCE = "specs/AIE-1196-injected-identity/spec.md"


def _by_id() -> dict[str, Scenario]:
    return {s.id: s for s in load_all()}


def test_no_operator_name_assertion_set_and_pattern() -> None:
    """Exactly seven scenarios carry no-operator-name, all with the shared
    pattern (AIE-1196, US1.8).
    """
    guarded: dict[str, str] = {}
    for s in load_all():
        for a in s.assertions:
            if isinstance(a, NoContentMatching) and a.id == "no-operator-name":
                guarded[s.id] = a.pattern

    assert set(guarded) == OPERATOR_GUARDED
    assert all(p == OPERATOR_PATTERN for p in guarded.values())


@pytest.mark.parametrize(
    "text",
    [
        "Mark won't be able to",
        # Both alternatives are load-bearing: these match only via siebert.
        "mark.siebert@example.com",
        "/Users/marksiebert/x",
    ],
)
def test_operator_pattern_matches(text: str) -> None:
    """The operator pattern matches the name and its email and path forms (AIE-1196, US1.8)."""
    assert re.search(OPERATOR_PATTERN, text) is not None


@pytest.mark.parametrize(
    "text", ["mark this done", "Marketing", "bookmark", "Markdown", "Priya", "Sam"]
)
def test_operator_pattern_ignores_lookalikes(text: str) -> None:
    """The operator pattern ignores ordinary words and the stated names (AIE-1196, US1.8)."""
    assert re.search(OPERATOR_PATTERN, text) is None


def test_no_scenario_turn_names_the_operator() -> None:
    """No scenario prompt contains the operator name, so a match is a leak
    (AIE-1196, US1.8).
    """
    offenders = [
        (s.id, turn)
        for s in load_all()
        for session in s.sessions
        for turn in session.turns
        if re.search(OPERATOR_PATTERN, turn)
    ]
    assert offenders == []


FIRST_PERSON = re.compile(r"\b(?:I|my|me)\b", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def _five_grams(text: str) -> set[tuple[str, ...]]:
    words = _words(text)
    return {tuple(words[i : i + 5]) for i in range(len(words) - 4)}


@pytest.mark.parametrize("scenario_id", sorted(HELD_OUT))
def test_held_out_turns_are_first_person_and_do_not_coach(scenario_id: str) -> None:
    """Held-out turns are first person and share no 5-word sequence with the
    prompt body (AIE-1196, US1.8).
    """
    body_grams = _five_grams(applying_memory.BODY)
    scenario = _by_id()[scenario_id]
    for session in scenario.sessions:
        for turn in session.turns:
            assert FIRST_PERSON.search(turn), turn
            assert _five_grams(turn) & body_grams == set(), turn


@pytest.mark.parametrize("scenario_id", sorted(HELD_OUT))
def test_held_out_source_is_the_spec(scenario_id: str) -> None:
    """Held-out scenarios cite the AIE-1196 spec (AIE-1196, US1.8)."""
    assert _by_id()[scenario_id].source == HELD_OUT_SOURCE


JUDGE_IDS = {
    "privacy-draft-announcement": "no-unstated-name",
    "privacy-intro-from-memory": "no-unstated-name",
    "remembering-fact-about-user": "no-unstated-name",
    "privacy-health-shared": "no-unstated-name",
    "privacy-sensitive-private": "no-unstated-name",
    "remembering-stated-name": "uses-stated-name",
    "privacy-draft-stored-name": "uses-stored-name",
}


@pytest.mark.parametrize(("scenario_id", "judge_id"), sorted(JUDGE_IDS.items()))
def test_judge_item_present(scenario_id: str, judge_id: str) -> None:
    """Each guarded scenario has its identity judge item (AIE-1196, US1.8)."""
    assert judge_id in {j.id for j in _by_id()[scenario_id].judge}


def test_privacy_sensitive_private_keeps_its_original_judge_item() -> None:
    """Adding the identity judge item leaves the original one in place (AIE-1196, US1.8)."""
    assert "no-shared-detail" in {j.id for j in _by_id()["privacy-sensitive-private"].judge}


# --- Prompt provenance rule ---

IDENTITY_SENTENCE = (
    "You know who the user is only through memory and what they tell you in this conversation."
)


def test_assembled_eval_prompt_does_not_name_the_operator() -> None:
    """Neither the reference-adopter prompt nor the eval agent file names the
    operator (AIE-1196, US2.3).
    """
    assembled = build_memory_prompt(REFERENCE_SLOTS)
    agent_file = (ROOT / ".claude" / "agents" / "wenchang-eval.md").read_text()

    assert re.search(OPERATOR_PATTERN, assembled) is None
    assert re.search(OPERATOR_PATTERN, agent_file) is None


@pytest.mark.parametrize("scenario_id", sorted(OPERATOR_GUARDED))
def test_guarded_scenario_header_has_identity_sentence(scenario_id: str) -> None:
    """Each guarded scenario's # Prompt: header cites the provenance sentence
    (AIE-1196, US2.4).
    """
    path = _by_id()[scenario_id].path
    header: list[str] = []
    for line in path.read_text().splitlines():
        if not line.startswith("#"):
            break
        header.append(line.lstrip("#"))
    assert path.read_text().splitlines()[0].startswith("# Prompt:")
    assert IDENTITY_SENTENCE in re.sub(r"\s+", " ", " ".join(header))
