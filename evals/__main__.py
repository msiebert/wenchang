"""Eval CLI: python -m evals <command>."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import evals.agent


def _render_agent(args: argparse.Namespace) -> int:
    out: Path = args.out if args.out is not None else evals.agent.AGENT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(evals.agent.render_agent_file())
    print(out)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals")
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser("render-agent", help="write the eval agent definition")
    render.add_argument("--out", type=Path, default=None)
    render.set_defaults(handler=_render_agent)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
