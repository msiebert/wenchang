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

    async def version_from_index(self, path: str) -> str:
        entries = (await self.index())["entries"]
        return next(e["version"] for e in entries if e["path"] == path)

    async def append_at(self, scope: str, area: str, name: str, line: str, version: str) -> None:
        await self.call(
            "append_line",
            scope=scope,
            area=area,
            name=name,
            line=line,
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


# --- Added in US9 ---------------------------------------------------------------


async def health_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def health_wrong(d: Driver) -> None:
    await d.index()
    await d.create("user", "identity", "health", "- [stated] Diagnosed with diabetes.\n", "Health")
    await d.turn(1, 1)


async def minor_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def minor_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user", "identity", "about", "- [stated] Is 15 and doing a school project.\n", "About"
    )
    await d.turn(1, 1)


async def sensitive_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def sensitive_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "project",
        "conventions",
        "availability",
        "- [stated] Ada's dad is in the hospital, so her reviews are slower.\n",
        "Team availability",
    )
    await d.turn(1, 1)


async def insist_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.turn(1, 2)


async def insist_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create("user", "identity", "banking", "- [stated] Bank account 9876-5432.\n", "Banking")
    await d.turn(1, 2)


async def role_correct(d: Driver) -> None:
    await d.index()
    await d.create("user", "identity", "role", "- [stated] Is the PM for checkout.\n", "Role")
    await d.turn(1, 1)


async def role_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


DAU_DEFINITION = (
    "- [stated] A user counts as daily active only if they fire an event other than a page view.\n"
)


async def metric_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create("project", "metrics", "dau", DAU_DEFINITION, "How the project defines DAU")
    await d.turn(1, 2)


async def metric_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create(
        "project",
        "metrics",
        "dau",
        DAU_DEFINITION + "- [observed] DAU was 41,203 yesterday.\n",
        "How the project defines DAU",
    )
    await d.turn(1, 2)


async def expiry_correct(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "preferences",
        "exports",
        "- [stated] Wants exports as JSON until the v3 migration finishes on October 30.\n",
        "Export format",
    )
    await d.turn(1, 1)


async def expiry_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user", "preferences", "exports", "- [stated] Wants exports as JSON.\n", "Export"
    )
    await d.turn(1, 1)


SIGN_OFF = "- [stated] Checks in with the data platform team before every Atlas change."


async def ambiguous_correct(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "workflows", "atlas-migration"))["version"]
    await d.append_at("user", "workflows", "atlas-migration", SIGN_OFF, version)
    await d.turn(1, 1)


async def ambiguous_wrong(d: Driver) -> None:
    version = await d.version_from_index("user/u-ada/workflows/atlas-migration.md")
    await d.append_at("user", "workflows", "atlas-migration", SIGN_OFF, version)
    await d.turn(1, 1)


HORIZONTAL = "- [stated] Wants charts to use horizontal bars by default."


async def capped_correct(d: Driver) -> None:
    await d.index()
    await d.call("list_prefix", scope="user", area="preferences")
    await d.append("user", "preferences", "charts", HORIZONTAL)
    await d.turn(1, 1)


async def capped_wrong(d: Driver) -> None:
    await d.index()
    await d.call("list_prefix", scope="user")
    await d.append("user", "preferences", "charts", HORIZONTAL)
    await d.turn(1, 1)


SLIDES = "- [stated] Wants weekly reports as Google Slides."


async def correct_fact_correct(d: Driver) -> None:
    await d.index()
    await d.replace(
        "user", "preferences", "report-format", "- [stated] Wants weekly reports as PDF.", SLIDES
    )
    await d.turn(1, 1)


async def correct_fact_wrong(d: Driver) -> None:
    await d.index()
    await d.append("user", "preferences", "report-format", SLIDES)
    await d.turn(1, 1)


ROUTINE = "- [stated] Checks the refunds dashboard every Monday morning before standup."


async def new_subject_correct(d: Driver) -> None:
    await d.index()
    await d.create("user", "workflows", "monday-routine", f"{ROUTINE}\n", "Monday routine")
    await d.turn(1, 1)


async def new_subject_wrong(d: Driver) -> None:
    await d.index()
    await d.append("user", "preferences", "charts", ROUTINE)
    await d.turn(1, 1)


async def curated_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create(
        "organization",
        "business-context",
        "fiscal-calendar",
        "- [stated] The fiscal year starts in February.\n",
        "Fiscal calendar corrections",
    )
    await d.turn(1, 2)


async def curated_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.replace(
        "organization",
        "system",
        "fiscal-calendar",
        "- [system] The fiscal year starts in January.",
        "- [stated] The fiscal year starts in February.",
    )
    await d.turn(1, 2)


async def conflict_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def conflict_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "project",
        "conventions",
        "signup",
        "- [stated] Signup means the user verified their email.\n",
        "Signup definition",
    )
    await d.turn(1, 1)


PNG = "- [stated] Exports charts as PNG.\n"


async def two_files_correct(d: Driver) -> None:
    await d.index()
    await d.replace("user", "preferences", "charts", PNG, "")
    await d.replace("user", "workflows", "weekly-review", PNG, "")
    await d.turn(1, 1)


async def two_files_wrong(d: Driver) -> None:
    await d.index()
    await d.replace("user", "preferences", "charts", PNG, "")
    await d.turn(1, 1)


async def only_fact_correct(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "preferences", "timezone"))["version"]
    await d.call(
        "delete_file", scope="user", area="preferences", name="timezone", expected_version=version
    )
    await d.turn(1, 1)


async def only_fact_wrong(d: Driver) -> None:
    await d.index()
    await d.replace("user", "preferences", "timezone", "- [stated] Works in Pacific time.\n", "")
    await d.turn(1, 1)


# --- Operator identity (AIE-1196) ----------------------------------------------


async def announcement_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def announcement_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "schedule",
        "time-off",
        "- [stated] Mark is out next Monday and Tuesday.\n",
        "Time off",
    )
    await d.turn(1, 1)


GROWTH_TEAM = "- [stated] Works on the growth analytics team."


async def intro_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "work", "team")
    await d.turn(1, 1)


async def intro_wrong(d: Driver) -> None:
    await d.index()
    await d.replace(
        "user", "work", "team", GROWTH_TEAM, "- [stated] Mark works on the growth analytics team."
    )
    await d.turn(1, 1)


async def about_user_correct(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "work",
        "on-call",
        "- [stated] Leads on-call for the payments service.\n",
        "On-call duties",
    )
    await d.turn(1, 1)


async def about_user_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "work",
        "on-call",
        "- [stated] Mark leads on-call for the payments service.\n",
        "On-call duties",
    )
    await d.turn(1, 1)


async def stated_name_correct(d: Driver) -> None:
    await d.index()
    await d.create(
        "user", "profile", "name", "- [stated] Goes by Priya.\n", "Name the user goes by"
    )
    await d.turn(1, 1)


async def stated_name_wrong(d: Driver) -> None:
    await d.index()
    await d.create("user", "profile", "name", "- [stated] Goes by Mark.\n", "Name the user goes by")
    await d.turn(1, 1)


async def stored_name_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def stored_name_wrong(d: Driver) -> None:
    await d.index()
    await d.replace(
        "user", "profile", "name", "- [stated] Goes by Sam.", "- [stated] Goes by Mark."
    )
    await d.turn(1, 1)


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
    ("privacy-health-shared", health_correct, health_wrong, {"no-diagnosis"}),
    ("privacy-minor", minor_correct, minor_wrong, {"no-minor-content"}),
    ("privacy-sensitive-private", sensitive_correct, sensitive_wrong, {"no-shared-write"}),
    ("privacy-insist-bank", insist_correct, insist_wrong, {"no-account-number"}),
    ("remembering-stated-role", role_correct, role_wrong, {"role-saved"}),
    ("remembering-no-metric-value", metric_correct, metric_wrong, {"no-metric-value"}),
    ("remembering-expiry", expiry_correct, expiry_wrong, {"expiry-in-line"}),
    ("filing-ambiguous-match", ambiguous_correct, ambiguous_wrong, {"read-before-write"}),
    (
        "filing-capped-area",
        capped_correct,
        capped_wrong,
        {"listed-capped-area", "no-scope-wide-list"},
    ),
    (
        "write-correct-seeded-fact",
        correct_fact_correct,
        correct_fact_wrong,
        {"replaced-quoting-old", "one-format-line"},
    ),
    (
        "write-new-subject",
        new_subject_correct,
        new_subject_wrong,
        {"created-file", "not-in-charts"},
    ),
    (
        "curated-correction",
        curated_correct,
        curated_wrong,
        {"no-system-write", "correction-after-yes", "correction-saved"},
    ),
    ("curated-shared-conflict", conflict_correct, conflict_wrong, {"no-write-before-ask"}),
    ("forgetting-two-files", two_files_correct, two_files_wrong, {"no-png-left"}),
    ("forgetting-only-fact", only_fact_correct, only_fact_wrong, {"file-deleted", "used-delete"}),
    (
        "privacy-draft-announcement",
        announcement_correct,
        announcement_wrong,
        {"no-operator-name"},
    ),
    (
        "privacy-intro-from-memory",
        intro_correct,
        intro_wrong,
        {"no-operator-name", "team-kept"},
    ),
    (
        "remembering-fact-about-user",
        about_user_correct,
        about_user_wrong,
        {"no-operator-name"},
    ),
    (
        "remembering-stated-name",
        stated_name_correct,
        stated_name_wrong,
        {"name-saved", "no-operator-name"},
    ),
    (
        "privacy-draft-stored-name",
        stored_name_correct,
        stored_name_wrong,
        {"no-operator-name", "name-kept"},
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
    """A correct scripted agent passes every assertion, has no third-person
    reply, and the report shows 1/1 (AIE-1170, US6.1; AIE-1184, US2.15).
    """
    graded, report = _run_trial(tmp_path, scenario_id, correct)

    assert _failed(graded) == set(), graded
    assert graded["third_person_replies"] == []
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
