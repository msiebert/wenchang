# pyright: basic
import os
from datetime import UTC, datetime

from google.cloud import storage

from wenchang.core import MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.paths import build_path
from wenchang.storage.gcs import GcsStorage
from wenchang.transport import InProcessClient

bucket = storage.Client(project="my-gcp-project").bucket(os.environ["WENCHANG_BUCKET"])
client = InProcessClient(MemoryStore(GcsStorage(bucket)))

# Goes through the store directly, so it may write system/.
path = build_path("organization", "o-hanlin-press", "system", "house-style")
client.write_file(
    path,
    "- [system] Dialogue uses double quotation marks.\n"
    "- [system] Spelling follows British English.\n",
    FileMetadata(
        description="Hanlin Press house style",
        aliases=("style guide", "house style"),
        sources=frozenset(),
        last_updated=datetime.now(UTC),
    ),
    None,  # create; pass the current version to replace
    source="seed-job",
)
