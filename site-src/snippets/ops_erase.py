import logging
from datetime import timedelta

from wenchang.core import ExportedObject, MemoryStore, PurgeIncompleteError
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.index_cache import IndexCache, InMemoryIndexCache
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

log = logging.getLogger("erasure")


def revoke_grant(user_id: str) -> None:
    """Your auth layer: stop resolving any caller to this user's grant."""


def erase_user(store: MemoryStore, user_id: str) -> tuple[tuple[ExportedObject, ...], int]:
    revoke_grant(user_id)  # 1. stop writers, and let in-flight sessions end
    backup = store.export("user", user_id)  # 2. optional: hand over or archive
    try:
        deleted = store.purge("user", user_id)  # 3. everything under user/{user_id}/
    except PurgeIncompleteError as exc:
        # Objects kept reappearing: a writer is still active. Stop it and re-run.
        log.error("erasure incomplete in scope %r after %d passes", exc.scope, exc.passes)
        raise
    log.info("purged %d objects", deleted)
    return backup, deleted


# The server's store configuration, cache included, so the purge invalidates
# the user's cached index.
storage = InMemoryStorage()
cache = InMemoryIndexCache()
store = MemoryStore(
    storage, index_cache=IndexCache(get=cache.get, set=cache.set, ttl=timedelta(minutes=10))
)

identity = Identity(grants={"user": ScopeGrant("u-tianlong", "owner")})
tools = bind_tools(
    InProcessClient(store), SandboxResolver(identity), None, ScopePolicy({}), source="inkwell-cli"
)
for area, name, line in [
    ("preferences", "prose-style", "- [stated] Close third person.\n"),
    ("workflows", "drafting", "- [stated] Drafts in the morning.\n"),
]:
    tools.write_file("user", area, name, line, name, [], None)
assert len(tools.get_memory_index().entries) == 2  # this listing is now cached

backup, deleted = erase_user(store, "u-tianlong")

assert [o.key for o in backup] == [
    "user/u-tianlong/preferences/prose-style.md",
    "user/u-tianlong/workflows/drafting.md",
]
assert backup[0].data == b"- [stated] Close third person.\n"
assert deleted == 2
assert not storage.list_page("user/u-tianlong/", None, 1)  # nothing left under the prefix
assert not tools.get_memory_index().entries  # the cached listing was invalidated
