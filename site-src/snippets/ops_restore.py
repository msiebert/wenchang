# pyright: basic
from collections.abc import Iterable

from wenchang.core import ExportedObject, MemoryStore
from wenchang.storage import Storage


def restore(
    storage: Storage, store: MemoryStore, objects: Iterable[ExportedObject], user_id: str
) -> None:
    for o in objects:
        storage.put(o.key, o.data, o.metadata)
    # Direct puts bypass the index cache.
    store.invalidate_index("user", user_id)
