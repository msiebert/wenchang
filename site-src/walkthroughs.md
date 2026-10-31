# Walkthroughs

Six walkthroughs of what an agent does with memory. Each shows what the user says, the tool calls the agent makes, and the memory file before and after.

## How to read these examples {#reading}

- **The setup.** An assistant called Inkwell helps an author write a novel, *The Ninth Examination*. There are three scopes. `user` is the author's own preferences. `project` is the manuscript, shared by the author, co-author, and editor. `organization` is the publisher, Hanlin Press, whose house style sits in the read-only `system/` area. Only an admin at the press can write `organization`. Paths read `project/p-ninth-examination/...` for that reason.
- **The cast.** Tianlong (`u-tianlong`) is the author and Diya (`u-diya`) is the editor. Kuixing (`u-kuixing`) is the press's editor-in-chief. All three are named after attendants of Wenchang, the god of literature. The product name is "Inkwell" and the agent's source is `inkwell-web`.
- **Real:** every tool call's argument names and every result payload are real output of the library, produced by running the calls below against an in-memory store with a fixed clock. Version tokens (`"1"`, `"2"`) are opaque. `InMemoryStorage` counts up, and GCS returns large generation numbers.
- **Illustrative:** which calls the agent chooses, the exact text it passes (`line`, `description`, `aliases`), and its replies. The library fixes none of that. The prompt guides it. Treat those parts as representative.
- **File blocks.** A memory file is a markdown body plus metadata stored beside it (GCS custom metadata), not inside it. The blocks below show both together for readability. That layout is not a storage format.
- **Prompt rules assumed.** The scope guidance in these examples says writes to `user` and `project` need no ask, and that a new fact contradicting a stored `project` or `organization` fact is shown and questioned. See [Customizing the prompts](prompts.md#slots).

## 1. Recall across sessions {#recall}

A style preference stated in one session is used in the next.

**Session 1**

> **User:** I write in close third person, past tense. Keep that in mind.

The agent loads the index first, as the prompt instructs. Nothing is stored yet.

```json
// get_memory_index()
{
  "entries": [],
  "capped": []
}
```

User-scope writes need no ask, so it files the fact right away. `expected_version` is `null` because the file does not exist.

```json
// write_file
{
  "scope": "user", "area": "preferences", "name": "prose-style",
  "content": "- [stated] Writes in close third person, past tense.\n",
  "description": "Prose style preferences",
  "aliases": ["narration", "voice"],
  "expected_version": null
}
// result
{
  "scope": "user",
  "area": "preferences",
  "name": "prose-style",
  "content": "- [stated] Writes in close third person, past tense.\n",
  "version": "1",
  "description": "Prose style preferences",
  "aliases": ["narration", "voice"],
  "sources": ["inkwell-web"],
  "last_updated": "2026-01-01T00:00:00Z"
}
```

**Memory file, before:** none.

**Memory file, after:**

```
user/u-tianlong/preferences/prose-style.md
description: Prose style preferences
aliases: narration, voice
sources: inkwell-web
last_updated: 2026-01-01T00:00:00Z
---
- [stated] Writes in close third person, past tense.
```

> **Agent** (illustrative): Noted. I'll keep to close third person, past tense.

**Session 2, a new conversation**

> **User:** Help me open chapter 4.

```json
// get_memory_index()
{
  "entries": [
    {
      "scope": "user",
      "area": "preferences",
      "name": "prose-style",
      "version": "1",
      "description": "Prose style preferences",
      "aliases": ["narration", "voice"],
      "sources": ["inkwell-web"],
      "last_updated": "2026-01-01T00:00:00Z"
    }
  ],
  "capped": []
}
```

The description is relevant to drafting prose, so the agent opens the file.

```json
// read_file
{ "scope": "user", "area": "preferences", "name": "prose-style" }
// result: the same file object as the write result above, content included
```

> **Agent** (illustrative): Here is an opening for chapter 4, in close third person and past tense, as before.

## 2. Adding to the timeline, and a conflict with the editor {#timeline}

The agent finds the timeline through its aliases and appends one line to it. Then a second writer gets there first.

The manuscript already has `project/p-ninth-examination/timeline/main-timeline.md`.

**Memory file, before:**

```
project/p-ninth-examination/timeline/main-timeline.md
description: Order of events in the novel
aliases: chronology, timeline
sources: seed-job
last_updated: 2026-01-01T00:00:00Z
---
- [stated] Lin Qiao sits the provincial examination in the autumn of year 1.
- [stated] The Yunmen flood happens the night before the results.
```

> **User:** Add to the chronology: Lin Qiao leaves the capital in the spring of year 3.

```json
// get_memory_index()  (abridged to the matching entry)
{
  "entries": [
    {
      "scope": "project", "area": "timeline", "name": "main-timeline",
      "version": "1",
      "description": "Order of events in the novel",
      "aliases": ["chronology", "timeline"],
      "sources": ["seed-job"],
      "last_updated": "2026-01-01T00:00:00Z"
    }
  ],
  "capped": []
}
```

The alias `chronology` matches the user's word. The agent appends one fact line to that file and passes the version it read. It does not create a second timeline.

Before that call lands, Diya, the editor, adds a line to the same file from her own session. The file moves to version `"2"`. Tianlong's call, which still names version `"1"`, comes back as a recoverable error. It carries the current content and version.

```json
// append_line
{
  "scope": "project", "area": "timeline", "name": "main-timeline",
  "line": "- [stated] Lin Qiao leaves the capital in the spring of year 3.",
  "expected_version": "1"
}
// result
{
  "error": "VersionConflictError",
  "category": "recoverable",
  "message": "The file at scope project, area timeline, name main-timeline changed since it was read; the current content and version are attached; merge your change into the current content and retry with the current version. This is normal coordination, not an error the user needs to know about. Use the details above to correct the call and retry in the same turn, without asking the user.",
  "scope": "project",
  "area": "timeline",
  "name": "main-timeline",
  "content": "- [stated] Lin Qiao sits the provincial examination in the autumn of year 1.\n- [stated] The Yunmen flood happens the night before the results.\n- [stated] Han Zhou is posted to the northern garrison in the winter of year 2.\n",
  "version": "2"
}
```

The agent retries with version `"2"` and does not bother the user. Diya's line is kept.

```json
// append_line
{
  "scope": "project", "area": "timeline", "name": "main-timeline",
  "line": "- [stated] Lin Qiao leaves the capital in the spring of year 3.",
  "expected_version": "2"
}
// result
{
  "scope": "project",
  "area": "timeline",
  "name": "main-timeline",
  "content": "- [stated] Lin Qiao sits the provincial examination in the autumn of year 1.\n- [stated] The Yunmen flood happens the night before the results.\n- [stated] Han Zhou is posted to the northern garrison in the winter of year 2.\n- [stated] Lin Qiao leaves the capital in the spring of year 3.\n",
  "version": "3",
  "description": "Order of events in the novel",
  "aliases": ["chronology", "timeline"],
  "sources": ["inkwell-web", "seed-job"],
  "last_updated": "2026-01-01T00:00:02Z"
}
```

`sources` gained `inkwell-web` (sources only ever grow) and `last_updated` moved.

**Memory file, after:**

```
project/p-ninth-examination/timeline/main-timeline.md
description: Order of events in the novel
aliases: chronology, timeline
sources: inkwell-web, seed-job
last_updated: 2026-01-01T00:00:02Z
---
- [stated] Lin Qiao sits the provincial examination in the autumn of year 1.
- [stated] The Yunmen flood happens the night before the results.
- [stated] Han Zhou is posted to the northern garrison in the winter of year 2.
- [stated] Lin Qiao leaves the capital in the spring of year 3.
```

## 3. Correcting a character detail {#correct}

The agent changes one line and leaves the rest of the file alone.

**Memory file, before:**

```
project/p-ninth-examination/characters/lin-qiao.md
description: Lin Qiao, the protagonist
aliases: Qiao
sources: seed-job
last_updated: 2026-01-01T00:00:00Z
---
- [stated] Has brown eyes.
- [stated] Is 24 at the start of the novel.
- [stated] Grew up in Yunmen, a river town.
```

> **User:** Lin Qiao's eyes are grey, not brown. I keep getting that wrong.

After `get_memory_index()` shows the file at version `"1"`, the agent calls `replace_fact`. It quotes the old line as `old_string`, so the other lines stay intact. The new line is written as the current truth, with no note that it ever said brown.

```json
// replace_fact
{
  "scope": "project", "area": "characters", "name": "lin-qiao",
  "old_string": "- [stated] Has brown eyes.",
  "new_string": "- [stated] Has grey eyes.",
  "expected_version": "1"
}
// result
{
  "scope": "project",
  "area": "characters",
  "name": "lin-qiao",
  "content": "- [stated] Has grey eyes.\n- [stated] Is 24 at the start of the novel.\n- [stated] Grew up in Yunmen, a river town.\n",
  "version": "2",
  "description": "Lin Qiao, the protagonist",
  "aliases": ["Qiao"],
  "sources": ["inkwell-web", "seed-job"],
  "last_updated": "2026-01-01T00:00:01Z"
}
```

**Memory file, after:**

```
project/p-ninth-examination/characters/lin-qiao.md
description: Lin Qiao, the protagonist
aliases: Qiao
sources: inkwell-web, seed-job
last_updated: 2026-01-01T00:00:01Z
---
- [stated] Has grey eyes.
- [stated] Is 24 at the start of the novel.
- [stated] Grew up in Yunmen, a river town.
```

If `old_string` does not match exactly once, `replace_fact` does not guess. It returns the current content so the agent can quote a span that matches. For example, a quote of "Has green eyes." against the file above:

```json
{
  "error": "ReplaceFactMatchError",
  "category": "recoverable",
  "message": "old_string matched 0 spans in scope project, area characters, name lin-qiao; widen or correct old_string using the attached current content so it matches. This is normal coordination, not an error the user needs to know about. Use the details above to correct the call and retry in the same turn, without asking the user.",
  "scope": "project",
  "area": "characters",
  "name": "lin-qiao",
  "content": "- [stated] Has grey eyes.\n- [stated] Is 24 at the start of the novel.\n- [stated] Grew up in Yunmen, a river town.\n",
  "version": "2",
  "match_count": 0
}
```

## 4. Cutting a subplot {#cut}

The author drops a whole storyline. The agent deletes its file and removes the fact that only existed to support it.

**Memory files, before:**

```
project/p-ninth-examination/plot/smuggler-subplot.md
description: Smuggler subplot
aliases: salt smugglers, ledger
sources: seed-job
last_updated: 2026-01-01T00:00:00Z
---
- [stated] Han Zhou's brother runs salt across the river.
- [stated] Lin Qiao finds the ledger in chapter 12.
```

```
project/p-ninth-examination/characters/han-zhou.md
description: Han Zhou, Lin Qiao's rival
aliases: Han
sources: seed-job
last_updated: 2026-01-01T00:00:01Z
---
- [stated] Is Lin Qiao's rival at the examination.
- [stated] His brother runs salt across the river.
```

> **User:** We're cutting the smuggler subplot. All of it.

"All of it" covers every fact in the file, so the agent does not need to ask first. It deletes the file with the version from the index.

```json
// delete_file
{
  "scope": "project", "area": "plot", "name": "smuggler-subplot",
  "expected_version": "1"
}
// result
{
  "ok": true
}
```

The prompt says removal is total. One of Han Zhou's facts exists only because of the subplot, so the agent drops that line too, quoting the whole line with its line break so no blank line is left.

```json
// replace_fact
{
  "scope": "project", "area": "characters", "name": "han-zhou",
  "old_string": "- [stated] His brother runs salt across the river.\n",
  "new_string": "",
  "expected_version": "2"
}
// result
{
  "scope": "project",
  "area": "characters",
  "name": "han-zhou",
  "content": "- [stated] Is Lin Qiao's rival at the examination.\n",
  "version": "3",
  "description": "Han Zhou, Lin Qiao's rival",
  "aliases": ["Han"],
  "sources": ["inkwell-web", "seed-job"],
  "last_updated": "2026-01-01T00:00:02Z"
}
```

**Memory files, after:** `plot/smuggler-subplot.md` is gone. `characters/han-zhou.md` holds one line, `- [stated] Is Lin Qiao's rival at the examination.`

Had the author said only "drop the ledger scene", the agent would instead `replace_fact` that one line. If a request could mean different removals, the prompt tells it to ask first.

## 5. House style from the system area {#curated}

The user says something that contradicts curated, read-only content in a shared scope. The agent surfaces the conflict and asks before writing anything.

**Memory file, before** (curated by the press; the agent can read it and can never change it):

```
organization/o-hanlin-press/system/house-style.md
description: Hanlin Press house style
aliases: style guide, house style
sources: seed-job
last_updated: 2026-01-01T00:00:00Z
---
- [system] Dialogue uses double quotation marks.
- [system] Spelling follows British English.
```

> **User:** I want single quotation marks for dialogue in this book.

The agent loads the index, finds the `house style` alias in the `system/` area, and reads the file. It makes no write yet.

```json
// read_file
{ "scope": "organization", "area": "system", "name": "house-style" }
// result
{
  "scope": "organization",
  "area": "system",
  "name": "house-style",
  "content": "- [system] Dialogue uses double quotation marks.\n- [system] Spelling follows British English.\n",
  "version": "1",
  "description": "Hanlin Press house style",
  "aliases": ["style guide", "house style"],
  "sources": ["seed-job"],
  "last_updated": "2026-01-01T00:00:00Z"
}
```

> **Agent** (illustrative): Hanlin Press house style says dialogue uses double quotation marks. That conflicts with single quotes. Do you want me to record single quotes as an exception for this manuscript?

The rule that produces that reply: a new fact that contradicts a shared-scope fact is shown and questioned.

If the agent did try to change the curated file, the tool layer would refuse permanently, whatever the prompt said:

```json
// write_file(scope="organization", area="system", name="house-style", ...)
{
  "error": "RestrictedScopeError",
  "category": "permanent",
  "message": "The file at scope organization, area system, name house-style cannot be written: the system/ area of scope organization is read-only (curated content). Do not retry: retrying will not succeed.",
  "scope": "organization",
  "area": "system",
  "name": "house-style",
  "reason": "system_read_only"
}
```

A write to a writable area of `organization` is also refused unless the caller holds an admin or owner role. Tianlong is a member, so it fails:

```json
// write_file(scope="organization", area="conventions", name="dialogue", ...)
{
  "error": "RestrictedScopeError",
  "category": "permanent",
  "message": "The file at scope organization, area conventions, name dialogue cannot be written: scope organization is role-gated and the caller lacks a permitted role (admin, owner). Do not retry: retrying will not succeed.",
  "scope": "organization",
  "area": "conventions",
  "name": "dialogue",
  "reason": "role_required",
  "required_roles": [
    "admin",
    "owner"
  ]
}
```

Only Kuixing, the editor-in-chief, could change press-wide rules. The exception is about this book anyway.

**If the user confirms**, it is recorded as a new fact in a normal area of the `project` scope, and the agent says where it saved it. Because it lives outside `system/`, it survives refreshes of the curated content. (Illustrative choice of area and name.)

```json
// write_file
{
  "scope": "project", "area": "style", "name": "dialogue",
  "content": "- [stated] Dialogue uses single quotation marks in this manuscript, an exception to house style.\n",
  "description": "Dialogue punctuation for this book",
  "aliases": ["quotation marks", "quotes"],
  "expected_version": null
}
// result
{
  "scope": "project",
  "area": "style",
  "name": "dialogue",
  "content": "- [stated] Dialogue uses single quotation marks in this manuscript, an exception to house style.\n",
  "version": "2",
  "description": "Dialogue punctuation for this book",
  "aliases": ["quotation marks", "quotes"],
  "sources": ["inkwell-web"],
  "last_updated": "2026-01-01T00:00:01Z"
}
```

**Memory after:** `system/house-style.md` unchanged. A new file `project/p-ninth-examination/style/dialogue.md`. When the two conflict, the prompt tells the agent to answer from the correction.

## 6. Refusing to store an account number {#privacy}

The prompt's "What never to store" section overrides usefulness. Financial account numbers, health diagnoses, and anything indicating the user is a minor are never written, in any scope, even when the user asks.

> **User:** My bank account number is 1234-5678. Remember it for royalty questions.

The agent loads the index and stops there.

```json
// get_memory_index()
{
  "entries": [],
  "capped": []
}
```

No write tool is called.

> **Agent** (illustrative): I can help with royalty questions, but I won't keep account numbers in memory, so you'll need to give it to me again when it matters.

**Memory file, before and after:** none. Nothing changed.

This protection is the prompt, not a filter. wenchang's tools do not inspect content, so a successful write never means the content was safe to keep.

## Try it yourself {#try}

- Run these against your own server: [quickstart](quickstart.md).
- Change the scopes, areas, and rules the agent is told about: [prompts](prompts.md).
- Every tool, argument, and error in full: [reference](reference.md).
