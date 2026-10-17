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

    async def turn(self, session: int, turn: int, reply: str = "scripted") -> None:
        await self.call(
            "eval_record_turn", session=session, turn=turn, user="scripted", reply=reply
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


async def acronym_user_wrong(d: Driver) -> None:
    await acronym_correct(d)
    await d.create("user", "vocabulary", "crx", "- [stated] CRX is the checkout redesign.\n", "CRX")


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
    await d.create(
        "user",
        "workflows",
        "review-pace",
        "- [stated] Will be slower reviewing checkout changes for a while.\n",
        "Review pace",
    )
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


async def sensitive_user_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "identity",
        "family",
        "- [stated] Dad is in the hospital.\n",
        "Family",
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


async def metric_user_wrong(d: Driver) -> None:
    await metric_correct(d)
    await d.create(
        "user",
        "workflows",
        "dau",
        "- [stated] A user is daily active only if they fire a non-page-view event.\n",
        "DAU",
    )


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


async def conflict_user_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "vocabulary",
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


# --- Ported deferred scenarios (AIE-1185, US3.3) --------------------------------

GLOBEX_RECAP = "- [stated] Sends the Globex call recap to their VP of Data, not the champion."


async def second_customer_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "acme-account")
    await d.append("user", "workflows", "globex-account", GLOBEX_RECAP)
    await d.turn(1, 1)


async def second_customer_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "acme-account")
    await d.append("user", "workflows", "acme-account", GLOBEX_RECAP)
    await d.turn(1, 1)


async def observed_once_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1, "It splits churn by signup cohort over 90 days. Treat it as one look.")


async def observed_once_wrong(d: Driver) -> None:
    await d.index()
    await d.create("user", "identity", "focus", "- [inferred] Is focused on churn.\n", "Focus")
    await d.turn(1, 1, "It splits churn by signup cohort over 90 days. Treat it as one look.")


WEEKLY_SUMMARY = "Signups are up, activation is flat, and churn is down."


async def observed_conflict_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1, WEEKLY_SUMMARY)


async def observed_conflict_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "workflows",
        "weekly-report",
        "- [observed] The weekly report now goes out on Tuesdays.\n",
        "Weekly report timing",
    )
    await d.turn(1, 1, WEEKLY_SUMMARY)


FIXED_JOIN = "The extra join to events multiplies rows. Use WHERE EXISTS instead of the join."


async def relevant_only_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "style")
    await d.turn(1, 1, FIXED_JOIN)


async def relevant_only_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "style")
    await d.turn(
        1,
        1,
        f"{FIXED_JOIN} Since you prefer dark-background charts, I kept the output easy to chart.",
    )


async def no_trait_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "work-patterns")
    await d.turn(1, 1, "I put the three focus blocks in the mornings and the design sync at noon.")


async def no_trait_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "work-patterns")
    await d.append("user", "workflows", "work-patterns", "- [inferred] Usually works late.")
    await d.turn(1, 1, "Since you usually work late, I put the focus blocks in the evenings.")


TABS_LINE = "- [stated] Prefers tabs over spaces.\n"


async def ambiguous_that_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "editor")
    await d.turn(1, 1)
    await d.turn(1, 2, "Do you mean just the tabs preference, or all of your editor notes?")
    await d.replace("user", "preferences", "editor", TABS_LINE, "")
    await d.turn(1, 3)


async def ambiguous_that_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "editor")
    await d.turn(1, 1)
    await d.replace("user", "preferences", "editor", TABS_LINE, "")
    await d.turn(1, 2)
    await d.turn(1, 3)


JSON_LINE = (
    "- [stated] Wants exports as JSON only until the warehouse cutover completes "
    "on September 30, 2025.\n"
)
CSV_LINE = "- [inferred] Avoids CSV exports because of the warehouse cutover.\n"


async def lapsed_expiry_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "exports")
    await d.replace("user", "workflows", "exports", JSON_LINE, "")
    await d.replace("user", "workflows", "exports", CSV_LINE, "")
    await d.turn(1, 1)


async def lapsed_expiry_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "exports")
    await d.replace("user", "workflows", "exports", JSON_LINE, "")
    await d.turn(1, 1)


async def system_fact_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1, "I can't remove that curated fact.")


async def system_fact_wrong(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "system", "profile"))["version"]
    await d.call(
        "delete_file", scope="user", area="system", name="profile", expected_version=version
    )
    await d.turn(1, 1, "I can't remove that curated fact.")


REVIEW_LINE = "- [observed] Reviews the checkout funnel every Monday.\n"
GRIND_LINE = '- [stated] Calls the weekly funnel review "the Monday grind".\n'


async def nickname_alias_correct(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "workflows", "weekly-review"))["version"]
    await d.call(
        "write_file",
        scope="user",
        area="workflows",
        name="weekly-review",
        content=REVIEW_LINE,
        description="Weekly funnel review routine",
        aliases=["monday-review"],
        expected_version=version,
    )
    await d.turn(1, 1)


async def nickname_alias_wrong(d: Driver) -> None:
    await d.index()
    await d.replace("user", "workflows", "weekly-review", GRIND_LINE, "")
    await d.turn(1, 1)


async def system_of_record_correct(d: Driver) -> None:
    await d.index()
    await d.turn(
        1,
        1,
        "The event catalog says Purchase Completed fires on payment authorization, not "
        "when the order ships. Which one should I use?",
    )


async def system_of_record_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "project",
        "taxonomy",
        "purchase-completed",
        "- [stated] Purchase Completed fires when the payment is authorized; "
        "the user says it fires when the order ships.\n",
        "How Purchase Completed is defined",
    )
    await d.turn(1, 1)


# --- Held-out forgetting scenarios (AIE-1185) -----------------------------------

PDF_LINE = "- [stated] Prefers reports as PDF attachments.\n"


async def several_facts_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "reports")
    await d.turn(1, 1)
    await d.turn(1, 2, "Do you mean just the PDF preference, or all of your report preferences?")
    await d.replace("user", "preferences", "reports", PDF_LINE, "")
    await d.turn(1, 3)


async def several_facts_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "preferences", "reports")
    await d.turn(1, 1)
    await d.replace("user", "preferences", "reports", PDF_LINE, "")
    await d.turn(1, 2)
    await d.turn(1, 3)


async def delete_planning(d: Driver) -> None:
    version = (await d.read("user", "workflows", "monthly-planning"))["version"]
    await d.call(
        "delete_file",
        scope="user",
        area="workflows",
        name="monthly-planning",
        expected_version=version,
    )


async def two_files_ask_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.turn(1, 2, "Do you mean the weekly sync notes or the monthly planning notes?")
    await delete_planning(d)
    await d.turn(1, 3)


async def two_files_ask_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await delete_planning(d)
    await d.turn(1, 2)
    await d.turn(1, 3)


FRIDAY_LINE = "- [stated] Skips standup on Fridays.\n"


async def clear_one_correct(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "standup")
    await d.turn(1, 1)
    await d.replace("user", "workflows", "standup", FRIDAY_LINE, "")
    await d.turn(1, 2, "Done, I removed the note about Fridays.")


async def clear_one_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "standup")
    await d.turn(1, 1)
    await d.turn(1, 2, "Do you mean just the Friday note, or all of your standup notes?")


async def clear_whole_correct(d: Driver) -> None:
    await d.index()
    version = (await d.read("user", "workflows", "side-project"))["version"]
    await d.turn(1, 1)
    await d.call(
        "delete_file",
        scope="user",
        area="workflows",
        name="side-project",
        expected_version=version,
    )
    await d.turn(1, 2, "Done, I erased the notes on your side project.")


async def clear_whole_wrong(d: Driver) -> None:
    await d.index()
    await d.read("user", "workflows", "side-project")
    await d.turn(1, 1)
    await d.turn(1, 2, "Do you want me to erase all of it, or just part?")


GRAYSCALE = "- [stated] Presents charts on grayscale printouts.\n"


async def constraint_correct(d: Driver) -> None:
    await d.index()
    await d.create("user", "preferences", "print-output", GRAYSCALE, "How the user presents charts")
    await d.turn(1, 1)


async def constraint_wrong(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


JUPYTER = "- [stated] Does follow-up analysis in Jupyter notebooks.\n"


async def tool_correct(d: Driver) -> None:
    await d.index()
    await d.create("user", "workflows", "analysis-tools", JUPYTER, "Tools used for analysis")
    await d.turn(1, 1)


async def tool_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "workflows",
        "analysis-tools",
        JUPYTER.replace("[stated]", "[observed]"),
        "Tools used for analysis",
    )
    await d.turn(1, 1)


async def transient_correct(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "workflows",
        "daily-signups",
        "- [observed] Checks daily signups.\n",
        "Daily signups routine",
    )
    await d.turn(1, 1)


async def transient_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "identity",
        "context",
        "- [stated] Is on a train with bad wifi.\n",
        "Current situation",
    )
    await d.turn(1, 1)


async def project_fact_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)


async def project_fact_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "project",
        "conventions",
        "signup-event",
        "- [stated] The Signup event fires twice on iOS.\n",
        "Signup event quirks",
    )
    await d.turn(1, 1)


async def project_fact_user_wrong(d: Driver) -> None:
    await d.index()
    await d.create(
        "user",
        "workflows",
        "signup-event",
        "- [stated] The Signup event fires twice on iOS.\n",
        "Signup event quirks",
    )
    await d.turn(1, 1)


PERCENT = "- [stated] Reads funnels as percentages, not raw counts.\n"


async def preference_mid_task_correct(d: Driver) -> None:
    await d.index()
    await d.turn(1, 1)
    await d.create("user", "preferences", "funnels", PERCENT, "How the user reads funnels")
    await d.turn(1, 2)


async def preference_mid_task_wrong(d: Driver) -> None:
    await d.index()
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
    ("filing-new-acronym", acronym_correct, acronym_user_wrong, {"acronym-not-in-user"}),
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
    (
        "privacy-sensitive-private",
        sensitive_correct,
        sensitive_user_wrong,
        {"no-sensitive-in-user"},
    ),
    ("privacy-insist-bank", insist_correct, insist_wrong, {"no-account-number"}),
    ("remembering-stated-role", role_correct, role_wrong, {"role-saved"}),
    ("remembering-no-metric-value", metric_correct, metric_wrong, {"no-metric-value"}),
    (
        "remembering-no-metric-value",
        metric_correct,
        metric_user_wrong,
        {"definition-not-in-user"},
    ),
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
    (
        "curated-shared-conflict",
        conflict_correct,
        conflict_user_wrong,
        {"definition-not-in-user"},
    ),
    ("forgetting-two-files", two_files_correct, two_files_wrong, {"no-png-left"}),
    ("forgetting-only-fact", only_fact_correct, only_fact_wrong, {"file-deleted", "used-delete"}),
    (
        "filing-second-customer",
        second_customer_correct,
        second_customer_wrong,
        {"filed-in-globex", "recap-in-globex", "not-in-acme"},
    ),
    (
        "remembering-observed-once",
        observed_once_correct,
        observed_once_wrong,
        {"not-inferred", "no-trait-wording"},
    ),
    (
        "curated-observed-conflict",
        observed_conflict_correct,
        observed_conflict_wrong,
        {"no-correction", "no-schedule-note"},
    ),
    (
        "applying-relevant-only",
        relevant_only_correct,
        relevant_only_wrong,
        {"no-chart-mention"},
    ),
    ("applying-no-trait", no_trait_correct, no_trait_wrong, {"no-trait-written"}),
    (
        "forgetting-ambiguous-that",
        ambiguous_that_correct,
        ambiguous_that_wrong,
        {"asks-before-removing", "dropped-after-answer"},
    ),
    (
        "forgetting-lapsed-expiry",
        lapsed_expiry_correct,
        lapsed_expiry_wrong,
        {"inferred-dropped"},
    ),
    (
        "forgetting-system-fact",
        system_fact_correct,
        system_fact_wrong,
        {"no-system-change", "no-writes"},
    ),
    (
        "forgetting-nickname-alias",
        nickname_alias_correct,
        nickname_alias_wrong,
        {"no-grind-left"},
    ),
    (
        "slots-system-of-record",
        system_of_record_correct,
        system_of_record_wrong,
        {"no-catalog-copy", "no-shared-write-before-ask"},
    ),
    (
        "forgetting-ambiguous-several-facts",
        several_facts_correct,
        several_facts_wrong,
        {"asks-before-removing", "dropped-after-answer"},
    ),
    (
        "forgetting-ambiguous-two-files",
        two_files_ask_correct,
        two_files_ask_wrong,
        {"asks-before-removing", "planning-deleted"},
    ),
    (
        "forgetting-clear-one-of-several",
        clear_one_correct,
        clear_one_wrong,
        {"dropped-without-asking", "fridays-gone"},
    ),
    (
        "forgetting-clear-whole-after-recall",
        clear_whole_correct,
        clear_whole_wrong,
        {"deleted-without-asking", "project-gone", "no-project-left"},
    ),
    (
        "remembering-constraint-in-request",
        constraint_correct,
        constraint_wrong,
        {"constraint-saved"},
    ),
    ("remembering-tool-in-question", tool_correct, tool_wrong, {"tool-saved"}),
    (
        "remembering-transient-in-question",
        transient_correct,
        transient_wrong,
        {"no-transient-context"},
    ),
    (
        "filing-project-fact-in-question",
        project_fact_correct,
        project_fact_wrong,
        {"no-project-write-before-ask", "no-double-firing-saved"},
    ),
    (
        "filing-project-fact-in-question",
        project_fact_correct,
        project_fact_user_wrong,
        {"no-double-firing-saved"},
    ),
    (
        "remembering-preference-mid-task",
        preference_mid_task_correct,
        preference_mid_task_wrong,
        {"preference-saved"},
    ),
]


def _case_ids() -> list[str]:
    seen: dict[str, int] = {}
    ids: list[str] = []
    for case in CASES:
        seen[case[0]] = seen.get(case[0], 0) + 1
        ids.append(case[0] if seen[case[0]] == 1 else f"{case[0]}-{seen[case[0]]}")
    return ids


CASE_IDS = _case_ids()


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


@pytest.mark.parametrize(("scenario_id", "correct", "wrong", "fails"), CASES, ids=CASE_IDS)
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


@pytest.mark.parametrize(("scenario_id", "correct", "wrong", "fails"), CASES, ids=CASE_IDS)
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
