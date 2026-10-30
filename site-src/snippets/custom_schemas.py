from collections.abc import Callable
from dataclasses import dataclass

from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.schemas import tool_schemas
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import MemoryTools, bind_tools, render_error, render_result
from wenchang.transport import InProcessClient


@dataclass
class ToolDef:  # stand-in for your framework's tool definition
    name: str
    description: str
    parameters: dict[str, object]
    handler: Callable[[dict[str, object]], dict[str, object]]


def handler(tools: MemoryTools, name: str) -> Callable[[dict[str, object]], dict[str, object]]:
    method = tools.tools()[name]

    def call(arguments: dict[str, object]) -> dict[str, object]:
        try:
            return render_result(method(**arguments))  # matches the schema's output
        except Exception as exc:
            return render_error(exc)  # matches the schema's error

    return call


client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")}))
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="inkwell-cli", product="Inkwell")

defs: dict[str, ToolDef] = {}
for s in tool_schemas(product="Inkwell").values():
    call = handler(tools, s.name)
    defs[s.name] = ToolDef(name=s.name, description=s.description, parameters=s.input, handler=call)

# A NotFoundError payload, valid against tool_schemas()["read_file"].error.
print(defs["read_file"].handler({"scope": "user", "area": "notes", "name": "tea"}))
