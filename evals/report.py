"""Run planning, trial grading, and the per-run report.

A run directory holds run.json and, per scenario and trial, a trial dir with
trial.json, the driver's dumps, grade.json, and optionally judge.json.
"""

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

import evals.agent
from evals.graders import (
    GradeInputError,
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
    "new_run",
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


def new_run(
    scenarios: Sequence[Scenario],
    *,
    model: str,
    trials: int,
    runs_dir: Path = RUNS_DIR,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create the run and trial dirs; return the run dir and the runner's plan."""
    check_model(model)
    if trials < 1:
        raise ValueError("trials must be at least 1")
    created = datetime.now(UTC) if now is None else now
    base = f"{created.strftime('%Y%m%d-%H%M%S')}-{_slug(model)}"
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


def grade_trial(trial_dir: Path) -> dict[str, Any]:
    """Grade one dumped trial and write grade.json; raises GradeInputError on bad inputs."""
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
    }
    _write_json(trial_dir / "grade.json", graded)
    return graded


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


def _load_grade(path: Path) -> dict[str, Any]:
    graded = _checked(path, _read_json(path), _GRADE_FIELDS, "grade.json")
    for i, result in enumerate(cast(list[object], graded["results"])):
        _checked(path, result, _RESULT_FIELDS, f"results[{i}]")
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
        scenario: Scenario | None = None
        for k in range(1, trials + 1):
            trial_dir = run_dir / ident / f"trial-{k}"
            scenario, _ = _trial_scenario(trial_dir)
            dumped = (trial_dir / "store.json").exists() and (trial_dir / "trace.json").exists()
            if _grade_is_current(trial_dir):
                graded.append(_load_grade(trial_dir / "grade.json"))
            elif dumped:
                graded.append(grade_trial(trial_dir))
            else:
                not_run.append(k)
                continue
            if (trial_dir / "judge.json").exists():
                verdicts = _judge_verdicts(trial_dir, scenario)
                if verdicts is None:
                    invalid_judge.append(k)
                else:
                    judged.append(verdicts)
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
                        "id": j.id,
                        "passes": sum(1 for v in judged if v.get(j.id) is True),
                        "runs": sum(1 for v in judged if j.id in v),
                    }
                    for j in scenario.judge
                    if any(j.id in v for v in judged)
                ],
                "invalid_judge_trials": invalid_judge,
            }
        )
    report: dict[str, Any] = {"run": run, "scenarios": scenario_reports}
    markdown = _markdown(run, scenario_reports)
    (run_dir / "report.md").write_text(markdown)
    _write_json(run_dir / "report.json", report)
    return markdown, report


def _markdown(run: dict[str, Any], scenarios: Sequence[dict[str, object]]) -> str:
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
    for s in scenarios:
        lines += ["", f"## {s['id']}", ""]
        not_run = cast(list[int], s["trials_not_run"])
        if not_run:
            lines += [f"Trials not run: {', '.join(map(str, not_run))}", ""]
        lines += ["| Assertion | Kind | Passes |", "| --------- | ---- | ------ |"]
        for a in cast(list[dict[str, object]], s["assertions"]):
            lines.append(f"| {a['id']} | {a['kind']} | {a['passes']}/{a['runs']} |")
        judge = cast(list[dict[str, object]], s["judge"])
        if judge:
            lines += ["", "| Judge item | Passes |", "| ---------- | ------ |"]
            for j in judge:
                lines.append(f"| {j['id']} | {j['passes']}/{j['runs']} |")
        invalid = cast(list[int], s["invalid_judge_trials"])
        if invalid:
            lines += ["", f"Trials with an invalid judge.json: {', '.join(map(str, invalid))}"]
    return "\n".join(lines) + "\n"
