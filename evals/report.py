"""Run planning, trial grading, and the per-run report.

A run directory holds run.json and, per scenario and trial, a trial dir with
trial.json, the driver's dumps, grade.json, and optionally judge.json.
"""

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

import evals.agent
from evals.graders import (
    GradeInputError,
    find_third_person_replies,
    grade,
    load_store_dump,
    load_trace,
    load_transcript,
)
from evals.scenario import RUNS_DIR, Scenario, ScenarioError, assertion_kind, load_scenario

__all__ = [
    "MODEL_ALIASES",
    "RUNS_DIR",
    "build_report",
    "check_model",
    "grade_trial",
    "merge_runs",
    "new_run",
    "parse_shard",
    "shard_scenarios",
    "turn_prompt",
]

MODEL_ALIASES: Final[frozenset[str]] = frozenset({"sonnet", "opus", "haiku", "fable", "inherit"})


def check_model(model: str) -> None:
    """Raise ValueError unless model is an Agent-tool alias or a full claude- id."""
    if model not in MODEL_ALIASES and not model.startswith("claude-"):
        raise ValueError(
            f"unknown model {model!r}: use one of {sorted(MODEL_ALIASES)} or a claude-* id"
        )


GIT_TIMEOUT_S: Final = 10


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _git_commit() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _agent_sha256() -> str | None:
    try:
        return hashlib.sha256(evals.agent.AGENT_PATH.read_bytes()).hexdigest()
    except OSError:
        return None


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def parse_shard(text: str) -> tuple[int, int]:
    """Parse "k/n" with 1 <= k <= n; raises ValueError otherwise."""
    parts = text.split("/")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"shard must be k/n, got {text!r}")
    k, n = int(parts[0]), int(parts[1])
    if n < 1 or not 1 <= k <= n:
        raise ValueError(f"shard {text!r} is out of range: need 1 <= k <= n")
    return k, n


def shard_scenarios(scenarios: Sequence[Scenario], k: int, n: int) -> list[Scenario]:
    """Shard k of n: the scenarios, sorted by id, whose index % n == k - 1."""
    ordered = sorted(scenarios, key=lambda s: s.id)
    return [s for i, s in enumerate(ordered) if i % n == k - 1]


def new_run(
    scenarios: Sequence[Scenario],
    *,
    model: str,
    trials: int,
    runs_dir: Path = RUNS_DIR,
    now: datetime | None = None,
    shard: tuple[int, int] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create the run and trial dirs; return the run dir and the runner's plan.

    A shard run's dir ends in -shard<k>of<n>, so sibling shards started in the
    same second do not collide, and its run.json records the shard.
    """
    check_model(model)
    if trials < 1:
        raise ValueError("trials must be at least 1")
    created = datetime.now(UTC) if now is None else now
    base = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slug(model)}"
    if shard is not None:
        base += f"-shard{shard[0]}of{shard[1]}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id, suffix = base, 1
    while True:
        try:
            (runs_dir / run_id).mkdir()
            break
        except FileExistsError:
            suffix += 1
            run_id = f"{base}-{suffix}"
    run_dir = runs_dir / run_id
    _write_json(
        run_dir / "run.json",
        {
            "run_id": run_id,
            "created": created.isoformat(),
            "model": model,
            "trials": trials,
            "scenarios": [s.id for s in scenarios],
            "git_commit": _git_commit(),
            "agent_sha256": _agent_sha256(),
            **({"shard": f"{shard[0]}/{shard[1]}"} if shard is not None else {}),
        },
    )
    planned: list[dict[str, object]] = []
    for scenario in scenarios:
        for k in range(1, trials + 1):
            trial_dir = run_dir / scenario.id / f"trial-{k}"
            trial_dir.mkdir(parents=True)
            _write_json(
                trial_dir / "trial.json",
                {"scenario": scenario.id, "scenario_path": str(scenario.path), "trial": k},
            )
            planned.append(
                {
                    "scenario": scenario.id,
                    "scenario_path": str(scenario.path),
                    "trial": k,
                    "trial_dir": str(trial_dir),
                    "sessions": [list(s.turns) for s in scenario.sessions],
                }
            )
    return run_dir, {"run_dir": str(run_dir), "model": model, "trials": planned}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        raise GradeInputError(f"{path}: cannot read: {exc.strerror}") from None
    except json.JSONDecodeError as exc:
        raise GradeInputError(f"{path}: invalid JSON: {exc}") from None


def _trial_scenario(trial_dir: Path) -> tuple[Scenario, int]:
    meta = _read_json(trial_dir / "trial.json")
    if not isinstance(meta, dict) or "scenario_path" not in meta or "trial" not in meta:
        raise GradeInputError(f"{trial_dir / 'trial.json'}: expected scenario_path and trial")
    info = cast(dict[str, Any], meta)
    try:
        scenario = load_scenario(Path(str(info["scenario_path"])))
    except ScenarioError as exc:
        raise GradeInputError(str(exc)) from None
    return scenario, int(info["trial"])


def turn_prompt(trial_dir: Path, session: int, turn: int) -> str:
    """The Agent prompt for one turn of a trial.

    Turn 1 of a session is the scripted text alone. A later turn replays the
    session's earlier exchanges from transcript.json, user text and verbatim
    reply in order, then gives the new turn. Raises GradeInputError if the
    turn is not in the scenario or an earlier reply is not recorded.
    """
    scenario, _ = _trial_scenario(trial_dir)
    if not 1 <= session <= len(scenario.sessions):
        raise GradeInputError(f"{trial_dir}: scenario has no session {session}")
    turns = scenario.sessions[session - 1].turns
    if not 1 <= turn <= len(turns):
        raise GradeInputError(f"{trial_dir}: session {session} has no turn {turn}")
    if turn == 1:
        return turns[0]
    recorded = {(t.session, t.turn): t for t in load_transcript(trial_dir / "transcript.json")}
    lines = ["[Earlier in this conversation]"]
    for earlier in range(1, turn):
        exchange = recorded.get((session, earlier))
        if exchange is None:
            raise GradeInputError(
                f"{trial_dir}: transcript.json has no reply for session {session} turn {earlier}"
            )
        if earlier > 1:
            lines.append("")
        lines += [f"User: {exchange.user}", f"Assistant: {exchange.reply}"]
    lines += ["", "[Newest message]", turns[turn - 1]]
    return "\n".join(lines)


_REPLY_CHECK_KEYS: Final = ("third_person_replies", "transcript_error")


def _reply_check(trial_dir: Path, scenario: Scenario) -> dict[str, Any]:
    """The reply check's grade.json fields; empty without a transcript.

    A malformed transcript is recorded, never raised, so it cannot block
    deterministic grading.
    """
    path = trial_dir / "transcript.json"
    if not path.exists():
        return {}
    try:
        transcript = load_transcript(path)
    except GradeInputError as exc:
        return {"transcript_error": str(exc)}
    return {
        "third_person_replies": [
            {"session": f.session, "turn": f.turn, "phrase": f.phrase}
            for f in find_third_person_replies(scenario, transcript)
        ]
    }


def grade_trial(trial_dir: Path) -> dict[str, Any]:
    """Grade one dumped trial and write grade.json; raises GradeInputError on bad
    store or trace inputs.
    """
    scenario, trial = _trial_scenario(trial_dir)
    store = load_store_dump(trial_dir / "store.json")
    trace = load_trace(trial_dir / "trace.json")
    results = grade(scenario, store, trace)
    graded: dict[str, Any] = {
        "scenario": scenario.id,
        "trial": trial,
        "results": [
            {"id": r.id, "kind": r.kind, "passed": r.passed, "detail": r.detail} for r in results
        ],
        "passed": all(r.passed for r in results),
        **_reply_check(trial_dir, scenario),
    }
    _write_json(trial_dir / "grade.json", graded)
    return graded


def _refresh_reply_check(trial_dir: Path, scenario: Scenario, graded: dict[str, Any]) -> None:
    """Recompute only the reply check of a grade.json that is current for the
    store and trace, when it lacks one or the transcript is newer.
    """
    transcript = trial_dir / "transcript.json"
    if not transcript.exists():
        return
    has_check = any(key in graded for key in _REPLY_CHECK_KEYS)
    newer = transcript.stat().st_mtime > (trial_dir / "grade.json").stat().st_mtime
    if has_check and not newer:
        return
    for key in _REPLY_CHECK_KEYS:
        graded.pop(key, None)
    graded.update(_reply_check(trial_dir, scenario))
    _write_json(trial_dir / "grade.json", graded)


def _judge_verdicts(trial_dir: Path, scenario: Scenario) -> dict[str, bool] | None:
    """Verdicts by judge id, or None if judge.json does not match the schema."""
    try:
        raw = _read_json(trial_dir / "judge.json")
    except GradeInputError:
        return None
    if not isinstance(raw, dict):
        return None
    verdicts: object = cast(dict[str, Any], raw).get("verdicts")
    if not isinstance(verdicts, list):
        return None
    allowed = {j.id for j in scenario.judge}
    found: dict[str, bool] = {}
    for item in cast(list[object], verdicts):
        if not isinstance(item, dict):
            return None
        entry = cast(dict[str, Any], item)
        ident, verdict, reason = entry.get("id"), entry.get("verdict"), entry.get("reason")
        if ident not in allowed or verdict not in ("pass", "fail") or not isinstance(reason, str):
            return None
        if ident in found:
            return None
        found[cast(str, ident)] = verdict == "pass"
    return found


_RUN_FIELDS: Final[Mapping[str, type | tuple[type, ...]]] = MappingProxyType(
    {
        "run_id": str,
        "created": str,
        "model": str,
        "trials": int,
        "scenarios": list,
        "git_commit": (str, type(None)),
        "agent_sha256": (str, type(None)),
    }
)
_GRADE_FIELDS: Final[Mapping[str, type]] = MappingProxyType(
    {"scenario": str, "trial": int, "passed": bool, "results": list}
)
_RESULT_FIELDS: Final[Mapping[str, type]] = MappingProxyType(
    {"id": str, "kind": str, "passed": bool, "detail": str}
)


def _checked(path: Path, value: object, fields: Mapping[str, Any], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GradeInputError(f"{path}: {where} must be an object")
    data = cast(dict[str, Any], value)
    for key, kind in fields.items():
        if key not in data:
            raise GradeInputError(f"{path}: {where} is missing {key!r}")
        if not isinstance(data[key], kind) or (kind is int and isinstance(data[key], bool)):
            raise GradeInputError(f"{path}: {where} field {key!r} has the wrong type")
    return data


def _load_run(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    run = _checked(path, _read_json(path), _RUN_FIELDS, "run.json")
    if run["trials"] < 1 or not all(isinstance(s, str) for s in run["scenarios"]):
        raise GradeInputError(f"{path}: trials must be >= 1 and scenarios a list of ids")
    return run


_REPLY_FIELDS: Final[Mapping[str, type]] = MappingProxyType(
    {"session": int, "turn": int, "phrase": str}
)


def _load_grade(path: Path) -> dict[str, Any]:
    graded = _checked(path, _read_json(path), _GRADE_FIELDS, "grade.json")
    for i, result in enumerate(cast(list[object], graded["results"])):
        _checked(path, result, _RESULT_FIELDS, f"results[{i}]")
    if "third_person_replies" in graded:
        replies: object = graded["third_person_replies"]
        if not isinstance(replies, list):
            raise GradeInputError(f"{path}: grade.json third_person_replies must be a list")
        for i, reply in enumerate(cast(list[object], replies)):
            _checked(path, reply, _REPLY_FIELDS, f"third_person_replies[{i}]")
    if "transcript_error" in graded and not isinstance(graded["transcript_error"], str):
        raise GradeInputError(f"{path}: grade.json transcript_error must be a string")
    return graded


def _grade_is_current(trial_dir: Path) -> bool:
    grade_path = trial_dir / "grade.json"
    if not grade_path.exists():
        return False
    dumps = [trial_dir / "store.json", trial_dir / "trace.json"]
    newest = max((p.stat().st_mtime for p in dumps if p.exists()), default=0.0)
    return grade_path.stat().st_mtime >= newest


def build_report(run_dir: Path) -> tuple[str, dict[str, Any]]:
    """Grade dumped trials whose grade.json is missing or stale, then write
    report.md and report.json. Raises GradeInputError on malformed inputs.
    """
    run = _load_run(run_dir)
    trials = int(run["trials"])
    scenario_reports: list[dict[str, object]] = []
    for ident in cast(list[str], run["scenarios"]):
        not_run: list[int] = []
        invalid_judge: list[int] = []
        graded: list[dict[str, Any]] = []
        judged: list[dict[str, bool]] = []
        flagged: list[dict[str, object]] = []
        unchecked: list[int] = []
        flagged_verdicts: list[dict[str, bool]] = []
        scenario: Scenario | None = None
        for k in range(1, trials + 1):
            trial_dir = run_dir / ident / f"trial-{k}"
            scenario, _ = _trial_scenario(trial_dir)
            dumped = (trial_dir / "store.json").exists() and (trial_dir / "trace.json").exists()
            if _grade_is_current(trial_dir):
                current = _load_grade(trial_dir / "grade.json")
                _refresh_reply_check(trial_dir, scenario, current)
            elif dumped:
                current = grade_trial(trial_dir)
            else:
                not_run.append(k)
                continue
            graded.append(current)
            replies = cast(list[dict[str, object]] | None, current.get("third_person_replies"))
            if replies is None:
                unchecked.append(k)
            elif replies:
                flagged.append({"trial": k, "replies": replies})
            if (trial_dir / "judge.json").exists():
                verdicts = _judge_verdicts(trial_dir, scenario)
                if verdicts is None:
                    invalid_judge.append(k)
                else:
                    judged.append(verdicts)
                    if replies:
                        flagged_verdicts.append(verdicts)
        assert scenario is not None
        assertions = [
            {
                "id": a.id,
                "kind": assertion_kind(a),
                "passes": sum(
                    1
                    for g in graded
                    for r in cast(list[dict[str, Any]], g["results"])
                    if r["id"] == a.id and r["passed"]
                ),
                "runs": len(graded),
            }
            for a in scenario.assertions
        ]
        passed_trials = sum(1 for g in graded if g["passed"])
        judged_ids = [j.id for j in scenario.judge if any(j.id in v for v in judged)]
        scenario_reports.append(
            {
                "id": ident,
                "trials_run": len(graded),
                "trials_not_run": not_run,
                "passed_trials": passed_trials,
                "pass_rate": passed_trials / len(graded) if graded else None,
                "assertions": assertions,
                "judge": [
                    {
                        "id": ident,
                        "passes": sum(1 for v in judged if v.get(ident) is True),
                        "runs": sum(1 for v in judged if ident in v),
                    }
                    for ident in judged_ids
                ],
                "invalid_judge_trials": invalid_judge,
                "third_person_trials": flagged,
                "addressee_unchecked_trials": unchecked,
                "judge_third_person_fails": [
                    {
                        "id": ident,
                        "fails": sum(1 for v in flagged_verdicts if v.get(ident) is False),
                    }
                    for ident in judged_ids
                ],
            }
        )
    totals = {
        "flagged_trials": sum(
            len(cast(list[object], s["third_person_trials"])) for s in scenario_reports
        ),
        "checked_trials": sum(
            cast(int, s["trials_run"]) - len(cast(list[object], s["addressee_unchecked_trials"]))
            for s in scenario_reports
        ),
    }
    report: dict[str, Any] = {
        "run": run,
        "scenarios": scenario_reports,
        "third_person": totals,
    }
    markdown = _markdown(run, scenario_reports, totals)
    (run_dir / "report.md").write_text(markdown)
    _write_json(run_dir / "report.json", report)
    return markdown, report


_MATCHED_RUN_FIELDS: Final = ("model", "trials", "git_commit", "agent_sha256")


def merge_runs(out_dir: Path, run_dirs: Sequence[Path]) -> tuple[str, dict[str, Any]]:
    """Merge shard runs into out_dir and write its report.

    Every input must share model, trials, git commit, and agent sha256, and no
    scenario may appear in two inputs. Trial dirs are copied; out_dir must not
    exist. Raises GradeInputError, leaving nothing behind, on any mismatch.
    """
    if not run_dirs:
        raise GradeInputError("merge-runs needs at least one run dir")
    if out_dir.exists():
        raise GradeInputError(f"{out_dir}: output dir already exists")
    runs = [_load_run(d) for d in run_dirs]
    first = runs[0]
    for run_dir, run in zip(run_dirs, runs, strict=True):
        for key in _MATCHED_RUN_FIELDS:
            if run[key] != first[key]:
                raise GradeInputError(
                    f"{run_dir}: {key} {run[key]!r} differs from {run_dirs[0]}'s {first[key]!r}"
                )
    seen: dict[str, Path] = {}
    for run_dir, run in zip(run_dirs, runs, strict=True):
        for ident in run["scenarios"]:
            if ident in seen:
                raise GradeInputError(f"scenario {ident!r} is in both {seen[ident]} and {run_dir}")
            seen[ident] = run_dir
    out_dir.mkdir(parents=True)
    for ident, source in seen.items():
        shutil.copytree(source / ident, out_dir / ident)
    _write_json(
        out_dir / "run.json",
        {
            "run_id": out_dir.name,
            "created": datetime.now(UTC).isoformat(),
            **{key: first[key] for key in _MATCHED_RUN_FIELDS},
            "scenarios": sorted(seen),
            "sources": [str(d) for d in run_dirs],
        },
    )
    return build_report(out_dir)


def _flagged_line(flagged: Sequence[dict[str, Any]]) -> str:
    trials = [
        f"trial {f['trial']} ("
        + ", ".join(
            f'session {r["session"]} turn {r["turn"]}: "{r["phrase"]}"'
            for r in cast(list[dict[str, object]], f["replies"])
        )
        + ")"
        for f in flagged
    ]
    return "Third-person replies: " + "; ".join(trials)


def _markdown(
    run: dict[str, Any], scenarios: Sequence[dict[str, object]], totals: Mapping[str, int]
) -> str:
    lines = [
        f"# Eval report: {run['run_id']}",
        "",
        f"- Model: {run['model']}",
        f"- Trials per scenario: {run['trials']}",
        f"- Created: {run['created']}",
        f"- Git commit: {run['git_commit']}",
        f"- Agent file sha256: {run['agent_sha256']}",
        "",
        "| Scenario | Trials passed | Pass rate |",
        "| -------- | ------------- | --------- |",
    ]
    for s in scenarios:
        rate = s["pass_rate"]
        shown = "n/a" if rate is None else f"{cast(float, rate):.0%}"
        lines.append(f"| {s['id']} | {s['passed_trials']}/{s['trials_run']} | {shown} |")
    lines += [
        "",
        f"Trials with a third-person reply: {totals['flagged_trials']} of "
        f"{totals['checked_trials']} checked.",
    ]
    for s in scenarios:
        lines += ["", f"## {s['id']}", ""]
        not_run = cast(list[int], s["trials_not_run"])
        if not_run:
            lines += [f"Trials not run: {', '.join(map(str, not_run))}", ""]
        lines += ["| Assertion | Kind | Passes |", "| --------- | ---- | ------ |"]
        for a in cast(list[dict[str, object]], s["assertions"]):
            lines.append(f"| {a['id']} | {a['kind']} | {a['passes']}/{a['runs']} |")
        flagged = cast(list[dict[str, Any]], s["third_person_trials"])
        if flagged:
            lines += ["", _flagged_line(flagged)]
        unchecked = cast(list[int], s["addressee_unchecked_trials"])
        if unchecked:
            lines += ["", f"Addressee not checked: {', '.join(map(str, unchecked))}"]
        judge = cast(list[dict[str, object]], s["judge"])
        fails = {
            cast(str, f["id"]): f["fails"]
            for f in cast(list[dict[str, object]], s["judge_third_person_fails"])
        }
        if judge:
            lines += [
                "",
                "| Judge item | Passes | Fails with a third-person reply |",
                "| ---------- | ------ | ------------------------------- |",
            ]
            for j in judge:
                lines.append(
                    f"| {j['id']} | {j['passes']}/{j['runs']} | {fails[cast(str, j['id'])]} |"
                )
        invalid = cast(list[int], s["invalid_judge_trials"])
        if invalid:
            lines += ["", f"Trials with an invalid judge.json: {', '.join(map(str, invalid))}"]
    return "\n".join(lines) + "\n"
