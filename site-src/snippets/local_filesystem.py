import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wenchang.core import MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.paths import build_path
from wenchang.storage.filesystem import FilesystemStorage

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "memory"  # created if missing; use a persistent path in practice
    store = MemoryStore(FilesystemStorage(root))

    path = build_path("user", "u-tianlong", "preferences", "prose-style")
    store.write_file(
        path,
        "- [stated] Writes in close third person, past tense.\n",
        FileMetadata(
            description="Prose style preferences",
            aliases=("narration",),
            sources=frozenset(),
            last_updated=datetime.now(UTC),
        ),
        None,  # create
        source="local-dev",
    )

    memory = store.read_file(path)
    assert memory.content == "- [stated] Writes in close third person, past tense.\n"

    # Each file is a plain body object beside a metadata sidecar.
    [body] = root.rglob("*%obj")
    assert body.read_text() == memory.content
    print(body.relative_to(root))
