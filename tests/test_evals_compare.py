"""Comparing eval runs across arms (AIE-1384, AC10)."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from evals.__main__ import main
from evals.compare import ArmMetrics, compare_runs, compute_metrics
from evals.graders import (
    GradeInputError,
    StoredFile,
    StoreDump,
    TraceCall,
    store_dump_to_json,
    trace_to_json,
)

pytestmark = pytest.mark.unit

SCENARIO = """\
id: {id}
title: {id}
category: privacy
source: AIE-1384
seed:
  - scope: user
    area: notes
    name: n
    content: |
      - [stated] seeded fact
    description: Notes
    aliases: []
sessions:
  - turns: ["one"]
  - turns: ["two"]
  - turns: ["three"]
assertions:
  - kind: index_read_first
    id: index-first
  - kind: no_content_matching
    id: no-secret
    pattern: secret
judge:
  - id: polite
    rubric: The agent is polite.
"""


def _scenario(tmp_path: Path, ident: str) -> Path:
    directory = tmp_path / "scenarios"
    directory.mkdir(exist_ok=True)
    path = directory / f"{ident}.yaml"
    path.write_text(SCENARIO.format(id=ident))
    return path


def _calls(sessions: Sequence[Sequence[str]]) -> list[TraceCall]:
    calls: list[TraceCall] = []
    for session, tools in enumerate(sessions, start=1):
        for tool in tools:
            seq = len(calls) + 1
            calls.append(
                TraceCall(
                    seq=seq,
                    request_id=str(seq),
                    duration_s=0.001,
                    started_ms=float(seq * 10),
                    completed_ms=float(seq * 10 + 1),
                    session=session,
                    turn=1,
                    tool=tool,
                    arguments={},
                    result={},
                    is_error=False,
                )
            )
    return calls


def _make_run(
    tmp_path: Path,
    name: str,
    *,
    arm: dict[str, object] | None,
    sessions: Sequence[Sequence[str]],
    added_lines: Sequence[str],
    index_first_passed: bool,
    assertions_passed: int,
    judge: bool | None,
    scenario_ids: Sequence[str] = ("alpha",),
    model: str = "sonnet",
) -> Path:
    run_dir = tmp_path / "runs" / name
    run_dir.mkdir(parents=True)
    meta: dict[str, object] = {
        "run_id": name,
        "created": "2026-11-13T00:00:00+00:00",
        "model": model,
        "trials": 1,
        "scenarios": list(scenario_ids),
        "git_commit": None,
        "agent_sha256": None,
    }
    if arm is not None:
        meta["arm"] = arm
    (run_dir / "run.json").write_text(json.dumps(meta))
    for ident in scenario_ids:
        trial_dir = run_dir / ident / "trial-1"
        trial_dir.mkdir(parents=True)
        (trial_dir / "trial.json").write_text(
            json.dumps(
                {
                    "scenario": ident,
                    "scenario_path": str(_scenario(tmp_path, ident)),
                    "trial": 1,
                }
            )
        )
        content = "- [stated] seeded fact\n" + "".join(f"{line}\n" for line in added_lines)
        store = StoreDump(
            (
                StoredFile(
                    "user/u-ada/notes/n.md",
                    "user",
                    "notes",
                    "n",
                    content,
                    "Notes",
                    (),
                    (),
                    "3",
                ),
            )
        )
        (trial_dir / "store.json").write_text(json.dumps(store_dump_to_json(store)))
        (trial_dir / "trace.json").write_text(json.dumps(trace_to_json(_calls(sessions))))
        if judge is not None:
            verdict = {"id": "polite", "verdict": "pass" if judge else "fail", "reason": "r"}
            (trial_dir / "judge.json").write_text(json.dumps({"verdicts": [verdict]}))
        results = [
            {
                "id": "index-first",
                "kind": "index_read_first",
                "passed": index_first_passed,
                "detail": "",
            },
            {
                "id": "no-secret",
                "kind": "no_content_matching",
                "passed": assertions_passed == 2 or not index_first_passed,
                "detail": "",
            },
        ]
        (trial_dir / "grade.json").write_text(
            json.dumps(
                {
                    "scenario": ident,
                    "trial": 1,
                    "passed": all(r["passed"] for r in results),
                    "results": results,
                    "operator_identity": {"unchecked": True},
                }
            )
        )
    return run_dir


ADDED_A = ["- [stated] new one", "- unlabeled new", "  - [inferred] indented", "plain text"]
ADDED_B = [
    "- [stated] new one",
    "- [observed] two",
    "- [inferred] three",
    "- unlabeled",
    "- [system] skipped",
    "[stated] not a bullet",
]


@pytest.fixture
def default_run(tmp_path: Path) -> Path:
    """Default arm: session 1 index first, session 2 read_file first, session 3 silent."""
    return _make_run(
        tmp_path,
        "default",
        arm=None,
        sessions=[["get_memory_index", "read_file"], ["read_file", "get_memory_index"], []],
        added_lines=ADDED_A,
        index_first_passed=False,
        assertions_passed=2,
        judge=True,
    )


@pytest.fixture
def renamed_run(tmp_path: Path) -> Path:
    """Renamed arm: both calling sessions start with the index, session 3 silent."""
    return _make_run(
        tmp_path,
        "renamed",
        arm={"index_tool": "recall", "agent_prompt": False},
        sessions=[["get_memory_index"], ["get_memory_index", "read_file"], []],
        added_lines=ADDED_B,
        index_first_passed=True,
        assertions_passed=2,
        judge=False,
    )


def test_compute_metrics_counts_a_default_run(default_run: Path) -> None:
    """A run.json without an arm is the default arm; sessions, first calls,
    labels, and assertions are counted (AIE-1384, AC10).
    """
    metrics = compute_metrics(default_run)

    assert isinstance(metrics, ArmMetrics)
    assert metrics.run_dir == default_run
    assert (metrics.index_tool, metrics.agent_prompt) == ("get_memory_index", True)
    assert (metrics.model, metrics.trials, metrics.sessions) == ("sonnet", 1, 3)
    assert (metrics.first_call_index, metrics.no_memory_call) == (1, 1)
    assert (metrics.index_first_passes, metrics.index_first_total) == (0, 1)
    assert (metrics.assertion_passes, metrics.assertion_total) == (1, 2)
    assert (metrics.judge_passes, metrics.judge_total) == (1, 1)


def test_compute_metrics_counts_added_and_labeled_fact_lines(
    default_run: Path, renamed_run: Path
) -> None:
    """Seed lines, [system] lines, and non-bullet lines are not added fact
    lines; a bullet with a provenance label is labeled (AIE-1384, AC10).
    """
    default = compute_metrics(default_run)
    renamed = compute_metrics(renamed_run)

    assert (default.added_fact_lines, default.labeled_fact_lines) == (3, 2)
    assert (renamed.added_fact_lines, renamed.labeled_fact_lines) == (4, 3)


def test_compute_metrics_reads_the_recorded_arm(renamed_run: Path) -> None:
    """The recorded arm is reported, and the canonical trace name counts as
    the index call (AIE-1384, AC10).
    """
    metrics = compute_metrics(renamed_run)

    assert (metrics.index_tool, metrics.agent_prompt) == ("recall", False)
    assert (metrics.first_call_index, metrics.no_memory_call) == (2, 1)
    assert (metrics.index_first_passes, metrics.index_first_total) == (1, 1)
    assert (metrics.judge_passes, metrics.judge_total) == (0, 1)


def test_compute_metrics_unjudged_run_has_zero_judge_counts(tmp_path: Path) -> None:
    """An unjudged run has judge_passes and judge_total of 0 (AIE-1384, AC10)."""
    run = _make_run(
        tmp_path,
        "unjudged",
        arm=None,
        sessions=[["get_memory_index"], [], []],
        added_lines=[],
        index_first_passed=True,
        assertions_passed=2,
        judge=None,
    )

    metrics = compute_metrics(run)

    assert (metrics.judge_passes, metrics.judge_total) == (0, 0)
    assert (metrics.added_fact_lines, metrics.labeled_fact_lines) == (0, 0)


def test_compare_table_has_a_row_per_run_with_rates(default_run: Path, renamed_run: Path) -> None:
    """One row per run with index tool, prompt state, model, and rates as
    percentages with k/n (AIE-1384, AC10).
    """
    markdown = compare_runs([default_run, renamed_run])

    rows = [line for line in markdown.splitlines() if line.startswith("|")]
    default_row = next(r for r in rows if "get_memory_index" in r)
    renamed_row = next(r for r in rows if "recall" in r)
    assert "sonnet" in default_row
    assert "1/3" in default_row
    assert "33.3%" in default_row
    assert "2/3" in renamed_row
    assert "66.7%" in renamed_row
    assert "100.0%" in renamed_row
    assert "0.0%" in default_row


def test_compare_shows_deltas_from_the_first_run(default_run: Path, renamed_run: Path) -> None:
    """Rows other than the baseline show signed percentage-point deltas
    (AIE-1384, AC10).
    """
    markdown = compare_runs([default_run, renamed_run])

    renamed_row = next(line for line in markdown.splitlines() if "recall" in line)
    default_row = next(line for line in markdown.splitlines() if "get_memory_index" in line)
    assert "+33.3" in renamed_row
    assert "+100.0" in renamed_row
    assert "+50.0" in renamed_row
    assert "-100.0" in renamed_row
    assert "+33.3" not in default_row


def test_compare_baseline_option_changes_the_reference(
    default_run: Path, renamed_run: Path
) -> None:
    """--baseline makes that run the reference, so the other row's deltas flip
    sign (AIE-1384, AC10).
    """
    markdown = compare_runs([default_run, renamed_run], baseline=renamed_run)

    default_row = next(line for line in markdown.splitlines() if "get_memory_index" in line)
    renamed_row = next(line for line in markdown.splitlines() if "recall" in line)
    assert "-33.3" in default_row
    assert "-100.0" in default_row
    assert "+100.0" in default_row
    assert "+33.3" not in renamed_row


def test_compare_zero_denominator_rate_is_n_a_without_delta(
    tmp_path: Path, default_run: Path
) -> None:
    """An unjudged run shows n/a for the judge rate and no delta for it
    (AIE-1384, AC10).
    """
    unjudged = _make_run(
        tmp_path,
        "unjudged",
        arm={"index_tool": "recall", "agent_prompt": False},
        sessions=[["get_memory_index"], [], []],
        added_lines=[],
        index_first_passed=True,
        assertions_passed=2,
        judge=None,
    )

    markdown = compare_runs([default_run, unjudged])

    row = next(line for line in markdown.splitlines() if "recall" in line)
    assert "n/a" in row
    assert "-100.0" not in row


def test_compare_rejects_different_scenario_sets(tmp_path: Path, default_run: Path) -> None:
    """Runs covering different scenarios cannot be compared (AIE-1384, AC10)."""
    other = _make_run(
        tmp_path,
        "other",
        arm=None,
        sessions=[["get_memory_index"], [], []],
        added_lines=[],
        index_first_passed=True,
        assertions_passed=2,
        judge=None,
        scenario_ids=("beta",),
    )

    with pytest.raises(GradeInputError):
        compare_runs([default_run, other])


def test_compute_metrics_rejects_a_missing_run(tmp_path: Path) -> None:
    """A directory without run.json is bad input (AIE-1384, AC10)."""
    with pytest.raises(GradeInputError):
        compute_metrics(tmp_path / "nowhere")


def test_compare_cli_writes_the_markdown(
    tmp_path: Path, default_run: Path, renamed_run: Path
) -> None:
    """The compare command writes OUT_FILE and exits 0 (AIE-1384, AC10)."""
    out = tmp_path / "compare.md"

    code = main(["compare", str(out), str(default_run), str(renamed_run)])

    assert code == 0
    assert out.read_text() == compare_runs([default_run, renamed_run])


def test_compare_cli_baseline_flag(tmp_path: Path, default_run: Path, renamed_run: Path) -> None:
    """--baseline selects the reference run (AIE-1384, AC10)."""
    out = tmp_path / "compare.md"

    code = main(
        ["compare", str(out), str(default_run), str(renamed_run), "--baseline", str(renamed_run)]
    )

    assert code == 0
    assert out.read_text() == compare_runs([default_run, renamed_run], baseline=renamed_run)


def test_compare_cli_exits_2_on_different_scenario_sets(tmp_path: Path, default_run: Path) -> None:
    """Differing scenario sets exit 2 and write nothing (AIE-1384, AC10)."""
    other = _make_run(
        tmp_path,
        "other",
        arm=None,
        sessions=[["get_memory_index"], [], []],
        added_lines=[],
        index_first_passed=True,
        assertions_passed=2,
        judge=None,
        scenario_ids=("beta",),
    )
    out = tmp_path / "compare.md"

    assert main(["compare", str(out), str(default_run), str(other)]) == 2
    assert not out.exists()


def test_compare_cli_exits_2_on_a_missing_run(tmp_path: Path, default_run: Path) -> None:
    """A run dir that does not exist exits 2 (AIE-1384, AC10)."""
    out = tmp_path / "compare.md"

    assert main(["compare", str(out), str(default_run), str(tmp_path / "nowhere")]) == 2
