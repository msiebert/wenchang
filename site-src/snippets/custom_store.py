from datetime import UTC, datetime

from wenchang.core import MemoryStore
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient

store = MemoryStore(
    InMemoryStorage(),
    max_file_bytes=8 * 1024,  # default 16384: larger writes raise OversizeWriteError
    index_max_bytes=32 * 1024,  # default 65536: the startup index is capped at this size
    list_page_size=50,  # default 100: entries per list_prefix page
    scope_priority=("user", "project", "organization"),  # which scopes the capped index keeps first
    clock=lambda: datetime.now(UTC),  # must return timezone-aware datetimes
)
client = InProcessClient(store)
print(store.index_max_bytes, store.scope_priority)
