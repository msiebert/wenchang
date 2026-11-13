"""Eval CLI: python -m evals <command>."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import evals.agent
from evals.arm import ARM_PATH, Arm, ArmError, load_arm, save_arm
from evals.compare import compare_runs
from evals.graders import GradeInputError
from evals.report import (
    build_report,
    check_model,
    grade_trial,
    merge_runs,
    new_run,
    parse_shard,
    shard_scenarios,
    turn_prompt,
)
from evals.scenario import RUNS_DIR, SCENARIO_DIR, ScenarioError, load_all


def _render_agent(args: argparse.Namespace) -> int:
    out: Path = args.out if args.out is not None else evals.agent.AGENT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(evals.agent.render_agent_file())
    print(out)
    return 0


def _set_arm(args: argparse.Namespace) -> int:
    arm_path: Path = args.arm_path
    agent_out: Path = args.agent_out if args.agent_out is not None else evals.agent.AGENT_PATH
    if args.reset:
        arm = Arm()
        arm_path.unlink(missing_ok=True)
    else:
        if args.index_tool is None:
            print("set-arm requires --index-tool or --reset", file=sys.stderr)
            return 2
        try:
            arm = Arm(index_tool=args.index_tool, agent_prompt=not args.no_agent_prompt)
        except ArmError as exc:
            print(exc, file=sys.stderr)
            return 2
        save_arm(arm, arm_path)
    agent_out.parent.mkdir(parents=True, exist_ok=True)
    agent_out.write_text(evals.agent.render_agent_file(arm))
    print(agent_out)
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
    try:
        arm = load_arm(args.arm_path)
    except ArmError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not arm.is_default:
        print(
            f"warning: running with a non-default arm: index tool {arm.index_tool}, "
            f"agent prompt {'on' if arm.agent_prompt else 'off'}",
            file=sys.stderr,
        )
    selected = [by_id[i] for i in wanted]
    shard: tuple[int, int] | None = None
    if args.shard is not None:
        try:
            shard = parse_shard(args.shard)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        selected = shard_scenarios(selected, *shard)
        if not selected:
            print(f"shard {args.shard} selects no scenarios", file=sys.stderr)
            return 2
    _, plan = new_run(
        selected,
        model=args.model,
        trials=args.trials,
        runs_dir=args.runs_dir,
        shard=shard,
        arm=arm,
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
    for reply in graded.get("third_person_replies", []):
        print(f"THIRD-PERSON session {reply['session']} turn {reply['turn']}: {reply['phrase']}")
    for hit in graded["operator_identity"].get("hits", []):
        print(
            f"OPERATOR-IDENTITY {hit['where']} session {hit['session']} turn {hit['turn']} "
            f"{hit['path']} {hit['field']}: {hit['token']}".replace("  ", " ")
        )
    if "transcript_error" in graded:
        print(f"TRANSCRIPT ERROR: {graded['transcript_error']}")
    return 0


def _turn_prompt(args: argparse.Namespace) -> int:
    try:
        print(turn_prompt(args.trial_dir, args.session, args.turn))
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


def _merge_runs(args: argparse.Namespace) -> int:
    try:
        merge_runs(args.out_dir, args.run_dirs)
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(args.out_dir / "report.md")
    return 0


def _compare(args: argparse.Namespace) -> int:
    try:
        markdown = compare_runs(args.run_dirs, args.baseline)
    except GradeInputError as exc:
        print(exc, file=sys.stderr)
        return 2
    args.out_file.write_text(markdown)
    print(args.out_file)
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

    set_arm = commands.add_parser("set-arm", help="set the eval arm and rewrite the agent file")
    set_arm.add_argument("--index-tool", default=None)
    set_arm.add_argument("--no-agent-prompt", action="store_true")
    set_arm.add_argument("--reset", action="store_true")
    set_arm.add_argument("--arm-path", type=Path, default=ARM_PATH)
    set_arm.add_argument("--agent-out", type=Path, default=None)
    set_arm.set_defaults(handler=_set_arm)

    plan = commands.add_parser("new-run", help="create a run and print the runner's plan")
    plan.add_argument("--model", default="sonnet")
    plan.add_argument("--trials", type=int, default=3)
    plan.add_argument("--scenarios-dir", type=Path, default=SCENARIO_DIR)
    plan.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    plan.add_argument("--shard", default=None, help="k/n: run only shard k of n")
    plan.add_argument("--arm-path", type=Path, default=ARM_PATH)
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

    merge = commands.add_parser("merge-runs", help="merge shard runs into one report")
    merge.add_argument("out_dir", type=Path)
    merge.add_argument("run_dirs", type=Path, nargs="+")
    merge.set_defaults(handler=_merge_runs)

    compare = commands.add_parser("compare", help="compare runs across arms")
    compare.add_argument("out_file", type=Path)
    compare.add_argument("run_dirs", type=Path, nargs="+")
    compare.add_argument("--baseline", type=Path, default=None)
    compare.set_defaults(handler=_compare)

    report = commands.add_parser("report", help="write report.md and report.json for a run")
    report.add_argument("run_dir", type=Path)
    report.set_defaults(handler=_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
