"""Reference adopter configuration for prompt tests (AIE-1055).

Notion spec section 9 rendered as the three PromptSlots blobs plus a scope
priority order. This is illustrative adopter configuration, not library code.
"""

from typing import Final

from wenchang.prompts import PromptSlots

REFERENCE_SCOPE_GUIDANCE: Final[str] = """\
There are three scopes: user, project, and organization. An organization contains projects, and
a user can belong to several organizations.

- user is a private scope: it belongs to the person you are talking with and follows them
  across organizations.
- project is a shared scope, visible to every member of the current project; any member may
  write to it.
- organization is a shared scope, visible to every member of the organization; only admins and
  owners may write to it. Members who can access only some projects read it, so it holds only
  project-agnostic facts. Never write a fact about one project there.

Before saving a new fact to project or organization, ask the user and name the scope. Writes to
user need no ask. If a new fact contradicts one stored in a shared scope, show the stored fact,
say what conflicts, and ask which to keep.

Scope a fact by who it is true for, not who said it: if it would hold for a different person in
this project, use project, or organization if it holds for every project; otherwise use user.
When in doubt, write narrow. "I prefer charts with a dark background" goes in user; "This
project's weekly report goes out on Mondays" in project; "Our fiscal year starts in February"
in organization."""

REFERENCE_SEED_AREAS: Final[str] = """\
- user: identity, preferences, workflows, people
- project: taxonomy, metrics, entities, conventions, glossary
- organization: business-context, vocabulary

Every scope also has a `system/` area."""

REFERENCE_SYSTEMS_OF_RECORD: Final[str] = """\
- Event definitions live in the product's event catalog; refer to an event by its catalog name.
- Dashboards and cohorts are objects with IDs; refer to one by name and ID, and store what it is
  used for and what people have said about it."""

REFERENCE_SLOTS: Final[PromptSlots] = PromptSlots(
    scope_guidance=REFERENCE_SCOPE_GUIDANCE,
    seed_areas=REFERENCE_SEED_AREAS,
    systems_of_record=REFERENCE_SYSTEMS_OF_RECORD,
)

REFERENCE_SCOPE_PRIORITY: Final[tuple[str, ...]] = ("user", "project", "organization")
