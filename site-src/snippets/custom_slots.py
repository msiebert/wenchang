from wenchang.prompts import SECTION_ORDER, PromptSlots, build_memory_prompt

slots = PromptSlots(
    purpose=(
        "You have persistent memory of your work in Acme Analytics: reference it and save to it "
        "with these tools whenever you work with Acme."
    ),
    scope_guidance=(
        "There are two scopes: user and project.\n\n"
        "- user is private: it belongs to the person you are talking with.\n"
        "- project is shared with every member of the current project; any member may write to "
        "it.\n\n"
        "Before saving a new fact to project, ask the user and name the scope. If a new fact "
        "contradicts one stored in project, show the stored fact, say what conflicts, and ask "
        "which to keep."
    ),
    seed_areas=(
        "- user: preferences, workflows, people\n"
        "- project: metrics, conventions, glossary\n\n"
        "Every scope also has a `system/` area."
    ),
    # Optional. None omits the whole section.
    systems_of_record=(
        "- Dashboards are objects with IDs; refer to one by name and ID, and store what it is "
        "used for and what people have said about it."
    ),
)

print(SECTION_ORDER)
prompt = build_memory_prompt(slots)
print([line for line in prompt.splitlines() if line.startswith("## ")])
