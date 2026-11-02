# pyright: basic
import os
from datetime import timedelta

import redis
from google.cloud import storage

from wenchang.core import MemoryStore
from wenchang.index_cache import IndexCache
from wenchang.storage.gcs import GcsStorage

# decode_responses=True makes get return str, which the cache must return.
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def cache_get(key: str) -> str | None:
    return r.get(key)


def cache_set(key: str, value: str, ttl: timedelta | None) -> None:
    if ttl is None:
        r.set(key, value)
    else:
        r.set(key, value, px=max(1, ttl // timedelta(milliseconds=1)))


index_cache = IndexCache(get=cache_get, set=cache_set, ttl=timedelta(minutes=10))

bucket = storage.Client(project="my-gcp-project").bucket(os.environ["WENCHANG_BUCKET"])
store = MemoryStore(
    GcsStorage(bucket),
    scope_priority=("user", "project", "organization"),
    index_cache=index_cache,
)
