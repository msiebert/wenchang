"""Reference adopter configuration for prompt tests (AIE-1055).

Notion spec section 9 rendered as the three PromptSlots blobs plus a scope
priority order. This is illustrative adopter configuration, not library code.
"""

from typing import Final

from wenchang.prompts import PromptSlots

REFERENCE_SCOPE_GUIDANCE: Final[str] = """\
There are three scopes: user, project, and organization. An organization contains projects,
and a user can belong to several organizations.

- user is a private scope. It belongs to the person you are talking with and follows them
  across organizations.
- project is a shared scope, visible to every member of the current project. Any member may
  write to it.
- organization is a shared scope, visible to every member of the organization. Only admins
  and owners may write to it.

Before saving a new fact to a shared scope (project or organization), ask the user first and
say which scope you intend to use. Writes to the private user scope need no ask.

If a new fact contradicts one already stored in a shared scope, do not overwrite it silently:
show the stored fact, say what conflicts with it, and ask which to keep.

Organization scope is readable by members who can access only some projects, so it holds only
project-agnostic facts. Never write a fact about one project there.

Scope test: scope a fact by who it is true for, not who said it. Would this still be true if a
different person opened this project? If yes, it belongs in project, or in organization if it
holds for every project; if no, it belongs in user. When in doubt, write narrow.

Examples:
- "I prefer charts with a dark background" goes in user.
- "This project's weekly report goes out on Mondays" goes in project.
- "Our fiscal year starts in February" goes in organization."""

REFERENCE_SEED_AREAS: Final[str] = """\
Each scope starts with the areas below. They are a starting point, not a fixed list: create a
new area, named as a lowercase slug, whenever none of these fits.

- user: identity, preferences, workflows, people
- project: taxonomy, metrics, entities, conventions, glossary
- organization: business-context, vocabulary

Every scope also has a `system/` area. It holds curated content maintained for you and is
read-only. Every other area is agent-writable, subject to each scope's write rules under
Scopes."""

REFERENCE_SYSTEMS_OF_RECORD: Final[str] = """\
- Event definitions live in the product's event catalog. Refer to an event by its catalog
  name; do not copy its definition into memory.
- Dashboards and cohorts are real objects with IDs. Refer to one by its name and ID, and store
  what it is used for and what people have said about it, never a copy of its contents.

Memory references and annotates these objects; it never mirrors them."""

REFERENCE_SLOTS: Final[PromptSlots] = PromptSlots(
    scope_guidance=REFERENCE_SCOPE_GUIDANCE,
    seed_areas=REFERENCE_SEED_AREAS,
    systems_of_record=REFERENCE_SYSTEMS_OF_RECORD,
)

REFERENCE_SCOPE_PRIORITY: Final[tuple[str, ...]] = ("user", "project", "organization")
