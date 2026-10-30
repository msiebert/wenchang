"""Tests for wenchang.schemas: exported tool input, output, and error schemas.

Covers AIE-1295 US1, US2.1, US3, US4, FR-002, and FR-003. Rendered payloads come from a real
MemoryTools over InProcessClient and MemoryStore on in-memory storage, or
from values constructed directly. Validation runs without format checking.
"""

import copy
import inspect
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator

from wenchang.core import CappedPrefix, FileEntry, MemoryFile, MemoryIndex, MemoryStore
from wenchang.errors import (
    BackendUnavailableError,
    ErrorCategory,
    FileQuotaExceededError,
    InvalidArgumentError,
    NotFoundError,
    NotFoundReason,
    OversizeWriteError,
    PermanentError,
    RecoverableError,
    ReplaceFactMatchError,
    ResolverFailureError,
    RestrictedScopeError,
    RestrictionReason,
    TransientError,
    TransientReason,
    VersionConflictError,
    WenchangError,
)
from wenchang.file_format import FileMetadata, MetadataFormatError
from wenchang.identity import Identity, ScopeGrant
from wenchang.schemas import ToolSchema, error_schema, tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import TOOL_NAMES, MemoryTools, render_error, render_result, tool_descriptions
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

_SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_schemas.json"
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT.*Z$")
_SOURCE = "test-surface"
_PATH = "user/u-1/notes/today.md"
_BAD_PATH = "not a memory path"
_VERSION = VersionToken("v-1")
_NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
_META = FileMetadata("A note.", ("alias",), frozenset({"src"}), _NOW)
_FACT = "- [stated] Prefers tea"

Payloads = list[tuple[str, dict[str, object]]]


def _obj(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value)


def _session(list_page_size: int = 100) -> MemoryTools:
    store = MemoryStore(InMemoryStorage(), list_page_size=list_page_size)
    return MemoryTools(
        InProcessClient(store),
        Identity({"user": ScopeGrant("u-1", "owner")}),
        ScopePolicy({}),
        source=_SOURCE,
    )


def _errors(schema: dict[str, object], payload: Any) -> list[str]:
    # No format_checker: "format": "date-time" is documentation only.
    validator = cast(Validator, Draft202012Validator(schema))
    return [error.message for error in validator.iter_errors(payload)]


def _assert_output(tool: str, payload: dict[str, object]) -> None:
    assert _errors(tool_schemas()[tool].output, payload) == [], (tool, payload)


def _file_dicts(payload: dict[str, object]) -> list[dict[str, Any]]:
    """The rendered file objects in a payload: itself, or its entries."""
    if "entries" in payload:
        return cast(list[dict[str, Any]], payload["entries"])
    if "ok" in payload:
        return []
    return [payload]


def _assert_timestamps(payload: dict[str, object]) -> None:
    for file in _file_dicts(payload):
        assert _TIMESTAMP.match(cast(str, file["last_updated"])), file


# US1: the export


def test_keys_are_tool_names_in_order() -> None:
    """tool_schemas() keys equal TOOL_NAMES in order; each value is a ToolSchema
    named by its key (AIE-1295, US1.1).
    """
    schemas = tool_schemas()

    assert list(schemas) == list(TOOL_NAMES)
    for name, schema in schemas.items():
        assert isinstance(schema, ToolSchema)
        assert schema.name == name


@pytest.mark.parametrize("product", [None, "Mixpanel"], ids=["no-product", "product"])
def test_descriptions_equal_tool_descriptions(product: str | None) -> None:
    """Each description equals tool_descriptions(product)[name] (AIE-1295, US1.2)."""
    expected = tool_descriptions(product)

    for name, schema in tool_schemas(product).items():
        assert schema.description == expected[name]


def test_default_product_matches_no_product() -> None:
    """With no product argument, descriptions equal tool_descriptions()
    (AIE-1295, US1.2).
    """
    expected = tool_descriptions()

    for name, schema in tool_schemas().items():
        assert schema.description == expected[name]


@pytest.mark.parametrize(
    ("product", "error"),
    [("", ValueError), ("  ", ValueError), ("a\nb", ValueError), (5, TypeError)],
    ids=["empty", "blank", "multiline", "not-str"],
)
def test_invalid_product_raises_what_tool_descriptions_raises(
    product: object, error: type[Exception]
) -> None:
    """An invalid product raises the same exception type and message as
    tool_descriptions (AIE-1295, US1.2).
    """
    with pytest.raises(error) as expected:
        tool_descriptions(cast(str, product))
    with pytest.raises(error) as actual:
        tool_schemas(cast(str, product))

    assert type(actual.value) is type(expected.value)
    assert str(actual.value) == str(expected.value)


def test_every_schema_is_valid_and_json_serializable() -> None:
    """Each tool's input, output, and error is a valid draft 2020-12 schema and
    json.dumps succeeds; error_schema() too (AIE-1295, US1.3).
    """
    for name, schema in tool_schemas().items():
        for part in (schema.input, schema.output, schema.error):
            Draft202012Validator.check_schema(part)
            json.dumps(part)
        assert name
    Draft202012Validator.check_schema(error_schema())
    json.dumps(error_schema())


def _snapshot() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_SNAPSHOT.read_text(encoding="utf-8")))


def test_schemas_match_committed_snapshot() -> None:
    """Each tool's input and output, and the error schema, equal the committed
    snapshot, with each input's property order pinned (AIE-1295, US1.4).
    """
    snapshot = _snapshot()
    schemas = tool_schemas()
    actual = {
        "tools": {n: {"input": s.input, "output": s.output} for n, s in schemas.items()},
        "error": error_schema(),
    }
    hint = f"exported schemas differ from {_SNAPSHOT}; update it deliberately if intended"

    assert actual == snapshot, hint
    assert list(snapshot["tools"]) == list(TOOL_NAMES), hint
    for name, schema in schemas.items():
        expected_order = list(snapshot["tools"][name]["input"]["properties"])
        assert list(_obj(schema.input["properties"])) == expected_order, (name, hint)


def test_each_call_returns_fresh_objects() -> None:
    """Mutating nested dicts and lists in one result leaves the next call's
    result unaffected, for tool_schemas() and error_schema() (AIE-1295, US1.5).
    """
    first = tool_schemas()
    before = {n: (copy.deepcopy(s.input), copy.deepcopy(s.output)) for n, s in first.items()}
    error_before = copy.deepcopy(error_schema())

    read_input = _obj(first["read_file"].input)
    _obj(read_input["properties"])["scope"]["type"] = "integer"
    cast(list[str], read_input["required"]).append("extra")
    page_entry = _obj(first["list_prefix"].output)["properties"]["entries"]["items"]
    cast(list[str], page_entry["required"]).clear()
    _obj(first["write_file"].output["properties"]).clear()
    _obj(first["append_line"].error)["properties"]["category"]["enum"].append("other")
    errors = error_schema()
    cast(list[str], _obj(errors["properties"])["reason"]["enum"]).append("other")
    cast(list[str], errors["required"]).clear()

    second = tool_schemas()
    for name, schema in second.items():
        assert (schema.input, schema.output) == before[name], name
        assert schema.error == error_before, name
        assert schema.input is not first[name].input
    assert error_schema() == error_before


def test_tool_error_equals_error_schema() -> None:
    """Every ToolSchema's error equals error_schema() (AIE-1295, US1.6)."""
    expected = error_schema()

    for schema in tool_schemas().values():
        assert schema.error == expected


# US2.1: inputs follow the signatures


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_input_mirrors_signature(name: str) -> None:
    """properties are the parameters in signature order, required is those
    without a default in order, and defaults are carried as "default"
    (AIE-1295, US2.1).
    """
    params = list(inspect.signature(getattr(MemoryTools, name)).parameters.values())
    assert params[0].name == "self"
    params = params[1:]
    schema = tool_schemas()[name].input
    properties = _obj(schema["properties"])

    assert list(properties) == [p.name for p in params]
    assert schema["required"] == [p.name for p in params if p.default is inspect.Parameter.empty]
    for p in params:
        if p.default is inspect.Parameter.empty:
            assert "default" not in properties[p.name], (name, p.name)
        else:
            assert "default" in properties[p.name], (name, p.name)
            assert properties[p.name]["default"] == p.default, (name, p.name)


# FR-002 / FR-003: derivation rejects anything outside the closed maps

_ODD_DEFAULT = cast(str | None, object())


def _unmapped_param(self: MemoryTools, scope: int) -> MemoryFile:
    raise NotImplementedError


def _unmapped_generic_param(self: MemoryTools, scope: dict[str, str]) -> MemoryFile:
    raise NotImplementedError


def _wide_union_param(self: MemoryTools, scope: str | Sequence[str]) -> MemoryFile:
    raise NotImplementedError


def _odd_default(self: MemoryTools, area: str | None = _ODD_DEFAULT) -> MemoryFile:
    raise NotImplementedError


def _keyword_only(self: MemoryTools, *, scope: str) -> MemoryFile:
    raise NotImplementedError


def _unmapped_return(self: MemoryTools, scope: str) -> str:
    raise NotImplementedError


def _nullable_token(self: MemoryTools, x: VersionToken | None = None) -> None:
    raise NotImplementedError


@pytest.mark.parametrize(
    "fake",
    [_unmapped_param, _unmapped_generic_param, _wide_union_param, _odd_default, _keyword_only],
    ids=["int", "dict", "wide-union", "object-default", "keyword-only"],
)
def test_unmapped_parameter_raises(
    monkeypatch: pytest.MonkeyPatch, fake: Callable[..., object]
) -> None:
    """A parameter with an unmapped annotation, a union of two non-None types,
    a default that is not None/bool/int/float/str, or a keyword-only kind
    raises TypeError (AIE-1295, FR-002).
    """
    monkeypatch.setattr(MemoryTools, "read_file", fake)

    with pytest.raises(TypeError):
        tool_schemas()


def test_unmapped_return_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A return annotation outside the output map raises TypeError
    (AIE-1295, FR-003).
    """
    monkeypatch.setattr(MemoryTools, "read_file", _unmapped_return)

    with pytest.raises(TypeError):
        tool_schemas()


def test_nullable_newtype_default_derives(monkeypatch: pytest.MonkeyPatch) -> None:
    """VersionToken | None = None derives a nullable string with default null, and
    -> None derives the OK output (AIE-1295, FR-002, FR-003).
    """
    monkeypatch.setattr(MemoryTools, "delete_file", _nullable_token)

    schema = tool_schemas()["delete_file"]

    assert schema.input == {
        "type": "object",
        "properties": {
            "x": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
        "required": [],
        "additionalProperties": False,
    }
    assert schema.output == {
        "type": "object",
        "properties": {"ok": {"const": True}},
        "required": ["ok"],
        "additionalProperties": False,
    }


# US3: outputs follow render_result


def _us3_1_payloads() -> Payloads:
    tools = _session()
    out: Payloads = []
    created = tools.write_file("user", "notes", "today", f"{_FACT}\n", "Today.", ["day"], None)
    out.append(("write_file", render_result(created)))
    replaced = tools.write_file(
        "user", "notes", "today", f"{_FACT}\n", "Today.", ["day"], created.version
    )
    out.append(("write_file", render_result(replaced)))
    appended = tools.append_line(
        "user", "notes", "today", "- [observed] Likes jasmine", replaced.version
    )
    out.append(("append_line", render_result(appended)))
    appended = tools.append_line(
        "user",
        "notes",
        "today",
        "- [inferred] Drinks it daily",
        appended.version,
        aliases=["tea"],
        description="Tea notes.",
    )
    out.append(("append_line", render_result(appended)))
    fact = tools.replace_fact(
        "user", "notes", "today", "Likes jasmine", "Likes oolong", appended.version
    )
    out.append(("replace_fact", render_result(fact)))
    out.append(("read_file", render_result(tools.read_file("user", "notes", "today"))))
    tools.write_file("user", "notes", "other", f"{_FACT}\n", "Other.", [], None)
    page = tools.list_prefix("user", "notes")
    assert page.next_cursor is None
    out.append(("list_prefix", render_result(page)))
    out.append(("get_memory_index", render_result(tools.get_memory_index())))
    other = tools.read_file("user", "notes", "other")
    out.append(
        ("delete_file", render_result(tools.delete_file("user", "notes", "other", other.version)))
    )
    return out


def _us3_1a_payloads() -> Payloads:
    tools = _session()
    no_aliases = tools.write_file("user", "notes", "bare", f"{_FACT}\n", "Bare.", [], None)
    blank = tools.write_file("user", "notes", "blank", f"{_FACT}\n", "", ["b"], None)
    return [
        ("write_file", render_result(no_aliases)),
        ("write_file", render_result(blank)),
        ("read_file", render_result(tools.read_file("user", "notes", "blank"))),
        ("list_prefix", render_result(tools.list_prefix("user", "empty"))),
        ("get_memory_index", render_result(MemoryIndex())),
        ("get_memory_index", render_result(_session().get_memory_index())),
    ]


def _us3_2_payloads() -> Payloads:
    tools = _session(list_page_size=1)
    tools.write_file("user", "notes", "one", f"{_FACT}\n", "One.", [], None)
    tools.write_file("user", "notes", "two", f"{_FACT}\n", "Two.", [], None)
    return [("list_prefix", render_result(tools.list_prefix("user", "notes")))]


def _capped_index() -> MemoryIndex:
    return MemoryIndex(
        entries=(FileEntry(_PATH, _META, _VERSION),),
        capped=(CappedPrefix("user/u-1/", 3), CappedPrefix("user/u-1/notes/", 2)),
    )


def _unparseable_file() -> MemoryFile:
    return MemoryFile(_BAD_PATH, f"{_FACT}\n", _META, _VERSION)


def _all_success_payloads() -> Payloads:
    return [
        *_us3_1_payloads(),
        *_us3_1a_payloads(),
        *_us3_2_payloads(),
        ("get_memory_index", render_result(_capped_index())),
        ("read_file", render_result(_unparseable_file())),
    ]


def test_successful_calls_validate() -> None:
    """Each successful tool call's render_result validates against that tool's
    output, and every last_updated is a UTC timestamp ending in Z
    (AIE-1295, US3.1).
    """
    payloads = _us3_1_payloads()

    assert {tool for tool, _ in payloads} == set(TOOL_NAMES)
    for tool, payload in payloads:
        _assert_output(tool, payload)
        _assert_timestamps(payload)


def test_edge_results_validate() -> None:
    """aliases=[], description="", an empty listing, and an empty index keep
    their keys and validate (AIE-1295, US3.1a).
    """
    payloads = _us3_1a_payloads()

    assert payloads[0][1]["aliases"] == []
    assert payloads[1][1]["description"] == ""
    assert payloads[3][1] == {"entries": [], "next_cursor": None}
    assert payloads[4][1] == {"entries": [], "capped": []}
    for tool, payload in payloads:
        _assert_output(tool, payload)
        _assert_timestamps(payload)


def test_paged_listing_validates() -> None:
    """A first page with a string next_cursor validates (AIE-1295, US3.2)."""
    [(tool, payload)] = _us3_2_payloads()

    assert isinstance(payload["next_cursor"], str)
    assert len(cast(list[object], payload["entries"])) == 1
    _assert_output(tool, payload)


def test_capped_index_validates() -> None:
    """A MemoryIndex with entity-level and area-level capped rows validates
    against get_memory_index's output (AIE-1295, US3.3).
    """
    payload = render_result(_capped_index())

    assert payload["capped"] == [
        {"scope": "user", "area": None, "omitted": 3},
        {"scope": "user", "area": "notes", "omitted": 2},
    ]
    _assert_output("get_memory_index", payload)


def test_unparseable_path_validates() -> None:
    """A MemoryFile whose path does not parse renders null scope, area, and name
    and validates against read_file's output (AIE-1295, US3.4).
    """
    payload = render_result(_unparseable_file())

    assert (payload["scope"], payload["area"], payload["name"]) == (None, None, None)
    _assert_output("read_file", payload)


def test_rendered_keys_cover_declared_properties() -> None:
    """Per tool, the union of rendered keys equals the output's declared
    properties, including file entries and capped rows (AIE-1295, US3.5).
    """
    payloads = _all_success_payloads()
    schemas = tool_schemas()

    for name in TOOL_NAMES:
        output = schemas[name].output
        properties = _obj(output["properties"])
        rendered = [p for tool, p in payloads if tool == name]
        assert rendered, name
        assert set().union(*rendered) == set(properties), name
        if "entries" in properties:
            entry_keys = set(properties["entries"]["items"]["properties"])
            entries = [e for p in rendered for e in _file_dicts(p)]
            assert entries, name
            assert set().union(*entries) == entry_keys, name
        if "capped" in properties:
            row_keys = set(properties["capped"]["items"]["properties"])
            rows = [r for p in rendered for r in cast(list[dict[str, object]], p["capped"])]
            assert rows, name
            assert set().union(*rows) == row_keys, name


def test_read_file_output_is_closed_and_complete() -> None:
    """A read_file payload with an extra key, or without version, fails
    validation (AIE-1295, US3.6).
    """
    payload = render_result(_session_file())
    output = tool_schemas()["read_file"].output
    assert _errors(output, payload) == []

    extra = {**payload, "extra": "x"}
    missing = {k: v for k, v in payload.items() if k != "version"}

    assert _errors(output, extra) != []
    assert _errors(output, missing) != []


def _session_file() -> MemoryFile:
    tools = _session()
    tools.write_file("user", "notes", "today", f"{_FACT}\n", "Today.", [], None)
    return tools.read_file("user", "notes", "today")


# US4: the error schema follows render_error


class _OffCategoryError(WenchangError):
    """A WenchangError whose category is not an ErrorCategory."""

    category = cast(ErrorCategory, "recoverable")
    guidance = "Nothing to do."


def _discovered_error_classes() -> set[type[WenchangError]]:
    found: set[type[WenchangError]] = set()
    pending = list(WenchangError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__ == "wenchang" or cls.__module__.startswith("wenchang."):
            found.add(cls)
    return found - {RecoverableError, PermanentError, TransientError}


def _error_fixtures() -> list[WenchangError]:
    fixtures: list[WenchangError] = []
    for path in (_PATH, _BAD_PATH):
        fixtures += [
            VersionConflictError(path, "body", _VERSION),
            OversizeWriteError(path, 10, 5),
            FileQuotaExceededError(path, 3),
            ReplaceFactMatchError(path, "body", _VERSION, 0),
            ReplaceFactMatchError(path, "body", _VERSION, 2),
        ]
        fixtures += [NotFoundError(path, reason) for reason in NotFoundReason]
    system_path = "user/u-1/system/rules.md"
    fixtures += [
        RestrictedScopeError(system_path, "user", RestrictionReason.SYSTEM_READ_ONLY),
        RestrictedScopeError(_PATH, "user", RestrictionReason.NOT_GRANTED),
        RestrictedScopeError(
            "org/o-1/notes/x.md",
            "org",
            RestrictionReason.ROLE_REQUIRED,
            frozenset({"admin", "owner"}),
        ),
        RestrictedScopeError(_BAD_PATH, "org", RestrictionReason.NOT_GRANTED),
        InvalidArgumentError("area", "area must be a slug"),
        ResolverFailureError(),
        ResolverFailureError("no such user"),
    ]
    fixtures += [BackendUnavailableError(reason) for reason in TransientReason]
    fixtures += [BackendUnavailableError(reason, "Read failed.") for reason in TransientReason]
    return fixtures


def _internal_errors() -> list[Exception]:
    return [
        MetadataFormatError("description", "malformed"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        RuntimeError("boom"),
        _OffCategoryError("detail"),
    ]


def test_every_error_class_has_a_fixture() -> None:
    """Every concrete wenchang error class has a fixture, and the fixtures cover
    every reason, both match_count branches, and a scoped unparseable
    RestrictedScopeError (AIE-1295, US4.1).
    """
    fixtures = _error_fixtures()
    discovered = _discovered_error_classes()

    assert FileQuotaExceededError in discovered
    assert discovered <= {type(f) for f in fixtures}
    reasons = {cast(object, getattr(f, "reason", None)) for f in fixtures}
    for enum in (NotFoundReason, RestrictionReason, TransientReason):
        assert set(enum) <= reasons, enum
    match_counts = {f.match_count for f in fixtures if isinstance(f, ReplaceFactMatchError)}
    assert {0, 2} <= match_counts
    paths = {cast(object, getattr(f, "path", None)) for f in fixtures}
    assert {_PATH, _BAD_PATH} <= paths
    scoped = render_error(RestrictedScopeError(_BAD_PATH, "org", RestrictionReason.NOT_GRANTED))
    assert scoped["scope"] == "org"
    assert "area" not in scoped
    assert "name" not in scoped


@pytest.mark.parametrize("fixture", _error_fixtures(), ids=lambda f: type(f).__name__)
def test_error_fixture_validates(fixture: WenchangError) -> None:
    """render_error of each fixture validates against error_schema()
    (AIE-1295, US4.2).
    """
    payload = render_error(fixture)

    assert _errors(error_schema(), payload) == [], payload


@pytest.mark.parametrize("exc", _internal_errors(), ids=lambda e: type(e).__name__)
def test_internal_errors_validate(exc: Exception) -> None:
    """MetadataFormatError, UnicodeDecodeError, RuntimeError, and a
    WenchangError with a non-ErrorCategory category render as "internal" and
    validate (AIE-1295, US4.3).
    """
    payload = render_error(exc)

    assert payload["category"] == "internal"
    assert _errors(error_schema(), payload) == [], payload


def test_error_keys_cover_declared_properties() -> None:
    """The union of rendered error keys equals the error schema's properties
    (AIE-1295, US4.4).
    """
    exceptions: list[Exception] = [*_error_fixtures(), *_internal_errors()]
    keys: set[str] = set()
    for exc in exceptions:
        keys |= set(render_error(exc))

    assert keys == set(_obj(error_schema()["properties"]))


def test_error_enums_follow_the_error_enums() -> None:
    """category's enum is ErrorCategory plus "internal"; reason's is
    NotFoundReason, RestrictionReason, then TransientReason (AIE-1295, US4.5).
    """
    properties = _obj(error_schema()["properties"])

    assert properties["category"]["enum"] == [c.value for c in ErrorCategory] + ["internal"]
    assert properties["reason"]["enum"] == [
        *(r.value for r in NotFoundReason),
        *(r.value for r in RestrictionReason),
        *(r.value for r in TransientReason),
    ]


def test_real_tool_failures_validate() -> None:
    """Errors raised by real failing tool calls render and validate against
    that tool's error schema (AIE-1295, US4.6).
    """
    tools = _session()
    created = tools.write_file("user", "notes", "today", f"{_FACT}\n", "Today.", [], None)
    tools.write_file("user", "notes", "today", f"{_FACT}\n", "Today.", [], created.version)
    failures: list[tuple[str, Exception]] = []

    with pytest.raises(NotFoundError) as absent:
        tools.read_file("user", "notes", "missing")
    failures.append(("read_file", absent.value))
    with pytest.raises(RestrictedScopeError) as system:
        tools.write_file("user", "system", "rules", f"{_FACT}\n", "Rules.", [], None)
    failures.append(("write_file", system.value))
    with pytest.raises(VersionConflictError) as stale:
        tools.write_file("user", "notes", "today", f"{_FACT}\n", "Today.", [], created.version)
    failures.append(("write_file", stale.value))
    with pytest.raises(InvalidArgumentError) as bad_area:
        tools.read_file("user", "Bad Area", "today")
    failures.append(("read_file", bad_area.value))
    current = tools.read_file("user", "notes", "today")
    with pytest.raises(ReplaceFactMatchError) as no_match:
        tools.replace_fact("user", "notes", "today", "absent text", "x", current.version)
    failures.append(("replace_fact", no_match.value))

    schemas = tool_schemas()
    for tool, exc in failures:
        payload = render_error(exc)
        assert _errors(schemas[tool].error, payload) == [], (tool, payload)
