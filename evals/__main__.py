"""Eval CLI: python -m evals <command>."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import evals.agent
from evals.graders import GradeInputError
from evals.report import build_report, check_model, grade_trial, new_run, turn_prompt
from evals.scenario import RUNS_DIR, SCENARIO_DIR, ScenarioError, load_all


def _render_agent(args: argparse.Namespace) -> int:
    out: Path = args.out if args.out is not None else evals.agent.AGENT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(evals.agent.render_agent_file())
    print(out)
    return 0


def _new_run(args: argparse.Namespace) -> int:
    try:
        check_model(args.model)
        scenarios = load_all(args.scenarios_dir)
    except (ValueError, ScenarioError) as exc:
        print(exc, file=sys.stderr)
        return 2
    by_id = {s.id: s for s in scenarios}
    wanted: list[str] = args.ids or list(by_id)
    unknown = [i for i in wanted if i not in by_id]
    if unknown:
        print(f"unknown scenario id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.trials < 1:
        print("--trials must be at least 1", file=sys.stderr)
        return 2
    _, plan = new_run(
        [by_id[i] for i in wanted], model=args.model, trials=args.trials, runs_dir=args.runs_dir
    )
    print(json.dumps(plan, indent=2))
    return 0


def _grade(args: argparse.Namespace) -> int:
    try:
        graded = grade_trial(args.trial_dir)
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    for result in graded["results"]:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} {result['id']}: {result['detail']}")
    return 0


def _turn_prompt(args: argparse.Namespace) -> int:
    try:
        print(turn_prompt(args.trial_dir, args.session, args.turn))
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _report(args: argparse.Namespace) -> int:
    try:
        build_report(args.run_dir)
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(args.run_dir / "report.md")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals")
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser("render-agent", help="write the eval agent definition")
    render.add_argument("--out", type=Path, default=None)
    render.set_defaults(handler=_render_agent)

    plan = commands.add_parser("new-run", help="create a run and print the runner's plan")
    plan.add_argument("--model", default="sonnet")
    plan.add_argument("--trials", type=int, default=3)
    plan.add_argument("--scenarios-dir", type=Path, default=SCENARIO_DIR)
    plan.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    plan.add_argument("ids", nargs="*")
    plan.set_defaults(handler=_new_run)

    grade = commands.add_parser("grade", help="grade one dumped trial")
    grade.add_argument("trial_dir", type=Path)
    grade.set_defaults(handler=_grade)

    prompt = commands.add_parser("turn-prompt", help="print the Agent prompt for one turn")
    prompt.add_argument("trial_dir", type=Path)
    prompt.add_argument("session", type=int)
    prompt.add_argument("turn", type=int)
    prompt.set_defaults(handler=_turn_prompt)

    report = commands.add_parser("report", help="write report.md and report.json for a run")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(handler=_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
