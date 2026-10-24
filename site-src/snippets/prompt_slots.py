from wenchang.prompts import SECTION_ORDER, PromptSlots, build_memory_prompt

slots = PromptSlots(
    purpose=(
        "You have persistent memory of your work helping an author write a novel: reference it "
        "and save to it with these tools whenever you work on a manuscript."
    ),
    scope_guidance=(
        "There are three scopes: user, project, and organization. A project is one manuscript. "
        "An organization is a publisher, and an author may work on several manuscripts.\n\n"
        "- user is private: it belongs to the author you are talking with and follows them "
        "across manuscripts.\n"
        "- project is the manuscript, shared by its author, co-author, and editor; any of them "
        "may write to it.\n"
        "- organization is Hanlin Press, shared by every author and editor there; only "
        "editors-in-chief may write to it. It holds press-wide conventions, never facts about "
        "one book.\n\n"
        "Writes to user and project need no ask. If a new fact contradicts one stored in project "
        "or organization, show the stored fact, say what conflicts, and ask which to keep.\n\n"
        "Scope a fact by who it is true for, not who said it: if it would hold for a different "
        "author on this manuscript, use project, or organization if it holds for every book at "
        'the press; otherwise use user. When in doubt, write narrow. "I draft in the morning" '
        'goes in user; "Lin Qiao\'s eyes are grey" in project; "The press spells in British '
        'English" in organization.'
    ),
    # To let the agent choose, say so: "No fixed areas. Create areas as subjects need them."
    seed_areas=(
        "- user: preferences, workflows\n"
        "- project: characters, plot, timeline, style, research\n"
        "- organization: conventions\n\n"
        "Every scope also has a `system/` area."
    ),
    # Optional. None omits the whole section.
    systems_of_record=(
        "- The manuscript text lives in the author's word processor. Never copy chapters into "
        "memory; refer to a chapter by number and title, and store decisions about it.\n"
        "- Editorial queries live in the press's tracker; refer to one by its ID."
    ),
)

print(SECTION_ORDER)
prompt = build_memory_prompt(slots)
print([line for line in prompt.splitlines() if line.startswith("## ")])
