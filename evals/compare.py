"""Compare eval runs across arms: index-tool use, fact labeling, and pass rates."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from evals.graders import INDEX_TOOL, GradeInputError, load_store_dump, load_trace, order_key
from evals.report import judge_verdicts, load_grade, load_run, load_run_arm, trial_scenario
from wenchang.tools import TOOL_NAMES

__all__ = ["ArmMetrics", "compare_runs", "compute_metrics"]

_LABEL = re.compile(r"\[(stated|observed|inferred)\]")


@dataclass(frozen=True)
class ArmMetrics:
    run_dir: Path
    index_tool: str
    agent_prompt: bool
    model: str
    trials: int
    sessions: int
    first_call_index: int
    no_memory_call: int
    index_first_passes: int
    index_first_total: int
    added_fact_lines: int
    labeled_fact_lines: int
    assertion_passes: int
    assertion_total: int
    judge_passes: int
    judge_total: int


def _scenario_ids(run_dir: Path) -> list[str]:
    return sorted(cast(list[str], load_run(run_dir)["scenarios"]))


def compute_metrics(run_dir: Path) -> ArmMetrics:
    """Counts over every trial of the run. Raises GradeInputError on bad input."""
    run = load_run(run_dir)
    arm = load_run_arm(run_dir)
    counts = dict.fromkeys(
        (
            "sessions",
            "first_call_index",
            "no_memory_call",
            "index_first_passes",
            "index_first_total",
            "added",
            "labeled",
            "assertion_passes",
            "assertion_total",
            "judge_passes",
            "judge_total",
        ),
        0,
    )
    for ident in cast(list[str], run["scenarios"]):
        for k in range(1, int(run["trials"]) + 1):
            trial_dir = run_dir / ident / f"trial-{k}"
            scenario, _ = trial_scenario(trial_dir)
            counts["sessions"] += len(scenario.sessions)
            trace = sorted(load_trace(trial_dir / "trace.json"), key=order_key)
            for session in range(1, len(scenario.sessions) + 1):
                first = next(
                    (c for c in trace if c.session == session and c.tool in TOOL_NAMES), None
                )
                if first is None:
                    counts["no_memory_call"] += 1
                elif first.tool == INDEX_TOOL:
                    counts["first_call_index"] += 1
            seeded = {line for seed in scenario.seed_files for line in seed.content.splitlines()}
            for stored in load_store_dump(trial_dir / "store.json").files:
                for line in stored.content.splitlines():
                    is_fact = line.lstrip().startswith("- ") and "[system]" not in line
                    if is_fact and line not in seeded:
                        counts["added"] += 1
                        counts["labeled"] += bool(_LABEL.search(line))
            graded = load_grade(trial_dir / "grade.json")
            for result in cast(list[dict[str, Any]], graded["results"]):
                counts["assertion_total"] += 1
                counts["assertion_passes"] += bool(result["passed"])
                if result["kind"] == "index_read_first":
                    counts["index_first_total"] += 1
                    counts["index_first_passes"] += bool(result["passed"])
            verdicts = (
                judge_verdicts(trial_dir, scenario) if (trial_dir / "judge.json").exists() else None
            )
            if verdicts is not None:
                counts["judge_total"] += len(verdicts)
                counts["judge_passes"] += sum(verdicts.values())
    return ArmMetrics(
        run_dir=run_dir,
        index_tool=arm.index_tool,
        agent_prompt=arm.agent_prompt,
        model=str(run["model"]),
        trials=int(run["trials"]),
        sessions=counts["sessions"],
        first_call_index=counts["first_call_index"],
        no_memory_call=counts["no_memory_call"],
        index_first_passes=counts["index_first_passes"],
        index_first_total=counts["index_first_total"],
        added_fact_lines=counts["added"],
        labeled_fact_lines=counts["labeled"],
        assertion_passes=counts["assertion_passes"],
        assertion_total=counts["assertion_total"],
        judge_passes=counts["judge_passes"],
        judge_total=counts["judge_total"],
    )


def _rate(passes: int, total: int) -> float | None:
    return None if total == 0 else 100 * passes / total


def _rates(m: ArmMetrics) -> list[tuple[int, int]]:
    return [
        (m.first_call_index, m.sessions),
        (m.no_memory_call, m.sessions),
        (m.index_first_passes, m.index_first_total),
        (m.labeled_fact_lines, m.added_fact_lines),
        (m.assertion_passes, m.assertion_total),
        (m.judge_passes, m.judge_total),
    ]


def _cell(passes: int, total: int, baseline: tuple[int, int] | None) -> str:
    rate = _rate(passes, total)
    if rate is None:
        return "n/a"
    shown = f"{rate:.1f}% ({passes}/{total})"
    reference = None if baseline is None else _rate(*baseline)
    return shown if reference is None else f"{shown} {rate - reference:+.1f}"


_COLUMNS = (
    "First call is index",
    "No memory call",
    "Index read first",
    "Labeled fact lines",
    "Assertions",
    "Judge",
)


def compare_runs(run_dirs: Sequence[Path], baseline: Path | None = None) -> str:
    """A markdown table, one row per run, with deltas in points from the baseline.

    The baseline is baseline or the first run. Raises GradeInputError on bad
    input or when the runs cover different scenarios.
    """
    if not run_dirs:
        raise GradeInputError("compare needs at least one run dir")
    reference_dir = run_dirs[0] if baseline is None else baseline
    all_dirs = [*run_dirs, *([] if baseline is None or baseline in run_dirs else [baseline])]
    expected = _scenario_ids(reference_dir)
    for run_dir in all_dirs:
        if _scenario_ids(run_dir) != expected:
            raise GradeInputError(f"{run_dir}: scenarios differ from {reference_dir}'s: {expected}")
    reference = compute_metrics(reference_dir)
    reference_rates = _rates(reference)
    lines = [
        "# Eval arm comparison",
        "",
        f"Baseline: {reference_dir.name}. Rates are percent (passes/total); "
        "other rows show the change in points.",
        "",
        "| Run | Index tool | Agent prompt | Model | Trials | Sessions | "
        + " | ".join(_COLUMNS)
        + " |",
        "| " + " | ".join(["---"] * (6 + len(_COLUMNS))) + " |",
    ]
    for run_dir in run_dirs:
        m = reference if run_dir == reference_dir else compute_metrics(run_dir)
        is_baseline = run_dir == reference_dir
        cells = [
            _cell(p, t, None if is_baseline else reference_rates[i])
            for i, (p, t) in enumerate(_rates(m))
        ]
        lines.append(
            f"| {run_dir.name} | {m.index_tool} | {'on' if m.agent_prompt else 'off'} | "
            f"{m.model} | {m.trials} | {m.sessions} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines) + "\n"
