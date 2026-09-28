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


class PreconditionFailedError(Exception):
    """A conditional put's precondition did not hold; storage is unchanged.

    Subclasses `Exception` directly, not `WenchangError`: this is an internal
    signal between the storage layer and `core`, never surfaced to agents.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"Precondition failed for {key!r}.")
        self.key = key


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

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        """Replace the object at `key` only if its current version matches.

        `expected=None` means "create; must not exist": the put commits only
        if no object exists at `key`. A non-None `expected` commits only if
        the current object's version equals it exactly (including when no
        object exists at all). Otherwise raises `PreconditionFailedError(key)`
        and changes nothing.

        On success, has the same guarantees as `put`: atomic, a new token
        distinct from every earlier token for `key`, and the caller's mapping
        copied. May raise BackendUnavailableError.
        """
        ...
