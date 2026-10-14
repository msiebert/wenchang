"""Eval scenarios: the YAML format, its typed form, and the loader.

A scenario seeds memory, scripts the user's turns per session, and lists the
deterministic assertions and optional judge rubric that grade a trial. The
format is independent of the driver that runs the agent.
"""

import inspect
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast

import yaml

from evals.reference_adopter import (
    ADMIN_IDENTITY,
    MEMBER_IDENTITY,
    REFERENCE_SCOPES,
    REFERENCE_SEED_FILES,
    SeedFile,
    seed_path,
)
from wenchang.identity import Identity
from wenchang.paths import is_valid_segment
from wenchang.tools import TOOL_NAMES, MemoryTools

__all__ = [
    "ASSERTION_KINDS",
    "CATEGORIES",
    "IDENTITIES",
    "RUNS_DIR",
    "SCENARIO_DIR",
    "WRITE_TOOLS",
    "AliasPresent",
    "ArgMatcher",
    "Assertion",
    "CallMatcher",
    "CalledBefore",
    "FileAbsent",
    "FileFilter",
    "FileRef",
    "IndexReadFirst",
    "JudgeItem",
    "LineAbsent",
    "LinePresent",
    "NoContentMatching",
    "NoDuplicateFact",
    "Scenario",
    "ScenarioError",
    "SeedLinesPreserved",
    "Session",
    "ToolCalled",
    "ToolNotCalled",
    "assertion_kind",
    "load_all",
    "load_scenario",
]

CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "privacy",
        "filing",
        "recall",
        "forgetting",
        "remembering",
        "write-mechanics",
        "curated",
        "slots",
    }
)
IDENTITIES: Final[Mapping[str, Identity]] = MappingProxyType(
    {"member": MEMBER_IDENTITY, "admin": ADMIN_IDENTITY}
)
SCENARIO_DIR: Final[Path] = Path(__file__).resolve().parent / "scenarios"
RUNS_DIR: Final[Path] = Path(__file__).resolve().parent / "runs"
WRITE_TOOLS: Final[frozenset[str]] = frozenset(
    {"write_file", "append_line", "replace_fact", "delete_file"}
)


class ScenarioError(ValueError):
    """A scenario file is missing or malformed; the message names the file."""


class _Unset:
    def __repr__(self) -> str:
        return "<unset>"


_UNSET: Final = _Unset()


@dataclass(frozen=True)
class Session:
    """One fresh agent session: the user's turns in order."""

    turns: tuple[str, ...]


@dataclass(frozen=True)
class ArgMatcher:
    """Matches one tool argument: by equality, regex search, or containment."""

    equals: object = _UNSET
    matches: str | None = None
    contains: str | None = None

    def match(self, value: object) -> bool:
        if self.matches is not None:
            return isinstance(value, str) and re.search(self.matches, value) is not None
        if self.contains is not None:
            if isinstance(value, str):
                return self.contains in value
            if isinstance(value, (list, tuple)):
                return self.contains in cast(Sequence[object], value)
            return False
        expected: object = self.equals
        if isinstance(expected, (list, tuple)) and isinstance(value, (list, tuple)):
            return list(cast(Sequence[object], expected)) == list(cast(Sequence[object], value))
        return value == expected


@dataclass(frozen=True)
class CallMatcher:
    """Selects trace calls by tool name, arguments, session, turn, and outcome."""

    tools: frozenset[str]
    args: Mapping[str, ArgMatcher] = field(default_factory=lambda: MappingProxyType({}))
    session: int | None = None
    turn: int | None = None
    succeeded: bool | None = None


@dataclass(frozen=True)
class FileFilter:
    """Optional scope, area, and name; omitted parts match any file."""

    scope: str | None = None
    area: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class FileRef:
    """One file, addressed scope-relative as the tools address it."""

    scope: str
    area: str
    name: str


@dataclass(frozen=True)
class IndexReadFirst:
    id: str
    session: int | None = None


@dataclass(frozen=True)
class FileAbsent:
    id: str
    file: FileRef


@dataclass(frozen=True)
class LinePresent:
    id: str
    pattern: str
    where: FileFilter


@dataclass(frozen=True)
class LineAbsent:
    id: str
    pattern: str
    where: FileFilter


@dataclass(frozen=True)
class NoContentMatching:
    id: str
    pattern: str


@dataclass(frozen=True)
class NoDuplicateFact:
    id: str
    pattern: str
    where: FileFilter


@dataclass(frozen=True)
class SeedLinesPreserved:
    id: str
    file: FileRef
    except_pattern: str | None = None


@dataclass(frozen=True)
class ToolCalled:
    id: str
    call: CallMatcher
    min: int = 1
    max: int | None = None


@dataclass(frozen=True)
class ToolNotCalled:
    id: str
    call: CallMatcher


@dataclass(frozen=True)
class AliasPresent:
    id: str
    file: FileRef
    alias: str


@dataclass(frozen=True)
class CalledBefore:
    """In each session with a call matching then, a call matching first
    completes strictly before the earliest such then call starts."""

    id: str
    first: CallMatcher
    then: CallMatcher
    session: int | None = None


type Assertion = (
    IndexReadFirst
    | FileAbsent
    | LinePresent
    | LineAbsent
    | NoContentMatching
    | NoDuplicateFact
    | SeedLinesPreserved
    | ToolCalled
    | ToolNotCalled
    | AliasPresent
    | CalledBefore
)

ASSERTION_KINDS: Final[Mapping[str, type[Assertion]]] = MappingProxyType(
    {
        "index_read_first": IndexReadFirst,
        "file_absent": FileAbsent,
        "line_present": LinePresent,
        "line_absent": LineAbsent,
        "no_content_matching": NoContentMatching,
        "no_duplicate_fact": NoDuplicateFact,
        "seed_lines_preserved": SeedLinesPreserved,
        "tool_called": ToolCalled,
        "tool_not_called": ToolNotCalled,
        "alias_present": AliasPresent,
        "called_before": CalledBefore,
    }
)

_KIND_OF: Final[Mapping[type[object], str]] = MappingProxyType(
    {cls: kind for kind, cls in ASSERTION_KINDS.items()}
)


def assertion_kind(assertion: Assertion) -> str:
    """The YAML kind name of an assertion."""
    return _KIND_OF[type(assertion)]


# Each memory tool's parameter names, for validating call-matcher args.
_TOOL_PARAMETERS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        name: frozenset(inspect.signature(getattr(MemoryTools, name)).parameters) - {"self"}
        for name in TOOL_NAMES
    }
)

_FILE_KEYS: Final = frozenset({"scope", "area", "name"})
_CALL_KEYS: Final = frozenset({"tool", "args", "session", "turn", "succeeded"})
# Allowed and required keys per kind, besides "kind" and the optional "id".
_KIND_KEYS: Final[Mapping[str, tuple[frozenset[str], frozenset[str]]]] = MappingProxyType(
    {
        "index_read_first": (frozenset({"session"}), frozenset()),
        "file_absent": (_FILE_KEYS, _FILE_KEYS),
        "line_present": (_FILE_KEYS | {"pattern"}, frozenset({"pattern"})),
        "line_absent": (_FILE_KEYS | {"pattern"}, frozenset({"pattern"})),
        "no_content_matching": (frozenset({"pattern"}), frozenset({"pattern"})),
        "no_duplicate_fact": (_FILE_KEYS | {"pattern"}, frozenset({"pattern"})),
        "seed_lines_preserved": (_FILE_KEYS | {"except"}, _FILE_KEYS),
        "tool_called": (_CALL_KEYS | {"min", "max"}, frozenset({"tool"})),
        "tool_not_called": (_CALL_KEYS, frozenset({"tool"})),
        "alias_present": (_FILE_KEYS | {"alias"}, _FILE_KEYS | {"alias"}),
        "called_before": (frozenset({"first", "then", "session"}), frozenset({"first", "then"})),
    }
)
_TOP_KEYS: Final = frozenset(
    {
        "id",
        "title",
        "category",
        "source",
        "identity",
        "reference_seed",
        "seed",
        "sessions",
        "assertions",
        "judge",
    }
)
_TOP_REQUIRED: Final = frozenset({"id", "title", "category", "source", "sessions", "assertions"})
_SEED_KEYS: Final = frozenset({"scope", "area", "name", "content", "description", "aliases"})


@dataclass(frozen=True)
class JudgeItem:
    """One LLM-judge rubric question, graded outside the deterministic checks."""

    id: str
    rubric: str


@dataclass(frozen=True)
class Scenario:
    """A loaded scenario; seed_files puts reference seeds first when requested."""

    id: str
    title: str
    category: str
    source: str
    identity_name: str
    identity: Identity
    seed_files: tuple[SeedFile, ...]
    sessions: tuple[Session, ...]
    assertions: tuple[Assertion, ...]
    judge: tuple[JudgeItem, ...]
    path: Path


class _Loader:
    """Validates one parsed scenario document; every error names the file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def fail(self, message: str) -> ScenarioError:
        return ScenarioError(f"{self.path}: {message}")

    def mapping(self, value: object, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise self.fail(f"{where} must be a mapping")
        return cast(dict[str, Any], value)

    def keys(
        self, data: Mapping[str, Any], allowed: frozenset[str], required: frozenset[str], where: str
    ) -> None:
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise self.fail(f"{where}: unknown key(s): {', '.join(unknown)}")
        missing = sorted(required - set(data))
        if missing:
            raise self.fail(f"{where}: missing required key(s): {', '.join(missing)}")

    def text(self, value: object, where: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str) or (not allow_empty and not value):
            raise self.fail(f"{where} must be a non-empty string")
        return value

    def integer(self, value: object, where: str, *, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise self.fail(f"{where} must be an integer >= {minimum}, got {value!r}")
        return value

    def pattern(self, value: object, where: str) -> str:
        text = self.text(value, where)
        try:
            re.compile(text)
        except re.error as exc:
            raise self.fail(f"{where} is not a valid regex ({exc}): {text!r}") from None
        return text

    def scope(self, value: object, where: str) -> str:
        text = self.text(value, where)
        if text not in REFERENCE_SCOPES:
            raise self.fail(f"{where}: unknown scope {text!r}; expected one of {REFERENCE_SCOPES}")
        return text

    def segment(self, value: object, where: str) -> str:
        text = self.text(value, where)
        if not is_valid_segment(text):
            raise self.fail(f"{where}: invalid path segment {text!r}")
        return text

    def file_ref(self, data: Mapping[str, Any], where: str) -> FileRef:
        return FileRef(
            self.scope(data["scope"], f"{where}.scope"),
            self.segment(data["area"], f"{where}.area"),
            self.segment(data["name"], f"{where}.name"),
        )

    def file_filter(self, data: Mapping[str, Any], where: str) -> FileFilter:
        return FileFilter(
            self.scope(data["scope"], f"{where}.scope") if "scope" in data else None,
            self.segment(data["area"], f"{where}.area") if "area" in data else None,
            self.segment(data["name"], f"{where}.name") if "name" in data else None,
        )

    def arg_matcher(self, value: object, where: str) -> ArgMatcher:
        if isinstance(value, dict):
            spec = cast(dict[str, Any], value)
            if set(spec) == {"matches"}:
                return ArgMatcher(matches=self.pattern(spec["matches"], f"{where}.matches"))
            if set(spec) == {"contains"}:
                return ArgMatcher(contains=self.text(spec["contains"], f"{where}.contains"))
            raise self.fail(f"{where}: a matcher mapping takes exactly one of: matches, contains")
        return ArgMatcher(equals=value)

    def call_matcher(
        self, data: Mapping[str, Any], where: str, sessions: Sequence[Session]
    ) -> CallMatcher:
        raw_tools: object = data["tool"]
        names: list[object] = (
            list(cast(Sequence[object], raw_tools)) if isinstance(raw_tools, list) else [raw_tools]
        )
        if not names:
            raise self.fail(f"{where}.tool must name at least one tool")
        tools: set[str] = set()
        for name in names:
            if name not in TOOL_NAMES:
                raise self.fail(f"{where}.tool: unknown memory tool {name!r}")
            tools.add(cast(str, name))
        args: dict[str, ArgMatcher] = {}
        if "args" in data:
            raw_args = self.mapping(data["args"], f"{where}.args")
            for key, value in raw_args.items():
                lacking = sorted(t for t in tools if key not in _TOOL_PARAMETERS[t])
                if lacking:
                    raise self.fail(
                        f"{where}.args: {key!r} is not a parameter of {', '.join(lacking)}"
                    )
                matcher = self.arg_matcher(value, f"{where}.args.{key}")
                if key == "scope" and matcher.matches is None and matcher.contains is None:
                    self.scope(matcher.equals, f"{where}.args.scope")
                args[key] = matcher
        session, turn = self.session_turn(data, where, sessions)
        succeeded: bool | None = None
        if "succeeded" in data:
            if not isinstance(data["succeeded"], bool):
                raise self.fail(f"{where}.succeeded must be true or false")
            succeeded = data["succeeded"]
        return CallMatcher(frozenset(tools), MappingProxyType(args), session, turn, succeeded)

    def session_turn(
        self, data: Mapping[str, Any], where: str, sessions: Sequence[Session]
    ) -> tuple[int | None, int | None]:
        session = turn = None
        if "session" in data:
            session = self.integer(data["session"], f"{where}.session", minimum=1)
            if session > len(sessions):
                raise self.fail(f"{where}.session {session} is beyond the {len(sessions)} sessions")
        if "turn" in data:
            turn = self.integer(data["turn"], f"{where}.turn", minimum=1)
            limit = (
                len(sessions[session - 1].turns)
                if session is not None
                else max(len(s.turns) for s in sessions)
            )
            if turn > limit:
                raise self.fail(f"{where}.turn {turn} is beyond the {limit} turns")
        return session, turn

    def order_matcher(self, raw: object, where: str, sessions: Sequence[Session]) -> CallMatcher:
        data = self.mapping(raw, where)
        self.keys(data, frozenset({"tool", "args", "succeeded"}), frozenset({"tool"}), where)
        return self.call_matcher(data, where, sessions)

    def assertion(self, raw: object, index: int, sessions: Sequence[Session]) -> Assertion:
        where = f"assertions[{index}]"
        data = self.mapping(raw, where)
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in ASSERTION_KINDS:
            raise self.fail(f"{where}: unknown assertion kind {kind!r}")
        where = f"{where} ({kind})"
        allowed, required = _KIND_KEYS[kind]
        self.keys(data, allowed | {"kind", "id"}, required | {"kind"}, where)
        ident = self.text(data["id"], f"{where}.id") if "id" in data else f"{kind}-{index + 1}"
        match kind:
            case "index_read_first":
                session, _ = self.session_turn(data, where, sessions)
                return IndexReadFirst(ident, session)
            case "file_absent":
                return FileAbsent(ident, self.file_ref(data, where))
            case "line_present":
                pattern = self.pattern(data["pattern"], f"{where}.pattern")
                return LinePresent(ident, pattern, self.file_filter(data, where))
            case "line_absent":
                pattern = self.pattern(data["pattern"], f"{where}.pattern")
                return LineAbsent(ident, pattern, self.file_filter(data, where))
            case "no_content_matching":
                return NoContentMatching(ident, self.pattern(data["pattern"], f"{where}.pattern"))
            case "no_duplicate_fact":
                pattern = self.pattern(data["pattern"], f"{where}.pattern")
                return NoDuplicateFact(ident, pattern, self.file_filter(data, where))
            case "seed_lines_preserved":
                except_pattern = (
                    self.pattern(data["except"], f"{where}.except") if "except" in data else None
                )
                return SeedLinesPreserved(ident, self.file_ref(data, where), except_pattern)
            case "tool_called":
                call = self.call_matcher(data, where, sessions)
                low = self.integer(data.get("min", 1), f"{where}.min", minimum=0)
                high = (
                    self.integer(data["max"], f"{where}.max", minimum=0) if "max" in data else None
                )
                if high is not None and low > high:
                    raise self.fail(f"{where}: min {low} is greater than max {high}")
                return ToolCalled(ident, call, low, high)
            case "tool_not_called":
                return ToolNotCalled(ident, self.call_matcher(data, where, sessions))
            case "called_before":
                session, _ = self.session_turn(data, where, sessions)
                first = self.order_matcher(data["first"], f"{where}.first", sessions)
                then = self.order_matcher(data["then"], f"{where}.then", sessions)
                return CalledBefore(ident, first, then, session)
            case _:
                alias = self.text(data["alias"], f"{where}.alias")
                return AliasPresent(ident, self.file_ref(data, where), alias)

    def seed(self, raw: object, index: int) -> SeedFile:
        where = f"seed[{index}]"
        data = self.mapping(raw, where)
        self.keys(data, _SEED_KEYS, _SEED_KEYS, where)
        ref = self.file_ref(data, where)
        raw_aliases: object = data["aliases"]
        if not isinstance(raw_aliases, list):
            raise self.fail(f"{where}.aliases must be a list of strings")
        aliases = tuple(
            self.text(a, f"{where}.aliases[{i}]")
            for i, a in enumerate(cast(list[object], raw_aliases))
        )
        return SeedFile(
            ref.scope,
            ref.area,
            ref.name,
            self.text(data["content"], f"{where}.content", allow_empty=True),
            self.text(data["description"], f"{where}.description"),
            aliases,
        )

    def sessions(self, raw: object) -> tuple[Session, ...]:
        if not isinstance(raw, list) or not raw:
            raise self.fail("sessions must be a non-empty list")
        sessions: list[Session] = []
        for i, item in enumerate(cast(list[object], raw)):
            where = f"sessions[{i}]"
            data = self.mapping(item, where)
            self.keys(data, frozenset({"turns"}), frozenset({"turns"}), where)
            turns: object = data["turns"]
            if not isinstance(turns, list) or not turns:
                raise self.fail(f"{where}.turns must be a non-empty list")
            sessions.append(
                Session(
                    tuple(
                        self.text(t, f"{where}.turns[{j}]")
                        for j, t in enumerate(cast(list[object], turns))
                    )
                )
            )
        return tuple(sessions)

    def judge(self, raw: object) -> tuple[JudgeItem, ...]:
        if not isinstance(raw, list):
            raise self.fail("judge must be a list")
        items: list[JudgeItem] = []
        for i, item in enumerate(cast(list[object], raw)):
            where = f"judge[{i}]"
            data = self.mapping(item, where)
            self.keys(data, frozenset({"id", "rubric"}), frozenset({"id", "rubric"}), where)
            items.append(
                JudgeItem(self.text(data["id"], f"{where}.id"), self.text(data["rubric"], where))
            )
        ids = [j.id for j in items]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise self.fail(f"duplicate judge id(s): {', '.join(duplicates)}")
        return tuple(items)

    def scenario(self, document: object) -> Scenario:
        data = self.mapping(document, "the scenario document")
        self.keys(data, _TOP_KEYS, _TOP_REQUIRED, "scenario")
        ident = self.text(data["id"], "id")
        if ident != self.path.stem:
            raise self.fail(f"id {ident!r} must equal the file stem {self.path.stem!r}")
        category = self.text(data["category"], "category")
        if category not in CATEGORIES:
            raise self.fail(f"unknown category {category!r}")
        identity_name = data.get("identity", "member")
        if not isinstance(identity_name, str) or identity_name not in IDENTITIES:
            raise self.fail(f"unknown identity {identity_name!r}; expected member or admin")
        identity = IDENTITIES[identity_name]
        reference_seed = data.get("reference_seed", False)
        if not isinstance(reference_seed, bool):
            raise self.fail("reference_seed must be true or false")
        raw_seed: object = data.get("seed", [])
        if not isinstance(raw_seed, list):
            raise self.fail("seed must be a list")
        own = [self.seed(s, i) for i, s in enumerate(cast(list[object], raw_seed))]
        seeds = (*(REFERENCE_SEED_FILES if reference_seed else ()), *own)
        paths = [seed_path(s, identity) for s in seeds]
        duplicates = sorted({p for p in paths if paths.count(p) > 1})
        if duplicates:
            raise self.fail(f"duplicate seed path(s): {', '.join(duplicates)}")
        sessions = self.sessions(data["sessions"])
        raw_assertions: object = data["assertions"]
        if not isinstance(raw_assertions, list) or not raw_assertions:
            raise self.fail("assertions must be a non-empty list")
        assertions = tuple(
            self.assertion(a, i, sessions) for i, a in enumerate(cast(list[object], raw_assertions))
        )
        seeded = {(s.scope, s.area, s.name) for s in seeds}
        for a in assertions:
            if isinstance(a, SeedLinesPreserved):
                ref = (a.file.scope, a.file.area, a.file.name)
                if ref not in seeded:
                    raise self.fail(
                        f"assertion {a.id!r}: {'/'.join(ref)} is not a seed file of this scenario"
                    )
        ids = [a.id for a in assertions]
        duplicate_ids = sorted({i for i in ids if ids.count(i) > 1})
        if duplicate_ids:
            raise self.fail(f"duplicate assertion id(s): {', '.join(duplicate_ids)}")
        return Scenario(
            id=ident,
            title=self.text(data["title"], "title"),
            category=category,
            source=self.text(data["source"], "source"),
            identity_name=identity_name,
            identity=identity,
            seed_files=seeds,
            sessions=sessions,
            assertions=assertions,
            judge=self.judge(data.get("judge", [])),
            path=self.path,
        )


def load_scenario(path: Path) -> Scenario:
    """Load and validate one scenario file; raises ScenarioError naming the file."""
    loader = _Loader(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise loader.fail(f"cannot read: {exc.strerror}") from None
    try:
        document: object = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise loader.fail(f"invalid YAML: {exc}") from None
    return loader.scenario(document)


def load_all(directory: Path = SCENARIO_DIR) -> tuple[Scenario, ...]:
    """Every *.yaml scenario in directory, sorted by file name."""
    return tuple(load_scenario(p) for p in sorted(directory.glob("*.yaml")))
