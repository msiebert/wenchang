"""Conformance and filesystem-specific tests for FilesystemStorage (AIE-1335).

Covers the shared conformance suites (AC1), the on-disk layout (AC3), key
encoding and safety (AC4-AC6), version tokens (AC7, AC8), locking across
threads, instances and processes (AC9, AC10), crash leftovers (AC11),
listing (AC12, AC13), and error mapping (AC14-AC17).
"""

import itertools
import json
import multiprocessing
import os
import random
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from storage_conformance import EntityPurgeExportConformance, StorageConformance
from wenchang.errors import BackendUnavailableError, TransientReason
from wenchang.storage import PreconditionFailedError, Storage
from wenchang.storage.filesystem import FilesystemStorage, InvalidStorageKeyError
from wenchang.version_token import VersionToken

pytestmark = pytest.mark.unit

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="permission bits do not bind root"
)


@pytest.fixture
def storage(tmp_path: Path) -> FilesystemStorage:
    return FilesystemStorage(tmp_path / "root")


class TestFilesystemStorage(StorageConformance):
    """Runs the shared conformance suite against FilesystemStorage (AIE-1335, AC1)."""


class TestFilesystemEntityPurgeExport(EntityPurgeExportConformance):
    """Runs entity purge and export against FilesystemStorage (AIE-1335, AC1)."""


def _files(root: Path) -> set[str]:
    """Relative POSIX paths of every non-hidden file under `root`."""
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if not name.startswith("."):
                found.add((Path(dirpath) / name).relative_to(root).as_posix())
    return found


def _tree(root: Path) -> set[str]:
    """Relative paths of every file and directory under `root`, hidden included."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _list_keys(storage: Storage, prefix: str = "") -> list[str]:
    return [o.key for o in storage.list_page(prefix, None, 1000)]


# ---------------------------------------------------------------------------
# AC17 type compatibility
# ---------------------------------------------------------------------------


def test_filesystem_storage_satisfies_storage_protocol(tmp_path: Path) -> None:
    """FilesystemStorage is assignable to a `Storage`-typed variable without a
    cast (AIE-1335, AC17).
    """
    instance: Storage = FilesystemStorage(tmp_path / "root")
    assert instance.get("anything") is None


# ---------------------------------------------------------------------------
# AC3 on-disk layout
# ---------------------------------------------------------------------------


def test_put_writes_body_and_sidecar_in_mirrored_directories(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """put writes the body bytes to `L%obj` and a UTF-8 JSON sidecar to
    `L%meta` beside it, and no other non-hidden file (AIE-1335, AC3).
    """
    root = tmp_path / "root"
    body = "- fact café\n".encode() + b"\xff\x00"
    token = storage.put("user/u1/notes/a.md", body, {"k": "v"})

    assert (root / "user/u1/notes/a.md%obj").read_bytes() == body
    sidecar = json.loads((root / "user/u1/notes/a.md%meta").read_bytes().decode("utf-8"))
    assert sidecar == {"format": 1, "version": token, "metadata": {"k": "v"}}
    assert _files(root) == {"user/u1/notes/a.md%obj", "user/u1/notes/a.md%meta"}


def test_worked_example_layout(storage: FilesystemStorage, tmp_path: Path) -> None:
    """The plan's worked example produces exactly the documented tree: a key
    equal to a directory prefix, escaped uppercase and non-ASCII, and an empty
    segment (AIE-1335, AC3).
    """
    root = tmp_path / "root"
    storage.put("user/u1/notes/a.md", b"- fact\n", {"k": "v"})
    storage.put("user/u1/notes", b"x", {})
    storage.put("User/Éa", b"y", {})
    storage.put("a//b", b"z", {})

    assert _files(root) == {
        "user/u1/notes/a.md%obj",
        "user/u1/notes/a.md%meta",
        "user/u1/notes%obj",
        "user/u1/notes%meta",
        "%55ser/%C3%89a%obj",
        "%55ser/%C3%89a%meta",
        "a/%/b%obj",
        "a/%/b%meta",
    }
    assert (root / "user/u1/notes%obj").read_bytes() == b"x"
    assert (root / "%55ser/%C3%89a%obj").read_bytes() == b"y"
    assert (root / "a/%/b%obj").read_bytes() == b"z"
    assert (root / ".lock").is_file()


def test_sidecar_is_ascii_sorted_json_and_round_trips_lone_surrogates(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """The sidecar is `ensure_ascii`, `sort_keys` JSON, so lone surrogates in
    metadata values round-trip (AIE-1335, AC3).
    """
    metadata = {"z": "\ud800", "a": "é"}
    storage.put("k", b"d", metadata)
    raw = (tmp_path / "root" / "k%meta").read_bytes()
    text = raw.decode("ascii")
    assert text == json.dumps(json.loads(text), ensure_ascii=True, sort_keys=True)
    result = storage.get("k")
    assert result is not None
    assert dict(result.metadata) == metadata


def test_no_temp_files_remain_after_writes_and_deletes(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """Successful and failed writes leave no `.tmp-*` file behind (AIE-1335, AC3)."""
    root = tmp_path / "root"
    token = storage.put("d/k", b"1", {})
    with pytest.raises(PreconditionFailedError):
        storage.put_if_version("d/k", b"2", {}, VersionToken("nope"))
    token = storage.put_if_version("d/k", b"3", {}, token)
    storage.delete_if_version("d/k", token)
    assert [p for p in root.rglob(".tmp-*")] == []


def test_delete_removes_files_and_empty_parent_directories(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """delete_if_version removes the body, sidecar and now-empty parent
    directories, but never `root` itself (AIE-1335, AC3).
    """
    root = tmp_path / "root"
    token = storage.put("a/b/c.md", b"x", {})
    other = storage.put("a/keep.md", b"y", {})
    storage.delete_if_version("a/b/c.md", token)
    assert _files(root) == {"a/keep.md%obj", "a/keep.md%meta"}
    assert not (root / "a/b").exists()
    storage.delete_if_version("a/keep.md", other)
    assert _files(root) == set()
    assert not (root / "a").exists()
    assert root.is_dir()


def test_hand_edited_body_is_visible_and_keeps_its_version(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """Editing a body in place changes what get returns but not the version
    (AIE-1335, AC3).
    """
    token = storage.put("n/a.md", b"before", {"k": "v"})
    (tmp_path / "root" / "n/a.md%obj").write_bytes(b"after")
    result = storage.get("n/a.md")
    assert result is not None
    assert result.data == b"after"
    assert result.version == token
    assert dict(result.metadata) == {"k": "v"}
    assert storage.put_if_version("n/a.md", b"next", {}, token) != token


# ---------------------------------------------------------------------------
# AC4 coexisting keys
# ---------------------------------------------------------------------------

COEXISTING = ("a", "a/b", "a/b/c", "a/")


@pytest.mark.parametrize("order", list(itertools.permutations(COEXISTING)))
def test_a_and_a_slash_b_coexist_in_any_write_order(tmp_path: Path, order: tuple[str, ...]) -> None:
    """`a`, `a/b`, `a/b/c` and `a/` coexist in any write order, each returns
    its own bytes, and listing is ascending (AIE-1335, AC4).
    """
    storage = FilesystemStorage(tmp_path / "root")
    for key in order:
        storage.put(key, key.encode(), {"key": key})
    for key in COEXISTING:
        result = storage.get(key)
        assert result is not None
        assert result.data == key.encode()
        assert dict(result.metadata) == {"key": key}
    assert _list_keys(storage) == sorted(COEXISTING)


def test_deleting_a_leaves_children_intact(storage: FilesystemStorage) -> None:
    """Deleting `a` leaves `a/b`, `a/b/c` and `a/` readable; deleting `a/b`
    leaves `a/b/c` (AIE-1335, AC4).
    """
    tokens = {key: storage.put(key, key.encode(), {}) for key in COEXISTING}
    storage.delete_if_version("a", tokens["a"])
    assert storage.get("a") is None
    assert _list_keys(storage) == ["a/", "a/b", "a/b/c"]
    storage.delete_if_version("a/b", tokens["a/b"])
    result = storage.get("a/b/c")
    assert result is not None
    assert result.data == b"a/b/c"
    assert _list_keys(storage) == ["a/", "a/b/c"]


# ---------------------------------------------------------------------------
# AC5 key-escape safety
# ---------------------------------------------------------------------------

AWKWARD_KEYS = (
    "../x",
    "/abs",
    "a/../b",
    ".",
    "..",
    "a/./b",
    "a//b",
    ".hidden",
    "a\x00b",
    "%2e%2e/x",
    "A",
    "a",
    "café/é",
    "back\\slash",
)


@pytest.mark.parametrize("key", AWKWARD_KEYS)
def test_awkward_key_round_trips_and_lists_under_its_exact_key(
    storage: FilesystemStorage, key: str
) -> None:
    """Each awkward key round-trips byte-for-byte and lists under its exact
    original key (AIE-1335, AC5).
    """
    data = b"payload:" + key.encode()
    token = storage.put(key, data, {"origin": key})
    result = storage.get(key)
    assert result is not None
    assert result.data == data
    assert dict(result.metadata) == {"origin": key}
    assert result.version == token
    listed = storage.list_page("", None, 100)
    assert [o.key for o in listed] == [key]
    assert listed[0].version == token


def test_awkward_keys_coexist_distinctly_and_stay_inside_root(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """All awkward keys coexist as distinct objects (`A` vs `a` included), every
    path under root resolves inside root, and nothing is written outside it
    (AIE-1335, AC5).
    """
    root = tmp_path / "root"
    for key in AWKWARD_KEYS:
        storage.put(key, key.encode(), {})
    for key in AWKWARD_KEYS:
        result = storage.get(key)
        assert result is not None
        assert result.data == key.encode()
    assert _list_keys(storage) == sorted(AWKWARD_KEYS)

    real_root = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            resolved = os.path.realpath(os.path.join(dirpath, name))
            assert resolved == real_root or resolved.startswith(real_root + os.sep)
    assert {p.name for p in tmp_path.iterdir()} == {"root"}


@pytest.mark.parametrize("prefix", ["../", "..", "../x", ".", "a/../"])
def test_list_page_with_traversal_prefix_returns_nothing(
    storage: FilesystemStorage, prefix: str
) -> None:
    """A traversal-shaped prefix lists nothing and does not leave root
    (AIE-1335, AC5).
    """
    storage.put("a", b"x", {})
    assert storage.list_page(prefix, None, 100) == []


def test_case_variants_get_distinct_names_on_disk(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """Keys differing only by case map to names that differ even when folded to
    lower case, so a case-insensitive filesystem cannot merge them (AIE-1335, AC5).
    """
    storage.put("Abc", b"1", {})
    storage.put("abc", b"2", {})
    names = [n for n in _files(tmp_path / "root")]
    assert len({n.lower() for n in names}) == len(names) == 4


# ---------------------------------------------------------------------------
# AC6 invalid keys
# ---------------------------------------------------------------------------

INVALID_KEYS = ("", "\ud800", "x/\ud800", "a" * 201, "ok/" + "b" * 250, "é" * 70)


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_key_raises_on_every_keyed_method_and_writes_nothing(
    storage: FilesystemStorage, tmp_path: Path, key: str
) -> None:
    """An empty, unencodable, or over-long-segment key raises
    InvalidStorageKeyError from get, put, put_if_version and delete_if_version
    and creates no file (AIE-1335, AC6).
    """
    root = tmp_path / "root"
    before = _tree(root)
    token = VersionToken("a" * 32)
    calls: list[Callable[[], Any]] = [
        lambda: storage.get(key),
        lambda: storage.put(key, b"x", {}),
        lambda: storage.put_if_version(key, b"x", {}, None),
        lambda: storage.put_if_version(key, b"x", {}, token),
        lambda: storage.delete_if_version(key, token),
    ]
    for call in calls:
        with pytest.raises(InvalidStorageKeyError):
            call()
    assert _tree(root) - {".lock"} == before - {".lock"}


def test_invalid_storage_key_error_is_a_value_error() -> None:
    """InvalidStorageKeyError subclasses ValueError (AIE-1335, AC6)."""
    assert issubclass(InvalidStorageKeyError, ValueError)


def test_segment_of_exactly_200_encoded_bytes_is_accepted(storage: FilesystemStorage) -> None:
    """A segment whose encoding is exactly 200 bytes is valid (AIE-1335, AC6)."""
    key = "d/" + "a" * 200
    storage.put(key, b"x", {})
    result = storage.get(key)
    assert result is not None
    assert result.data == b"x"


@pytest.mark.parametrize("prefix", ["\ud800", "a" * 300, "x/\ud800"])
def test_list_page_with_unencodable_prefix_returns_nothing(
    storage: FilesystemStorage, prefix: str
) -> None:
    """list_page does not raise for a prefix no stored key can start with
    (AIE-1335, AC6).
    """
    storage.put("a", b"x", {})
    assert storage.list_page(prefix, None, 100) == []


@pytest.mark.parametrize("start_after", ["\ud800", "a" * 300, ""])
def test_list_page_with_unusual_start_after_does_not_raise(
    storage: FilesystemStorage, start_after: str
) -> None:
    """list_page does not raise for an unencodable or over-long `start_after`
    (AIE-1335, AC6).
    """
    storage.put("a", b"x", {})
    expected = [k for k in ["a"] if k > start_after]
    assert _list_keys_after(storage, start_after) == expected


def _list_keys_after(storage: Storage, start_after: str) -> list[str]:
    return [o.key for o in storage.list_page("", start_after, 100)]


# ---------------------------------------------------------------------------
# AC7 token non-reuse
# ---------------------------------------------------------------------------


def test_tokens_have_documented_shape(storage: FilesystemStorage) -> None:
    """A token is 32 lowercase hex characters (AIE-1335, AC7)."""
    token = storage.put("k", b"x", {})
    assert re.fullmatch(r"[0-9a-f]{32}", token)


@pytest.mark.parametrize("create", ["put", "put_if_version"])
def test_tokens_never_repeat_across_put_delete_reput(
    storage: FilesystemStorage, create: str
) -> None:
    """Fifty create/delete cycles on one key never reuse a token, including
    the deleted one (AIE-1335, AC7).
    """
    seen: list[str] = []
    for _ in range(50):
        if create == "put":
            token = storage.put("k", b"x", {})
        else:
            token = storage.put_if_version("k", b"x", {}, None)
        assert token not in seen
        seen.append(token)
        storage.delete_if_version("k", token)
    assert len(set(seen)) == 50


# ---------------------------------------------------------------------------
# AC8 fresh instance on same root
# ---------------------------------------------------------------------------


def test_fresh_instance_sees_same_state_and_tokens(tmp_path: Path) -> None:
    """A second instance on the same root reads the same bytes, metadata and
    token, can update with it, and invalidates the first instance's token
    (AIE-1335, AC8).
    """
    root = tmp_path / "root"
    a = FilesystemStorage(root)
    t1 = a.put("k", b"one", {"m": "1"})
    b = FilesystemStorage(root)
    seen = b.get("k")
    assert seen is not None
    assert seen.data == b"one"
    assert dict(seen.metadata) == {"m": "1"}
    assert seen.version == t1
    t2 = b.put_if_version("k", b"two", {}, t1)
    assert t2 != t1
    with pytest.raises(PreconditionFailedError):
        a.put_if_version("k", b"three", {}, t1)
    current = a.get("k")
    assert current is not None
    assert current.data == b"two"
    assert current.version == t2


# ---------------------------------------------------------------------------
# AC9 threads across two instances
# ---------------------------------------------------------------------------

THREADS_PER_INSTANCE = 8
ROUNDS = 5


def _race(
    instances: list[FilesystemStorage],
    action: Callable[[FilesystemStorage, int], VersionToken | None],
) -> tuple[list[tuple[int, VersionToken | None]], int]:
    """Run `action` from 16 threads released together. Returns the winners as
    (thread index, result) and the count of PreconditionFailedError losers.
    """
    total = THREADS_PER_INSTANCE * len(instances)
    barrier = threading.Barrier(total)

    def run(index: int) -> tuple[int, VersionToken | None] | None:
        instance = instances[index % len(instances)]
        barrier.wait(timeout=30)
        try:
            return (index, action(instance, index))
        except PreconditionFailedError:
            return None

    with ThreadPoolExecutor(max_workers=total) as pool:
        outcomes = list(pool.map(run, range(total)))
    winners = [o for o in outcomes if o is not None]
    return winners, total - len(winners)


def test_two_instances_race_create_update_delete_with_one_winner(tmp_path: Path) -> None:
    """Sixteen threads over two instances racing create, update and delete
    each produce exactly one winner and `PreconditionFailedError` for the rest
    (AIE-1335, AC9).
    """
    root = tmp_path / "root"
    instances = [FilesystemStorage(root), FilesystemStorage(root)]
    reader = instances[0]
    total = THREADS_PER_INSTANCE * len(instances)

    for round_no in range(ROUNDS):
        key = f"race/{round_no}"

        winners, losers = _race(
            instances,
            lambda s, i, key=key: s.put_if_version(key, f"create-{i}".encode(), {}, None),
        )
        assert len(winners) == 1
        assert losers == total - 1
        created = reader.get(key)
        assert created is not None
        assert created.data == f"create-{winners[0][0]}".encode()
        v1 = winners[0][1]
        assert created.version == v1
        assert v1 is not None

        winners, losers = _race(
            instances,
            lambda s, i, key=key, v1=v1: s.put_if_version(key, f"update-{i}".encode(), {}, v1),
        )
        assert len(winners) == 1
        assert losers == total - 1
        updated = reader.get(key)
        assert updated is not None
        assert updated.data == f"update-{winners[0][0]}".encode()
        v2 = winners[0][1]
        assert updated.version == v2
        assert v2 is not None

        def delete(s: FilesystemStorage, _i: int, key: str = key, v2: VersionToken = v2) -> None:
            s.delete_if_version(key, v2)

        winners, losers = _race(instances, delete)
        assert len(winners) == 1
        assert losers == total - 1
        assert reader.get(key) is None


# ---------------------------------------------------------------------------
# AC10 cross-process race
# ---------------------------------------------------------------------------

PROCESSES = 4
PROCESS_ROUNDS = 5


def _process_worker(root: str, worker_id: int, barrier: Any, results: Any) -> None:
    """Spawned-process target: race to create each round's key once."""
    local = FilesystemStorage(Path(root))
    for round_no in range(PROCESS_ROUNDS):
        key = f"proc/{round_no}"
        barrier.wait(timeout=60)
        try:
            local.put_if_version(key, f"worker-{worker_id}".encode(), {}, None)
            results.put((round_no, worker_id, "won"))
        except PreconditionFailedError:
            results.put((round_no, worker_id, "lost"))
        except Exception as exc:
            results.put((round_no, worker_id, f"error: {exc!r}"))


def test_processes_race_create_with_exactly_one_winner_per_key(tmp_path: Path) -> None:
    """Four spawned processes racing to create each of five keys produce one
    winner per key, and every loser sees `PreconditionFailedError`
    (AIE-1335, AC10).
    """
    root = tmp_path / "root"
    FilesystemStorage(root)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(PROCESSES)
    results = ctx.Queue()
    procs = [
        ctx.Process(target=_process_worker, args=(str(root), i, barrier, results))
        for i in range(PROCESSES)
    ]
    for proc in procs:
        proc.start()
    outcomes: list[tuple[int, int, str]] = [
        results.get(timeout=120) for _ in range(PROCESSES * PROCESS_ROUNDS)
    ]
    for proc in procs:
        proc.join(timeout=60)
        assert proc.exitcode == 0

    reader = FilesystemStorage(root)
    for round_no in range(PROCESS_ROUNDS):
        round_outcomes = [(w, o) for r, w, o in outcomes if r == round_no]
        assert sorted(o for _, o in round_outcomes) == ["lost"] * (PROCESSES - 1) + ["won"]
        winner = next(w for w, o in round_outcomes if o == "won")
        stored = reader.get(f"proc/{round_no}")
        assert stored is not None
        assert stored.data == f"worker-{winner}".encode()


# ---------------------------------------------------------------------------
# AC11 orphans and stray temp files
# ---------------------------------------------------------------------------


def _plant_orphan_and_temps(root: Path) -> Path:
    directory = root / "dir"
    directory.mkdir(parents=True)
    (directory / "orphan%obj").write_bytes(b"orphan body")
    (directory / ".tmp-0123456789abcdef0123456789abcdef").write_bytes(b"stray")
    (directory / ".tmp-fedcba9876543210fedcba9876543210").write_bytes(b'{"format": 1}')
    return directory


def test_orphan_body_and_temp_files_are_invisible(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A body with no sidecar and stray `.tmp-*` files are invisible to get and
    list_page (AIE-1335, AC11).
    """
    _plant_orphan_and_temps(tmp_path / "root")
    storage.put("dir/real", b"real", {})
    assert storage.get("dir/orphan") is None
    assert _list_keys(storage) == ["dir/real"]
    assert _list_keys(storage, "dir/o") == []


def test_create_overwrites_orphan_body(storage: FilesystemStorage, tmp_path: Path) -> None:
    """put_if_version(..., None) succeeds over an orphan body and replaces it
    (AIE-1335, AC11).
    """
    directory = _plant_orphan_and_temps(tmp_path / "root")
    token = storage.put_if_version("dir/orphan", b"fresh", {"k": "v"}, None)
    result = storage.get("dir/orphan")
    assert result is not None
    assert result.data == b"fresh"
    assert result.version == token
    assert (directory / "orphan%obj").read_bytes() == b"fresh"
    assert _list_keys(storage) == ["dir/orphan"]


def test_sidecar_less_body_after_interrupted_delete_is_absent(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A body left behind after its sidecar was removed reads as absent and a
    stale token no longer deletes it (AIE-1335, AC11).
    """
    token = storage.put("dir/k", b"x", {})
    (tmp_path / "root" / "dir" / "k%meta").unlink()
    assert storage.get("dir/k") is None
    assert _list_keys(storage) == []
    with pytest.raises(PreconditionFailedError):
        storage.delete_if_version("dir/k", token)
    storage.put_if_version("dir/k", b"y", {}, None)


# ---------------------------------------------------------------------------
# AC12 ordering and paging
# ---------------------------------------------------------------------------

ORDER_KEYS = ["a-b", "a/b", "a0", "a.b", "a", "B", "a/", "é"]
PAGING_KEYS = [
    *ORDER_KEYS,
    "a//b",
    "user/u1/notes/a.md",
    "user/u1/notes/b.md",
    "user/u1/prefs/c.md",
    "user/u10/notes/a.md",
    "user-archive/u1/notes/a.md",
    "user/u1",
    "%",
    "%41",
    "A",
]


def _shuffled(keys: list[str]) -> list[str]:
    shuffled = list(keys)
    random.Random(1335).shuffle(shuffled)
    return shuffled


def test_list_page_returns_code_point_order_not_walk_order(
    storage: FilesystemStorage,
) -> None:
    """Keys come back in `sorted(keys)` order whatever the write order
    (AIE-1335, AC12).
    """
    for key in _shuffled(ORDER_KEYS):
        storage.put(key, key.encode(), {})
    assert _list_keys(storage) == sorted(ORDER_KEYS)


def test_list_page_pages_through_every_key_once(storage: FilesystemStorage) -> None:
    """Paging with limit 3 and `start_after` carried forward reproduces the
    sorted sequence with no repeats or gaps (AIE-1335, AC12).
    """
    for key in _shuffled(ORDER_KEYS):
        storage.put(key, key.encode(), {})
    collected: list[str] = []
    start_after: str | None = None
    while True:
        page = storage.list_page("", start_after, 3)
        assert len(page) <= 3
        if not page:
            break
        if len(collected) + len(page) < len(ORDER_KEYS):
            assert len(page) == 3
        collected.extend(o.key for o in page)
        start_after = page[-1].key
    assert collected == sorted(ORDER_KEYS)


@pytest.mark.parametrize(
    "prefix",
    ["", "a", "a/", "a-", "a/b", "a//", "é", "B", "user/u1/", "user/u1", "user/u1/n", "user/u10",
     "user", "user-", "x/", "%", "%4", "A", "a.", "zz"],
)  # fmt: skip
@pytest.mark.parametrize("start_after", [None, "a", "a/b", "user/u1/notes/a.md", "￿"])
def test_list_page_matches_sorted_filter_for_any_prefix_and_start_after(
    storage: FilesystemStorage, prefix: str, start_after: str | None
) -> None:
    """list_page equals the sorted, prefix-and-start_after-filtered key set,
    for whole-segment and partial-segment prefixes alike (AIE-1335, AC12).
    """
    for key in _shuffled(PAGING_KEYS):
        storage.put(key, key.encode(), {"key": key})
    expected = [
        k
        for k in sorted(PAGING_KEYS)
        if k.startswith(prefix) and (start_after is None or k > start_after)
    ]
    for limit in (1, 4, 100):
        listed = storage.list_page(prefix, start_after, limit)
        assert [o.key for o in listed] == expected[:limit]
        assert [dict(o.metadata) for o in listed] == [{"key": o.key} for o in listed]


def test_list_page_metadata_and_version_match_get(storage: FilesystemStorage) -> None:
    """Listed metadata and version equal get's for the same key (AIE-1335, AC12)."""
    for key in ORDER_KEYS:
        storage.put(key, b"x", {"key": key})
    for listed in storage.list_page("", None, 100):
        got = storage.get(listed.key)
        assert got is not None
        assert got.version == listed.version
        assert dict(got.metadata) == dict(listed.metadata)


# ---------------------------------------------------------------------------
# AC13 no body reads
# ---------------------------------------------------------------------------


@needs_non_root
def test_list_page_never_opens_bodies(storage: FilesystemStorage, tmp_path: Path) -> None:
    """list_page succeeds with correct keys, metadata and versions when every
    body is unreadable (AIE-1335, AC13).
    """
    keys = ["n/a.md", "n/b.md", "m/c.md"]
    tokens = {k: storage.put(k, b"secret", {"key": k}) for k in keys}
    bodies = [p for p in (tmp_path / "root").rglob("*%obj")]
    assert len(bodies) == len(keys)
    try:
        for body in bodies:
            body.chmod(0o000)
        listed = storage.list_page("", None, 100)
    finally:
        for body in bodies:
            body.chmod(0o600)
    assert [o.key for o in listed] == sorted(keys)
    for o in listed:
        assert o.version == tokens[o.key]
        assert dict(o.metadata) == {"key": o.key}


# ---------------------------------------------------------------------------
# AC14 missing key
# ---------------------------------------------------------------------------


def test_get_missing_key_returns_none_in_every_shape(storage: FilesystemStorage) -> None:
    """get returns None, not an error, for a missing key, a key under an
    absent directory, a key whose parent is itself an object, and a key that is
    only a directory (AIE-1335, AC14).
    """
    assert storage.get("nope") is None
    assert storage.get("no/such/dir/key") is None
    storage.put("a", b"x", {})
    storage.put("d/e", b"x", {})
    assert storage.get("a/b") is None
    assert storage.get("d") is None
    assert storage.get("d/") is None


# ---------------------------------------------------------------------------
# AC15 error mapping
# ---------------------------------------------------------------------------


@needs_non_root
def test_put_into_read_only_root_raises_backend_unavailable(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A write that fails with an OSError raises BackendUnavailableError
    (UNAVAILABLE) chained from it (AIE-1335, AC15).
    """
    root = tmp_path / "root"
    storage.put("seed", b"x", {})
    root.chmod(0o500)
    try:
        with pytest.raises(BackendUnavailableError) as excinfo:
            storage.put("new/key", b"y", {})
    finally:
        root.chmod(0o700)
    assert excinfo.value.reason is TransientReason.UNAVAILABLE
    assert isinstance(excinfo.value.__cause__, OSError)
    assert storage.get("new/key") is None


def _corrupt_sidecar(storage: FilesystemStorage, tmp_path: Path, content: bytes) -> None:
    storage.put("d/k", b"body", {})
    (tmp_path / "root" / "d" / "k%meta").write_bytes(content)


def test_invalid_json_sidecar_raises_backend_unavailable_on_get_and_list(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A sidecar that is not JSON makes get and list_page raise
    BackendUnavailableError (UNAVAILABLE) chained from the decode error
    (AIE-1335, AC15).
    """
    _corrupt_sidecar(storage, tmp_path, b"{not json")
    with pytest.raises(BackendUnavailableError) as get_info:
        storage.get("d/k")
    assert get_info.value.reason is TransientReason.UNAVAILABLE
    assert isinstance(get_info.value.__cause__, ValueError)
    with pytest.raises(BackendUnavailableError) as list_info:
        storage.list_page("", None, 100)
    assert list_info.value.reason is TransientReason.UNAVAILABLE
    assert isinstance(list_info.value.__cause__, ValueError)


@pytest.mark.parametrize(
    "content",
    [
        b"[]",
        b'{"format": 1}',
        b'{"format": 1, "version": 7, "metadata": {}}',
        b'{"format": 1, "version": "abc", "metadata": {"k": 1}}',
        b'{"format": 1, "version": "abc", "metadata": []}',
    ],
)
def test_wrong_shape_sidecar_raises_backend_unavailable(
    storage: FilesystemStorage, tmp_path: Path, content: bytes
) -> None:
    """A sidecar of valid JSON but the wrong shape raises
    BackendUnavailableError from get and list_page (AIE-1335, AC15).
    """
    _corrupt_sidecar(storage, tmp_path, content)
    with pytest.raises(BackendUnavailableError):
        storage.get("d/k")
    with pytest.raises(BackendUnavailableError):
        storage.list_page("", None, 100)


def test_invalid_sidecar_does_not_silently_pass_conditional_writes(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A conditional write over a corrupt sidecar raises
    BackendUnavailableError rather than overwriting it (AIE-1335, AC15).
    """
    _corrupt_sidecar(storage, tmp_path, b"{not json")
    with pytest.raises(BackendUnavailableError):
        storage.put_if_version("d/k", b"new", {}, VersionToken("a" * 32))
    with pytest.raises(BackendUnavailableError):
        storage.delete_if_version("d/k", VersionToken("a" * 32))


def test_body_missing_while_sidecar_exists_raises_backend_unavailable(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A sidecar with no body is a corrupt store and get raises
    BackendUnavailableError (AIE-1335, AC15).
    """
    storage.put("d/k", b"body", {})
    (tmp_path / "root" / "d" / "k%obj").unlink()
    with pytest.raises(BackendUnavailableError):
        storage.get("d/k")


@needs_non_root
def test_unreadable_sidecar_raises_backend_unavailable(
    storage: FilesystemStorage, tmp_path: Path
) -> None:
    """A permission error reading a sidecar raises BackendUnavailableError
    chained from the OSError (AIE-1335, AC15).
    """
    storage.put("d/k", b"body", {})
    sidecar = tmp_path / "root" / "d" / "k%meta"
    sidecar.chmod(0o000)
    try:
        with pytest.raises(BackendUnavailableError) as excinfo:
            storage.get("d/k")
    finally:
        sidecar.chmod(0o600)
    assert excinfo.value.reason is TransientReason.UNAVAILABLE
    assert isinstance(excinfo.value.__cause__, PermissionError)


def test_precondition_and_key_errors_are_not_mapped(storage: FilesystemStorage) -> None:
    """PreconditionFailedError and InvalidStorageKeyError pass through
    unwrapped (AIE-1335, AC15).
    """
    with pytest.raises(PreconditionFailedError):
        storage.delete_if_version("missing", VersionToken("a" * 32))
    with pytest.raises(InvalidStorageKeyError):
        storage.get("")


# ---------------------------------------------------------------------------
# AC16 root creation
# ---------------------------------------------------------------------------


def test_missing_root_and_parents_are_created(tmp_path: Path) -> None:
    """Constructing on a missing root creates it and its parents, and the
    `root` property returns the path as given (AIE-1335, AC16).
    """
    root = tmp_path / "deep" / "er" / "root"
    storage = FilesystemStorage(root)
    assert root.is_dir()
    assert storage.root == root
    assert storage.get("k") is None


def test_construction_on_existing_root_changes_nothing(tmp_path: Path) -> None:
    """Constructing on an existing root leaves its contents untouched
    (AIE-1335, AC16).
    """
    root = tmp_path / "root"
    first = FilesystemStorage(root)
    token = first.put("a/b", b"x", {"k": "v"})
    before = _tree(root)
    contents = (root / "a/b%obj").read_bytes()
    second = FilesystemStorage(root)
    assert _tree(root) == before
    assert (root / "a/b%obj").read_bytes() == contents
    result = second.get("a/b")
    assert result is not None
    assert result.version == token


def test_root_that_is_a_file_raises_backend_unavailable(tmp_path: Path) -> None:
    """An OSError creating the root maps to BackendUnavailableError
    (AIE-1335, AC16).
    """
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not a directory")
    with pytest.raises(BackendUnavailableError) as excinfo:
        FilesystemStorage(blocker)
    assert excinfo.value.reason is TransientReason.UNAVAILABLE
    assert isinstance(excinfo.value.__cause__, OSError)
