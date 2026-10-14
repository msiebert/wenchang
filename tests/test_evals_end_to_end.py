"""Scripted drivers run every shipped scenario end to end through the eval
server, grader, and report (AIE-1170, US6).

Each scenario has a correct driver, which must pass every assertion, and one
wrong driver, which must fail exactly the listed assertions. The drivers prove
the mechanics; whether a real agent follows the prompt is the live run's job.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client import Client
from mcp.types import CallToolResult

from evals.report import build_report, grade_trial, new_run
from evals.scenario import SCENARIO_DIR, load_scenario
from evals.server import EvalState, build_eval_server

pytestmark = pytest.mark.unit


class Driver:
    """Plays one scripted agent through the harness, as the runner would."""

    def __init__(self, client: Client) -> None:
        self.client = client

    async def call(self, tool: str, **arguments: object) -> dict[str, Any]:
        result: CallToolResult = await self.client.call_tool(tool, arguments)
        payload = result.structured_content
        assert payload is not None, result
        return payload

    async def index(self) -> dict[str, Any]:
        return await self.call("get_memory_index")

    async def read(self, scope: str, area: str, name: str) -> dict[str, Any]:
        return await self.call("read_file", scope=scope, area=area, name=name)

    async def create(
        self, scope: str, area: str, name: str, content: str, description: str
    ) -> None:
        await self.call(
            "write_file",
            scope=scope,
            area=area,
            name=name,
            content=content,
            description=description,
            aliases=[],
            expected_version=None,
        )

    async def append(
        self, scope: str, area: str, name: str, line: str, aliases: list[str] | None = None
    ) -> None:
        version = (await self.read(scope, area, name))["version"]
        await self.call(
            "append_line",
            scope=scope,
            area=area,
            name=name,
            line=line,
            expected_version=version,
            aliases=aliases,
        )

    async def replace(self, scope: str, area: str, name: str, old: str, new: str) -> None:
        version = (await self.read(scope, area, name))["version"]
        await self.call(
            "replace_fact",
            scope=scope,
            area=area,
            name=name,
            old_string=old,
            new_string=new,
            expected_version=version,
        )

    async def turn(self, session: int, turn: int) -> None:
        await self.call(
            "eval_record_turn", session=session, turn=turn, user="scripted", reply="scripted"
        )


Script = Callable[[Driver], Awaitable[None]]


# --- privacy-account-number ---------------------------------------------------


async def privacy_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def privacy_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user", "identity", "banking", "- [stated] Checking account 1234-5678.\n", "Banking"
    )
    await d.turn(1, 1)


BOARD_DECK_SCHEDULE = (
    "- [stated] The board deck always goes out the Friday before the board meeting."
)


# --- filing-alias-append ------------------------------------------------------


async def alias_correct(d: Driver) -> None:
    await d.index()
    await d.append("user", "workflows", "board-deck", BOARD_DECK_SCHEDULE)
    await d.turn(1, 1)


async def alias_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "workflows",
        "board-deck-schedule",
        f"{BOARD_DECK_SCHEDULE}\n",
        "When the board deck goes out",
    )
    await d.turn(1, 1)


# --- recall-across-sessions ---------------------------------------------------


async def recall_correct(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "preferences",
        "report-charts",
        "- [stated] Prefers bar charts for weekly reports.\n",
        "Chart types for reports",
    )
    await d.turn(1, 1)
    await d.index()
    await d.read("user", "preferences", "report-charts")
    await d.turn(2, 1)


async def recall_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "preferences",
        "report-charts",
        "- [stated] Prefers bar charts for weekly reports.\n",
        "Chart types for reports",
    )
    await d.turn(1, 1)
    await d.turn(2, 1)


# --- forgetting-one-fact ------------------------------------------------------


async def forget_fact_correct(d: Driver) -> None:
    await d.index()
    await d.replace("user", "preferences", "editor", "- [stated] Prefers tabs over spaces.\n", "")
    await d.turn(1, 1)


async def forget_fact_wrong(d: Driver) -> None:
    await d.index()
    await d.append("user", "preferences", "editor", "- [stated] No longer prefers tabs.")
    await d.turn(1, 1)


# --- filing-new-acronym -------------------------------------------------------


async def acronym_correct(d: Driver) -> None:
    await d.index()
    await d.read("project", "entities", "checkout-redesign")
    await d.turn(1, 1)
    await d.append(
        "project",
        "entities",
        "checkout-redesign",
        "- [stated] CRX launches on November 3.",
        aliases=["CRX"],
    )
    await d.turn(1, 2)


async def acronym_wrong(d: Driver) -> None:
    await d.index()
    await d.read("project", "entities", "checkout-redesign")
    await d.turn(1, 1)
    await d.append(
        "project", "entities", "checkout-redesign", "- [stated] CRX launches on November 3."
    )
    await d.turn(1, 2)


# --- recall-replace-fact ------------------------------------------------------

GROWTH = "- [stated] Sends the weekly report to the growth team."
RETENTION = "- [stated] Sends the weekly report to the retention team."


async def replace_correct(d: Driver) -> None:
    await d.index()
    await d.create("user", "workflows", "weekly-report", f"{GROWTH}\n", "Weekly report routine")
    await d.turn(1, 1)
    await d.index()
    await d.replace("user", "workflows", "weekly-report", GROWTH, RETENTION)
    await d.turn(2, 1)


async def replace_wrong(d: Driver) -> None:
    await d.index()
    await d.create("user", "workflows", "weekly-report", f"{GROWTH}\n", "Weekly report routine")
    await d.turn(1, 1)
    await d.index()
    await d.append("user", "workflows", "weekly-report", RETENTION)
    await d.turn(2, 1)


# --- forgetting-whole-file ----------------------------------------------------


async def forget_file_correct(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "workflows", "atlas-migration"))["version"]
    await d.call(
        "delete_file",
        scope="user",
        area="workflows",
        name="atlas-migration",
        expected_version=version,
    )
    await d.turn(1, 1)


async def forget_file_wrong(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "workflows", "atlas-migration"))["version"]
    await d.call(
        "write_file",
        scope="user",
        area="workflows",
        name="atlas-migration",
        content="",
        description="The Atlas migration the user leads",
        aliases=["atlas"],
        expected_version=version,
    )
    await d.turn(1, 1)


# --- slots-ask-before-shared --------------------------------------------------

MEMBERS = '- [stated] The company calls customers "members".\n'


async def ask_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create("organization", "vocabulary", "customers", MEMBERS, "What customers are called")
    await d.turn(1, 2)


async def ask_wrong(d: Driver) -> None:
    await d.index()
    await d.create("organization", "vocabulary", "customers", MEMBERS, "What customers are called")
    await d.turn(1, 1)
    await d.turn(1, 2)


# (scenario id, correct driver, wrong driver, ids the wrong driver must fail)
CASES: list[tuple[str, Script, Script, set[str]]] = [
    ("privacy-account-number", privacy_correct, privacy_wrong, {"no-account-number"}),
    (
        "filing-alias-append",
        alias_correct,
        alias_wrong,
        {"appended-to-board-deck", "no-new-file", "schedule-filed"},
    ),
    (
        "recall-across-sessions",
        recall_correct,
        recall_wrong,
        {"recalled-in-session-2"},
    ),
    (
        "forgetting-one-fact",
        forget_fact_correct,
        forget_fact_wrong,
        {"dropped-with-replace", "tabs-gone"},
    ),
    ("filing-new-acronym", acronym_correct, acronym_wrong, {"alias-added"}),
    (
        "recall-replace-fact",
        replace_correct,
        replace_wrong,
        {"replaced-in-session-2", "one-recipient-line"},
    ),
    (
        "forgetting-whole-file",
        forget_file_correct,
        forget_file_wrong,
        {"file-deleted", "used-delete", "no-atlas-left"},
    ),
    (
        "slots-ask-before-shared",
        ask_correct,
        ask_wrong,
        {"no-org-write-before-ask", "org-write-after-yes"},
    ),
]


def _run_trial(
    tmp_path: Path, scenario_id: str, script: Script
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = load_scenario(SCENARIO_DIR / f"{scenario_id}.yaml")
    runs = tmp_path / "runs"
    run_dir, plan = new_run([scenario], model="sonnet", trials=1, runs_dir=runs)
    (trial,) = plan["trials"]
    state = EvalState(runs_root=runs)

    async def main() -> None:
        with anyio.fail_after(30):
            async with Client(build_eval_server(state)) as client:
                driver = Driver(client)
                reset = await client.call_tool(
                    "eval_reset",
                    {"scenario_path": trial["scenario_path"], "trial_dir": trial["trial_dir"]},
                )
                assert not reset.is_error, reset
                await script(driver)
                await driver.call("eval_dump")

    anyio.run(main)
    graded = grade_trial(Path(trial["trial_dir"]))
    _, report = build_report(run_dir)
    return graded, report


def _failed(graded: dict[str, Any]) -> set[str]:
    return {r["id"] for r in graded["results"] if not r["passed"]}


@pytest.mark.parametrize(
    ("scenario_id", "correct", "wrong", "fails"), CASES, ids=[c[0] for c in CASES]
)
def test_correct_driver_passes_every_assertion(
    tmp_path: Path, scenario_id: str, correct: Script, wrong: Script, fails: set[str]
) -> None:
    """A correct scripted agent passes every assertion and the report shows
    1/1 (AIE-1170, US6.1).
    """
    graded, report = _run_trial(tmp_path, scenario_id, correct)

    assert _failed(graded) == set(), graded
    (entry,) = report["scenarios"]
    assert (entry["passed_trials"], entry["trials_run"]) == (1, 1)


@pytest.mark.parametrize(
    ("scenario_id", "correct", "wrong", "fails"), CASES, ids=[c[0] for c in CASES]
)
def test_wrong_driver_fails_exactly_the_listed_assertions(
    tmp_path: Path, scenario_id: str, correct: Script, wrong: Script, fails: set[str]
) -> None:
    """One wrong move fails exactly the listed assertions and the report shows
    0/1 (AIE-1170, US6.2).
    """
    graded, report = _run_trial(tmp_path, scenario_id, wrong)

    assert _failed(graded) == fails, graded
    (entry,) = report["scenarios"]
    assert (entry["passed_trials"], entry["trials_run"]) == (0, 1)


def test_every_shipped_scenario_has_scripted_drivers() -> None:
    """Every scenario in the corpus is covered here (AIE-1170, US6.1)."""
    shipped = {p.stem for p in SCENARIO_DIR.glob("*.yaml")}
    assert {c[0] for c in CASES} == shipped
