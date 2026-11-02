import logging
import threading
from collections import Counter, defaultdict
from contextlib import suppress

from wenchang.core import MemoryStore
from wenchang.errors import NotFoundError
from wenchang.identity import Identity, SandboxResolver, ScopeGrant
from wenchang.observer import ToolCallRecord
from wenchang.scope import ScopePolicy
from wenchang.storage.memory import InMemoryStorage
from wenchang.tools import bind_tools
from wenchang.transport import InProcessClient

log = logging.getLogger("inkwell.memory")

# Stand-ins for your metrics client: a call counter and per-tool latencies.
lock = threading.Lock()
calls: Counter[tuple[str, str]] = Counter()
latencies: defaultdict[str, list[float]] = defaultdict(list)


def on_call(record: ToolCallRecord) -> None:
    # arguments and result carry memory content; log only the call's shape.
    category = record.result.get("category") if record.is_error else None
    log.info(
        "memory tool=%s is_error=%s category=%s duration_s=%.3f",
        record.tool,
        record.is_error,
        category,
        record.duration_s,
    )
    with lock:  # under MCP, observers run on worker threads
        calls[(record.tool, str(category or "ok"))] += 1
        latencies[record.tool].append(record.duration_s)


client = InProcessClient(MemoryStore(InMemoryStorage()))
resolver = SandboxResolver(Identity(grants={"user": ScopeGrant("u-tianlong", "owner")}))
tools = bind_tools(client, resolver, None, ScopePolicy({}), source="inkwell-cli", on_call=on_call)

tools.get_memory_index()  # on_call has run by the time this returns
with suppress(NotFoundError):  # on_call sees it first: is_error=True, category=recoverable
    tools.read_file("user", "preferences", "csv")
print(calls)
