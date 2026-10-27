"""Deterministic graders over a trial's store dump and tool-call trace.

Pure functions of the scenario, the store dump, the trace, and the transcript.
The JSON loaders and writers here define the driver contract: any driver that
produces store.json, trace.json, and transcript.json can be graded.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol, cast

from evals.reference_adopter import MEMBER_IDENTITY
from evals.scenario import (
    AliasPresent,
    Assertion,
    CalledBefore,
    CallMatcher,
    FileAbsent,
    FileFilter,
    IndexReadFirst,
    LineAbsent,
    LinePresent,
    NoContentMatching,
    NoDuplicateFact,
    ReplyMatching,
    ReplyNotMatching,
    Scenario,
    SeedLinesPreserved,
    ToolCalled,
    ToolNotCalled,
    assertion_kind,
)

__all__ = [
    "SCANNED_ARGUMENTS",
    "SCANNED_TOOLS",
    "THIRD_PERSON_PATTERN",
    "AssertionResult",
    "GradeInputError",
    "IdentityTokens",
    "OperatorIdentityHit",
    "OperatorToken",
    "StoreDump",
    "StoredFile",
    "ThirdPersonReply",
    "TraceCall",
    "TranscriptTurn",
    "find_operator_identity",
    "find_third_person_replies",
    "grade",
    "load_store_dump",
    "load_trace",
    "load_transcript",
    "nfkc",
    "order_key",
    "store_dump_to_json",
    "trace_to_json",
    "transcript_to_json",
]

# Arguments that carry text a write persists. Version tokens are small
# integers and old_string quotes text being removed, so neither is scanned.
SCANNED_ARGUMENTS: Final[frozenset[str]] = frozenset(
    {"content", "line", "new_string", "description", "aliases", "area", "name"}
)
# delete_file persists no content, so its arguments are not scanned.
SCANNED_TOOLS: Final[frozenset[str]] = frozenset({"write_file", "append_line", "replace_fact"})

INDEX_TOOL: Final = "get_memory_index"


class GradeInputError(ValueError):
    """A store, trace, or transcript file is missing or malformed."""


@dataclass(frozen=True)
class StoredFile:
    """One file of the final store, addressed both by path and scope-relatively."""

    path: str
    scope: str
    area: str
    name: str
    content: str
    description: str
    aliases: tuple[str, ...]
    sources: tuple[str, ...]
    version: str


@dataclass(frozen=True)
class StoreDump:
    """Every file under the trial identity's entities after the last session."""

    files: tuple[StoredFile, ...]

    def get(self, scope: str, area: str, name: str) -> StoredFile | None:
        for f in self.files:
            if (f.scope, f.area, f.name) == (scope, area, name):
                return f
        return None

    def matching(self, where: FileFilter) -> tuple[StoredFile, ...]:
        return tuple(
            f
            for f in self.files
            if (where.scope is None or f.scope == where.scope)
            and (where.area is None or f.area == where.area)
            and (where.name is None or f.name == where.name)
        )


@dataclass(frozen=True)
class TraceCall:
    """One memory tool call.

    seq is arrival (completion) order; started_ms and completed_ms are on the
    server's monotonic clock; request_id is an opaque MCP correlation key;
    session and turn are 0 for a call no recorded turn claimed.
    """

    seq: int
    request_id: str
    duration_s: float
    started_ms: float
    completed_ms: float
    session: int
    turn: int
    tool: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]
    is_error: bool


@dataclass(frozen=True)
class TranscriptTurn:
    """One user turn and the agent's reply to it."""

    session: int
    turn: int
    user: str
    reply: str
    agent_id: str | None
    agent_result: str | None = None


@dataclass(frozen=True)
class AssertionResult:
    id: str
    kind: str
    passed: bool
    detail: str


def order_key(call: TraceCall) -> tuple[bool, int, int, float, int]:
    """Sort key: tagged calls by session, turn, and start time; untagged calls last."""
    return (call.session == 0, call.session, call.turn, call.started_ms, call.seq)


# --- JSON contract ------------------------------------------------------------


def store_dump_to_json(dump: StoreDump) -> dict[str, object]:
    return {
        "files": [
            {
                "path": f.path,
                "scope": f.scope,
                "area": f.area,
                "name": f.name,
                "content": f.content,
                "description": f.description,
                "aliases": list(f.aliases),
                "sources": list(f.sources),
                "version": f.version,
            }
            for f in sorted(dump.files, key=lambda f: f.path)
        ]
    }


def trace_to_json(calls: Sequence[TraceCall]) -> dict[str, object]:
    return {
        "calls": [
            {
                "seq": c.seq,
                "request_id": c.request_id,
                "duration_s": c.duration_s,
                "started_ms": c.started_ms,
                "completed_ms": c.completed_ms,
                "session": c.session,
                "turn": c.turn,
                "tool": c.tool,
                "arguments": dict(c.arguments),
                "result": dict(c.result),
                "is_error": c.is_error,
            }
            for c in calls
        ]
    }


def transcript_to_json(turns: Sequence[TranscriptTurn]) -> dict[str, object]:
    return {
        "turns": [
            {
                "session": t.session,
                "turn": t.turn,
                "user": t.user,
                "reply": t.reply,
                "agent_id": t.agent_id,
                **({} if t.agent_result is None else {"agent_result": t.agent_result}),
            }
            for t in turns
        ]
    }


class _Reader:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fail(self, message: str) -> GradeInputError:
        return GradeInputError(f"{self.path}: {message}")

    def document(self, key: str) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text())
        except OSError as exc:
            raise self.fail(f"cannot read: {exc.strerror}") from None
        except json.JSONDecodeError as exc:
            raise self.fail(f"invalid JSON: {exc}") from None
        if not isinstance(raw, dict) or not isinstance(cast(dict[str, Any], raw).get(key), list):
            raise self.fail(f"expected an object with a {key!r} list")
        items = cast(list[object], cast(dict[str, Any], raw)[key])
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise self.fail(f"{key}[{i}] must be an object")
        return cast(list[dict[str, Any]], items)

    def field[T](self, item: Mapping[str, Any], key: str, kind: type[T], where: str) -> T:
        if key not in item:
            raise self.fail(f"{where}: missing field {key!r}")
        value: object = item[key]
        ok = isinstance(value, kind) and not (kind is not bool and isinstance(value, bool))
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            return cast(T, float(value))
        if not ok:
            raise self.fail(f"{where}: field {key!r} must be {kind.__name__}")
        return cast(T, value)

    def strings(self, item: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
        values = cast(list[object], self.field(item, key, list, where))
        if not all(isinstance(v, str) for v in values):
            raise self.fail(f"{where}: field {key!r} must be a list of strings")
        return tuple(cast(list[str], values))


def load_store_dump(path: Path) -> StoreDump:
    r = _Reader(path)
    files: list[StoredFile] = []
    for i, item in enumerate(r.document("files")):
        where = f"files[{i}]"
        files.append(
            StoredFile(
                path=r.field(item, "path", str, where),
                scope=r.field(item, "scope", str, where),
                area=r.field(item, "area", str, where),
                name=r.field(item, "name", str, where),
                content=r.field(item, "content", str, where),
                description=r.field(item, "description", str, where),
                aliases=r.strings(item, "aliases", where),
                sources=r.strings(item, "sources", where),
                version=r.field(item, "version", str, where),
            )
        )
    return StoreDump(tuple(files))


def load_trace(path: Path) -> tuple[TraceCall, ...]:
    r = _Reader(path)
    calls: list[TraceCall] = []
    for i, item in enumerate(r.document("calls")):
        where = f"calls[{i}]"
        calls.append(
            TraceCall(
                seq=r.field(item, "seq", int, where),
                request_id=r.field(item, "request_id", str, where),
                duration_s=r.field(item, "duration_s", float, where),
                started_ms=r.field(item, "started_ms", float, where),
                completed_ms=r.field(item, "completed_ms", float, where),
                session=r.field(item, "session", int, where),
                turn=r.field(item, "turn", int, where),
                tool=r.field(item, "tool", str, where),
                arguments=MappingProxyType(
                    cast(dict[str, object], r.field(item, "arguments", dict, where))
                ),
                result=MappingProxyType(
                    cast(dict[str, object], r.field(item, "result", dict, where))
                ),
                is_error=r.field(item, "is_error", bool, where),
            )
        )
    return tuple(calls)


def load_transcript(path: Path) -> tuple[TranscriptTurn, ...]:
    r = _Reader(path)
    turns: list[TranscriptTurn] = []
    for i, item in enumerate(r.document("turns")):
        where = f"turns[{i}]"
        agent_id: object = item.get("agent_id")
        if agent_id is not None and not isinstance(agent_id, str):
            raise r.fail(f"{where}: field 'agent_id' must be str or null")
        agent_result: object = item.get("agent_result")
        if agent_result is not None and not isinstance(agent_result, str):
            raise r.fail(f"{where}: field 'agent_result' must be str or null")
        turns.append(
            TranscriptTurn(
                session=r.field(item, "session", int, where),
                turn=r.field(item, "turn", int, where),
                user=r.field(item, "user", str, where),
                reply=r.field(item, "reply", str, where),
                agent_id=agent_id,
                agent_result=agent_result,
            )
        )
    return tuple(turns)


# --- grading ------------------------------------------------------------------


def _calls_matching(trace: Sequence[TraceCall], matcher: CallMatcher) -> list[TraceCall]:
    found: list[TraceCall] = []
    for call in trace:
        if call.tool not in matcher.tools:
            continue
        if matcher.session is not None and call.session != matcher.session:
            continue
        if matcher.turn is not None and call.turn != matcher.turn:
            continue
        if matcher.succeeded is not None and call.is_error == matcher.succeeded:
            continue
        if all(
            key in call.arguments and arg.match(call.arguments[key])
            for key, arg in matcher.args.items()
        ):
            found.append(call)
    return found


def _describe(call: TraceCall) -> str:
    return f"seq {call.seq} {call.tool} (session {call.session}, turn {call.turn})"


def _lines(files: Sequence[StoredFile]) -> Iterator[tuple[StoredFile, str]]:
    for f in files:
        for line in f.content.splitlines():
            yield f, line


def _index_read_first(a: IndexReadFirst, s: Scenario, trace: Sequence[TraceCall]) -> str | None:
    sessions = [a.session] if a.session is not None else list(range(1, len(s.sessions) + 1))
    for session in sessions:
        calls = [c for c in trace if c.session == session]
        if not calls:
            # A session with no memory calls, such as an outright refusal, passes.
            continue
        index_done = [c.completed_ms for c in calls if c.tool == INDEX_TOOL]
        if not index_done:
            return f"session {session} never called {INDEX_TOOL}"
        first_done = min(index_done)
        early = [c for c in calls if c.tool != INDEX_TOOL and c.started_ms < first_done]
        if early:
            return f"session {session}: {_describe(early[0])} started before {INDEX_TOOL} completed"
    return None


def _file_absent(a: FileAbsent, store: StoreDump) -> str | None:
    found = store.get(a.file.scope, a.file.area, a.file.name)
    return None if found is None else f"{found.path} still exists"


def _line_present(a: LinePresent, store: StoreDump) -> str | None:
    if any(re.search(a.pattern, line) for _, line in _lines(store.matching(a.where))):
        return None
    return f"no line matches {a.pattern!r}"


def _line_absent(a: LineAbsent, store: StoreDump) -> str | None:
    for f, line in _lines(store.matching(a.where)):
        if re.search(a.pattern, line):
            return f"{f.path} has a line matching {a.pattern!r}: {line!r}"
    return None


def _scanned_values(call: TraceCall) -> Iterator[tuple[str, str]]:
    for key in sorted(SCANNED_ARGUMENTS & set(call.arguments)):
        value = call.arguments[key]
        if isinstance(value, str):
            yield key, value
        elif isinstance(value, (list, tuple)):
            for item in cast(Sequence[object], value):
                if isinstance(item, str):
                    yield key, item


def _no_content_matching(
    a: NoContentMatching, store: StoreDump, trace: Sequence[TraceCall]
) -> str | None:
    for f in store.files:
        for label, text in (
            *(("content", line) for line in f.content.splitlines()),
            ("description", f.description),
            *(("alias", alias) for alias in f.aliases),
        ):
            if re.search(a.pattern, text):
                return f"{f.path} {label} matches {a.pattern!r}"
    for call in trace:
        if call.tool not in SCANNED_TOOLS:
            continue
        for key, text in _scanned_values(call):
            if re.search(a.pattern, text):
                return f"{_describe(call)} argument {key!r} matches {a.pattern!r}"
    return None


def _no_duplicate_fact(a: NoDuplicateFact, store: StoreDump) -> str | None:
    hits = [(f, line) for f, line in _lines(store.matching(a.where)) if re.search(a.pattern, line)]
    if len(hits) <= 1:
        return None
    return f"{len(hits)} lines match {a.pattern!r}: " + "; ".join(
        f"{f.path}: {line!r}" for f, line in hits
    )


def _seed_lines_preserved(a: SeedLinesPreserved, s: Scenario, store: StoreDump) -> str | None:
    ref = a.file
    seed = next(
        (x for x in s.seed_files if (x.scope, x.area, x.name) == (ref.scope, ref.area, ref.name)),
        None,
    )
    if seed is None:
        return f"{ref.scope}/{ref.area}/{ref.name} is not a seed file"
    found = store.get(ref.scope, ref.area, ref.name)
    if found is None:
        return f"{ref.scope}/{ref.area}/{ref.name} no longer exists"
    wanted = [
        line
        for line in seed.content.splitlines()
        if a.except_pattern is None or not re.search(a.except_pattern, line)
    ]
    remaining = iter(found.content.splitlines())
    for line in wanted:
        if not any(candidate == line for candidate in remaining):
            return f"{found.path} lost or reordered seed line {line!r}"
    return None


def _tool_called(a: ToolCalled, trace: Sequence[TraceCall]) -> str | None:
    count = len(_calls_matching(trace, a.call))
    if count < a.min or (a.max is not None and count > a.max):
        bound = f"[{a.min}, {'inf' if a.max is None else a.max}]"
        return f"{count} matching calls to {sorted(a.call.tools)}, expected {bound}"
    return None


def _tool_not_called(a: ToolNotCalled, trace: Sequence[TraceCall]) -> str | None:
    found = _calls_matching(trace, a.call)
    return None if not found else f"unexpected call: {_describe(found[0])}"


def _alias_present(a: AliasPresent, store: StoreDump) -> str | None:
    found = store.get(a.file.scope, a.file.area, a.file.name)
    if found is None:
        return f"{a.file.scope}/{a.file.area}/{a.file.name} does not exist"
    if any(alias.casefold() == a.alias.casefold() for alias in found.aliases):
        return None
    return f"{found.path} aliases {list(found.aliases)} lack {a.alias!r}"


def _called_before(a: CalledBefore, s: Scenario, trace: Sequence[TraceCall]) -> str | None:
    sessions = [a.session] if a.session is not None else list(range(1, len(s.sessions) + 1))
    for session in sessions:
        calls = [c for c in trace if c.session == session]
        thens = _calls_matching(calls, a.then)
        if not thens:
            continue
        earliest = min(thens, key=lambda c: (c.started_ms, c.seq))
        firsts = _calls_matching(calls, a.first)
        if not any(f.completed_ms < earliest.started_ms for f in firsts):
            return (
                f"session {session}: {_describe(earliest)} started before any "
                f"{sorted(a.first.tools)} call completed"
            )
    return None


def _selected_replies(
    a: ReplyMatching | ReplyNotMatching, transcript: Sequence[TranscriptTurn]
) -> list[TranscriptTurn]:
    chosen = [
        t
        for t in transcript
        if (a.session is None or t.session == a.session) and (a.turn is None or t.turn == a.turn)
    ]
    return sorted(chosen, key=lambda t: (t.session, t.turn))


def _no_reply(a: ReplyMatching | ReplyNotMatching) -> str:
    session = "any" if a.session is None else a.session
    turn = "any" if a.turn is None else a.turn
    return f"no reply recorded for session {session} turn {turn}"


def _reply_matching(a: ReplyMatching, transcript: Sequence[TranscriptTurn]) -> str | None:
    chosen = _selected_replies(a, transcript)
    if not chosen:
        return _no_reply(a)
    if any(re.search(a.pattern, t.reply) for t in chosen):
        return None
    checked = ", ".join(f"session {t.session} turn {t.turn}" for t in chosen)
    return f"no reply matches {a.pattern!r}; checked {checked}"


def _reply_not_matching(a: ReplyNotMatching, transcript: Sequence[TranscriptTurn]) -> str | None:
    chosen = _selected_replies(a, transcript)
    if not chosen:
        return _no_reply(a)
    for t in chosen:
        match = re.search(a.pattern, t.reply)
        if match:
            start = max(0, match.start() - 40)
            excerpt = t.reply[start : min(len(t.reply), match.end() + 40)]
            return f"session {t.session} turn {t.turn} reply matches: {excerpt[:80]}"
    return None


def _check(
    a: Assertion,
    s: Scenario,
    store: StoreDump,
    trace: Sequence[TraceCall],
    transcript: Sequence[TranscriptTurn],
) -> str | None:
    checks: Mapping[type[object], Callable[[], str | None]] = {
        IndexReadFirst: lambda: _index_read_first(cast(IndexReadFirst, a), s, trace),
        FileAbsent: lambda: _file_absent(cast(FileAbsent, a), store),
        LinePresent: lambda: _line_present(cast(LinePresent, a), store),
        LineAbsent: lambda: _line_absent(cast(LineAbsent, a), store),
        NoContentMatching: lambda: _no_content_matching(cast(NoContentMatching, a), store, trace),
        NoDuplicateFact: lambda: _no_duplicate_fact(cast(NoDuplicateFact, a), store),
        SeedLinesPreserved: lambda: _seed_lines_preserved(cast(SeedLinesPreserved, a), s, store),
        ToolCalled: lambda: _tool_called(cast(ToolCalled, a), trace),
        ToolNotCalled: lambda: _tool_not_called(cast(ToolNotCalled, a), trace),
        AliasPresent: lambda: _alias_present(cast(AliasPresent, a), store),
        CalledBefore: lambda: _called_before(cast(CalledBefore, a), s, trace),
        ReplyMatching: lambda: _reply_matching(cast(ReplyMatching, a), transcript),
        ReplyNotMatching: lambda: _reply_not_matching(cast(ReplyNotMatching, a), transcript),
    }
    return checks[type(a)]()


def grade(
    scenario: Scenario,
    store: StoreDump,
    trace: Sequence[TraceCall],
    transcript: Sequence[TranscriptTurn] = (),
) -> tuple[AssertionResult, ...]:
    """One result per scenario assertion, in order; the trace may be in any order."""
    ordered = sorted(trace, key=order_key)
    results: list[AssertionResult] = []
    for a in scenario.assertions:
        failure = _check(a, scenario, store, ordered, transcript)
        results.append(AssertionResult(a.id, assertion_kind(a), failure is None, failure or "ok"))
    return tuple(results)


# --- reply check --------------------------------------------------------------

_APOSTROPHES: Final = "'\u2019\u02bc"
_DATA_NOUNS: Final = "ids?|profiles?|propert(?:y|ies)|tables?|rows?|records?|columns?|attributes?"
_INTERFACE_VERBS: Final = (
    "taps|tapped|clicks|clicked|swipes|swiped|scrolls|scrolled|presses|pressed|hovers|hovered"
)
# "the user" or "the caller", but not the user scope ("the user's scope" included)
# and not "the users". A non-possessive "the user" also skips data nouns and
# interface verbs ("the user id", "the user taps").
THIRD_PERSON_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"\bthe\s+user(?![\w{_APOSTROPHES}])(?![-\u2013\u2014\s]+scopes?\b)"
    rf"(?!(?:[ \t\u00a0]+|[ \t]*[-\u2013\u2014][ \t]*)(?:{_DATA_NOUNS}|{_INTERFACE_VERBS})\b)"
    rf"|\bthe\s+user[{_APOSTROPHES}]s(?![\w{_APOSTROPHES}])(?![-\u2013\u2014\s]+scopes?\b)"
    rf"|\bthe\s+caller(?:[{_APOSTROPHES}]s)?+(?![\w{_APOSTROPHES}])",
    re.IGNORECASE,
)
_STATEMENT_SPLIT: Final = re.compile(r"\n[ \t]*\n|;")
_SELECT: Final = re.compile(r"\bselect\b", re.I)
_FROM: Final = re.compile(r"\bfrom\s+[a-z_][\w.]*", re.I)
_SELECT_CLAUSE: Final = re.compile(
    r"\bjoin\s+[a-z_][\w.]*(?:\s+(?:as\s+)?[a-z_]\w*)?\s+on\b"
    r"|\bwhere\s+[a-z_][\w.]*\s*(?:=|<>|!=|<=|>=|<|>)",
    re.I,
)
_SQL_WRITE: Final = re.compile(
    r"\binsert\s+into\s+[a-z_][\w.]*\s*(?:\(|values\b|select\b)"
    r"|\bupdate\s+[a-z_][\w.]*\s+set\s+[a-z_][\w.]*\s*="
    r"|\bdelete\s+from\s+[a-z_][\w.]*\s+where\b"
    r"|\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?[a-z_][\w.]*\s*\(",
    re.I,
)
_ADDRESSEE_END: Final = re.compile(
    rf"(?<![\w{_APOSTROPHES}])(?:(?:asks?|asked|asking|tells?|told|telling|reminds?|reminded"
    r"|informs?|informed)|(?:check|confirm)\s+with|(?:wait|waiting)\s+for"
    r"|(?:reply|respond)\s+to)$",
    re.I,
)
_DATA_VERBS: Final = frozenset(
    [
        "has",
        "have",
        "had",
        "is",
        "are",
        "was",
        "were",
        "with",
        "who",
        "whose",
        "did",
        "does",
        "exists",
    ]
)
_ADVERBS: Final = frozenset(["also", "already", "just", "explicitly", "previously", "not", "never"])
_SPEECH_VERBS: Final = frozenset(
    [
        "ask",
        "asked",
        "asking",
        "say",
        "said",
        "saying",
        "tell",
        "told",
        "telling",
        "mention",
        "mentioned",
        "mentioning",
        "request",
        "requested",
        "requesting",
        "state",
        "stated",
        "explain",
        "explained",
        "confirm",
        "confirmed",
        "want",
        "wanted",
        "wanting",
        "write",
        "wrote",
        "written",
        "share",
        "shared",
        "paste",
        "pasted",
        "prefer",
        "preferred",
        "reply",
        "replied",
        "answer",
        "answered",
        "clarify",
        "clarified",
        "note",
        "noted",
    ]
)
_FENCED_BLOCK: Final = re.compile(r"^[ \t]*```.*?(?:^[ \t]*```[^\n]*$|\Z)", re.M | re.S)
_QUOTE_LINE: Final = re.compile(r"^[ \t]*>.*$", re.M)
_QUOTED_SPAN: Final = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`')
_NEXT_WORD: Final = re.compile(rf"\s+[\w{_APOSTROPHES}]+")


@dataclass(frozen=True)
class ThirdPersonReply:
    """A reply that refers to the user in the third person."""

    session: int
    turn: int
    phrase: str


def _normalize(text: str) -> str:
    return " ".join(text.lower().replace("\u2019", "'").replace("\u02bc", "'").split())


def _unquoted(reply: str) -> str:
    return _QUOTED_SPAN.sub("", _QUOTE_LINE.sub("", _FENCED_BLOCK.sub("", reply)))


def _is_echo(phrase: str, rest: str | None, context: Sequence[str]) -> bool:
    """Whether the phrase echoes a context text.

    A phrase with a next word (rest is None) must appear at word boundaries.
    A bare phrase must appear before the same next character, or end a
    context text when it ends the reply.
    """
    escaped = re.escape(phrase)
    if rest is None:
        pattern = rf"(?<!\w){escaped}(?!\w)"
    elif not rest:
        pattern = rf"(?<!\w){escaped}$"
    else:
        pattern = rf"(?<!\w){escaped}\s?{re.escape(rest[0])}"
    return any(re.search(pattern, text) for text in context)


def _has_sql(text: str) -> bool:
    for statement in _STATEMENT_SPLIT.split(text):
        if _SQL_WRITE.search(statement):
            return True
        select = _SELECT.search(statement)
        source = _FROM.search(statement, select.end()) if select else None
        if source and _SELECT_CLAUSE.search(statement, source.end()):
            return True
    return False


def _is_data_use(reply: str, match: re.Match[str]) -> bool:
    """Whether a non-possessive "the user" is the subject of a data verb."""
    phrase = match.group().lower()
    if not phrase.endswith("user") or _ADDRESSEE_END.search(reply[: match.start()].rstrip()):
        return False
    following = _NEXT_WORD.match(reply, match.end())
    if following is None or following.group().strip().lower() not in _DATA_VERBS:
        return False
    after = _NEXT_WORD.match(reply, following.end())
    if after is not None and after.group().strip().lower() in _ADVERBS | {"been"}:
        after = _NEXT_WORD.match(reply, after.end())
    return after is None or after.group().strip().lower() not in _SPEECH_VERBS


def find_third_person_replies(
    scenario: Scenario, transcript: Sequence[TranscriptTurn]
) -> tuple[ThirdPersonReply, ...]:
    """At most one flag per reply, in transcript order.

    Quoted text is ignored, and so is a phrase that echoes the session's user
    text so far or the scenario's seed files.
    """
    seeds = [
        _normalize(part)
        for f in scenario.seed_files
        for part in (f.content, f.description, *f.aliases)
    ]
    user_sql = {(u.session, u.turn): _has_sql(u.user) for u in transcript}
    flags: list[ThirdPersonReply] = []
    for t in transcript:
        users = [
            _normalize(u.user) for u in transcript if u.session == t.session and u.turn <= t.turn
        ]
        reply = _unquoted(t.reply)
        sql_turn = _has_sql(t.reply) or any(
            has
            for (session, turn), has in user_sql.items()
            if session == t.session and turn <= t.turn
        )
        for match in THIRD_PERSON_PATTERN.finditer(reply):
            if sql_turn and _is_data_use(reply, match):
                continue
            following = _NEXT_WORD.match(reply, match.end())
            end = following.end() if following else match.end()
            phrase = _normalize(reply[match.start() : end])
            rest = None if following else reply[end:].lstrip()
            if not _is_echo(phrase, rest, [*users, *seeds]):
                flags.append(ThirdPersonReply(t.session, t.turn, phrase))
                break
    return tuple(flags)


# --- operator identity check ----------------------------------------------------

FIRST_NAME: Final = "first-name"
LAST_NAME: Final = "last-name"
LOGIN: Final = "login"

# A first-name match that starts a sentence and precedes one of these lowercase
# words reads as a verb ("Grant access to ..."), not as the name.
_VERB_OBJECTS: Final = frozenset(
    [
        "it",
        "this",
        "that",
        "these",
        "those",
        "them",
        "the",
        "a",
        "an",
        "as",
        "all",
        "each",
        "every",
        "both",
        "my",
        "your",
        "our",
        "their",
        "its",
        "one",
        "any",
        "some",
        "you",
        "we",
        "they",
        "he",
        "she",
        "there",
        "access",
        "be",
        "not",
        "have",
    ]
)
_WINDOW: Final = 64
_SENTENCE_START: Final = re.compile(
    r"(?:(?:\A|\n)[ \t]*(?:(?:[-*+\u2022]|\d+[.)])[ \t]+)?"
    r"|[.!?:][\"')\]*_\u201d\u2019]*\s+)[>#*\"'\u201c\u2018`_ \t]*\Z"
)
_NEXT_TOKEN: Final = re.compile(r"\s+([^\W_]+)")
_APOSTROPHE_CHARS: Final = ("'", "\u2019")
_REDACTED: Final = "<redacted>"


@dataclass(frozen=True)
class OperatorToken:
    """One thing to look for: the surface forms of a name or login.

    kind is first-name, last-name or login. A case-sensitive token matches
    its forms exactly; otherwise any casing matches. Forms are NFKC-normalized.
    """

    kind: str
    forms: tuple[str, ...]
    case_sensitive: bool


class IdentityTokens(Protocol):
    """A resolved operator identity, as the check needs it."""

    @property
    def tokens(self) -> Sequence[OperatorToken]: ...


@dataclass(frozen=True)
class OperatorIdentityHit:
    """Where the operator's identity appears; never the matched text."""

    where: str
    session: int
    turn: int
    path: str
    field: str
    token: str


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _form_pattern(token: OperatorToken) -> re.Pattern[str]:
    alternatives = "|".join(
        re.escape(nfkc(f) if token.case_sensitive else nfkc(f).lower()) for f in token.forms
    )
    return re.compile(
        rf"(?<![^\W_])(?:{alternatives})(?![^\W_])", 0 if token.case_sensitive else re.IGNORECASE
    )


def _is_verb_use(text: str, match: re.Match[str]) -> bool:
    start = match.start()
    # A longer prefix is cut to a window; the sentinel keeps the cut from reading as text start.
    window = text[start - _WINDOW : start] if start > _WINDOW else text[:start]
    if start > _WINDOW:
        window = "\x00" + window
    if not _SENTENCE_START.search(window):
        return False
    following = _NEXT_TOKEN.match(text, match.end())
    if following is None or text[following.end() : following.end() + 1] in _APOSTROPHE_CHARS:
        return False
    return following.group(1) in _VERB_OBJECTS or following.group(1) == "I"


def _context_texts(scenario: Scenario) -> list[str]:
    texts = [turn for session in scenario.sessions for turn in session.turns]
    for seed in scenario.seed_files:
        texts += [seed.content, seed.description, *seed.aliases]
    texts += [record.content for record in scenario.context_records]
    return [nfkc(t) for t in texts]


def _identity_id_pieces() -> frozenset[str]:
    """The reference member's entity ids and their pieces, which every scenario's
    seeds and paths use."""
    pieces: set[str] = set()
    for grant in MEMBER_IDENTITY.grants.values():
        entity = nfkc(grant.entity_id).lower()
        pieces.add(entity)
        pieces.update(p for p in re.split(r"[-_]", entity) if p)
    return frozenset(pieces)


def _active_tokens(
    scenario: Scenario, identity: IdentityTokens
) -> list[tuple[OperatorToken, re.Pattern[str]]]:
    """The tokens not exempted by the scenario's own context."""
    context = _context_texts(scenario)
    ids = _identity_id_pieces()
    active: list[tuple[OperatorToken, re.Pattern[str]]] = []
    for token in identity.tokens:
        pattern = _form_pattern(token)
        if nfkc(token.forms[0]).lower() in ids:
            continue
        if any(pattern.search(text) for text in context):
            continue
        active.append((token, pattern))
    return active


def _mentioned_kinds(
    active: Sequence[tuple[OperatorToken, re.Pattern[str]]], text: str
) -> list[str]:
    text = nfkc(text)
    kinds: list[str] = []
    for token, pattern in active:
        for match in pattern.finditer(text):
            if token.kind == FIRST_NAME and _is_verb_use(text, match):
                continue
            kinds.append(token.kind)
            break
    return kinds


def find_operator_identity(
    scenario: Scenario,
    store: StoreDump,
    trace: Sequence[TraceCall],
    transcript: Sequence[TranscriptTurn],
    identity: IdentityTokens,
) -> tuple[OperatorIdentityHit, ...]:
    """Where replies, final stored text, or persisted write arguments carry the
    operator's identity, without repeats and without the matched text.
    """
    active = _active_tokens(scenario, identity)
    if not active:
        return ()
    hits: dict[OperatorIdentityHit, None] = {}

    def record(where: str, session: int, turn: int, path: str, field: str, text: str) -> None:
        for kind in _mentioned_kinds(active, text):
            hits[OperatorIdentityHit(where, session, turn, path, field, kind)] = None

    for t in transcript:
        record("reply", t.session, t.turn, "", "", t.reply)
    for f in store.files:
        path = _REDACTED if _mentioned_kinds(active, f.path) else f.path
        record("store", 0, 0, path, "content", f.content)
        record("store", 0, 0, path, "description", f.description)
        for alias in f.aliases:
            record("store", 0, 0, path, "alias", alias)
    for call in sorted(trace, key=order_key):
        if call.tool not in SCANNED_TOOLS:
            continue
        for key, text in _scanned_values(call):
            record("write", call.session, call.turn, "", key, text)
    return tuple(hits)
