from wenchang.core import MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-me", "owner")}))

# One MemoryTools per session; resolving the identity happens here.
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="my-agent", product="Acme")

descriptions = tools.descriptions()  # tool name -> description, product named in the first line
for name, fn in tools.tools().items():  # the seven tools, as bound methods
    print(name, fn.__name__, "-", descriptions[name].splitlines()[0])

print(tools.get_memory_index())
