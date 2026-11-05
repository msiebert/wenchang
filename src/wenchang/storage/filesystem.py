"""Local-filesystem implementation of the Storage protocol.

Each object is a body file `L%obj` plus a JSON sidecar `L%meta` (version and
metadata) in directories that mirror the key's `/` segments. Keys are encoded
per segment so any key is safe and collision-free (see `_encode_segment`). The
sidecar is the commit point: an object exists only if its sidecar does.

Version tokens are random (`uuid4().hex`) and compared by exact equality. A
`threading.Lock` plus `fcntl.flock` on `root/.lock` serialize operations across
threads, instances, and processes. POSIX local filesystems only.

Writes are atomic against process crashes with one exception: a crash between
the body and sidecar replaces of an overwrite pairs the new body with the old
sidecar. There is no fsync, so power loss is not covered.
"""

import fcntl
import json
import os
import threading
import uuid
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NamedTuple, cast

from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.storage import ListedObject, PreconditionFailedError, StoredObject
from wenchang.version_token import VersionToken

_BODY_SUFFIX = "%obj"
_SIDECAR_SUFFIX = "%meta"
_LOCK_NAME = ".lock"
_TEMP_PREFIX = ".tmp-"
_MAX_SEGMENT_BYTES = 200
_FORMAT = 1
_LITERAL = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-.")
_HEX = frozenset("0123456789ABCDEF")


class InvalidStorageKeyError(ValueError):
    """A key cannot be stored: empty, not encodable as UTF-8, or a segment too long."""


class _Sidecar(NamedTuple):
    version: VersionToken
    metadata: dict[str, str]


def _encode_segment(segment: str) -> str:
    """Percent-encode one key segment into a safe, reversible file name.

    Only lowercase letters, digits, `_`, `-`, and a non-leading `.` stay
    literal; everything else becomes uppercase `%XX` per UTF-8 byte, and the
    empty segment becomes `%`. Encoded names never contain `/`, never start
    with `.`, and never end with a suffix, so keys cannot escape the root or
    collide with each other, the lock file, or temp files.
    """
    if not segment:
        return "%"
    try:
        raw = segment.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidStorageKeyError(f"Key segment {segment!r} is not encodable as UTF-8.") from exc
    parts: list[str] = []
    for index, byte in enumerate(raw):
        char = chr(byte)
        if byte < 128 and char in _LITERAL and not (index == 0 and char == "."):
            parts.append(char)
        else:
            parts.append(f"%{byte:02X}")
    encoded = "".join(parts)
    if len(encoded) > _MAX_SEGMENT_BYTES:
        raise InvalidStorageKeyError(
            f"Key segment encodes to more than {_MAX_SEGMENT_BYTES} bytes."
        )
    return encoded


def _decode_segment(name: str) -> str | None:
    """Invert `_encode_segment`; None if `name` is not a canonical encoding."""
    if name == "%":
        return ""
    raw = bytearray()
    index = 0
    while index < len(name):
        char = name[index]
        if char == "%":
            digits = name[index + 1 : index + 3]
            if len(digits) != 2 or not all(d in _HEX for d in digits):
                return None
            raw.append(int(digits, 16))
            index += 3
        elif ord(char) < 128:
            raw.append(ord(char))
            index += 1
        else:
            return None
    try:
        decoded = raw.decode("utf-8")
        canonical = _encode_segment(decoded)
    except (UnicodeDecodeError, InvalidStorageKeyError):
        return None
    return decoded if canonical == name else None


def _unavailable(exc: Exception) -> BackendUnavailableError:
    return BackendUnavailableError(TransientReason.UNAVAILABLE, str(exc))


def _corrupt(path: Path, problem: str) -> BackendUnavailableError:
    return BackendUnavailableError(
        TransientReason.UNAVAILABLE, f"Invalid sidecar {path}: {problem}"
    )


def _read_sidecar(path: Path) -> _Sidecar | None:
    """Parse the sidecar at `path`; None if it does not exist."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise BackendUnavailableError(
            TransientReason.UNAVAILABLE, f"Invalid sidecar {path}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise _corrupt(path, "not an object")
    fields = cast(dict[str, Any], parsed)
    version = fields.get("version")
    metadata = fields.get("metadata")
    if not isinstance(version, str):
        raise _corrupt(path, "missing version")
    if not isinstance(metadata, dict):
        raise _corrupt(path, "missing metadata")
    result: dict[str, str] = {}
    for name, value in cast(dict[Any, Any], metadata).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise _corrupt(path, "metadata is not a string map")
        result[name] = value
    return _Sidecar(VersionToken(version), result)


def _write_temp(directory: Path, data: bytes) -> Path:
    path = directory / f"{_TEMP_PREFIX}{uuid.uuid4().hex}"
    with open(path, "xb") as handle:
        handle.write(data)
    return path


class FilesystemStorage:
    """Structurally satisfies Storage, backed by a directory tree under `root`."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _unavailable(exc) from exc

    @property
    def root(self) -> Path:
        return self._root

    @contextmanager
    def _locked(self, *, exclusive: bool) -> Generator[None]:
        with self._lock:
            fd = os.open(self._root / _LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o666)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                yield
            finally:
                os.close(fd)

    def _locate(self, key: str) -> tuple[Path, str]:
        """Validate `key` and return its parent directory and encoded leaf name."""
        if not key:
            raise InvalidStorageKeyError("Key must not be empty.")
        segments = [_encode_segment(s) for s in key.split("/")]
        return self._root.joinpath(*segments[:-1]), segments[-1]

    def get(self, key: str) -> StoredObject | None:
        directory, leaf = self._locate(key)
        try:
            with self._locked(exclusive=False):
                sidecar = _read_sidecar(directory / f"{leaf}{_SIDECAR_SUFFIX}")
                if sidecar is None:
                    return None
                body_path = directory / f"{leaf}{_BODY_SUFFIX}"
                try:
                    data = body_path.read_bytes()
                except FileNotFoundError as exc:
                    raise BackendUnavailableError(
                        TransientReason.UNAVAILABLE, f"Missing body file {body_path}."
                    ) from exc
        except OSError as exc:
            raise _unavailable(exc) from exc
        return StoredObject(data=data, metadata=sidecar.metadata, version=sidecar.version)

    def put(self, key: str, data: bytes, metadata: Mapping[str, str]) -> VersionToken:
        directory, leaf = self._locate(key)
        try:
            with self._locked(exclusive=True):
                return self._write(directory, leaf, data, metadata)
        except OSError as exc:
            raise _unavailable(exc) from exc

    def put_if_version(
        self,
        key: str,
        data: bytes,
        metadata: Mapping[str, str],
        expected: VersionToken | None,
    ) -> VersionToken:
        directory, leaf = self._locate(key)
        try:
            with self._locked(exclusive=True):
                current = _read_sidecar(directory / f"{leaf}{_SIDECAR_SUFFIX}")
                if (current.version if current is not None else None) != expected:
                    raise PreconditionFailedError(key)
                return self._write(directory, leaf, data, metadata)
        except OSError as exc:
            raise _unavailable(exc) from exc

    def _write(
        self, directory: Path, leaf: str, data: bytes, metadata: Mapping[str, str]
    ) -> VersionToken:
        """Write body then sidecar; the sidecar replace commits. Needs the exclusive lock."""
        token = VersionToken(uuid.uuid4().hex)
        sidecar = json.dumps(
            {"format": _FORMAT, "version": token, "metadata": dict(metadata)},
            ensure_ascii=True,
            sort_keys=True,
        ).encode("ascii")
        temps: list[Path] = []
        try:
            directory.mkdir(parents=True, exist_ok=True)
            body_tmp = _write_temp(directory, data)
            temps.append(body_tmp)
            sidecar_tmp = _write_temp(directory, sidecar)
            temps.append(sidecar_tmp)
            os.replace(body_tmp, directory / f"{leaf}{_BODY_SUFFIX}")
            os.replace(sidecar_tmp, directory / f"{leaf}{_SIDECAR_SUFFIX}")
        except BaseException:
            for temp in temps:
                temp.unlink(missing_ok=True)
            raise
        return token

    def delete_if_version(self, key: str, expected: VersionToken) -> None:
        directory, leaf = self._locate(key)
        try:
            with self._locked(exclusive=True):
                sidecar_path = directory / f"{leaf}{_SIDECAR_SUFFIX}"
                current = _read_sidecar(sidecar_path)
                if current is None or current.version != expected:
                    raise PreconditionFailedError(key)
                sidecar_path.unlink()
                (directory / f"{leaf}{_BODY_SUFFIX}").unlink(missing_ok=True)
                self._prune_empty(directory)
        except OSError as exc:
            raise _unavailable(exc) from exc

    def _prune_empty(self, directory: Path) -> None:
        """Remove empty directories from `directory` up to, excluding, the root."""
        while directory != self._root:
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    def list_page(self, prefix: str, start_after: str | None, limit: int) -> Sequence[ListedObject]:
        *complete, partial = prefix.split("/")
        try:
            base = self._root.joinpath(*(_encode_segment(s) for s in complete))
        except InvalidStorageKeyError:
            return []
        base_key = "".join(f"{s}/" for s in complete)
        try:
            with self._locked(exclusive=False):
                keys: list[tuple[str, Path]] = []
                self._collect(base, base_key, partial, keys)
                keys = [
                    (k, p)
                    for k, p in keys
                    if k.startswith(prefix) and (start_after is None or k > start_after)
                ]
                keys.sort(key=lambda item: item[0])
                listed: list[ListedObject] = []
                for key, path in keys[:limit]:
                    sidecar = _read_sidecar(path)
                    if sidecar is None:
                        raise _corrupt(path, "vanished during listing")
                    listed.append(ListedObject(key, sidecar.metadata, sidecar.version))
                return listed
        except OSError as exc:
            raise _unavailable(exc) from exc

    def _collect(
        self, directory: Path, key_prefix: str, partial: str, out: list[tuple[str, Path]]
    ) -> None:
        """Gather sidecars under `directory` whose entry names start with `partial`."""
        try:
            entries = list(os.scandir(directory))
        except (FileNotFoundError, NotADirectoryError):
            return
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            if name.endswith(_SIDECAR_SUFFIX):
                leaf = _decode_segment(name[: -len(_SIDECAR_SUFFIX)])
                if leaf is not None and leaf.startswith(partial) and entry.is_file():
                    out.append((key_prefix + leaf, Path(entry.path)))
            elif name.endswith(_BODY_SUFFIX):
                continue
            else:
                dirname = _decode_segment(name)
                if dirname is not None and dirname.startswith(partial) and entry.is_dir():
                    self._collect(Path(entry.path), f"{key_prefix}{dirname}/", "", out)
