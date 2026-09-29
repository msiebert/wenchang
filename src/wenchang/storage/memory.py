"""In-memory fake implementation of the Storage protocol, for tests."""

from collections.abc import Mapping, Sequence

from wenchang.storage import ListedObject, PreconditionFailedError, StoredObject
from wenchang.version_token import VersionToken


class InMemoryStorage:
    """Structurally satisfies Storage, backed by a plain dict.

    Version tokens come from a single counter shared across all keys of the
    instance, mirroring GCS generation numbers: monotonically increasing and
    never reused, even across different keys.
    """

    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}
        self._next_token = 1

    def get(self, key: str) -> StoredObject | None:
        stored = self._objects.get(key)
        if stored is None:
            return None
        return StoredObject(
            data=stored.data, metadata=dict(stored.metadata), version=stored.version
        )

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        token = VersionToken(str(self._next_token))
        self._next_token += 1
        self._objects[key] = StoredObject(data=data, metadata=dict(metadata), version=token)
        return token

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        current = self._objects.get(key)
        current_token = current.version if current is not None else None
        if current_token != expected:
            raise PreconditionFailedError(key)
        return self.put(key, data, metadata)

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        keys = sorted(k for k in self._objects if k.startswith(prefix))
        if start_after is not None:
            keys = [k for k in keys if k > start_after]
        keys = keys[:limit]
        return [
            ListedObject(
                key=key,
                metadata=dict(self._objects[key].metadata),
                version=self._objects[key].version,
            )
            for key in keys
        ]
