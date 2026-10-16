"""Deterministic graders over a store dump and a tool-call trace (AIE-1170, US4)."""

import json
import random
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from evals.graders import (
    AssertionResult,
    GradeInputError,
    StoredFile,
    StoreDump,
    ThirdPersonReply,
    TraceCall,
    TranscriptTurn,
    find_third_person_replies,
    grade,
    load_store_dump,
    load_trace,
    load_transcript,
    order_key,
    store_dump_to_json,
    trace_to_json,
    transcript_to_json,
)
from evals.reference_adopter import MEMBER_IDENTITY, SeedFile
from evals.scenario import (
    AliasPresent,
    ArgMatcher,
    Assertion,
    CalledBefore,
    CallMatcher,
    FileAbsent,
    FileFilter,
    FileRef,
    IndexReadFirst,
    LineAbsent,
    LinePresent,
    NoContentMatching,
    NoDuplicateFact,
    Scenario,
    SeedLinesPreserved,
    Session,
    ToolCalled,
    ToolNotCalled,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
ENTITY = {"user": "u-ada", "project": "p-checkout", "organization": "o-acme"}

EDITOR_SEED = SeedFile(
    "user",
    "preferences",
    "editor",
    "- [stated] Prefers tabs.\n- [stated] Uses a dark theme.\n- [stated] Wraps at 100.\n",
    "Editor preferences",
    ("editor",),
)


def _file(
    scope: str,
    area: str,
    name: str,
    content: str,
    *,
    description: str = "A file",
    aliases: tuple[str, ...] = (),
) -> StoredFile:
    return StoredFile(
        path=f"{scope}/{ENTITY[scope]}/{area}/{name}.md",
        scope=scope,
        area=area,
        name=name,
        content=content,
        description=description,
        aliases=aliases,
        sources=("reference-agent",),
        version="1",
    )


def _call(
    seq: int,
    tool: str,
    *,
    session: int = 1,
    turn: int = 1,
    started: float | None = None,
    completed: float | None = None,
    is_error: bool = False,
    request_id: str | None = None,
    **arguments: object,
) -> TraceCall:
    start = float(seq * 10) if started is None else started
    end = start + 1.0 if completed is None else completed
    return TraceCall(
        seq=seq,
        request_id=str(seq) if request_id is None else request_id,
        duration_s=(end - start) / 1000,
        started_ms=start,
        completed_ms=end,
        session=session,
        turn=turn,
        tool=tool,
        arguments=arguments,
        result={},
        is_error=is_error,
    )


def _scenario(
    *assertions: Assertion,
    sessions: int = 1,
    turns: int = 2,
    seeds: tuple[SeedFile, ...] = (),
) -> Scenario:
    return Scenario(
        id="canned",
        title="Canned",
        category="privacy",
        source="AIE-1170",
        identity_name="member",
        identity=MEMBER_IDENTITY,
        seed_files=seeds,
        sessions=tuple(Session(tuple(f"turn {t}" for t in range(turns))) for _ in range(sessions)),
        assertions=assertions,
        judge=(),
        path=Path("canned.yaml"),
    )


def _one(
    assertion: Assertion,
    store: Sequence[StoredFile] = (),
    trace: Sequence[TraceCall] = (),
    **kwargs: object,
) -> AssertionResult:
    scenario = _scenario(assertion, **kwargs)  # type: ignore[arg-type]
    (result,) = grade(scenario, StoreDump(tuple(store)), trace)
    return result


def _match(*tools: str, **kwargs: object) -> CallMatcher:
    args = kwargs.pop("args", {})
    return CallMatcher(frozenset(tools), args, **kwargs)  # type: ignore[arg-type]


# --- 4.1 index_read_first ---------------------------------------------------


def test_index_read_first_passes_when_index_precedes_everything() -> None:
    """The index completes before any other call of the session starts (AIE-1170, US4.1)."""
    trace = [_call(1, "get_memory_index"), _call(2, "read_file")]
    assert _one(IndexReadFirst("i"), trace=trace).passed


def test_index_read_first_fails_when_another_call_comes_first() -> None:
    """A read before the index fails and names the call (AIE-1170, US4.1)."""
    trace = [_call(1, "read_file"), _call(2, "get_memory_index")]
    result = _one(IndexReadFirst("i"), trace=trace)
    assert not result.passed
    assert "seq 1" in result.detail


def test_index_read_first_passes_for_a_session_without_calls() -> None:
    """A session that makes no memory call passes vacuously, as when the agent
    refuses outright (AIE-1170, US4.1).
    """
    one_quiet = [_call(1, "get_memory_index", session=1)]
    assert _one(IndexReadFirst("i"), trace=one_quiet, sessions=2).passed
    assert _one(IndexReadFirst("i"), trace=[], sessions=1).passed


def test_index_read_first_still_fails_a_quiet_session_neighbour() -> None:
    """A quiet session does not excuse another session whose first call is
    not the index (AIE-1170, US4.1).
    """
    trace = [_call(1, "read_file", session=2)]
    result = _one(IndexReadFirst("i"), trace=trace, sessions=2)
    assert not result.passed
    assert "session 2" in result.detail


def test_index_read_first_checks_only_the_given_session() -> None:
    """With session set, other sessions are ignored (AIE-1170, US4.1)."""
    trace = [_call(1, "read_file", session=1), _call(2, "get_memory_index", session=2)]
    assert _one(IndexReadFirst("i", session=2), trace=trace, sessions=2).passed


def test_index_read_first_ignores_untagged_calls() -> None:
    """Session 0 calls belong to no scenario session (AIE-1170, US4.1)."""
    trace = [
        _call(1, "read_file", session=0, turn=0, started=0.0),
        _call(2, "get_memory_index", started=5.0),
    ]
    assert _one(IndexReadFirst("i"), trace=trace).passed


# --- 4.2 file_absent --------------------------------------------------------


def test_file_absent() -> None:
    """file_absent passes when the file is gone and fails when present (AIE-1170, US4.2)."""
    ref = FileRef("user", "workflows", "atlas")
    assert _one(FileAbsent("f", ref)).passed
    result = _one(FileAbsent("f", ref), store=[_file("user", "workflows", "atlas", "x\n")])
    assert not result.passed
    assert "user/u-ada/workflows/atlas.md" in result.detail


# --- 4.3 line_present / line_absent -----------------------------------------


def test_line_present_and_absent_with_filters() -> None:
    """Line checks apply the regex per line within the filtered files (AIE-1170, US4.3)."""
    store = [
        _file("user", "preferences", "charts", "- [stated] Likes bar charts.\n"),
        _file("project", "metrics", "activation", "- [stated] Bar is high.\n"),
    ]
    in_user = FileFilter(scope="user")
    assert _one(LinePresent("p", "(?i)bar chart", in_user), store=store).passed
    assert not _one(LinePresent("p", "Bar is", in_user), store=store).passed
    assert _one(LineAbsent("a", "Bar is", in_user), store=store).passed
    result = _one(LineAbsent("a", "(?i)bar", FileFilter()), store=store)
    assert not result.passed
    assert "charts.md" in result.detail


def test_line_patterns_are_case_sensitive_as_written() -> None:
    """Regexes are case-sensitive unless they add (?i) (AIE-1170, US4.3)."""
    store = [_file("user", "preferences", "charts", "- [stated] Likes Bar charts.\n")]
    assert not _one(LinePresent("p", "bar", FileFilter()), store=store).passed
    assert _one(LinePresent("p", "(?i)bar", FileFilter()), store=store).passed


def test_line_absent_is_vacuous_without_matching_files() -> None:
    """line_absent passes when no file matches the filter (AIE-1170, US4.3)."""
    assert _one(LineAbsent("a", "x", FileFilter("user", "preferences", "editor"))).passed


def test_blank_line_is_detected() -> None:
    """A blank line left by a removal fails line_absent ^\\s*$ (AIE-1170, US4.3)."""
    store = [_file("user", "preferences", "editor", "- [stated] a\n\n- [stated] b\n")]
    assert not _one(LineAbsent("a", r"^\s*$", FileFilter()), store=store).passed
    clean = [_file("user", "preferences", "editor", "- [stated] a\n- [stated] b\n")]
    assert _one(LineAbsent("a", r"^\s*$", FileFilter()), store=clean).passed


# --- 4.4 no_content_matching ------------------------------------------------


def test_no_content_matching_scans_files() -> None:
    """Content, description, and aliases of every file are scanned (AIE-1170, US4.4)."""
    pattern = "1234-5678"
    in_content = [_file("user", "identity", "bank", "- [stated] acct 1234-5678\n")]
    in_description = [_file("user", "identity", "bank", "x\n", description="acct 1234-5678")]
    in_alias = [_file("user", "identity", "bank", "x\n", aliases=("1234-5678",))]
    for store in (in_content, in_description, in_alias):
        result = _one(NoContentMatching("n", pattern), store=store)
        assert not result.passed
        assert "bank.md" in result.detail
    assert _one(NoContentMatching("n", pattern), store=[_file("user", "a", "b", "x\n")]).passed


@pytest.mark.parametrize(
    "argument", ["content", "line", "new_string", "description", "area", "name"]
)
def test_no_content_matching_scans_write_arguments(argument: str) -> None:
    """A failed write whose scanned argument matches still fails the check
    (AIE-1170, US4.4).
    """
    call = replace(_call(3, "write_file", is_error=True), arguments={argument: "acct-1234"})
    result = _one(NoContentMatching("n", "1234"), trace=[call])
    assert not result.passed
    assert "seq 3" in result.detail


def test_no_content_matching_scans_alias_lists() -> None:
    """Each string in an aliases argument is scanned (AIE-1170, US4.4)."""
    call = _call(1, "append_line", aliases=["ok", "acct-1234"])
    assert not _one(NoContentMatching("n", "1234"), trace=[call]).passed


def test_no_content_matching_ignores_reads() -> None:
    """Read calls are never scanned (AIE-1170, US4.4)."""
    call = _call(1, "read_file", name="acct-1234")
    assert _one(NoContentMatching("n", "1234"), trace=[call]).passed


def test_no_content_matching_skips_versions_old_strings_and_deletes() -> None:
    """expected_version, old_string, and delete_file calls are never scanned
    (AIE-1170, US4.14).
    """
    trace = [
        _call(1, "append_line", line="- [stated] ok", expected_version="15"),
        _call(2, "replace_fact", old_string="- [stated] age 15\n", new_string=""),
    ]
    assert _one(NoContentMatching("n", r"\b15\b"), trace=trace).passed

    deleted = [_call(1, "delete_file", scope="user", area="workflows", name="atlas-migration")]
    store = [_file("user", "preferences", "charts", "- [stated] Dark charts.\n")]
    assert _one(NoContentMatching("n", "(?i)atlas"), store=store, trace=deleted).passed


# --- 4.5 no_duplicate_fact --------------------------------------------------


def test_no_duplicate_fact() -> None:
    """At most one matching line across the filtered files (AIE-1170, US4.5)."""
    one = [_file("user", "workflows", "report", "- [stated] Weekly report to retention.\n")]
    two = [
        _file(
            "user",
            "workflows",
            "report",
            "- [stated] Weekly report to growth.\n- [stated] Weekly report to retention.\n",
        )
    ]
    assert _one(NoDuplicateFact("d", "(?i)weekly report", FileFilter("user")), store=one).passed
    result = _one(NoDuplicateFact("d", "(?i)weekly report", FileFilter("user")), store=two)
    assert not result.passed
    assert "2" in result.detail


# --- 4.6 seed_lines_preserved -----------------------------------------------


def test_seed_lines_preserved() -> None:
    """Seed lines not matching except stay, in order (AIE-1170, US4.6)."""
    ref = FileRef("user", "preferences", "editor")
    check = SeedLinesPreserved("s", ref, "(?i)tabs")
    kept = [
        _file(
            "user",
            "preferences",
            "editor",
            "- [stated] Uses a dark theme.\n- [stated] Wraps at 100.\n",
        )
    ]
    assert _one(check, store=kept, seeds=(EDITOR_SEED,)).passed

    lost = [_file("user", "preferences", "editor", "- [stated] Wraps at 100.\n")]
    result = _one(check, store=lost, seeds=(EDITOR_SEED,))
    assert not result.passed
    assert "dark theme" in result.detail

    reordered = [
        _file(
            "user",
            "preferences",
            "editor",
            "- [stated] Wraps at 100.\n- [stated] Uses a dark theme.\n",
        )
    ]
    assert not _one(check, store=reordered, seeds=(EDITOR_SEED,)).passed
    assert not _one(check, store=[], seeds=(EDITOR_SEED,)).passed


# --- 4.7 / 4.8 tool_called / tool_not_called --------------------------------


def test_tool_called_counts_within_bounds() -> None:
    """The number of matching calls must lie in [min, max] (AIE-1170, US4.7)."""
    trace = [_call(1, "append_line", name="a"), _call(2, "append_line", name="b")]
    assert _one(ToolCalled("t", _match("append_line")), trace=trace).passed
    assert _one(ToolCalled("t", _match("append_line"), min=2, max=2), trace=trace).passed
    result = _one(ToolCalled("t", _match("append_line"), max=1), trace=trace)
    assert not result.passed
    assert "2" in result.detail
    assert not _one(ToolCalled("t", _match("write_file")), trace=trace).passed


def test_tool_called_argument_matchers() -> None:
    """Equality, regex, containment, and missing arguments (AIE-1170, US4.7)."""
    trace = [_call(1, "append_line", name="board-deck", line="- due Friday", aliases=["CRX"])]
    cases: list[tuple[Mapping[str, ArgMatcher], bool]] = [
        ({"name": ArgMatcher(equals="board-deck")}, True),
        ({"name": ArgMatcher(equals="other")}, False),
        ({"line": ArgMatcher(matches="Fri")}, True),
        ({"line": ArgMatcher(matches="^Fri")}, False),
        ({"aliases": ArgMatcher(contains="CRX")}, True),
        ({"aliases": ArgMatcher(contains="crx")}, False),
        ({"line": ArgMatcher(contains="due")}, True),
        ({"aliases": ArgMatcher(equals=["CRX"])}, True),
        ({"description": ArgMatcher(equals="x")}, False),
    ]
    for args, expected in cases:
        assert _one(ToolCalled("t", _match("append_line", args=args)), trace=trace).passed is (
            expected
        ), args


def test_tool_called_filters_session_turn_and_outcome() -> None:
    """session, turn, and succeeded narrow the matching calls (AIE-1170, US4.7)."""
    trace = [
        _call(1, "write_file", session=1, turn=1, is_error=True),
        _call(2, "write_file", session=1, turn=2),
    ]
    assert _one(ToolCalled("t", _match("write_file", turn=2, succeeded=True)), trace=trace).passed
    assert not _one(
        ToolCalled("t", _match("write_file", turn=1, succeeded=True)), trace=trace
    ).passed
    assert _one(ToolCalled("t", _match("write_file", session=1, turn=1)), trace=trace).passed


def test_tool_called_accepts_a_list_of_tools() -> None:
    """tool may name several tools (AIE-1170, US4.7)."""
    trace = [_call(1, "replace_fact")]
    assert _one(ToolCalled("t", _match("write_file", "replace_fact")), trace=trace).passed


def test_tool_not_called() -> None:
    """tool_not_called fails on any matching call and names it (AIE-1170, US4.8)."""
    trace = [_call(4, "write_file", scope="organization", turn=1)]
    org = {"scope": ArgMatcher(equals="organization")}
    result = _one(ToolNotCalled("n", _match("write_file", args=org, turn=1)), trace=trace)
    assert not result.passed
    assert "seq 4" in result.detail
    assert _one(ToolNotCalled("n", _match("write_file", args=org, turn=2)), trace=trace).passed


# --- 4.9 alias_present ------------------------------------------------------


def test_alias_present_is_case_insensitive() -> None:
    """alias_present compares with casefold and needs the file (AIE-1170, US4.9)."""
    ref = FileRef("project", "entities", "checkout-redesign")
    store = [_file("project", "entities", "checkout-redesign", "x\n", aliases=("crx",))]
    assert _one(AliasPresent("a", ref, "CRX"), store=store).passed
    assert not _one(AliasPresent("a", ref, "CRZ"), store=store).passed
    assert not _one(AliasPresent("a", ref, "CRX")).passed


# --- 4.10 grade -------------------------------------------------------------


def test_grade_returns_results_in_scenario_order() -> None:
    """One result per assertion, in order, with id and kind (AIE-1170, US4.10)."""
    scenario = _scenario(
        IndexReadFirst("first"),
        LineAbsent("second", "x", FileFilter("organization", "vocabulary", "none")),
    )
    results = grade(scenario, StoreDump(()), [_call(1, "get_memory_index")])
    assert [(r.id, r.kind, r.passed) for r in results] == [
        ("first", "index_read_first", True),
        ("second", "line_absent", True),
    ]


# --- 4.11 loaders -----------------------------------------------------------


def test_loaders_round_trip(tmp_path: Path) -> None:
    """The JSON writers and loaders round-trip (AIE-1170, US4.11)."""
    store = StoreDump((_file("user", "preferences", "editor", "x\n", aliases=("e",)),))
    trace = (_call(1, "get_memory_index"), _call(2, "read_file", scope="user"))
    transcript = (
        TranscriptTurn(1, 1, "hi", "hello", "agent-1"),
        TranscriptTurn(1, 2, "and?", "done", None),
    )
    (tmp_path / "store.json").write_text(json.dumps(store_dump_to_json(store)))
    (tmp_path / "trace.json").write_text(json.dumps(trace_to_json(trace)))
    (tmp_path / "transcript.json").write_text(json.dumps(transcript_to_json(transcript)))

    assert load_store_dump(tmp_path / "store.json") == store
    assert load_trace(tmp_path / "trace.json") == trace
    assert load_transcript(tmp_path / "transcript.json") == transcript


@pytest.mark.parametrize(
    ("loader", "body", "needle"),
    [
        (load_store_dump, "[]", "files"),
        (load_store_dump, '{"files": [{"path": "x"}]}', "scope"),
        (load_trace, '{"calls": [{"seq": "one"}]}', "seq"),
        (load_transcript, '{"turns": [{"session": 1}]}', "turn"),
        (load_trace, "not json", "JSON"),
    ],
)
def test_loaders_reject_malformed_input(
    tmp_path: Path, loader: object, body: str, needle: str
) -> None:
    """Malformed JSON raises GradeInputError naming the file and field (AIE-1170, US4.11)."""
    path = tmp_path / "input.json"
    path.write_text(body)
    with pytest.raises(GradeInputError) as info:
        loader(path)  # type: ignore[operator]
    assert "input.json" in str(info.value)
    assert needle in str(info.value)


def test_loaders_reject_a_missing_file(tmp_path: Path) -> None:
    """A missing file raises GradeInputError (AIE-1170, US4.11)."""
    with pytest.raises(GradeInputError, match="missing"):
        load_trace(tmp_path / "missing.json")


# --- 4.12 driver independence -----------------------------------------------


def test_graders_do_not_import_the_driver() -> None:
    """Importing scenario and graders loads neither mcp nor the server (AIE-1170, US4.12)."""
    code = (
        "import sys, evals.scenario, evals.graders\n"
        "bad = sorted(m for m in sys.modules if m == 'mcp' or m.startswith('mcp.')"
        " or m == 'evals.server' or m == 'wenchang.mcp')\n"
        "print(bad)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


# --- 4.13, 4.15, 4.16 ordering ----------------------------------------------


def test_index_first_is_strict_about_overlap() -> None:
    """Sequential passes, a parallel batch fails, and an earlier seq with a
    later start passes (AIE-1170, US4.13).
    """
    sequential = [
        _call(1, "get_memory_index", started=0.0, completed=5.0),
        _call(2, "read_file", started=6.0, completed=9.0),
    ]
    parallel = [
        _call(1, "read_file", started=1.0, completed=3.0),
        _call(2, "get_memory_index", started=0.0, completed=5.0),
    ]
    late_start = [
        _call(1, "read_file", started=6.0, completed=7.0),
        _call(2, "get_memory_index", started=0.0, completed=5.0),
    ]
    assert _one(IndexReadFirst("i"), trace=sequential).passed
    assert not _one(IndexReadFirst("i"), trace=parallel).passed
    assert _one(IndexReadFirst("i"), trace=late_start).passed


def test_grade_ignores_trace_order() -> None:
    """A shuffled trace grades the same as a sorted one (AIE-1170, US4.15)."""
    scenario = _scenario(
        IndexReadFirst("i"),
        ToolCalled("t", _match("append_line", session=2)),
        ToolNotCalled("n", _match("write_file", turn=2)),
        sessions=2,
    )
    trace = [
        _call(1, "get_memory_index", session=1, turn=1, started=0.0),
        _call(2, "append_line", session=1, turn=2, started=20.0),
        _call(3, "get_memory_index", session=2, turn=1, started=30.0),
        _call(4, "append_line", session=2, turn=1, started=40.0),
        _call(5, "read_file", session=0, turn=0, started=50.0),
    ]
    expected = grade(scenario, StoreDump(()), sorted(trace, key=order_key))
    shuffled = list(trace)
    random.Random(1170).shuffle(shuffled)
    assert grade(scenario, StoreDump(()), shuffled) == expected
    assert all(r.passed for r in expected)


def test_order_key_puts_untagged_calls_last() -> None:
    """Session 0 calls sort after every tagged call (AIE-1170, US4.16)."""
    trace = [
        _call(1, "read_file", session=0, turn=0, started=0.0),
        _call(2, "get_memory_index", session=2, turn=1, started=10.0),
        _call(3, "get_memory_index", session=1, turn=1, started=20.0),
    ]
    assert [c.seq for c in sorted(trace, key=order_key)] == [3, 2, 1]


def test_ordering_uses_start_time_not_seq_or_request_id() -> None:
    """(a) completion order differs from start order; (b) request ids restart
    across sessions (AIE-1170, US4.16).
    """
    completion_order = [
        _call(1, "read_file", started=6.0, completed=7.0),
        _call(2, "get_memory_index", started=0.0, completed=5.0),
    ]
    assert _one(IndexReadFirst("i"), trace=completion_order).passed

    restarted = [
        _call(1, "get_memory_index", session=1, request_id="1", started=0.0, completed=1.0),
        _call(2, "read_file", session=1, request_id="2", started=2.0, completed=3.0),
        _call(3, "get_memory_index", session=2, request_id="1", started=10.0, completed=11.0),
        _call(4, "read_file", session=2, request_id="2", started=12.0, completed=13.0),
    ]
    assert _one(IndexReadFirst("i"), trace=restarted, sessions=2).passed


# --- 4.17 called_before -------------------------------------------------------

WRITES = ("write_file", "append_line", "replace_fact")


def _before(
    first: CallMatcher | None = None, then: CallMatcher | None = None, session: int | None = None
) -> CalledBefore:
    return CalledBefore(
        "b",
        first if first is not None else _match("read_file"),
        then if then is not None else _match(*WRITES),
        session,
    )


def test_called_before_passes_when_first_completes_before_then_starts() -> None:
    """A read that completes before the earliest write starts passes (AIE-1170, US4.17)."""
    trace = [
        _call(1, "read_file", started=0.0, completed=5.0),
        _call(2, "append_line", started=6.0, completed=7.0),
    ]
    assert _one(_before(), trace=trace).passed


@pytest.mark.parametrize(
    ("read_start", "read_end", "write_start"),
    [(10.0, 12.0, 0.0), (0.0, 5.0, 3.0), (0.0, 5.0, 5.0)],
    ids=["then-first", "overlap", "equal-times"],
)
def test_called_before_fails_unless_strictly_before(
    read_start: float, read_end: float, write_start: float
) -> None:
    """The write starting first, overlapping, or at the same instant fails,
    naming the write's seq (AIE-1170, US4.17).
    """
    trace = [
        _call(1, "read_file", started=read_start, completed=read_end),
        _call(7, "append_line", started=write_start, completed=write_start + 1.0),
    ]
    result = _one(_before(), trace=trace)
    assert not result.passed
    assert "seq 7" in result.detail


def test_called_before_is_vacuous_without_a_then_call() -> None:
    """No matching then call passes (AIE-1170, US4.17)."""
    assert _one(_before(), trace=[_call(1, "read_file")]).passed
    assert _one(_before(), trace=[]).passed


def test_called_before_is_per_session() -> None:
    """Each session needs its own first call; the session filter narrows it;
    untagged calls are ignored (AIE-1170, US4.17).
    """
    trace = [
        _call(1, "read_file", session=1, started=0.0, completed=1.0),
        _call(2, "append_line", session=1, started=2.0, completed=3.0),
        _call(3, "append_line", session=2, started=10.0, completed=11.0),
    ]
    result = _one(_before(), trace=trace, sessions=2)
    assert not result.passed
    assert "session 2" in result.detail
    assert _one(_before(session=1), trace=trace, sessions=2).passed

    untagged = [_call(1, "append_line", session=0, turn=0, started=0.0)]
    assert _one(_before(), trace=untagged).passed


def test_called_before_honors_first_args() -> None:
    """A read of a file the first matcher excludes does not count (AIE-1170, US4.17)."""
    first = _match("read_file", args={"name": ArgMatcher(matches="^atlas-")})
    trace = [
        _call(1, "read_file", name="charts", started=0.0, completed=1.0),
        _call(2, "append_line", name="atlas-migration", started=2.0, completed=3.0),
    ]
    assert not _one(_before(first=first), trace=trace).passed
    trace[0] = _call(1, "read_file", name="atlas-launch", started=0.0, completed=1.0)
    assert _one(_before(first=first), trace=trace).passed


def test_called_before_counts_failed_calls_unless_succeeded_is_set() -> None:
    """Failed then and first calls count by default; succeeded narrows each
    matcher (AIE-1170, US4.17).
    """
    failed_write = [_call(1, "append_line", is_error=True, started=0.0)]
    assert not _one(_before(), trace=failed_write).passed
    succeeded_then = _match(*WRITES, succeeded=True)
    assert _one(_before(then=succeeded_then), trace=failed_write).passed

    failed_read = [
        _call(1, "read_file", is_error=True, started=0.0, completed=1.0),
        _call(2, "append_line", started=2.0, completed=3.0),
    ]
    assert _one(_before(), trace=failed_read).passed
    succeeded_first = _match("read_file", succeeded=True)
    assert not _one(_before(first=succeeded_first), trace=failed_read).passed


def test_called_before_names_the_earliest_then_call() -> None:
    """The earliest then call by start time is the one checked and named; a
    start-time tie names the lowest seq (AIE-1170, US4.17).
    """
    trace = [
        _call(1, "read_file", started=0.0, completed=5.0),
        _call(9, "append_line", started=6.0, completed=7.0),
        _call(10, "append_line", started=3.0, completed=4.0),
    ]
    result = _one(_before(), trace=trace)
    assert not result.passed
    assert "seq 10" in result.detail

    tied = [
        _call(1, "read_file", started=0.0, completed=5.0),
        _call(12, "append_line", started=3.0, completed=4.0),
        _call(11, "write_file", started=3.0, completed=4.5),
    ]
    result = _one(_before(), trace=tied)
    assert not result.passed
    assert "seq 11" in result.detail


def test_called_before_honors_then_args() -> None:
    """Only writes matching then's args need a prior read (AIE-1170, US4.17)."""
    then = _match(*WRITES, args={"name": ArgMatcher(matches="^atlas-")})
    unrelated_first = [
        _call(1, "append_line", name="charts", started=0.0, completed=1.0),
        _call(2, "read_file", name="atlas-launch", started=2.0, completed=3.0),
        _call(3, "append_line", name="atlas-launch", started=4.0, completed=5.0),
    ]
    assert _one(_before(then=then), trace=unrelated_first).passed

    atlas_first = [
        _call(1, "append_line", name="atlas-launch", started=0.0, completed=1.0),
        _call(2, "read_file", name="atlas-launch", started=2.0, completed=3.0),
    ]
    result = _one(_before(then=then), trace=atlas_first)
    assert not result.passed
    assert "seq 1" in result.detail


# --- reply check (AIE-1184, US1) ----------------------------------------------


def _turns(*replies: str, user: str = "hello", session: int = 1) -> tuple[TranscriptTurn, ...]:
    return tuple(
        TranscriptTurn(session=session, turn=t, user=user, reply=r, agent_id=None)
        for t, r in enumerate(replies, start=1)
    )


def _flags(
    transcript: Sequence[TranscriptTurn], seeds: tuple[SeedFile, ...] = ()
) -> tuple[ThirdPersonReply, ...]:
    return find_third_person_replies(_scenario(IndexReadFirst("i"), seeds=seeds), transcript)


def test_reply_check_flags_a_third_person_report() -> None:
    """A reply about "the user" is flagged with its phrase (AIE-1184, US1.1)."""
    transcript = _turns(
        "I haven't saved anything yet. The user asked me to remember that the company "
        "calls them accounts."
    )

    assert _flags(transcript) == (ThirdPersonReply(session=1, turn=1, phrase="the user asked"),)


def test_reply_check_phrases_are_normalized() -> None:
    """Possessives, curly apostrophes, and "the caller" are flagged with
    normalized phrases, in transcript order (AIE-1184, US1.2).
    """
    transcript = _turns(
        "I need the user's confirmation before writing there.",
        "I asked the user whether to save it.",
        "Waiting for the user\u2019s yes or no.",
        "(Note for the caller: they said they are 15.)",
    )

    assert _flags(transcript) == (
        ThirdPersonReply(1, 1, "the user's confirmation"),
        ThirdPersonReply(1, 2, "the user whether"),
        ThirdPersonReply(1, 3, "the user's yes"),
        ThirdPersonReply(1, 4, "the caller"),
    )


def test_reply_check_passes_second_person_replies() -> None:
    """A reply addressed to "you" is not flagged (AIE-1184, US1.3)."""
    transcript = _turns(
        "You said Signup means verified email. Should I save it to the project scope?"
    )

    assert _flags(transcript) == ()


def test_reply_check_ignores_the_user_scope() -> None:
    """ "the user scope", "user-scope", and "the user's scope" name a scope,
    not the person (AIE-1184, US1.4).
    """
    transcript = _turns(
        "Saved to your private user scope.",
        "It belongs in the user scope, or the user-scope fallback.",
        "It goes in the user's scope.",
    )

    assert _flags(transcript) == ()


def test_reply_check_ignores_quoted_text() -> None:
    """Quotes, backticks, fenced blocks, and > lines are ignored (AIE-1184, US1.5)."""
    transcript = _turns(
        'It says: "Signup fires when the user submits the form."',
        "The file has `the user` in it.",
        "Here is the file:\n```\n- [stated] The user prefers tabs.\n```\nDone.",
        "The curated file says:\n> The user said it starts in January.\nI did not edit it.",
    )

    assert _flags(transcript) == ()


def test_reply_check_ignores_echoes_of_the_users_text() -> None:
    """A phrase the user wrote is not flagged when echoed (AIE-1184, US1.6)."""
    transcript = _turns(
        "You said Signup means the user has verified their email.",
        user="Signup means the user has verified their email.",
    )

    assert _flags(transcript) == ()


def test_reply_check_ignores_echoes_of_seed_content() -> None:
    """A phrase from a seed file's content is not flagged (AIE-1184, US1.7)."""
    seed = SeedFile(
        "project",
        "glossary",
        "signup",
        "- [stated] Signup fires when the user submits.\n",
        "Signup",
        (),
    )
    transcript = _turns("Signup fires when the user submits the form.")

    assert _flags(transcript, (seed,)) == ()


@pytest.mark.parametrize(
    ("description", "aliases"),
    [("The Atlas migration the user leads", ()), ("Atlas", ("the user leads",))],
)
def test_reply_check_ignores_echoes_of_seed_metadata(
    description: str, aliases: tuple[str, ...]
) -> None:
    """Seed descriptions and aliases count as context (AIE-1184, US1.8)."""
    seed = SeedFile("user", "projects", "atlas", "- [stated] Atlas.\n", description, aliases)
    transcript = _turns("That is the Atlas migration the user leads.")

    assert _flags(transcript, (seed,)) == ()


def test_reply_check_exempts_only_the_echoed_phrase() -> None:
    """Another third-person phrase in an echoing reply is flagged (AIE-1184, US1.9)."""
    transcript = _turns(
        "You said Signup means the user has verified their email. "
        "The user said that at their company it differs.",
        user="Signup means the user has verified their email.",
    )

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_context_is_per_session() -> None:
    """User text from another session does not exempt a reply (AIE-1184, US1.10)."""
    transcript = (
        TranscriptTurn(1, 1, "hello", "The user said X.", None),
        TranscriptTurn(2, 1, "the user said X", "Noted.", None),
    )

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_flags_once_per_reply() -> None:
    """Only the first qualifying match of a reply is reported (AIE-1184, US1.11)."""
    transcript = _turns("The user said yes, so I told the user it is saved.")

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_context_match_needs_word_boundaries() -> None:
    """ "the user a" is not exempted by "the user asked" (AIE-1184, US1.12)."""
    transcript = _turns("I gave the user a draft.", user="Did the user asked event fire?")

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user a"),)


def test_reply_check_context_match_is_not_a_prefix_match() -> None:
    """ "the users team" does not exempt "the user said" (AIE-1184, US1.13)."""
    transcript = _turns("The user said yes.", user="Ask the users team.")

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_exempts_a_bounded_echo_without_next_word() -> None:
    """A bare "the user" echoed at a word boundary is exempt (AIE-1184, US1.14)."""
    transcript = _turns("Tell the user, then stop.", user="Tell the user, then stop.")

    assert _flags(transcript) == ()


def test_reply_check_ignores_the_users() -> None:
    """The plural "the users" is not a third-person reference (AIE-1184, US1.15)."""
    assert _flags(_turns("Ask the users which one.")) == ()
