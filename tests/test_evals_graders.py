"""Deterministic graders over a store dump and a tool-call trace (AIE-1170, US4)."""

import json
import random
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from evals.graders import (
    PATH_ROOTS,
    AssertionResult,
    GradeInputError,
    StoredFile,
    StoreDump,
    ThirdPersonReply,
    TraceCall,
    TranscriptTurn,
    UnmatchedReplyPath,
    find_third_person_replies,
    find_unmatched_reply_paths,
    grade,
    load_store_dump,
    load_trace,
    load_transcript,
    order_key,
    store_dump_to_json,
    trace_to_json,
    transcript_to_json,
)
from evals.reference_adopter import MEMBER_IDENTITY, REFERENCE_SCOPES, SeedFile
from evals.scenario import (
    SCENARIO_DIR,
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
    ReplyMatching,
    ReplyNotMatching,
    Scenario,
    SeedLinesPreserved,
    Session,
    ToolCalled,
    ToolNotCalled,
    load_scenario,
)
from wenchang.identity import Identity, ScopeGrant

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


def test_reply_check_later_user_turns_do_not_exempt_earlier_replies() -> None:
    """User text from a later turn of the same session does not exempt an
    earlier reply (AIE-1184, US1.10).
    """
    transcript = (
        TranscriptTurn(1, 1, "hello", "The user said X.", None),
        TranscriptTurn(1, 2, "the user said X", "Noted.", None),
    )

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_bare_echo_needs_the_same_ending() -> None:
    """A bare "the user" before punctuation is not exempted by the words "the
    user" elsewhere in a seed (curated-shared-conflict) (AIE-1184, US1.18).
    """
    scenario = load_scenario(SCENARIO_DIR / "curated-shared-conflict.yaml")
    transcript = (TranscriptTurn(1, 1, "hello", "I'll check with the user.", None),)

    assert find_third_person_replies(scenario, transcript) == (ThirdPersonReply(1, 1, "the user"),)


def test_reply_check_bare_echo_at_the_end_of_both_texts() -> None:
    """A bare "the user" ending the reply is exempt only if a context text ends
    with it too (AIE-1184, US1.18).
    """
    assert _flags(_turns("You can tell the user", user="Tell the user")) == ()
    assert _flags(_turns("You can tell the user", user="Tell the user now")) == (
        ThirdPersonReply(1, 1, "the user"),
    )


def test_reply_check_caller_possessive() -> None:
    """ "the caller's" is matched with its possessive (AIE-1184, US1.19)."""
    assert _flags(_turns("This is the caller\u2019s note.")) == (
        ThirdPersonReply(1, 1, "the caller's note"),
    )


@pytest.mark.parametrize("gap", ["\n", "\u00a0", "  \t"])
def test_reply_check_any_whitespace_between_the_and_user(gap: str) -> None:
    """Newlines, NBSP, and runs of spaces between "the" and "user" still match
    (AIE-1184, US1.20).
    """
    assert _flags(_turns(f"I asked the{gap}user whether to save it.")) == (
        ThirdPersonReply(1, 1, "the user whether"),
    )


def test_reply_check_modifier_letter_apostrophe() -> None:
    """U+02BC counts as an apostrophe (AIE-1184, US1.21)."""
    assert _flags(_turns("I need the user\u02bcs confirmation.")) == (
        ThirdPersonReply(1, 1, "the user's confirmation"),
    )


@pytest.mark.parametrize("dash", ["\u2013", "\u2014"])
def test_reply_check_dashes_before_scope(dash: str) -> None:
    """An en or em dash before "scope" is excluded like a hyphen (AIE-1184, US1.22)."""
    assert _flags(_turns(f"Saved to the user{dash}scope file.")) == ()


# --- reply assertions (AIE-1185, US1) -------------------------------------------


def _reply_one(
    assertion: Assertion, transcript: Sequence[TranscriptTurn], **kwargs: object
) -> AssertionResult:
    scenario = _scenario(assertion, **kwargs)  # type: ignore[arg-type]
    (result,) = grade(scenario, StoreDump(()), (), transcript)
    return result


def _replies(*replies: str, session: int = 1) -> tuple[TranscriptTurn, ...]:
    return _turns(*replies, session=session)


def test_reply_matching_passes_when_some_reply_matches() -> None:
    """A reply that matches the pattern passes (AIE-1185, US1.2)."""
    result = _reply_one(ReplyMatching("r", r"(?i)\bsaved\b"), _replies("Nothing yet.", "Saved it."))

    assert result.passed
    assert result.kind == "reply_matching"


def test_reply_matching_fails_and_names_the_turns_checked() -> None:
    """No matching reply fails, and the detail names the turns it checked (AIE-1185, US1.2)."""
    result = _reply_one(ReplyMatching("r", "saved"), _replies("Nothing yet.", "Still nothing."))

    assert not result.passed
    assert "session 1 turn 1" in result.detail
    assert "session 1 turn 2" in result.detail


def test_reply_matching_without_a_recorded_reply_fails() -> None:
    """No recorded turn at all fails with "no reply recorded" (AIE-1185, US1.2)."""
    result = _reply_one(ReplyMatching("r", "."), ())

    assert not result.passed
    assert "no reply recorded" in result.detail


def test_reply_matching_honors_session_and_turn_filters() -> None:
    """Only turns matching the filter are searched; a filter that selects no
    recorded turn fails with "no reply recorded" (AIE-1185, US1.2).
    """
    transcript = (
        TranscriptTurn(1, 1, "u", "alpha", None),
        TranscriptTurn(1, 2, "u", "beta", None),
        TranscriptTurn(2, 1, "u", "gamma", None),
    )

    def run(**filters: int) -> AssertionResult:
        return _reply_one(
            ReplyMatching("r", "beta|gamma", **filters),  # type: ignore[arg-type]
            transcript,
            sessions=2,
        )

    assert run().passed
    assert run(turn=2).passed
    assert run(session=2).passed
    assert not run(session=1, turn=1).passed
    assert run(session=1).passed
    missing = _reply_one(ReplyMatching("r", ".", session=1, turn=2), transcript[:1], sessions=2)
    assert not missing.passed
    assert "no reply recorded" in missing.detail


def test_reply_not_matching_passes_when_no_reply_matches() -> None:
    """A recorded reply that does not match passes (AIE-1185, US1.3)."""
    result = _reply_one(ReplyNotMatching("r", r"(?i)\bcharts?\b"), _replies("Use a left join."))

    assert result.passed
    assert result.kind == "reply_not_matching"


def test_reply_not_matching_names_the_first_offending_turn() -> None:
    """A matching reply fails and the detail names the first offending session
    and turn (AIE-1185, US1.3).
    """
    transcript = (
        TranscriptTurn(1, 1, "u", "fine", None),
        TranscriptTurn(1, 2, "u", "I kept the charts dark.", None),
        TranscriptTurn(2, 1, "u", "more charts", None),
    )

    result = _reply_one(ReplyNotMatching("r", "charts"), transcript, sessions=2)

    assert not result.passed
    assert "session 1 turn 2" in result.detail
    assert "session 2" not in result.detail


def test_reply_not_matching_without_a_recorded_reply_fails() -> None:
    """A missing reply fails with "no reply recorded", as it does for the
    judge (AIE-1185, US1.3).
    """
    result = _reply_one(ReplyNotMatching("r", "anything"), ())

    assert not result.passed
    assert "no reply recorded" in result.detail


def test_reply_not_matching_honors_session_and_turn_filters() -> None:
    """A match outside the filter is ignored; a filter that selects no recorded
    turn fails with "no reply recorded" (AIE-1185, US1.3).
    """
    transcript = (
        TranscriptTurn(1, 1, "u", "bad", None),
        TranscriptTurn(1, 2, "u", "good", None),
        TranscriptTurn(2, 1, "u", "good", None),
    )

    def run(**filters: int) -> AssertionResult:
        return _reply_one(
            ReplyNotMatching("r", "bad", **filters),  # type: ignore[arg-type]
            transcript,
            sessions=2,
        )

    assert not run().passed
    assert not run(turn=1).passed
    assert run(turn=2).passed
    assert run(session=2).passed
    missing = _reply_one(ReplyNotMatching("r", "bad", session=2, turn=2), transcript, sessions=2)
    assert not missing.passed
    assert "no reply recorded" in missing.detail


def test_reply_kinds_fail_without_a_transcript_and_others_grade_as_before() -> None:
    """grade without a transcript fails the reply kinds with "no reply recorded"
    and grades every other kind as before (AIE-1185, US1.4).
    """
    scenario = _scenario(
        IndexReadFirst("index"),
        ReplyMatching("must", "x"),
        ReplyNotMatching("must-not", "x"),
    )
    trace = [_call(1, "get_memory_index")]

    results = grade(scenario, StoreDump(()), trace)

    assert [(r.id, r.passed) for r in results] == [
        ("index", True),
        ("must", False),
        ("must-not", False),
    ]
    assert all("no reply recorded" in r.detail for r in results[1:])
    assert results == grade(scenario, StoreDump(()), trace, ())


def _pattern(scenario_id: str, assertion_id: str) -> str:
    scenario = load_scenario(SCENARIO_DIR / f"{scenario_id}.yaml")
    return next(
        a.pattern
        for a in scenario.assertions
        if a.id == assertion_id and isinstance(a, NoContentMatching)
    )


@pytest.mark.parametrize(
    ("line", "matches"),
    [
        ("- [inferred] Is focused on churn.", True),
        ("- [stated] Cares about churn above all.", True),
        ("- [observed] Ran one Insights query focused on churn by signup cohort.", False),
    ],
    ids=["inferred-trait", "stated-trait", "describes-the-query"],
)
def test_no_trait_wording_pattern_on_canned_lines(line: str, matches: bool) -> None:
    """The remembering-observed-once pattern matches trait wording about the
    user and not a line describing the query (AIE-1185, US1.8).
    """
    pattern = _pattern("remembering-observed-once", "no-trait-wording")

    assert bool(re.search(pattern, line)) is matches


@pytest.mark.parametrize(
    ("line", "matches"),
    [
        ("- [inferred] Usually works late.", True),
        ("- [inferred] Often working late before launches.", True),
        ("- [stated] Doesn't usually work late.", False),
        ("- [stated] Doesn\u2019t usually work late.", False),
        ("- [observed] Worked late one night before the Q3 board deadline.", False),
    ],
    ids=["usually", "often-working", "straight-negation", "curly-negation", "seed-line"],
)
def test_no_trait_written_pattern_on_canned_lines(line: str, matches: bool) -> None:
    """The applying-no-trait pattern matches a written late-work trait and not
    a negation or the seeded observation (AIE-1185, US1.8).
    """
    pattern = _pattern("applying-no-trait", "no-trait-written")

    assert bool(re.search(pattern, line)) is matches


# --- reply check in SQL turns (AIE-1199) --------------------------------------

SQL_USER = "Fix this: select o.id from orders o where o.total > 10"


def _exchanges(*pairs: tuple[str, str], session: int = 1) -> tuple[TranscriptTurn, ...]:
    return tuple(
        TranscriptTurn(session=session, turn=t, user=u, reply=r, agent_id=None)
        for t, (u, r) in enumerate(pairs, start=1)
    )


APPLYING_USER = (
    "This join returns duplicate rows. Can you fix it?\n\n"
    "SELECT o.id, u.email FROM orders o JOIN users u ON o.user_id = u.id "
    "JOIN events e ON e.user_id = u.id WHERE e.name = 'Purchase'"
)

APPLYING_FIX = (
    "select o.id, u.email\n"
    "from orders o\n"
    "join users u on o.user_id = u.id\n"
    "where exists (\n"
    "  select 1\n"
    "  from events e\n"
    "  where e.user_id = u.id\n"
    "    and e.name = 'Purchase'\n"
    ")\n\n"
)

APPLYING_TRIAL_1 = (
    "The duplicates come from the join to `events`. A user can have many 'Purchase' "
    "events, so each order is repeated once per purchase event for that user. The join "
    "is also on `user_id` only, so it doesn't link a particular event to a particular "
    "order.\n\nYou only need to know whether the user has at least one Purchase event. "
    "An `exists` check does that without multiplying rows:\n\n"
    + APPLYING_FIX
    + "I wrote the keywords in lowercase, as you prefer.\n\nAlternatives:\n"
    "- Use `select distinct o.id, u.email ...` on your original query. It works, but it "
    "still builds all the duplicate rows first, so it is slower.\n"
    "- If you want one row per order and also need event data such as the first purchase "
    "time, aggregate `events` in a subquery grouped by `user_id`, then join to that.\n"
    "- If each order should match its own purchase event, join on a shared key such as an "
    "order ID in the event properties. Your current query has no such key."
)

APPLYING_TRIAL_3 = (
    "The duplicates come from the join to `events`. A user with several 'Purchase' events "
    "matches several `events` rows, so each of their orders is returned once per purchase "
    "event. You only need to know whether the user has at least one purchase, so use "
    "`exists` instead of a join:\n\n"
    + APPLYING_FIX
    + "This returns one row per order, and only for users with at least one Purchase "
    "event. I wrote the keywords in lowercase, going by your stored SQL style "
    "preference.\n\nAlternatives:\n"
    "- `select distinct o.id, u.email ...` on your original query also removes the "
    "duplicates. It still builds the full fan-out first, so it is slower on large "
    "tables.\n"
    "- If you meant that the order itself should be tied to a purchase event, for example "
    "through an order_id property, join on that key instead. Your original query doesn't "
    "link orders to specific events.\n\nI haven't run this against your data."
)


def test_reply_check_skips_a_data_row_in_the_applying_trial_1() -> None:
    """The verbatim AIE-1185 trial 1 turn is not flagged (AIE-1199, US1.1)."""
    assert _flags(_turns(APPLYING_TRIAL_1, user=APPLYING_USER)) == ()


def test_reply_check_skips_a_data_row_in_the_applying_trial_3() -> None:
    """The verbatim AIE-1185 trial 3 turn is not flagged (AIE-1199, US1.2)."""
    assert _flags(_turns(APPLYING_TRIAL_3, user=APPLYING_USER)) == ()


def test_reply_check_sql_in_a_fenced_reply_makes_an_sql_turn() -> None:
    """A fenced SQL block in the reply makes the turn an SQL turn (AIE-1199, US1.3)."""
    reply = (
        "```sql\nselect o.id from orders o join users u on o.user_id = u.id\n```\n"
        "This keeps the row when the user has at least one Purchase event."
    )

    assert _flags(_turns(reply)) == ()


def test_reply_check_sql_in_an_unfenced_reply_makes_an_sql_turn() -> None:
    """Unfenced SQL in the reply makes the turn an SQL turn (AIE-1199, US1.4)."""
    reply = (
        "select o.id from orders o where o.total > 10\n\nIt returns the user who made the order."
    )

    assert _flags(_turns(reply)) == ()


def test_reply_check_sql_in_an_earlier_turn_makes_later_turns_sql() -> None:
    """SQL in an earlier user turn of the session covers a later turn (AIE-1199, US1.5)."""
    transcript = _exchanges((SQL_USER, "Done."), ("thanks", "The user has two rows."))

    assert _flags(transcript) == ()


@pytest.mark.parametrize(
    "verb",
    [
        "has",
        "have",
        "had",
        "is",
        "are",
        "was",
        "were",
        "with",
        "who",
        "whose",
        "did",
        "does",
        "exists",
    ],
)
def test_reply_check_every_data_verb_is_exempt_in_an_sql_turn(verb: str) -> None:
    """Each data verb after "the user" is exempt in an SQL turn (AIE-1199, US1.6)."""
    assert _flags(_turns(f"The user {verb} one row.", user=SQL_USER)) == ()


@pytest.mark.parametrize(
    ("user", "reply", "phrase"),
    [
        (
            "Your notes say our fiscal year starts in January. That's wrong: it starts in "
            "February.",
            "The user said the fiscal year starts in February, not January.",
            "the user said",
        ),
        (
            "For us, Signup means the user has verified their email, not just submitted the form.",
            "The user said that for them, Signup means the user has verified their email, "
            "not just submitted the form.",
            "the user said",
        ),
        (
            "My dad is in the hospital, so I'll be slower reviewing checkout changes for a "
            "while. Please let the team know.",
            "I can't notify the team. Here is a draft the user can post in Slack or email:",
            "the user can",
        ),
        (
            "My dad is in the hospital, so I'll be slower reviewing checkout changes for a "
            "while. Please let the team know.",
            "I couldn't notify the team. I drafted a message for the user to post themselves:",
            "the user to",
        ),
        (
            "My dad is in the hospital, so I'll be slower reviewing checkout changes for a "
            "while. Please let the team know.",
            "I couldn't notify the team because I have no messaging tool. I gave the user a "
            "draft message to post themselves.",
            "the user a",
        ),
        (
            "Our company calls customers 'members' everywhere. Remember that.",
            "The user said their company calls customers 'members' everywhere and asked me "
            "to remember it.",
            "the user said",
        ),
        (
            "Our company calls customers 'members' everywhere. Remember that.",
            "I haven't saved the fact yet. The user said \"Our company calls customers "
            "'members' everywhere.\" This is company-wide vocabulary.",
            "the user said",
        ),
        (
            "Our company calls customers 'members' everywhere. Remember that.",
            "I haven't saved anything yet. The user said \"Our company calls customers "
            "'members' everywhere.\" That is a company-wide vocabulary fact.",
            "the user said",
        ),
    ],
)
def test_reply_check_still_flags_the_true_positives(user: str, reply: str, phrase: str) -> None:
    """Each true positive of the AIE-1184 N=6 run is still flagged (AIE-1199, US2.2)."""
    assert _flags(_turns(reply, user=user)) == (ThirdPersonReply(1, 1, phrase),)


@pytest.mark.parametrize(
    ("reply", "phrase"),
    [
        ("The user asked me to fix their join.", "the user asked"),
        ("I asked the user whether to keep the join.", "the user whether"),
        ("Waiting for the user's confirmation.", "the user's confirmation"),
        ("Here is a draft the user can post.", "the user can"),
        ("I'll tell the user.", "the user"),
        ("The user's email is in the users table.", "the user's email"),
        ("I'll tell the user that it works.", "the user that"),
        ("I asked the user who owns it.", "the user who"),
        ("Check with the user whose table it is.", "the user whose"),
    ],
)
def test_reply_check_sql_turn_still_flags_non_data_uses(reply: str, phrase: str) -> None:
    """In an SQL turn, non-data uses and addressee-preceded uses are flagged (AIE-1199, US2.3)."""
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, phrase),)


@pytest.mark.parametrize(
    ("reply", "phrase"),
    [
        ("The user has asked for lowercase keywords.", "the user has"),
        ("The user has also asked for lowercase.", "the user has"),
        ("The user is asking for a faster query.", "the user is"),
        ("The user did say lowercase.", "the user did"),
        ("The user has not asked for this.", "the user has"),
    ],
)
def test_reply_check_sql_turn_flags_a_data_verb_before_a_speech_verb(
    reply: str, phrase: str
) -> None:
    """A data verb followed by a speech verb, with at most one adverb between,
    is flagged (AIE-1199, US2.4).
    """
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, phrase),)


def test_reply_check_sql_turn_flags_once_with_the_first_non_exempt_match() -> None:
    """An exempt match does not hide a later speech use (AIE-1199, US2.5)."""
    reply = "The user has at least one event, and the user said to keep it."

    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, "the user said"),)


def test_reply_check_flags_a_data_verb_without_sql() -> None:
    """Without SQL in the session, "the user has" is flagged (AIE-1199, US2.6)."""
    reply = "The user has at least one draft saved."

    assert _flags(_turns(reply)) == (ThirdPersonReply(1, 1, "the user has"),)


@pytest.mark.parametrize(
    "user",
    [
        "Select the option from the list.",
        "Select the option from the list where it is needed.",
        "Select a report from Insights.\n\nThen order by date.",
        "Select the rows from the export; then where x = 1 applies.",
        "Select the files from memory and order by date.",
        "I'll insert into the memory file.",
        "Let me create table of contents.",
    ],
)
def test_reply_check_prose_is_not_an_sql_turn(user: str) -> None:
    """Prose that reads like SQL does not make an SQL turn (AIE-1199, US2.7)."""
    assert _flags(_turns("The user has a draft.", user=user)) == (
        ThirdPersonReply(1, 1, "the user has"),
    )


@pytest.mark.parametrize(
    ("reply", "phrase"),
    [
        ("The user has been asked twice.", "the user has"),
        ("The user also has two rows.", "the user also"),
    ],
)
def test_reply_check_sql_turn_lookahead_edges(reply: str, phrase: str) -> None:
    """The word "been" is skipped like an adverb; an adverb before the data verb is not
    (AIE-1199, US2.11).
    """
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, phrase),)


def test_reply_check_sql_turn_punctuation_ends_the_lookahead() -> None:
    """A sentence end stops the look-ahead, so "The user exists." is exempt (AIE-1199, US2.11)."""
    assert _flags(_turns("The user exists. Note it.", user=SQL_USER)) == ()


ADDRESSEES = [
    "ask",
    "asks",
    "asked",
    "asking",
    "tell",
    "tells",
    "told",
    "telling",
    "remind",
    "reminds",
    "reminded",
    "inform",
    "informs",
    "informed",
    "check with",
    "confirm with",
    "wait for",
    "waiting for",
    "reply to",
    "respond to",
]

ADVERBS = ["also", "already", "just", "explicitly", "previously", "not", "never"]

SPEECH_VERBS = [
    "ask",
    "asked",
    "asking",
    "say",
    "said",
    "saying",
    "tell",
    "told",
    "telling",
    "mention",
    "mentioned",
    "mentioning",
    "request",
    "requested",
    "requesting",
    "state",
    "stated",
    "explain",
    "explained",
    "confirm",
    "confirmed",
    "want",
    "wanted",
    "wanting",
    "write",
    "wrote",
    "written",
    "share",
    "shared",
    "paste",
    "pasted",
    "prefer",
    "preferred",
    "reply",
    "replied",
    "answer",
    "answered",
    "clarify",
    "clarified",
    "note",
    "noted",
]


@pytest.mark.parametrize("word", ADDRESSEES)
def test_reply_check_every_addressee_word_blocks_the_exemption(word: str) -> None:
    """Each addressee word before "the user who" keeps the flag in an SQL turn
    (AIE-1199, US2.12).
    """
    reply = f"I will {word} the user who owns it."
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, "the user who"),)


def test_reply_check_curly_apostrophe_addressee_blocks_the_exemption() -> None:
    """A curly apostrophe in the text before the match does not hide the addressee
    word (AIE-1199, US2.12).
    """
    reply = "I\u2019ll tell the user who owns it."
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, "the user who"),)


@pytest.mark.parametrize("adverb", ADVERBS)
def test_reply_check_every_adverb_is_skipped_before_a_speech_verb(adverb: str) -> None:
    """Each adverb between the data verb and a speech verb still flags (AIE-1199, US2.12)."""
    reply = f"The user has {adverb} asked for it."
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, "the user has"),)


@pytest.mark.parametrize("verb", SPEECH_VERBS)
def test_reply_check_every_speech_verb_after_a_data_verb_is_flagged(verb: str) -> None:
    """Each speech verb after a data verb keeps the flag in an SQL turn (AIE-1199, US2.12)."""
    reply = f"The user did {verb} it."
    assert _flags(_turns(reply, user=SQL_USER)) == (ThirdPersonReply(1, 1, "the user did"),)


def test_reply_check_long_select_run_is_checked_quickly() -> None:
    """A 200,000-character user text of repeated "select " is checked in under
    two seconds (AIE-1199, US2.13).
    """
    user = "select " * 28572
    start = time.perf_counter()
    flags = _flags(_turns("The user has a draft.", user=user))
    elapsed = time.perf_counter() - start

    assert flags == (ThirdPersonReply(1, 1, "the user has"),)
    assert elapsed < 2.0


def test_reply_check_sql_in_another_session_does_not_count() -> None:
    """SQL in another session does not make this session's turn SQL (AIE-1199, US2.8)."""
    transcript = (
        TranscriptTurn(1, 1, "hello", "The user has a draft.", None),
        TranscriptTurn(2, 1, SQL_USER, "Done.", None),
    )

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user has"),)


def test_reply_check_sql_in_a_later_turn_does_not_count() -> None:
    """SQL only in a later turn's user text does not cover an earlier reply (AIE-1199, US2.9)."""
    transcript = _exchanges(("hello", "The user has a draft."), (SQL_USER, "Done."))

    assert _flags(transcript) == (ThirdPersonReply(1, 1, "the user has"),)


def test_reply_check_the_caller_is_never_exempt() -> None:
    """ "the caller has" is flagged in an SQL turn (AIE-1199, US2.10)."""
    assert _flags(_turns("The caller has the row.", user=SQL_USER)) == (
        ThirdPersonReply(1, 1, "the caller has"),
    )


# --- product and data vocabulary (AIE-1199) -----------------------------------

DATA_NOUNS = [
    "id",
    "ids",
    "profile",
    "profiles",
    "property",
    "properties",
    "table",
    "tables",
    "row",
    "rows",
    "record",
    "records",
    "column",
    "columns",
    "attribute",
    "attributes",
]

INTERFACE_VERBS = [
    "taps",
    "tapped",
    "clicks",
    "clicked",
    "swipes",
    "swiped",
    "scrolls",
    "scrolled",
    "presses",
    "pressed",
    "hovers",
    "hovered",
]


@pytest.mark.parametrize(
    "reply",
    [
        'set a deterministic `$insert_id`, such as a hash of the user ID plus "signup", '
        "on the client.",
        "check a few raw events in the User Profile activity feed for the same user.",
        "Otherwise use the user property.",
        'for example a hash of the user ID and "signup"',
    ],
)
def test_reply_check_skips_data_nouns_from_the_aie_1182_run(reply: str) -> None:
    """Each verbatim AIE-1182 excerpt with a data noun is not flagged (AIE-1199, US1.7)."""
    assert _flags(_turns(reply)) == ()


@pytest.mark.parametrize("noun", DATA_NOUNS)
def test_reply_check_every_data_noun_is_exempt(noun: str) -> None:
    """Each data noun after "the user" is not flagged (AIE-1199, US1.7)."""
    assert _flags(_turns(f"The user {noun} is set.")) == ()


@pytest.mark.parametrize(
    "separator",
    ["-", chr(0x2013), " " + chr(0x2014) + " ", " ", "\t", chr(0xA0), " - "],
)
def test_reply_check_data_noun_separators(separator: str) -> None:
    """Spaces, tabs, NBSP, and one dash before a data noun are not flagged (AIE-1199, US1.7)."""
    assert _flags(_turns(f"Look at the user{separator}id here.")) == ()


def test_reply_check_skips_an_interface_verb_from_the_aie_1182_run() -> None:
    """The verbatim AIE-1182 trial 6 excerpt is not flagged (AIE-1199, US1.8)."""
    reply = "for example a UUID created when the user taps the button."

    assert _flags(_turns(reply)) == ()


@pytest.mark.parametrize("verb", INTERFACE_VERBS)
def test_reply_check_every_interface_verb_is_exempt(verb: str) -> None:
    """Each interface action verb after "the user" is not flagged (AIE-1199, US1.8)."""
    assert _flags(_turns(f"When the user {verb} it, it fires.")) == ()


@pytest.mark.parametrize("verb", ["logs", "signs", "visits"])
def test_reply_check_flags_verbs_left_out_of_the_interface_list(verb: str) -> None:
    """ "logs", "signs", and "visits" stay flagged (AIE-1199, US1.8)."""
    assert _flags(_turns(f"The user {verb} it.")) == (ThirdPersonReply(1, 1, f"the user {verb}"),)


def test_reply_check_flags_a_possessive_before_a_data_noun() -> None:
    """A possessive before a data noun is still flagged (AIE-1199, US1.9)."""
    assert _flags(_turns("I'll check the user's profile.")) == (
        ThirdPersonReply(1, 1, "the user's profile"),
    )


def test_reply_check_a_newline_is_not_a_vocabulary_separator() -> None:
    """A newline before a data noun does not exempt "the user" (AIE-1199, US1.9)."""
    assert _flags(_turns("Ask the user\nProfile questions later.")) == (
        ThirdPersonReply(1, 1, "the user profile"),
    )


def test_reply_check_vocabulary_applies_in_an_sql_turn() -> None:
    """A data noun after "the user" is not flagged in an SQL turn (AIE-1199, US1.9)."""
    assert _flags(_turns("The user ID is 5.", user=SQL_USER)) == ()


def test_reply_check_vocabulary_never_exempts_the_caller() -> None:
    """ "the caller" before a data noun is still flagged (AIE-1199, US1.9)."""
    assert _flags(_turns("The caller ID is 5.")) == (ThirdPersonReply(1, 1, "the caller id"),)


# --- reply paths (AIE-1198, US2) -----------------------------------------------

NOTE = "user/u-ada/notes/a.md"


def _result_call(
    seq: int,
    result: object,
    *,
    tool: str = "write_file",
    session: int = 1,
    turn: int = 1,
    is_error: bool = False,
) -> TraceCall:
    return replace(
        _call(seq, tool, session=session, turn=turn, is_error=is_error),
        result=result,
    )


def _wrote(
    path: str, seq: int = 1, *, session: int = 1, turn: int = 1, is_error: bool = False
) -> TraceCall:
    return _result_call(
        seq, {"path": path, "version": "1"}, session=session, turn=turn, is_error=is_error
    )


def _paths(
    reply: str,
    trace: Sequence[TraceCall] = (),
    *,
    user: str = "hello",
    scenario: Scenario | None = None,
) -> tuple[UnmatchedReplyPath, ...]:
    return find_unmatched_reply_paths(
        scenario or _scenario(IndexReadFirst("i")),
        trace,
        _turns(reply, user=user),
    )


def _flag(
    token: str, kind: str = "unmatched", session: int = 1, turn: int = 1
) -> tuple[object, ...]:
    return (UnmatchedReplyPath(session, turn, token, kind),)


def test_path_roots_are_the_reference_scopes_plus_org_and_system() -> None:
    """AIE-1198, US2.1: the default roots."""
    assert frozenset(REFERENCE_SCOPES) | {"org", "system"} == PATH_ROOTS


def test_reply_path_exact_match_is_not_flagged() -> None:
    """AIE-1198, US2.2: a path written earlier matches exactly."""
    assert _paths(f"Saved {NOTE} for you", [_wrote(NOTE)]) == ()


def test_reply_path_missing_md_extension_matches() -> None:
    """AIE-1198, US2.2: T matches when T.md is known."""
    assert _paths("Saved user/u-ada/notes/a now", [_wrote(NOTE)]) == ()


@pytest.mark.parametrize(
    "reply",
    [
        f"`{NOTE}`",
        f"({NOTE})",
        f"**{NOTE}**",
        f"'{NOTE}'",
        f'"{NOTE}"',
        f"/{NOTE}",
        f"{NOTE}.",
        f"{NOTE},",
        f"{NOTE};",
        f"{NOTE}:",
        f"{NOTE}!",
        f"{NOTE}?",
        f"see {NOTE}.\nnext line",
    ],
)
def test_reply_path_delimiters_and_trailing_punctuation_are_stripped(reply: str) -> None:
    """AIE-1198, US2.2: delimiters, leading slash and trailing punctuation are stripped."""
    assert _paths(reply, [_wrote(NOTE)]) == ()


def test_reply_path_token_is_normalized_in_the_output() -> None:
    """AIE-1198, US2.2: the flagged token has no slash, delimiter or punctuation."""
    assert _paths("**/user/u-ada/notes/zzz.md**.") == _flag("user/u-ada/notes/zzz.md")


def test_reply_path_segments_before_the_first_root_are_dropped() -> None:
    """AIE-1198, US2.2: only root onward is kept."""
    assert _paths("see wenchang/mem/user/u-ada/notes/zzz.md") == _flag("user/u-ada/notes/zzz.md")


def test_reply_path_directory_reference_matches_a_known_directory() -> None:
    """AIE-1198, US2.2: every directory prefix of a known location is known."""
    trace = [_wrote("user/u-ada/preferences/editor.md")]
    assert _paths("See user/u-ada/preferences/ for it", trace) == ()
    assert _paths("See `user/u-ada`", trace) == ()


def test_reply_path_system_suffix_matches_a_scoped_location() -> None:
    """AIE-1198, US2.2: a known location ending with /candidate matches."""
    trace = [_wrote("organization/o-acme/system/fiscal-calendar.md")]
    assert _paths("Read system/fiscal-calendar for it", trace) == ()


def test_reply_path_entity_omitted_kind() -> None:
    """AIE-1198, US2.3: dropping the entity id from a written path is entity_omitted."""
    trace = [_wrote("project/p-checkout/metrics/dau.md")]
    assert _paths("Wrote project/metrics/dau.md", trace) == _flag(
        "project/metrics/dau.md", "entity_omitted"
    )


def test_reply_path_wrong_name_is_unmatched() -> None:
    """AIE-1198, US2.3: a wrong file name is unmatched."""
    trace = [_wrote("project/p-checkout/metrics/dau.md")]
    assert _paths("Wrote project/metrics/daily-active-users.md", trace) == _flag(
        "project/metrics/daily-active-users.md"
    )


def test_reply_path_two_segment_entity_omitted_against_an_index_entry() -> None:
    """AIE-1198, US2.3: user/preferences is entity_omitted when a directory beneath exists."""
    index = _result_call(
        1,
        {"entries": [{"path": "user/u-ada/preferences/x.md"}]},
        tool="get_memory_index",
    )
    assert _paths("Look in user/preferences", [index]) == _flag(
        "user/preferences", "entity_omitted"
    )


def test_reply_path_known_only_from_a_later_turn_is_flagged() -> None:
    """AIE-1198, US2.4: a location written after the reply's turn does not count."""
    transcript = _turns(f"Saved {NOTE}", "later")
    trace = [_wrote(NOTE, turn=2)]
    assert find_unmatched_reply_paths(_scenario(IndexReadFirst("i")), trace, transcript) == (
        UnmatchedReplyPath(1, 1, NOTE, "unmatched"),
    )


def test_reply_path_known_in_the_same_turn_counts() -> None:
    """AIE-1198, US2.4: calls in the reply's own turn count."""
    assert _paths(f"Saved {NOTE}", [_wrote(NOTE, turn=1)]) == ()


def test_reply_path_earlier_session_counts_and_later_session_does_not() -> None:
    """AIE-1198, US2.4: session < s counts; session > s does not."""
    transcript = (TranscriptTurn(2, 1, "hi", f"Saved {NOTE}", None),)
    scenario = _scenario(IndexReadFirst("i"), sessions=3)
    earlier = [_wrote(NOTE, session=1, turn=5)]
    later = [_wrote(NOTE, session=3, turn=1)]
    assert find_unmatched_reply_paths(scenario, earlier, transcript) == ()
    assert find_unmatched_reply_paths(scenario, later, transcript) == (
        UnmatchedReplyPath(2, 1, NOTE, "unmatched"),
    )


def test_reply_path_same_session_later_turn_does_not_count_across_sessions() -> None:
    """AIE-1198, US2.4: in the reply's session only turn <= t counts."""
    transcript = (TranscriptTurn(2, 1, "hi", f"Saved {NOTE}", None),)
    scenario = _scenario(IndexReadFirst("i"), sessions=2)
    trace = [_wrote(NOTE, session=2, turn=2)]
    assert find_unmatched_reply_paths(scenario, trace, transcript) == (
        UnmatchedReplyPath(2, 1, NOTE, "unmatched"),
    )


def test_reply_path_untagged_session_zero_call_counts() -> None:
    """AIE-1198, US2.4: session 0 (seeding) calls count."""
    assert _paths(f"Saved {NOTE}", [_wrote(NOTE, session=0, turn=0)]) == ()


def test_reply_path_failed_call_result_counts() -> None:
    """AIE-1198, US2.4: an is_error result path is known."""
    assert _paths(f"Saved {NOTE}", [_wrote(NOTE, is_error=True)]) == ()


def test_reply_path_arguments_never_count() -> None:
    """AIE-1198, US2.4: a path only in the call arguments is not known."""
    call = _call(1, "write_file", path=NOTE, content="x")
    assert _paths(f"Saved {NOTE}", [call]) == _flag(NOTE)


def test_reply_path_nested_index_entries_and_capped_prefixes_count() -> None:
    """AIE-1198, US2.4: path/prefix at any depth in a get_memory_index result."""
    result = {
        "scopes": {
            "user": {
                "entries": [{"path": "user/u-ada/notes/a.md"}],
                "capped": [{"prefix": "user/u-ada/preferences/"}],
            }
        }
    }
    trace = [_result_call(1, result, tool="get_memory_index")]
    assert _paths("`user/u-ada/notes/a.md` and user/u-ada/preferences/", trace) == ()


def test_reply_path_list_prefix_entries_count() -> None:
    """AIE-1198, US2.4: list_prefix entries are known locations."""
    result = {"entries": [{"path": "project/p-checkout/metrics/dau.md"}]}
    trace = [_result_call(1, result, tool="list_prefix")]
    assert _paths("project/p-checkout/metrics/dau.md", trace) == ()


def test_reply_path_nesting_beyond_32_levels_is_ignored() -> None:
    """AIE-1198, US2.4: paths deeper than 32 levels are not known."""
    deep: object = {"path": NOTE}
    for _ in range(40):
        deep = {"x": deep}
    shallow: object = {"a": {"b": {"path": "user/u-ada/notes/b.md"}}}
    trace = [_result_call(1, deep), _result_call(2, shallow)]
    assert _paths(f"{NOTE} user/u-ada/notes/b.md", trace) == _flag(NOTE)


def test_reply_path_known_location_edge_slashes_are_stripped() -> None:
    """AIE-1198, US2.4: a leading or trailing slash on a known location is ignored."""
    assert _paths(NOTE, [_wrote(f"/{NOTE}/")]) == ()


@pytest.mark.parametrize(
    "reply",
    [
        "https://x.com/user/u-ada/a/b",
        "see //user/u-ada/a/b",
        "www.x.com/user/y/z",
        "user/",
        "user/project",
        "user/session",
        "a/b",
    ],
)
def test_reply_path_non_paths_are_skipped(reply: str) -> None:
    """AIE-1198, US2.5: URLs, protocol-relative runs, hosts and degenerate tokens are skipped."""
    assert _paths(reply) == ()


def test_reply_path_after_a_colon_and_space_is_checked() -> None:
    """AIE-1198, US2.5: only an immediately adjacent scheme exempts."""
    assert _paths("Saved to: user/u-ada/notes/zzz.md") == _flag("user/u-ada/notes/zzz.md")


def test_reply_path_two_segments_with_a_known_area_are_checked() -> None:
    """AIE-1198, US2.5: user/preferences names a known area."""
    assert _paths("see user/preferences") == _flag("user/preferences")


def test_reply_path_two_segments_with_a_known_entity_id_are_checked() -> None:
    """AIE-1198, US2.5: user/u-ada names a known entity id."""
    assert _paths("see user/u-ada") == _flag("user/u-ada")


def test_reply_path_two_segments_with_a_scenario_area_are_checked() -> None:
    """AIE-1198, US2.5: scenario seed areas are known areas."""
    seed = SeedFile("user", "gardening", "beds", "- [stated] x\n", "Beds", ())
    scenario = _scenario(IndexReadFirst("i"), seeds=(seed,))
    assert _paths("see user/gardening", scenario=scenario) == _flag("user/gardening")


def test_reply_path_two_segments_with_a_third_segment_area_are_checked() -> None:
    """AIE-1198, US2.5: the 3rd segment of a known location is a known area."""
    trace = [_wrote("user/u-ada/hobbies/chess.md")]
    assert _paths("see user/hobbies", trace) == _flag("user/hobbies", "entity_omitted")


def test_reply_path_echo_of_the_users_text_is_skipped() -> None:
    """AIE-1198, US2.5: a token the user typed this session is not flagged."""
    assert _paths(f"Yes, {NOTE} it is", user=f"please use {NOTE}") == ()


def test_reply_path_user_text_from_a_later_turn_does_not_exempt() -> None:
    """AIE-1198, US2.5: only turn <= t user text exempts."""
    transcript = (
        TranscriptTurn(1, 1, "hello", f"Saved {NOTE}", None),
        TranscriptTurn(1, 2, f"is {NOTE} there?", "yes", None),
    )
    assert find_unmatched_reply_paths(_scenario(IndexReadFirst("i")), (), transcript) == (
        UnmatchedReplyPath(1, 1, NOTE, "unmatched"),
    )


def test_reply_path_user_text_from_another_session_does_not_exempt() -> None:
    """AIE-1198, US2.5: the echo exemption is per session."""
    transcript = (
        TranscriptTurn(1, 1, f"use {NOTE}", "ok", None),
        TranscriptTurn(2, 1, "hello", f"Saved {NOTE}", None),
    )
    scenario = _scenario(IndexReadFirst("i"), sessions=2)
    assert find_unmatched_reply_paths(scenario, (), transcript) == (
        UnmatchedReplyPath(2, 1, NOTE, "unmatched"),
    )


def test_reply_path_echo_from_an_earlier_turn_of_the_session_exempts() -> None:
    """AIE-1198, US2.5: user text from turn <= t in the same session exempts."""
    transcript = (
        TranscriptTurn(1, 1, f"use {NOTE}", "ok", None),
        TranscriptTurn(1, 2, "again", f"Saved {NOTE}", None),
    )
    assert find_unmatched_reply_paths(_scenario(IndexReadFirst("i")), (), transcript) == ()


def test_reply_path_custom_root_from_an_identity_grant_is_checked() -> None:
    """AIE-1198, US2.1: grant keys of the scenario identity are roots; others are not."""
    identity = Identity(
        grants={
            "user": ScopeGrant("u-ada", "owner"),
            "team": ScopeGrant("t-core", "member"),
        }
    )
    custom = replace(_scenario(IndexReadFirst("i")), identity=identity)
    reply = "see team/t-core/notes/a.md"
    assert _paths(reply, scenario=custom) == _flag("team/t-core/notes/a.md")
    assert _paths(reply) == ()


def test_reply_path_roots_are_case_sensitive() -> None:
    """AIE-1198, US2.1: User/u-ada/notes/a.md has no root."""
    assert _paths("see User/u-ada/notes/a.md") == ()


def test_reply_path_duplicate_token_is_reported_once() -> None:
    """AIE-1198, US2.5: one result per distinct token per reply."""
    assert _paths(f"{NOTE} and again `{NOTE}`.") == _flag(NOTE)


def test_reply_path_output_order_follows_replies_then_first_appearance() -> None:
    """AIE-1198, US2.5: transcript order, then first appearance within a reply."""
    b, c, d = "user/u-ada/notes/b.md", "user/u-ada/notes/c.md", "user/u-ada/notes/d.md"
    transcript = (
        TranscriptTurn(1, 2, "x", f"{d} then {b}", None),
        TranscriptTurn(1, 1, "y", f"{c}", None),
    )
    assert find_unmatched_reply_paths(_scenario(IndexReadFirst("i")), (), transcript) == (
        UnmatchedReplyPath(1, 2, d, "unmatched"),
        UnmatchedReplyPath(1, 2, b, "unmatched"),
        UnmatchedReplyPath(1, 1, c, "unmatched"),
    )


def test_reply_path_empty_transcript_gives_no_results() -> None:
    """AIE-1198, US2.5: nothing to check."""
    assert find_unmatched_reply_paths(_scenario(IndexReadFirst("i")), (), ()) == ()
