"""Run planning, trial grading, the per-run report, and the CLI (AIE-1170, US5)."""

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import evals.agent
import evals.report
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
from evals.identity import resolve_operator_identity
from evals.report import (
    _grade_is_current,  # pyright: ignore[reportPrivateUsage]
    build_report,
    grade_trial,
    merge_runs,
    new_run,
    parse_shard,
    shard_scenarios,
    turn_prompt,
    uses_reply_kinds,
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


# --- reply check in grade.json and the report (AIE-1184, US2) -----------------

SECOND_PERSON = "You asked me to remember that. Saved."
THIRD_PERSON = "I haven't saved anything yet. The user asked me to remember that."


def _reply_transcript(trial_dir: Path, reply: str) -> None:
    turns = [
        TranscriptTurn(1, 1, "first", reply, "a1"),
        TranscriptTurn(1, 2, "second", "Done.", "a2"),
        TranscriptTurn(2, 1, "third", "Done.", "a3"),
    ]
    (trial_dir / "transcript.json").write_text(json.dumps(transcript_to_json(turns)))


def _reply_trial(tmp_path: Path, trials: int = 1) -> tuple[Path, list[Path]]:
    _, scenarios = _scenarios(tmp_path, "alpha")
    run_dir, _ = new_run(
        scenarios, model="sonnet", trials=trials, runs_dir=tmp_path / "runs", now=NOW
    )
    return run_dir, [run_dir / "alpha" / f"trial-{k}" for k in range(1, trials + 1)]


def _age(path: Path, seconds: float) -> None:
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))


def test_grade_records_third_person_replies(tmp_path: Path) -> None:
    """grade.json lists flagged replies and its results do not depend on them
    (AIE-1184, US2.2).
    """
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, SECOND_PERSON)
    clean = grade_trial(trial)
    _reply_transcript(trial, THIRD_PERSON)

    graded = grade_trial(trial)

    assert graded["third_person_replies"] == [{"session": 1, "turn": 1, "phrase": "the user asked"}]
    assert _json(trial / "grade.json") == graded
    assert (graded["results"], graded["passed"]) == (clean["results"], clean["passed"])


def test_grade_records_an_empty_reply_check(tmp_path: Path) -> None:
    """A clean transcript gives an empty list (AIE-1184, US2.3)."""
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, SECOND_PERSON)

    assert grade_trial(trial)["third_person_replies"] == []


def test_grade_without_a_transcript_has_no_reply_check(tmp_path: Path) -> None:
    """With no transcript.json the reply check keys are absent (AIE-1184, US2.4)."""
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)

    graded = grade_trial(trial)

    assert "third_person_replies" not in graded
    assert "transcript_error" not in graded
    assert graded["passed"] is True


def test_malformed_transcript_never_blocks_grading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A malformed transcript is recorded as an error and grading goes on
    (AIE-1184, US2.5).
    """
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=True)
    (trial / "transcript.json").write_text("not json")

    assert main(["grade", str(trial)]) == 0

    graded = _json(trial / "grade.json")
    assert "third_person_replies" not in graded
    assert "transcript.json" in graded["transcript_error"]
    assert graded["passed"] is False
    assert [r["passed"] for r in graded["results"]] == [True, False]
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == f"TRANSCRIPT ERROR: {graded['transcript_error']}"


def test_grade_cli_prints_third_person_replies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The grade command prints one line per flagged reply (AIE-1184, US2.6)."""
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, THIRD_PERSON)

    assert main(["grade", str(trial)]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["PASS index-first: ok", "PASS no-secret: ok"]
    assert lines[2:] == ["THIRD-PERSON session 1 turn 1: the user asked"]


def test_report_adds_the_reply_check_without_regrading(tmp_path: Path) -> None:
    """A current grade.json without the reply check gains it and keeps its
    results, even when a fresh grade would differ (AIE-1184, US2.7).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, THIRD_PERSON)
    stale_results = [
        {"id": "index-first", "kind": "index_read_first", "passed": False, "detail": "old"},
        {"id": "no-secret", "kind": "no_content_matching", "passed": False, "detail": "old"},
    ]
    old = {"scenario": "alpha", "trial": 1, "results": stale_results, "passed": False}
    (trial / "grade.json").write_text(json.dumps(old))

    _, report = build_report(run_dir)

    graded = _json(trial / "grade.json")
    assert graded["results"] == stale_results
    assert graded["passed"] is False
    assert graded["third_person_replies"] == [{"session": 1, "turn": 1, "phrase": "the user asked"}]
    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0


def test_report_rechecks_replies_when_the_transcript_is_newer(tmp_path: Path) -> None:
    """A transcript newer than grade.json refreshes only the reply check
    (AIE-1184, US2.8).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, SECOND_PERSON)
    graded = grade_trial(trial)
    graded["results"][0]["detail"] = "kept"
    (trial / "grade.json").write_text(json.dumps(graded))
    _age(trial / "store.json", 20)
    _age(trial / "trace.json", 20)
    _age(trial / "grade.json", 10)
    _reply_transcript(trial, THIRD_PERSON)

    build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert refreshed["results"] == graded["results"]
    assert refreshed["results"][0]["detail"] == "kept"
    assert refreshed["passed"] == graded["passed"]
    assert refreshed["third_person_replies"] == [
        {"session": 1, "turn": 1, "phrase": "the user asked"}
    ]


def test_report_fully_regrades_when_dumps_are_newer(tmp_path: Path) -> None:
    """A grade.json older than the dumps is regraded, reply check included
    (AIE-1184, US2.9).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    grade_trial(trial)
    _age(trial / "grade.json", 10)
    _dump(trial, leak=True)
    _reply_transcript(trial, THIRD_PERSON)

    build_report(run_dir)

    graded = _json(trial / "grade.json")
    assert graded["passed"] is False
    assert graded["third_person_replies"] == [{"session": 1, "turn": 1, "phrase": "the user asked"}]


TWO_JUDGE_SCENARIO = (
    SCENARIO
    + """  - id: kind
    rubric: The agent is kind.
"""
)


def _judge(trial_dir: Path, verdict: str) -> None:
    (trial_dir / "judge.json").write_text(
        json.dumps({"verdicts": [{"id": "polite", "verdict": verdict, "reason": "r"}]})
    )


def _addressee_run(tmp_path: Path) -> Path:
    directory = tmp_path / "scenarios"
    directory.mkdir()
    path = directory / "alpha.yaml"
    path.write_text(TWO_JUDGE_SCENARIO.format(id="alpha"))
    run_dir, _ = new_run(
        [load_scenario(path)], model="sonnet", trials=3, runs_dir=tmp_path / "runs", now=NOW
    )
    t1, t2, t3 = (run_dir / "alpha" / f"trial-{k}" for k in (1, 2, 3))
    for trial in (t1, t2, t3):
        _dump(trial, leak=False)
    _reply_transcript(t1, "The user said it is fine.")
    _reply_transcript(t2, SECOND_PERSON)
    _judge(t1, "fail")
    _judge(t2, "fail")
    return run_dir


def test_report_separates_third_person_trials(tmp_path: Path) -> None:
    """The report lists flagged and unchecked trials and counts judge fails in
    flagged trials, leaving existing counts alone (AIE-1184, US2.10).
    """
    run_dir = _addressee_run(tmp_path)

    _, report = build_report(run_dir)

    (alpha,) = report["scenarios"]
    assert alpha["third_person_trials"] == [
        {"trial": 1, "replies": [{"session": 1, "turn": 1, "phrase": "the user said"}]}
    ]
    assert alpha["addressee_unchecked_trials"] == [3]
    assert alpha["judge_third_person_fails"] == [{"id": "polite", "fails": 1}]
    assert alpha["judge"] == [{"id": "polite", "passes": 0, "runs": 2}]
    assert (alpha["passed_trials"], alpha["pass_rate"]) == (3, 1.0)
    assert [a["passes"] for a in alpha["assertions"]] == [3, 3]


def test_report_json_totals_third_person_trials(tmp_path: Path) -> None:
    """report.json totals flagged and checked trials (AIE-1184, US2.11)."""
    _, report = build_report(_addressee_run(tmp_path))

    assert report["third_person"] == {"flagged_trials": 1, "checked_trials": 2}


def test_report_markdown_shows_third_person_trials(tmp_path: Path) -> None:
    """report.md shows the totals, the flagged replies, and the judge split
    (AIE-1184, US2.12).
    """
    markdown, _ = build_report(_addressee_run(tmp_path))

    summary_end = markdown.index("| alpha |")
    assert markdown.index("Trials with a third-person reply: 1 of 2 checked.") > summary_end
    assert 'Third-person replies: trial 1 (session 1 turn 1: "the user said")' in markdown
    assert "Addressee not checked: 3" in markdown
    assert "| Judge item | Passes | Fails with a third-person reply |" in markdown
    assert "| polite | 0/2 | 1 |" in markdown


def test_report_markdown_omits_empty_addressee_lines(tmp_path: Path) -> None:
    """A scenario with no flagged or unchecked trials has neither line
    (AIE-1184, US2.13).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, SECOND_PERSON)

    markdown, _ = build_report(run_dir)

    assert "Third-person replies:" not in markdown
    assert "Addressee not checked" not in markdown
    assert "Trials with a third-person reply: 0 of 1 checked." in markdown


def test_merge_runs_sums_third_person_trials(tmp_path: Path) -> None:
    """Merged totals are the sums over the shards (AIE-1184, US2.14)."""
    shard_dirs = _sharded_runs(tmp_path)
    for k, run_dir in enumerate(shard_dirs):
        for trial in sorted(run_dir.glob("*/trial-*")):
            flagged = k == 0 or trial.name == "trial-1"
            _reply_transcript(trial, THIRD_PERSON if flagged else SECOND_PERSON)

    _, report = merge_runs(tmp_path / "merged", shard_dirs)

    assert report["third_person"] == {"flagged_trials": 3, "checked_trials": 4}


@pytest.mark.parametrize(
    "body",
    [b'{"turns": [\xff]}', b"[" * 100000 + b"]" * 100000],
    ids=["undecodable", "deeply-nested"],
)
def test_unreadable_transcript_never_blocks_grading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: bytes
) -> None:
    """Undecodable or deeply nested transcripts are recorded as errors and
    grading and reporting go on (AIE-1184, US2.5).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    (trial / "transcript.json").write_bytes(body)

    assert main(["grade", str(trial)]) == 0

    graded = _json(trial / "grade.json")
    assert "transcript.json" in graded["transcript_error"]
    assert "third_person_replies" not in graded
    assert graded["passed"] is True
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"TRANSCRIPT ERROR: {graded['transcript_error']}"
    )
    _, report = build_report(run_dir)
    (alpha,) = report["scenarios"]
    assert alpha["addressee_unchecked_trials"] == [1]


def test_report_drops_the_check_when_the_transcript_is_gone(tmp_path: Path) -> None:
    """A recorded check whose transcript was deleted is dropped, so the trial
    counts as unchecked (AIE-1184, US2.16).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, THIRD_PERSON)
    graded = grade_trial(trial)
    (trial / "transcript.json").unlink()

    _, report = build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert "third_person_replies" not in refreshed
    assert "transcript_error" not in refreshed
    assert (refreshed["results"], refreshed["passed"]) == (graded["results"], graded["passed"])
    (alpha,) = report["scenarios"]
    assert alpha["addressee_unchecked_trials"] == [1]
    assert alpha["third_person_trials"] == []


def test_report_leaves_a_current_check_alone(tmp_path: Path) -> None:
    """A current grade.json whose check is unchanged is recomputed but not
    rewritten (AIE-1184, US2.17; AIE-1199, US3.2).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, THIRD_PERSON)
    _age(trial / "store.json", 30)
    _age(trial / "trace.json", 30)
    _age(trial / "transcript.json", 30)
    graded = grade_trial(trial)
    _age(trial / "grade.json", 10)
    before = (trial / "grade.json").stat().st_mtime

    build_report(run_dir)

    assert (trial / "grade.json").stat().st_mtime == before
    assert _json(trial / "grade.json")["third_person_replies"] == graded["third_person_replies"]


# --- reply kinds in grading and the report (AIE-1185, US1) ----------------------

REPLY_SCENARIO = """\
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
  - kind: reply_not_matching
    id: no-banned
    pattern: banned
    session: 1
    turn: 1
  - kind: reply_matching
    id: says-done
    pattern: "(?i)done"
    session: 1
    turn: 2
"""


def _reply_scenario_trial(tmp_path: Path, template: str = REPLY_SCENARIO) -> tuple[Path, Path]:
    directory = tmp_path / "scenarios"
    directory.mkdir(exist_ok=True)
    path = directory / "alpha.yaml"
    path.write_text(template.format(id="alpha"))
    run_dir, _ = new_run(
        [load_scenario(path)], model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW
    )
    return run_dir, run_dir / "alpha" / "trial-1"


def _outcomes(graded: dict[str, Any]) -> dict[str, bool]:
    return {r["id"]: r["passed"] for r in graded["results"]}


def test_uses_reply_kinds(tmp_path: Path) -> None:
    """A scenario uses reply kinds when any assertion is one (AIE-1185, US1.6)."""
    directory = tmp_path / "scenarios"
    directory.mkdir()
    plain = directory / "plain.yaml"
    plain.write_text(SCENARIO.format(id="plain"))
    replying = directory / "replying.yaml"
    replying.write_text(REPLY_SCENARIO.format(id="replying"))

    assert uses_reply_kinds(load_scenario(plain)) is False
    assert uses_reply_kinds(load_scenario(replying)) is True


def test_grade_trial_without_a_transcript_fails_reply_kinds(tmp_path: Path) -> None:
    """A trial dir without transcript.json grades with an empty transcript, so
    reply kinds fail with "no reply recorded" (AIE-1185, US1.5).
    """
    _, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)

    graded = grade_trial(trial)

    assert _outcomes(graded) == {"index-first": True, "no-banned": False, "says-done": False}
    assert graded["passed"] is False
    assert all("no reply recorded" in r["detail"] for r in graded["results"][1:])
    assert "transcript_error" not in graded


def test_grade_trial_grades_replies_from_the_transcript(tmp_path: Path) -> None:
    """A valid transcript.json feeds the reply kinds and the third-person check
    (AIE-1185, US1.5).
    """
    _, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, "All fine.")

    clean = grade_trial(trial)
    _reply_transcript(trial, "That is banned. The user asked.")
    dirty = grade_trial(trial)

    assert _outcomes(clean) == {"index-first": True, "no-banned": True, "says-done": True}
    assert clean["passed"] is True
    assert _outcomes(dirty) == {"index-first": True, "no-banned": False, "says-done": True}
    assert dirty["passed"] is False
    assert dirty["third_person_replies"] == [{"session": 1, "turn": 1, "phrase": "the user asked"}]
    assert _json(trial / "grade.json") == dirty


def test_grade_trial_loads_the_transcript_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """grade_trial reads transcript.json one time for grade and the reply check
    (AIE-1185, US1.5).
    """
    _, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, "All fine.")
    loaded: list[Path] = []
    original = evals.report.load_transcript

    def counting(path: Path) -> tuple[TranscriptTurn, ...]:
        loaded.append(path)
        return original(path)

    monkeypatch.setattr(evals.report, "load_transcript", counting)

    grade_trial(trial)

    assert loaded == [trial / "transcript.json"]


def test_grade_trial_survives_a_malformed_transcript(tmp_path: Path) -> None:
    """A malformed transcript.json does not raise: transcript_error is recorded,
    reply kinds fail with "no reply recorded", other kinds grade normally
    (AIE-1185, US1.5).
    """
    _, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    (trial / "transcript.json").write_text("not json")

    graded = grade_trial(trial)

    assert "transcript.json" in graded["transcript_error"]
    assert _outcomes(graded) == {"index-first": True, "no-banned": False, "says-done": False}
    assert all("no reply recorded" in r["detail"] for r in graded["results"][1:])
    assert "third_person_replies" not in graded


def test_grade_trial_survives_an_undecodable_transcript(tmp_path: Path) -> None:
    """A transcript.json with invalid UTF-8 does not raise: transcript_error is
    recorded, the reply assertion fails, and a non-reply assertion still passes
    (AIE-1185, US1.5).
    """
    _, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    (trial / "transcript.json").write_bytes(b'{"turns": [\xff]}')

    graded = grade_trial(trial)

    assert "transcript.json" in graded["transcript_error"]
    assert _json(trial / "grade.json")["transcript_error"] == graded["transcript_error"]
    outcomes = _outcomes(graded)
    assert outcomes["says-done"] is False
    assert outcomes["index-first"] is True
    assert graded["passed"] is False


def test_report_fully_regrades_a_reply_scenario_when_the_transcript_is_newer(
    tmp_path: Path,
) -> None:
    """A transcript newer than grade.json regrades a reply-kind scenario in
    full, so results change (AIE-1185, US1.6).
    """
    run_dir, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, "All fine.")
    assert grade_trial(trial)["passed"] is True
    _age(trial / "store.json", 20)
    _age(trial / "trace.json", 20)
    _age(trial / "grade.json", 10)
    _reply_transcript(trial, "That is banned.")

    _, report = build_report(run_dir)

    assert _outcomes(_json(trial / "grade.json")) == {
        "index-first": True,
        "no-banned": False,
        "says-done": True,
    }
    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0
    assert {a["id"]: a["passes"] for a in alpha["assertions"]}["no-banned"] == 0


def test_report_fully_regrades_a_reply_scenario_when_the_transcript_is_gone(
    tmp_path: Path,
) -> None:
    """A reply-kind scenario whose transcript.json disappears after grading is
    regraded in full once, so reply assertions fail and the reply check is
    dropped, and later reports do not regrade again (AIE-1185, US1.6).
    """
    run_dir, trial = _reply_scenario_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, "All fine. The user asked.")
    assert grade_trial(trial)["passed"] is True
    assert "third_person_replies" in _json(trial / "grade.json")
    build_report(run_dir)
    assert _outcomes(_json(trial / "grade.json"))["says-done"] is True

    (trial / "transcript.json").unlink()
    _, report = build_report(run_dir)

    graded = _json(trial / "grade.json")
    assert _outcomes(graded) == {"index-first": True, "no-banned": False, "says-done": False}
    assert "third_person_replies" not in graded
    assert "transcript_error" not in graded
    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0
    assertion_passes = {a["id"]: a["passes"] for a in alpha["assertions"]}
    assert assertion_passes["says-done"] == 0
    assert assertion_passes["no-banned"] == 0

    _age(trial / "store.json", 20)
    _age(trial / "trace.json", 20)
    _age(trial / "grade.json", 10)
    before = (trial / "grade.json").stat().st_mtime
    build_report(run_dir)
    assert (trial / "grade.json").stat().st_mtime == before


def test_report_regrades_a_reply_scenario_whose_grade_lacks_the_reply_check(
    tmp_path: Path,
) -> None:
    """A reply-kind grade.json with a transcript but none of the reply-check
    keys is not current, and the report regrades it (AIE-1185, US1.6).
    """
    run_dir, trial = _reply_scenario_trial(tmp_path)
    scenario = load_scenario(tmp_path / "scenarios" / "alpha.yaml")
    _dump(trial, leak=False)
    _reply_transcript(trial, "All fine. The user asked.")
    graded = grade_trial(trial)
    assert "third_person_replies" in graded
    stripped = {k: v for k, v in _json(trial / "grade.json").items() if k != "third_person_replies"}
    stripped.pop("transcript_error", None)
    (trial / "grade.json").write_text(json.dumps(stripped))
    _age(trial / "store.json", 20)
    _age(trial / "trace.json", 20)
    _age(trial / "transcript.json", 20)

    assert _grade_is_current(trial, scenario) is False

    build_report(run_dir)

    assert "third_person_replies" in _json(trial / "grade.json")


def test_grade_is_current_watches_the_transcript_only_for_reply_scenarios(
    tmp_path: Path,
) -> None:
    """transcript.json joins the freshness set only for scenarios that use a
    reply kind (AIE-1185, US1.6).
    """
    directory = tmp_path / "scenarios"
    directory.mkdir()
    plain_path, replying_path = directory / "plain.yaml", directory / "replying.yaml"
    plain_path.write_text(SCENARIO.format(id="plain"))
    replying_path.write_text(REPLY_SCENARIO.format(id="replying"))
    plain, replying = load_scenario(plain_path), load_scenario(replying_path)
    run_dir, _ = new_run(
        [plain, replying], model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW
    )
    trials = {s.id: run_dir / s.id / "trial-1" for s in (plain, replying)}
    for scenario, trial in ((plain, trials["plain"]), (replying, trials["replying"])):
        _dump(trial, leak=False)
        _reply_transcript(trial, "Done.")
        grade_trial(trial)
        assert _grade_is_current(trial, scenario)
        _age(trial / "store.json", 20)
        _age(trial / "trace.json", 20)
        _age(trial / "grade.json", 10)
        _reply_transcript(trial, "Done again.")

    assert _grade_is_current(trials["plain"], plain) is True
    assert _grade_is_current(trials["replying"], replying) is False


# --- context records in turn_prompt (AIE-1185, US2) -----------------------------

CONTEXT_SCENARIO = (
    SCENARIO
    + """context_records:
  - system: event catalog
    content: "Purchase Completed: fires when the payment is authorized.\\n\\n"
  - system: query history
    content: "One churn query."
"""
)
ONE_RECORD = (
    "[From the product's event catalog]\nPurchase Completed: fires when the payment is authorized."
)
TWO_RECORDS = ONE_RECORD + "\n\n[From the product's query history]\nOne churn query."


def _context_trial(tmp_path: Path, records: int) -> Path:
    directory = tmp_path / "scenarios"
    directory.mkdir(exist_ok=True)
    path = directory / "alpha.yaml"
    text = CONTEXT_SCENARIO.format(id="alpha")
    if records == 1:
        text = text.split("  - system: query history")[0]
    path.write_text(text)
    run_dir, _ = new_run(
        [load_scenario(path)], model="sonnet", trials=1, runs_dir=tmp_path / "runs", now=NOW
    )
    trial = run_dir / "alpha" / "trial-1"
    _transcript(trial, TranscriptTurn(1, 1, "first", "reply one", "a1"))
    return trial


def test_turn_prompt_renders_one_context_record_before_turn_one(tmp_path: Path) -> None:
    """Turn 1 starts with the record block, a blank line, then the newest
    message; trailing newlines of the content are stripped (AIE-1185, US2.2).
    """
    trial = _context_trial(tmp_path, records=1)

    assert turn_prompt(trial, 1, 1) == f"{ONE_RECORD}\n\n[Newest message]\nfirst"
    assert turn_prompt(trial, 2, 1) == f"{ONE_RECORD}\n\n[Newest message]\nthird"


def test_turn_prompt_renders_two_context_records_separated_by_a_blank_line(
    tmp_path: Path,
) -> None:
    """Blocks are separated by a blank line and a blank line follows the last
    (AIE-1185, US2.2).
    """
    trial = _context_trial(tmp_path, records=2)

    assert turn_prompt(trial, 1, 1) == f"{TWO_RECORDS}\n\n[Newest message]\nfirst"


def test_turn_prompt_puts_context_records_before_the_replay(tmp_path: Path) -> None:
    """A later turn carries the context blocks first, then the unchanged
    earlier-conversation replay (AIE-1185, US2.2).
    """
    trial = _context_trial(tmp_path, records=2)

    assert turn_prompt(trial, 1, 2) == (
        f"{TWO_RECORDS}\n\n"
        "[Earlier in this conversation]\n"
        "User: first\n"
        "Assistant: reply one\n"
        "\n"
        "[Newest message]\n"
        "second"
    )


def test_turn_prompt_without_context_records_is_unchanged(tmp_path: Path) -> None:
    """Without context_records the prompt is byte-identical to the plain
    rendering (AIE-1185, US2.3).
    """
    trial = _trial(tmp_path)
    _transcript(trial, TranscriptTurn(1, 1, "first", "reply one", "a1"))

    assert turn_prompt(trial, 1, 1) == "first"
    assert turn_prompt(trial, 1, 2) == (
        "[Earlier in this conversation]\nUser: first\nAssistant: reply one\n\n"
        "[Newest message]\nsecond"
    )


def test_report_replaces_a_stale_check_of_a_current_grade(tmp_path: Path) -> None:
    """A current grade.json whose recorded check differs from the grader's
    fresh value gets the fresh value, keeping results and passed (AIE-1199, US3.1).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, SECOND_PERSON)
    graded = grade_trial(trial)
    graded["results"][0]["detail"] = "kept"
    graded["third_person_replies"] = [{"session": 1, "turn": 1, "phrase": "the user asked"}]
    (trial / "grade.json").write_text(json.dumps(graded))
    for name in ("store.json", "trace.json", "transcript.json"):
        _age(trial / name, 30)
    _age(trial / "grade.json", 10)

    _, report = build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert refreshed["third_person_replies"] == []
    assert refreshed["results"] == graded["results"]
    assert refreshed["passed"] == graded["passed"]
    (alpha,) = report["scenarios"]
    assert alpha["third_person_trials"] == []
    assert report["third_person"] == {"flagged_trials": 0, "checked_trials": 1}


def test_report_replaces_a_recorded_transcript_error_once_the_transcript_is_valid(
    tmp_path: Path,
) -> None:
    """A current grade.json that records a transcript_error gets the fresh
    third_person_replies and loses the error once transcript.json is valid
    (AIE-1199, US4.1 limits).
    """
    run_dir, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _reply_transcript(trial, THIRD_PERSON)
    graded = grade_trial(trial)
    graded.pop("third_person_replies", None)
    graded["transcript_error"] = "cannot read /old/path/transcript.json: no such file"
    (trial / "grade.json").write_text(json.dumps(graded))
    for name in ("store.json", "trace.json", "transcript.json"):
        _age(trial / name, 30)
    _age(trial / "grade.json", 10)

    build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert "transcript_error" not in refreshed
    assert refreshed["third_person_replies"] == [
        {"session": 1, "turn": 1, "phrase": "the user asked"}
    ]
    assert refreshed["results"] == graded["results"]
    assert refreshed["passed"] == graded["passed"]


# --- operator-identity check in grade.json and the report (AIE-1196, US1.8-1.10) --

LEAK_REPLY = "Thanks, Grace. Saved."
LEAK_LINE = "- [stated] Grace is out Monday.\n"
NAME_TEXTS = ("Grace", "Hopper", "ghopper")


def _store_content(trial_dir: Path, content: str) -> None:
    """Replace the dumped store with one file holding content."""
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
    (trial_dir / "store.json").write_text(json.dumps(store_dump_to_json(store)))


def _identity_trial(tmp_path: Path, reply: str = SECOND_PERSON, trials: int = 1) -> Path:
    run_dir, dirs = _reply_trial(tmp_path, trials)
    for trial in dirs:
        _dump(trial, leak=False)
        _reply_transcript(trial, reply)
    return run_dir


def _stale_current_grade(trial: Path, check: dict[str, Any] | None) -> dict[str, Any]:
    """Write a grade.json that is current for the dumps, with stale results."""
    for name in ("store.json", "trace.json", "transcript.json"):
        if (trial / name).exists():
            _age(trial / name, 30)
    graded: dict[str, Any] = {
        "scenario": "alpha",
        "trial": 1,
        "results": [
            {"id": "index-first", "kind": "index_read_first", "passed": True, "detail": "old"},
            {"id": "no-secret", "kind": "no_content_matching", "passed": True, "detail": "old"},
        ],
        "passed": True,
    }
    if check is not None:
        graded["operator_identity"] = check
    (trial / "grade.json").write_text(json.dumps(graded))
    _age(trial / "grade.json", 10)
    return graded


REPLY_HIT = {
    "where": "reply",
    "session": 1,
    "turn": 1,
    "path": "",
    "field": "",
    "token": "first-name",
}


def test_grade_records_a_clean_operator_identity_check(tmp_path: Path) -> None:
    """A clean trial records no hits, the contributing sources, and scanned
    replies (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()

    graded = grade_trial(trial)

    check = graded["operator_identity"]
    assert check["hits"] == []
    assert check["replies_scanned"] is True
    assert check["sources"][:3] == ["git user.name", "git user.email", "$USER"]
    assert "unchecked" not in check
    assert graded["passed"] is True
    assert _json(trial / "grade.json") == graded


def test_grade_records_a_reply_hit_and_fails_the_trial(tmp_path: Path) -> None:
    """A reply naming the operator is recorded by kind and location, fails
    `passed`, and leaves `results` unchanged (AIE-1196, US1.8).
    """
    (tmp_path / "clean").mkdir()
    (tmp_path / "leak").mkdir()
    clean_dir = _identity_trial(tmp_path / "clean")
    leak_dir = _identity_trial(tmp_path / "leak", LEAK_REPLY)
    clean = grade_trial(next((clean_dir / "alpha").iterdir()))
    trial = next((leak_dir / "alpha").iterdir())

    graded = grade_trial(trial)

    assert graded["operator_identity"]["hits"] == [REPLY_HIT]
    assert graded["passed"] is False
    assert graded["results"] == clean["results"]
    assert all(r["passed"] for r in graded["results"])


def test_grade_records_a_store_hit_and_fails_the_trial(tmp_path: Path) -> None:
    """A stored line naming the operator is a store hit with session and turn
    0 (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    _store_content(trial, LEAK_LINE)

    graded = grade_trial(trial)

    hits = graded["operator_identity"]["hits"]
    assert hits == [
        {
            "where": "store",
            "session": 0,
            "turn": 0,
            "path": "user/u-ada/notes/n.md",
            "field": "content",
            "token": "first-name",
        }
    ]
    assert graded["passed"] is False
    assert all(r["passed"] for r in graded["results"])


def test_grade_records_a_write_hit_for_a_removed_name(tmp_path: Path) -> None:
    """A name written and then removed from the store is a write hit
    (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    calls = [
        _call(1, "get_memory_index", 1),
        _call(2, "append_line", 1, line="- [stated] Grace likes tea."),
    ]
    (trial / "trace.json").write_text(json.dumps(trace_to_json(calls)))

    graded = grade_trial(trial)

    (hit,) = graded["operator_identity"]["hits"]
    assert (hit["where"], hit["session"], hit["turn"], hit["field"]) == ("write", 1, 1, "line")
    assert graded["passed"] is False


@pytest.mark.parametrize("target", ["grade.json", "report.json", "report.md"])
def test_recorded_files_never_carry_the_name(tmp_path: Path, target: str) -> None:
    """grade.json, report.json and report.md omit the matched text and every
    token (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path, "Thanks, Grace Hopper (ghopper)")
    (trial,) = (run_dir / "alpha").iterdir()
    _store_content(trial, LEAK_LINE)
    build_report(run_dir)

    path = trial / target if target == "grade.json" else run_dir / target
    text = path.read_text()

    assert path.exists()
    for name in NAME_TEXTS:
        assert name.lower() not in text.lower()


def test_hit_path_containing_a_token_is_redacted_in_grade_json(tmp_path: Path) -> None:
    """A store path that contains a token is written as "<redacted>"
    (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    store = StoreDump(
        (
            StoredFile(
                "user/u-ada/people/ghopper.md",
                "user",
                "people",
                "ghopper",
                LEAK_LINE,
                "Notes",
                (),
                ("reference-agent",),
                "3",
            ),
        )
    )
    (trial / "store.json").write_text(json.dumps(store_dump_to_json(store)))

    graded = grade_trial(trial)

    assert {h["path"] for h in graded["operator_identity"]["hits"]} == {"<redacted>"}
    assert "ghopper" not in (trial / "grade.json").read_text()


def test_missing_transcript_still_scans_the_store(tmp_path: Path) -> None:
    """Without transcript.json the check records replies_scanned false, keeps
    the key, and a store hit still fails the trial (AIE-1196, US1.8).
    """
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _store_content(trial, LEAK_LINE)

    graded = grade_trial(trial)

    check = graded["operator_identity"]
    assert check["replies_scanned"] is False
    assert [h["where"] for h in check["hits"]] == ["store"]
    assert graded["passed"] is False
    assert "third_person_replies" not in graded


def test_missing_transcript_without_a_hit_passes(tmp_path: Path) -> None:
    """A clean trial without a transcript records replies_scanned false and
    still passes (AIE-1196, US1.8).
    """
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)

    graded = grade_trial(trial)

    assert graded["operator_identity"]["replies_scanned"] is False
    assert graded["operator_identity"]["hits"] == []
    assert graded["passed"] is True


def test_malformed_transcript_still_scans_the_store(tmp_path: Path) -> None:
    """A malformed transcript.json records replies_scanned false next to the
    transcript error, and the store scan still runs (AIE-1196, US1.8).
    """
    _, (trial,) = _reply_trial(tmp_path)
    _dump(trial, leak=False)
    _store_content(trial, LEAK_LINE)
    (trial / "transcript.json").write_text("not json")

    graded = grade_trial(trial)

    assert "transcript.json" in graded["transcript_error"]
    assert graded["operator_identity"]["replies_scanned"] is False
    assert [h["where"] for h in graded["operator_identity"]["hits"]] == ["store"]
    assert graded["passed"] is False


def test_unchecked_identity_records_unchecked_and_does_not_fail(
    tmp_path: Path, set_identity: Any
) -> None:
    """With no resolvable identity the check is {"unchecked": true} and the
    trial is not failed (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)
    (trial,) = (run_dir / "alpha").iterdir()
    _store_content(trial, LEAK_LINE)
    set_identity()

    graded = grade_trial(trial)

    assert graded["operator_identity"] == {"unchecked": True}
    assert graded["passed"] is True


def test_grade_trial_uses_a_given_identity(tmp_path: Path, set_identity: Any) -> None:
    """grade_trial(trial_dir, identity=...) checks that identity instead of
    resolving one (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path, "Thanks, Priya. Saved.")
    (trial,) = (run_dir / "alpha").iterdir()
    set_identity(name="Priya Rao")
    other = resolve_operator_identity()
    set_identity(name="Grace Hopper", email="grace.hopper@example.com", user="ghopper")

    graded = grade_trial(trial, identity=other)

    assert graded["operator_identity"]["hits"] == [REPLY_HIT]
    assert graded["operator_identity"]["sources"] == ["git user.name"]
    assert grade_trial(trial)["operator_identity"]["hits"] == []


def test_grade_trial_resolves_the_identity_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an identity argument grade_trial runs the resolver's git calls
    once (AIE-1196, US1.8).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    real_run: Callable[..., Any] = subprocess.run
    counts = {"git": 0}

    def counting(args: Any, *a: Any, **kw: Any) -> Any:
        if args and args[0] == "git":
            counts["git"] += 1
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counting)
    resolve_operator_identity()
    baseline, counts["git"] = counts["git"], 0

    grade_trial(trial)

    assert baseline > 0
    assert counts["git"] == baseline


def test_report_resolves_the_identity_once_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_report runs the resolver's git calls once however many trials it
    grades (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, trials=3)
    real_run: Callable[..., Any] = subprocess.run
    counts = {"git": 0}

    def counting(args: Any, *a: Any, **kw: Any) -> Any:
        if args and args[0] == "git":
            counts["git"] += 1
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counting)
    resolve_operator_identity()
    baseline, counts["git"] = counts["git"], 0

    build_report(run_dir)

    assert baseline > 0
    assert counts["git"] == baseline


def test_build_report_uses_a_given_identity(tmp_path: Path, set_identity: Any) -> None:
    """build_report(run_dir, identity=...) checks that identity (AIE-1196, US1.10)."""
    run_dir = _identity_trial(tmp_path, "Thanks, Priya. Saved.")
    set_identity(name="Priya Rao")
    other = resolve_operator_identity()
    set_identity(name="Grace Hopper", email="grace.hopper@example.com", user="ghopper")

    _, report = build_report(run_dir, identity=other)

    assert report["operator_identity"]["flagged_trials"] == 1
    assert report["operator_identity"]["sources"] == ["git user.name"]


# --- schema ---


@pytest.mark.parametrize(
    "check",
    [
        "yes",
        [],
        {"hits": "none", "sources": [], "replies_scanned": True},
        {"hits": [], "sources": "git", "replies_scanned": True},
        {"hits": [], "sources": [1], "replies_scanned": True},
        {"hits": [], "sources": [], "replies_scanned": "yes"},
        {"hits": ["x"], "sources": [], "replies_scanned": True},
        {"hits": [{"where": "reply"}], "sources": [], "replies_scanned": True},
        {"hits": [{**REPLY_HIT, "session": "1"}], "sources": [], "replies_scanned": True},
        {"hits": [{**REPLY_HIT, "token": 3}], "sources": [], "replies_scanned": True},
        {"unchecked": "yes"},
        {"unchecked": False},
    ],
)
def test_report_rejects_a_malformed_operator_identity(tmp_path: Path, check: object) -> None:
    """A current grade.json whose operator_identity breaks the schema raises
    GradeInputError naming grade.json (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    _stale_current_grade(trial, check)  # type: ignore[arg-type]

    with pytest.raises(GradeInputError, match=r"grade\.json"):
        build_report(run_dir)


@pytest.mark.parametrize(
    "check",
    [
        {"hits": [], "sources": ["git user.name"], "replies_scanned": True},
        {"hits": [REPLY_HIT], "sources": [], "replies_scanned": False},
        {"unchecked": True},
    ],
)
def test_report_accepts_a_well_formed_operator_identity(
    tmp_path: Path, check: dict[str, Any]
) -> None:
    """A well-formed operator_identity loads without error (AIE-1196, US1.10)."""
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    _stale_current_grade(trial, check)

    _, report = build_report(run_dir)

    assert report["run"]["run_id"]


# --- refresh ---


def test_report_computes_the_check_for_a_grade_without_it(tmp_path: Path) -> None:
    """A current grade.json lacking operator_identity gets it on first report,
    and a hit fails `passed` while `results` stays as recorded (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)
    (trial,) = (run_dir / "alpha").iterdir()
    old = _stale_current_grade(trial, None)

    _, report = build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert refreshed["operator_identity"]["hits"] == [REPLY_HIT]
    assert refreshed["results"] == old["results"]
    assert refreshed["passed"] is False
    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0


def test_report_clears_a_stale_hit_and_restores_passed(tmp_path: Path) -> None:
    """A recorded hit the fresh check no longer finds is dropped and `passed`
    follows the results again (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path)
    (trial,) = (run_dir / "alpha").iterdir()
    stale = {"hits": [REPLY_HIT], "sources": ["git user.name"], "replies_scanned": True}
    old = _stale_current_grade(trial, stale)
    old["passed"] = False
    (trial / "grade.json").write_text(json.dumps(old))
    _age(trial / "grade.json", 10)

    build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert refreshed["operator_identity"]["hits"] == []
    assert refreshed["passed"] is True
    assert refreshed["results"] == old["results"]


def test_report_leaves_a_current_identity_check_alone(tmp_path: Path) -> None:
    """A current grade.json whose operator_identity is unchanged is not
    rewritten (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)
    (trial,) = (run_dir / "alpha").iterdir()
    for name in ("store.json", "trace.json", "transcript.json"):
        _age(trial / name, 30)
    grade_trial(trial)
    _age(trial / "grade.json", 10)
    before = (trial / "grade.json").stat().st_mtime_ns

    build_report(run_dir)

    assert (trial / "grade.json").stat().st_mtime_ns == before


def test_report_keeps_recorded_hits_when_no_identity_resolves(
    tmp_path: Path, set_identity: Any
) -> None:
    """A refresh with no resolvable identity keeps the recorded check, hits
    included, and the trial stays failed (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)
    (trial,) = (run_dir / "alpha").iterdir()
    for name in ("store.json", "trace.json", "transcript.json"):
        _age(trial / name, 30)
    recorded = grade_trial(trial)
    _age(trial / "grade.json", 10)
    set_identity()

    _, report = build_report(run_dir)

    refreshed = _json(trial / "grade.json")
    assert refreshed["operator_identity"] == recorded["operator_identity"]
    assert refreshed["passed"] is False
    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0
    assert report["operator_identity"]["flagged_trials"] == 1


def test_report_grades_a_missing_grade_with_the_identity_check(tmp_path: Path) -> None:
    """A trial with dumps and no grade.json is graded with the check, so a
    hit fails the trial (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)

    _, report = build_report(run_dir)

    (alpha,) = report["scenarios"]
    assert alpha["passed_trials"] == 0
    assert report["operator_identity"]["flagged_trials"] == 1


# --- report fields ---


def test_report_lists_operator_identity_trials_and_totals(tmp_path: Path) -> None:
    """The report names flagged trials with their hit locations, counts
    unscanned trials, and totals the run (AIE-1196, US1.10).
    """
    run_dir, (t1, t2, t3) = _reply_trial(tmp_path, trials=3)
    for trial in (t1, t2, t3):
        _dump(trial, leak=False)
    _reply_transcript(t1, LEAK_REPLY)
    _reply_transcript(t2, SECOND_PERSON)

    markdown, report = build_report(run_dir)

    (alpha,) = report["scenarios"]
    assert alpha["operator_identity_trials"] == [{"trial": 1, "hits": [REPLY_HIT]}]
    assert alpha["unscanned_trials"] == [3]
    assert alpha["passed_trials"] == 2
    totals = report["operator_identity"]
    assert (totals["flagged_trials"], totals["checked_trials"], totals["unscanned_trials"]) == (
        1,
        3,
        1,
    )
    assert totals["sources"][:3] == ["git user.name", "git user.email", "$USER"]
    assert _json(run_dir / "report.json")["operator_identity"] == totals
    assert markdown == (run_dir / "report.md").read_text()


def test_report_without_an_identity_counts_no_checked_trials(
    tmp_path: Path, set_identity: Any
) -> None:
    """With no resolvable identity no trial is checked and nothing is flagged
    (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY, trials=2)
    set_identity()

    _, report = build_report(run_dir)

    assert report["operator_identity"] == {
        "flagged_trials": 0,
        "checked_trials": 0,
        "unscanned_trials": 0,
        "sources": [],
    }
    (alpha,) = report["scenarios"]
    assert alpha["operator_identity_trials"] == []
    assert alpha["passed_trials"] == 2


def test_report_markdown_summarizes_the_check_and_lists_hits(tmp_path: Path) -> None:
    """report.md has a run summary line and a per-scenario hit line with kind
    and location only (AIE-1196, US1.10).
    """
    run_dir = _identity_trial(tmp_path, LEAK_REPLY)

    markdown, _ = build_report(run_dir)

    lines = markdown.splitlines()
    identity_lines = [line for line in lines if "identity" in line.lower()]
    hit_lines = [line for line in identity_lines if "first-name" in line]
    assert len(identity_lines) >= 2
    assert len(hit_lines) == 1
    assert "trial 1" in hit_lines[0]
    assert "reply" in hit_lines[0]
    for name in NAME_TEXTS:
        assert name.lower() not in markdown.lower()


def test_report_markdown_omits_hit_lines_when_clean(tmp_path: Path) -> None:
    """A clean scenario has no hit line, only the run summary (AIE-1196, US1.10)."""
    run_dir = _identity_trial(tmp_path)

    markdown, _ = build_report(run_dir)

    lines = markdown.splitlines()
    assert not [line for line in lines if "first-name" in line]
    assert [line for line in lines if "identity" in line.lower()]
