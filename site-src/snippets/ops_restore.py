# pyright: basic
from collections.abc import Iterable
from datetime import timedelta

from wenchang.core import ExportedObject, MemoryStore
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.index_cache import IndexCache, InMemoryIndexCache
from wenchang.scope import ScopePolicy
from wenchang.storage import Storage
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient


def restore(
    storage: Storage, store: MemoryStore, objects: Iterable[ExportedObject], user_id: str
) -> None:
    for o in objects:
        storage.put(o.key, o.data, o.metadata)
    # Direct puts bypass the index cache.
    store.invalidate_index("user", user_id)


# The server's store configuration; the storage is the one the store wraps.
storage = InMemoryStorage()
cache = InMemoryIndexCache()
store = MemoryStore(
    storage, index_cache=IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=10))
)

identity = Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})
tools = bind_tools(
    InProcessClient(store), SandboxResolver(identity), None, ScopePolicy({}), source="inkwell-cli"
)
for area, name, line, aliases in [
    ("preferences", "prose-style", "- [stated] Close third person.\n", ["voice"]),
    ("workflows", "drafting", "- [stated] Drafts in the morning.\n", []),
]:
    tools.write_file("user", area, name, line, name, aliases, None)

backup = store.export("user", "u-tianlong")
store.purge("user", "u-tianlong")
assert not tools.get_memory_index().entries  # gone, and the empty listing is cached

restore(storage, store, backup, "u-tianlong")

restored = store.export("user", "u-tianlong")
assert [(o.key, o.data, dict(o.metadata)) for o in restored] == [
    (o.key, o.data, dict(o.metadata)) for o in backup
]
assert all(r.version != b.version for r, b in zip(restored, backup, strict=True))  # new versions

prose = tools.read_file("user", "preferences", "prose-style")
assert prose.content == "- [stated] Close third person.\n"
assert prose.metadata.aliases == ("voice",) and prose.metadata.sources == {"inkwell-cli"}
assert [e.path for e in tools.get_memory_index().entries] == [
    "user/u-tianlong/workflows/drafting.md",
    "user/u-tianlong/preferences/prose-style.md",
]  # the cached empty listing was invalidated
