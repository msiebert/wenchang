"""Run planning, trial grading, the per-run report, and the CLI (AIE-1170, US5)."""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import evals.agent
from evals.__main__ import main
from evals.graders import (
    GradeInputError,
    StoredFile,
    StoreDump,
    TraceCall,
    TranscriptTurn,
    store_dump_to_json,
    trace_to_json,
    transcript_to_json,
)
from evals.report import (
    build_report,
    grade_trial,
    merge_runs,
    new_run,
    parse_shard,
    shard_scenarios,
    turn_prompt,
)
from evals.scenario import Scenario, load_scenario

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 9, 12, 30, 5, tzinfo=UTC)

SCENARIO = """\
id: {id}
title: {id}
category: privacy
source: AIE-1170
sessions:
  - turns: ["first", "second"]
  - turns: ["third"]
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


def _scenarios(tmp_path: Path, *ids: str) -> tuple[Path, list[Scenario]]:
    directory = tmp_path / "scenarios"
    directory.mkdir(exist_ok=True)
    loaded: list[Scenario] = []
    for ident in ids:
        path = directory / f"{ident}.yaml"
        path.write_text(SCENARIO.format(id=ident))
        loaded.append(load_scenario(path))
    return directory, loaded


def _call(seq: int, tool: str, session: int, **arguments: object) -> TraceCall:
    return TraceCall(
        seq=seq,
        request_id=str(seq),
        duration_s=0.001,
        started_ms=float(seq * 10),
        completed_ms=float(seq * 10 + 1),
        session=session,
        turn=1,
        tool=tool,
        arguments=arguments,
        result={},
        is_error=False,
    )


def _dump(trial_dir: Path, *, leak: bool) -> None:
    content = "- [stated] the secret\n" if leak else "- [stated] fine\n"
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
                ("reference-agent",),
                "3",
            ),
        )
    )
    trace = [_call(1, "get_memory_index", 1), _call(2, "get_memory_index", 2)]
    (trial_dir / "store.json").write_text(json.dumps(store_dump_to_json(store)))
    (trial_dir / "trace.json").write_text(json.dumps(trace_to_json(trace)))


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def test_new_run_writes_metadata_and_plan(tmp_path: Path) -> None:
    """new_run writes run.json and one trial.json per trial and returns the
    plan (AIE-1170, US5.1).
    """
    _, scenarios = _scenarios(tmp_path, "alpha", "beta")

    run_dir, plan = new_run(
        scenarios, model="sonnet", trials=2, runs_dir=tmp_path / "runs", now=NOW
    )

    assert run_dir == tmp_path / "runs" / "20261009-123005-sonnet"
    meta = _json(run_dir / "run.json")
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
    assert meta == {
        "run_id": "20261009-123005-sonnet",
        "created": "2026-10-09T12:30:05+00:00",
        "model": "sonnet",
        "trials": 2,
        "scenarios": ["alpha", "beta"],
        "git_commit": head,
        "agent_sha256": hashlib.sha256(evals.agent.AGENT_PATH.read_bytes()).hexdigest(),
    }
    for ident in ("alpha", "beta"):
        for k in (1, 2):
            trial = _json(run_dir / ident / f"trial-{k}" / "trial.json")
            assert trial == {
                "scenario": ident,
                "scenario_path": str(tmp_path / "scenarios" / f"{ident}.yaml"),
                "trial": k,
            }
    assert plan["run_dir"] == str(run_dir)
    assert plan["model"] == "sonnet"
    assert [(t["scenario"], t["trial"]) for t in plan["trials"]] == [
        ("alpha", 1),
        ("alpha", 2),
        ("beta", 1),
        ("beta", 2),
    ]
    first = plan["trials"][0]
    assert first["trial_dir"] == str(run_dir / "alpha" / "trial-1")
    assert first["scenario_path"] == str(tmp_path / "scenarios" / "alpha.yaml")
    assert first["sessions"] == [["first", "second"], ["third"]]


def test_new_run_cli_prints_the_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The new-run command prints the plan as JSON; no ids means every
    scenario (AIE-1170, US5.1).
    """
    directory, _ = _scenarios(tmp_path, "alpha", "beta")
    code = main(
        [
            "new-run",
            "--model",
            "claude-sonnet-5-5",
            "--trials",
            "1",
            "--scenarios-dir",
            str(directory),
            "--runs-dir",
            str(tmp_path / "runs"),
        ]
    )
    assert code == 0
    plan = json.loads(capsys.readouterr().out)
    assert [t["scenario"] for t in plan["trials"]] == ["alpha", "beta"]
    assert Path(plan["run_dir"]).name.endswith("-claude-sonnet-5-5")


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["--model", "sonnet", "gamma"], "gamma"),
        (["--model", "gpt-5"], "gpt-5"),
    ],
)
def test_new_run_rejects_unknown_ids_and_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str], needle: str
) -> None:
    """An unknown scenario id or model exits 2 and creates nothing (AIE-1170, US5.2)."""
    directory, _ = _scenarios(tmp_path, "alpha")
    runs = tmp_path / "runs"

    code = main(["new-run", "--scenarios-dir", str(directory), "--runs-dir", str(runs), *args])

    assert code == 2
    assert needle in capsys.readouterr().err
    assert not runs.exists()


def test_grade_writes_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """grade writes grade.json and prints each result, exiting 0 even when an
    assertion fails (AIE-1170, US5.3).
    """
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    trial = run_dir / "alpha" / "trial-1"
    _dump(trial, leak=True)

    assert main(["grade", str(trial)]) == 0

    graded = _json(trial / "grade.json")
    assert graded["scenario"] == "alpha"
    assert graded["trial"] == 1
    assert graded["passed"] is False
    assert [(r["id"], r["kind"], r["passed"]) for r in graded["results"]] == [
        ("index-first", "index_read_first", True),
        ("no-secret", "no_content_matching", False),
    ]
    out = capsys.readouterr().out
    assert "PASS index-first" in out
    assert "FAIL no-secret" in out
    assert grade_trial(trial) == graded


def test_grade_rejects_missing_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """grade exits 2 when the dump is missing or malformed (AIE-1170, US5.3)."""
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    trial = run_dir / "alpha" / "trial-1"

    assert main(["grade", str(trial)]) == 2
    assert "store.json" in capsys.readouterr().err

    _dump(trial, leak=False)
    (trial / "trace.json").write_text("{}")
    assert main(["grade", str(trial)]) == 2
    assert "trace.json" in capsys.readouterr().err


def test_report_counts_passes_and_lists_unrun_trials(tmp_path: Path) -> None:
    """report grades dumped trials, counts passes per assertion over N, and
    lists never-dumped trials as not run (AIE-1170, US5.4).
    """
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=3, runs_dir=tmp_path / "runs", now=NOW)
    t1, t2 = run_dir / "alpha" / "trial-1", run_dir / "alpha" / "trial-2"
    _dump(t1, leak=False)
    grade_trial(t1)
    _dump(t2, leak=True)

    markdown, report = build_report(run_dir)

    assert (t2 / "grade.json").exists()
    assert (run_dir / "report.md").read_text() == markdown
    assert _json(run_dir / "report.json") == report
    assert report["run"]["run_id"] == "20261009-123005-sonnet"
    (alpha,) = report["scenarios"]
    assert alpha["id"] == "alpha"
    assert alpha["trials_run"] == 2
    assert alpha["trials_not_run"] == [3]
    assert alpha["passed_trials"] == 1
    assert alpha["pass_rate"] == 0.5
    assert alpha["assertions"] == [
        {"id": "index-first", "kind": "index_read_first", "passes": 2, "runs": 2},
        {"id": "no-secret", "kind": "no_content_matching", "passes": 1, "runs": 2},
    ]
    assert "20261009-123005-sonnet" in markdown
    assert "| no-secret | no_content_matching | 1/2 |" in markdown
    assert "not run: 3" in markdown


def test_report_keeps_judge_verdicts_separate(tmp_path: Path) -> None:
    """Valid judge verdicts get their own counts; invalid judge files are
    flagged and never counted (AIE-1170, US5.5).
    """
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=2, runs_dir=tmp_path / "runs", now=NOW)
    t1, t2 = run_dir / "alpha" / "trial-1", run_dir / "alpha" / "trial-2"
    for trial in (t1, t2):
        _dump(trial, leak=False)
    (t1 / "judge.json").write_text(
        json.dumps({"verdicts": [{"id": "polite", "verdict": "pass", "reason": "Thanked."}]})
    )
    (t2 / "judge.json").write_text(
        json.dumps({"verdicts": [{"id": "unknown", "verdict": "pass", "reason": "?"}]})
    )

    markdown, report = build_report(run_dir)

    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 2
    assert alpha["judge"] == [{"id": "polite", "passes": 1, "runs": 1}]
    assert alpha["invalid_judge_trials"] == [2]
    assert "| polite | 1/1 |" in markdown
    assert "invalid judge.json: 2" in markdown


def test_report_cli_prints_the_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The report command writes the report and prints its path (AIE-1170, US5.4)."""
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)

    assert main(["report", str(run_dir)]) == 0
    assert capsys.readouterr().out.strip() == str(run_dir / "report.md")


@pytest.mark.parametrize(
    ("target", "body"),
    [
        ("run.json", "not json"),
        ("run.json", '{"run_id": "x"}'),
        ("grade.json", "{}"),
        ("grade.json", '{"scenario": "alpha", "trial": 1, "passed": true, "results": [{}]}'),
    ],
)
def test_report_rejects_malformed_run_and_grade_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str, body: str
) -> None:
    """A malformed run.json or grade.json raises GradeInputError, and the
    report command exits 2 naming the file (AIE-1170, US5.4).
    """
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    trial = run_dir / "alpha" / "trial-1"
    _dump(trial, leak=False)
    path = run_dir / target if target == "run.json" else trial / target
    path.write_text(body)

    with pytest.raises(GradeInputError, match=target.replace(".", r"\.")):
        build_report(run_dir)
    assert main(["report", str(run_dir)]) == 2
    assert target in capsys.readouterr().err


def test_report_regrades_when_dumps_are_newer(tmp_path: Path) -> None:
    """A grade.json older than store.json or trace.json is regraded (AIE-1170, US5.4)."""
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    trial = run_dir / "alpha" / "trial-1"
    _dump(trial, leak=False)
    grade_trial(trial)
    _dump(trial, leak=True)
    stale = (trial / "grade.json").stat().st_mtime - 10
    os.utime(trial / "grade.json", (stale, stale))

    _, report = build_report(run_dir)

    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0
    assert _json(trial / "grade.json")["passed"] is False


def test_run_ids_do_not_collide(tmp_path: Path) -> None:
    """Two runs created in the same second get distinct directories (AIE-1170, US5.1)."""
    _, scenarios = _scenarios(tmp_path, "alpha")
    first, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    second, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)

    assert first != second
    assert second.name == "20261009-123005-sonnet-2"
    assert _json(second / "run.json")["run_id"] == second.name


def _transcript(trial_dir: Path, *turns: TranscriptTurn) -> None:
    (trial_dir / "transcript.json").write_text(json.dumps(transcript_to_json(turns)))


def _trial(tmp_path: Path) -> Path:
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW)
    return run_dir / "alpha" / "trial-1"


def _write_turns(trial_dir: Path, turns: list[str]) -> None:
    """Replace session 1's turns in the trial's scenario file."""
    path = Path(_json(trial_dir / "trial.json")["scenario_path"])
    old = '  - turns: ["first", "second"]'
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, f"  - turns: {json.dumps(turns)}"))


def test_turn_prompt_for_the_first_turn_is_the_bare_turn(tmp_path: Path) -> None:
    """Turn 1 of a session is sent as the scripted text alone (AIE-1170, US2.7)."""
    trial = _trial(tmp_path)
    _transcript(trial, TranscriptTurn(1, 1, "first", "reply one", "a1"))

    assert turn_prompt(trial, 1, 1) == "first"
    assert turn_prompt(trial, 2, 1) == "third"


def test_turn_prompt_replays_the_session_so_far(tmp_path: Path) -> None:
    """A later turn carries the session's earlier exchanges, verbatim and in
    order, then the new turn (AIE-1170, US2.7).
    """
    trial = _trial(tmp_path)
    _transcript(
        trial,
        TranscriptTurn(1, 1, "first", "reply one", "a1"),
        TranscriptTurn(1, 2, "second", "reply two\nwith a second line", "a2"),
    )
    _write_turns(trial, ["first", "second", "third turn"])

    assert turn_prompt(trial, 1, 3) == (
        "[Earlier in this conversation]\n"
        "User: first\n"
        "Assistant: reply one\n"
        "\n"
        "User: second\n"
        "Assistant: reply two\nwith a second line\n"
        "\n"
        "[Newest message]\n"
        "third turn"
    )


def test_turn_prompt_needs_the_earlier_replies(tmp_path: Path) -> None:
    """A later turn whose earlier replies are not recorded is an input error
    (AIE-1170, US2.7).
    """
    trial = _trial(tmp_path)
    _transcript(trial)

    with pytest.raises(GradeInputError, match="turn 1"):
        turn_prompt(trial, 1, 2)
    with pytest.raises(GradeInputError, match="session 3"):
        turn_prompt(trial, 3, 1)


def test_turn_prompt_cli_prints_the_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The turn-prompt command prints the prompt exactly, and exits 2 on bad
    input (AIE-1170, US2.7).
    """
    trial = _trial(tmp_path)
    _transcript(trial, TranscriptTurn(1, 1, "first", "reply one", "a1"))

    assert main(["turn-prompt", str(trial), "1", "2"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "[Earlier in this conversation]\nUser: first\nAssistant: reply one\n\n"
        "[Newest message]\nsecond\n"
    )
    assert main(["turn-prompt", str(trial), "1", "5"]) == 2


# --- Parallel shards ------------------------------------------------------------


def test_shards_partition_the_scenarios(tmp_path: Path) -> None:
    """Every scenario lands in exactly one of n shards, by sorted id
    (AIE-1170, parallel shards).
    """
    _, scenarios = _scenarios(tmp_path, "e", "a", "d", "b", "c")

    shards = [[x.id for x in shard_scenarios(scenarios, k, 3)] for k in (1, 2, 3)]

    assert shards == [["a", "d"], ["b", "e"], ["c"]]
    assert sorted(i for shard in shards for i in shard) == ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize("text", ["0/3", "4/3", "1/0", "x/3", "2", "-1/2", "1/2/3"])
def test_bad_shard_is_rejected(text: str) -> None:
    """A shard outside 1..n, or not in k/n form, is rejected (AIE-1170, parallel shards)."""
    with pytest.raises(ValueError, match="shard"):
        parse_shard(text)
    assert parse_shard("2/3") == (2, 3)


def test_shard_run_dir_is_named_and_recorded(tmp_path: Path) -> None:
    """A shard's run dir ends in -shard<k>of<n>, sibling shards in the same
    second do not collide, and run.json records the shard (AIE-1170, parallel shards).
    """
    _, scenarios = _scenarios(tmp_path, "alpha", "beta")
    runs = tmp_path / "runs"

    first, _ = new_run(
        scenarios[:1], model="sonnet", trials=1, runs_dir=runs, now=NOW, shard=(1, 2)
    )
    second, _ = new_run(
        scenarios[1:], model="sonnet", trials=1, runs_dir=runs, now=NOW, shard=(2, 2)
    )
    plain, _ = new_run(scenarios, model="sonnet", trials=1, runs_dir=runs, now=NOW)

    assert first.name == "20261009-123005-sonnet-shard1of2"
    assert second.name == "20261009-123005-sonnet-shard2of2"
    assert _json(first / "run.json")["shard"] == "1/2"
    assert "shard" not in _json(plain / "run.json")


def test_new_run_cli_shards(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """new-run --shard keeps only that shard's scenarios; a bad shard exits 2
    and creates nothing (AIE-1170, parallel shards).
    """
    directory, _ = _scenarios(tmp_path, "alpha", "beta", "gamma")
    runs = tmp_path / "runs"
    base = ["new-run", "--scenarios-dir", str(directory), "--runs-dir", str(runs)]

    assert main([*base, "--shard", "2/2"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [t["scenario"] for t in plan["trials"]] == ["beta"] * 3
    assert Path(plan["run_dir"]).name.endswith("-sonnet-shard2of2")

    assert main([*base, "--shard", "3/2"]) == 2
    assert "shard" in capsys.readouterr().err
    assert main([*base, "--shard", "2/5", "alpha"]) == 2
    assert "no scenarios" in capsys.readouterr().err
    assert len(list(runs.iterdir())) == 1


def _sharded_runs(tmp_path: Path) -> list[Path]:
    _, scenarios = _scenarios(tmp_path, "alpha", "beta")
    runs = tmp_path / "runs"
    dirs: list[Path] = []
    for k in (1, 2):
        run_dir, _ = new_run(
            shard_scenarios(scenarios, k, 2),
            model="sonnet",
            trials=2,
            runs_dir=runs,
            now=NOW,
            shard=(k, 2),
        )
        for trial in sorted(run_dir.glob("*/trial-*")):
            _dump(trial, leak=k == 2)
        dirs.append(run_dir)
    return dirs


def test_merge_runs_reports_every_scenario(tmp_path: Path) -> None:
    """Merging two shard runs copies their trials and writes one report with
    every scenario (AIE-1170, parallel shards).
    """
    shard_dirs = _sharded_runs(tmp_path)
    out = tmp_path / "merged"

    markdown, report = merge_runs(out, shard_dirs)

    meta = _json(out / "run.json")
    assert meta["run_id"] == "merged"
    assert meta["scenarios"] == ["alpha", "beta"]
    assert meta["sources"] == [str(d) for d in shard_dirs]
    assert (meta["model"], meta["trials"]) == ("sonnet", 2)
    assert [s["id"] for s in report["scenarios"]] == ["alpha", "beta"]
    by_id = {s["id"]: s for s in report["scenarios"]}
    assert (by_id["alpha"]["passed_trials"], by_id["alpha"]["trials_run"]) == (2, 2)
    assert (by_id["beta"]["passed_trials"], by_id["beta"]["trials_run"]) == (0, 2)
    assert (out / "report.md").read_text() == markdown
    assert (out / "alpha" / "trial-2" / "grade.json").exists()
    for d in shard_dirs:
        assert not (d / "report.md").exists()


@pytest.mark.parametrize("field", ["git_commit", "agent_sha256", "model", "trials"])
def test_merge_runs_rejects_mismatched_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str
) -> None:
    """Runs from different commits, agent files, models, or trial counts do not
    merge; the CLI exits 2 and writes nothing (AIE-1170, parallel shards).
    """
    shard_dirs = _sharded_runs(tmp_path)
    meta = _json(shard_dirs[1] / "run.json")
    meta[field] = 7 if field == "trials" else "different"
    (shard_dirs[1] / "run.json").write_text(json.dumps(meta))
    out = tmp_path / "merged"

    with pytest.raises(GradeInputError, match=field):
        merge_runs(out, shard_dirs)
    assert main(["merge-runs", str(out), *map(str, shard_dirs)]) == 2
    assert field in capsys.readouterr().err
    assert not out.exists()


def test_merge_runs_rejects_overlap_and_existing_output(tmp_path: Path) -> None:
    """A scenario in two inputs, or an output dir that already exists, is an
    error (AIE-1170, parallel shards).
    """
    shard_dirs = _sharded_runs(tmp_path)
    with pytest.raises(GradeInputError, match="alpha"):
        merge_runs(tmp_path / "dup", [shard_dirs[0], shard_dirs[0]])
    existing = tmp_path / "exists"
    existing.mkdir()
    with pytest.raises(GradeInputError, match="exists"):
        merge_runs(existing, shard_dirs)
