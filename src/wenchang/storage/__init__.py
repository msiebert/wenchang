"""Storage protocol: the boundary between wenchang and its backends.

A `Storage` implementation stores objects addressed by an opaque flat string
key, each with bytes, a flat string metadata map, and a version token. This
protocol is the only way the rest of wenchang touches storage; concrete
backends (in-memory fake, GCS) live in sibling modules.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from wenchang.version_token import VersionToken


@dataclass(frozen=True)
class StoredObject:
    """The bytes, metadata, and version of one object, from a single write."""

    data: bytes
    metadata: Mapping[str, str]
    version: VersionToken


class Storage(Protocol):
    """Minimal get/put storage boundary; backends implement this structurally."""

    def get(self, key: str) -> StoredObject | None:
        """Return the object at exactly `key`, or None if none exists.

        No prefix matching: a put at a different key never causes this to
        resolve. May raise BackendUnavailableError.
        """
        ...

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        """Unconditionally replace the object at `key`, atomically.

        Returns the new version token, distinct from every earlier token for
        `key`. The caller's mapping is copied. May raise
        BackendUnavailableError.
        """
        ...
