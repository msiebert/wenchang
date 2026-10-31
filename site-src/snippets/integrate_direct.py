from wenchang.core import MemoryStore
from wenchang.errors import InvalidArgumentError
from wenchang.identity import Identity, ResolutionFailure, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.schemas import tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools, render_error, render_result
from wenchang.transport import InProcessClient

USERS = {"tok-tianlong": "u-tianlong", "tok-diya": "u-diya"}  # stand-in for your IdP


class TokenResolver:
    """Maps a bearer token to the caller's grants. Must not raise."""

    def resolve(self, credentials: str | None) -> Identity | ResolutionFailure:
        user_id = USERS.get(credentials or "")
        if user_id is None:
            return ResolutionFailure("Invalid or expired token.")
        return Identity(grants={"user": ScopeGrant(user_id, "owner")})


# Built once per process and shared by every request; both must be thread-safe.
client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = TokenResolver()
policy = ScopePolicy({})
schemas = tool_schemas(product="Inkwell")
records: list[ToolCallRecord] = []

# Register these with your framework once: name, description, and parameter schema.
definitions = [
    {"name": s.name, "description": s.description, "input_schema": s.input}
    for s in schemas.values()
]


def check_arguments(name: str, arguments: dict[str, object]) -> None:
    # Your framework normally validates against the input schema; this checks names only.
    schema: dict = schemas[name].input
    for key in arguments:
        if key not in schema["properties"]:
            raise InvalidArgumentError(key, "not a parameter of this tool")
    for key in schema.get("required", []):
        if key not in arguments:
            raise InvalidArgumentError(key, "required")


def run_tool_calls(
    token: str | None, calls: list[tuple[str, dict[str, object]]]
) -> list[dict[str, object]]:
    """Run one request's tool calls as the caller the token names."""
    try:
        # Resolve once per request, never once per process.
        tools = bind_tools(
            client,
            resolver,
            token,
            policy,
            source="inkwell-api",
            product="Inkwell",
            on_call=records.append,
        )
    except Exception as exc:  # ResolverFailureError: no memory for this request
        return [render_error(exc) for _ in calls]
    methods = tools.tools()
    payloads: list[dict[str, object]] = []
    for name, arguments in calls:
        try:
            check_arguments(name, arguments)
            payloads.append(render_result(methods[name](**arguments)))
        except Exception as exc:
            payloads.append(render_error(exc))
    return payloads


created, missing = run_tool_calls(
    "tok-tianlong",
    [
        (
            "write_file",
            {
                "scope": "user",
                "area": "preferences",
                "name": "prose-style",
                "content": "- [stated] Writes in close third person, past tense.\n",
                "description": "Prose style preferences",
                "aliases": ["narration", "voice"],
                "expected_version": None,
            },
        ),
        ("read_file", {"scope": "user", "area": "preferences", "name": "tea"}),
    ],
)
assert created["name"] == "prose-style" and created["sources"] == ["inkwell-api"]
assert missing["error"] == "NotFoundError" and missing["category"] == "recoverable"

[denied] = run_tool_calls("tok-expired", [("get_memory_index", {})])
assert denied["error"] == "ResolverFailureError" and denied["category"] == "permanent"

# One record per tool call; request_id is None for direct calls.
assert [(r.tool, r.is_error, r.request_id) for r in records] == [
    ("write_file", False, None),
    ("read_file", True, None),
]
print(created["version"], missing["message"])
