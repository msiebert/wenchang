"""The eval MCP server: the memory tools over an in-memory store, plus harness tools.

The seven memory tools are mounted with wenchang.mcp.register_memory_tools and
act as the active scenario's reference identity. Three harness tools, which
the eval agent's allowlist excludes, let the runner reset and seed the store,
record each turn, and dump the store, trace, and transcript as JSON.

Run over stdio: python -m evals.server [--runs-root PATH]
"""

import argparse
import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent

import wenchang
from evals.graders import (
    StoredFile,
    StoreDump,
    TraceCall,
    TranscriptTurn,
    store_dump_to_json,
    trace_to_json,
    transcript_to_json,
)
from evals.reference_adopter import (
    AGENT_SOURCE,
    MEMBER_IDENTITY,
    REFERENCE_POLICY,
    REFERENCE_PRODUCT,
    REFERENCE_SCOPE_PRIORITY,
    REFERENCE_SLOTS,
    SEED_SOURCE,
    seed_path,
)
from evals.scenario import RUNS_DIR, Scenario, ScenarioError, load_scenario
from wenchang.core import ListCursor, ListPage, MemoryFile, MemoryIndex, MemoryStore
from wenchang.file_format import FileMetadata
from wenchang.identity import Identity
from wenchang.mcp import ToolCallRecord, register_memory_tools
from wenchang.paths import build_prefix, parse_path
from wenchang.prompts import build_memory_prompt
from wenchang.storage.memory import InMemoryStorage
from wenchang.transport import InProcessClient
from wenchang.version_token import VersionToken

__all__ = [
    "EVAL_SERVER_INSTRUCTIONS",
    "EVAL_SOURCE",
    "HARNESS_TOOL_NAMES",
    "EvalState",
    "build_eval_server",
    "main",
]

EVAL_SOURCE: Final = AGENT_SOURCE
EVAL_SERVER_INSTRUCTIONS: Final[str] = (
    "Dev-only wenchang eval server. The memory tools act on an in-memory store "
    "that the eval runner resets per trial; eval_* tools are for the runner only."
)
HARNESS_TOOL_NAMES: Final[tuple[str, ...]] = ("eval_reset", "eval_record_turn", "eval_dump")


@dataclass(frozen=True)
class _Record:
    seq: int
    record: ToolCallRecord
    started_ms: float
    completed_ms: float


@dataclass(frozen=True)
class _Boundary:
    at_ms: float
    session: int
    turn: int


def _new_store() -> MemoryStore:
    return MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY)


class EvalState:
    """The active trial: client, identity, trace, transcript, and trial dir.

    Times are milliseconds on clock (monotonic seconds by default) since the
    state was created; resets do not move that baseline.
    """

    def __init__(
        self, runs_root: Path = RUNS_DIR, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._baseline = clock()
        self.runs_root = runs_root.resolve()
        self._client = InProcessClient(_new_store())
        self._identity = MEMBER_IDENTITY
        self._trial_dir: Path | None = None
        self._records: list[_Record] = []
        self._boundaries: list[_Boundary] = []
        self._turns: list[TranscriptTurn] = []

    def _now_ms(self) -> float:
        return (self._clock() - self._baseline) * 1000

    @property
    def client(self) -> InProcessClient:
        with self._lock:
            return self._client

    @property
    def identity(self) -> Identity:
        with self._lock:
            return self._identity

    def resolve_trial_dir(self, trial_dir: Path) -> Path:
        """trial_dir made absolute; raises ValueError unless it is under runs_root."""
        resolved = trial_dir.resolve()
        if not resolved.is_relative_to(self.runs_root):
            raise ValueError(f"trial_dir {trial_dir} is not under the runs root {self.runs_root}")
        return resolved

    def reset(self, scenario: Scenario, trial_dir: Path) -> None:
        """Start a trial: a fresh store seeded for the scenario, an empty trace.

        Raises ValueError, leaving the current trial untouched, if trial_dir
        is outside runs_root.
        """
        resolved = self.resolve_trial_dir(trial_dir)
        client = InProcessClient(_new_store())
        now = datetime.now(UTC)
        for seed in scenario.seed_files:
            metadata = FileMetadata(
                description=seed.description,
                aliases=seed.aliases,
                sources=frozenset(),
                last_updated=now,
            )
            client.write_file(
                seed_path(seed, scenario.identity),
                seed.content,
                metadata,
                None,
                source=SEED_SOURCE,
            )
        with self._lock:
            self._client = client
            self._identity = scenario.identity
            self._trial_dir = resolved
            self._records = []
            self._boundaries = []
            self._turns = []

    def record_call(self, record: ToolCallRecord) -> None:
        """The on_call observer: stamp the record and append it to the trace."""
        with self._lock:
            completed = self._now_ms()
            self._records.append(
                _Record(
                    seq=len(self._records) + 1,
                    record=record,
                    started_ms=completed - record.duration_s * 1000,
                    completed_ms=completed,
                )
            )

    def record_turn(
        self, session: int, turn: int, user: str, reply: str, agent_id: str | None = None
    ) -> None:
        """Close the time window for (session, turn) and keep the exchange."""
        with self._lock:
            self._boundaries.append(_Boundary(self._now_ms(), session, turn))
            self._turns.append(TranscriptTurn(session, turn, user, reply, agent_id))

    def _tag(self, started_ms: float) -> tuple[int, int]:
        for boundary in self._boundaries:
            if started_ms < boundary.at_ms:
                return boundary.session, boundary.turn
        return 0, 0

    def trace(self) -> tuple[TraceCall, ...]:
        with self._lock:
            calls: list[TraceCall] = []
            for r in self._records:
                session, turn = self._tag(r.started_ms)
                calls.append(
                    TraceCall(
                        seq=r.seq,
                        request_id=r.record.request_id,
                        duration_s=r.record.duration_s,
                        started_ms=r.started_ms,
                        completed_ms=r.completed_ms,
                        session=session,
                        turn=turn,
                        tool=r.record.tool,
                        arguments=r.record.arguments,
                        result=r.record.result,
                        is_error=r.record.is_error,
                    )
                )
            return tuple(calls)

    def transcript(self) -> tuple[TranscriptTurn, ...]:
        with self._lock:
            return tuple(self._turns)

    def store_dump(self) -> StoreDump:
        """Every file under the identity's entities, with content and metadata."""
        client, identity = self.client, self.identity
        files: list[StoredFile] = []
        for scope, entity in sorted(identity.scope_map.items()):
            cursor: ListCursor | None = None
            while True:
                page = client.list_prefix(build_prefix(scope, entity), cursor)
                for entry in page.entries:
                    files.append(_stored(client.read_file(entry.path)))
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        return StoreDump(tuple(sorted(files, key=lambda f: f.path)))

    def dump(self) -> dict[str, object]:
        """Write store.json, trace.json, and transcript.json to the trial dir.

        Raises RuntimeError if no trial has been started with reset.
        """
        with self._lock:
            trial_dir = self._trial_dir
        if trial_dir is None:
            raise RuntimeError("no trial in progress: call eval_reset first")
        store, trace, transcript = self.store_dump(), self.trace(), self.transcript()
        trial_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "store": trial_dir / "store.json",
            "trace": trial_dir / "trace.json",
            "transcript": trial_dir / "transcript.json",
        }
        paths["store"].write_text(json.dumps(store_dump_to_json(store), indent=2))
        paths["trace"].write_text(json.dumps(trace_to_json(trace), indent=2))
        paths["transcript"].write_text(json.dumps(transcript_to_json(transcript), indent=2))
        return {
            **{key: str(path) for key, path in paths.items()},
            "files": len(store.files),
            "calls": len(trace),
        }


def _stored(f: MemoryFile) -> StoredFile:
    parts = parse_path(f.path)
    return StoredFile(
        path=f.path,
        scope=parts.scope,
        area=parts.area,
        name=parts.name,
        content=f.content,
        description=f.metadata.description,
        aliases=f.metadata.aliases,
        sources=tuple(sorted(f.metadata.sources)),
        version=str(f.version),
    )


class _ActiveClient:
    """A TransportClient forwarding to the state's current in-process client."""

    def __init__(self, state: EvalState) -> None:
        self._state = state

    def read_file(self, path: str) -> MemoryFile:
        return self._state.client.read_file(path)

    def write_file(
        self,
        path: str,
        content: str,
        metadata: FileMetadata,
        expected_version: VersionToken | None,
        *,
        source: str,
    ) -> MemoryFile:
        return self._state.client.write_file(
            path, content, metadata, expected_version, source=source
        )

    def append_line(
        self,
        path: str,
        line: str,
        expected_version: VersionToken,
        *,
        source: str,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        return self._state.client.append_line(
            path, line, expected_version, source=source, aliases=aliases, description=description
        )

    def replace_fact(
        self,
        path: str,
        old_string: str,
        new_string: str,
        expected_version: VersionToken,
        *,
        source: str,
        aliases: Sequence[str] | None = None,
        description: str | None = None,
    ) -> MemoryFile:
        return self._state.client.replace_fact(
            path,
            old_string,
            new_string,
            expected_version,
            source=source,
            aliases=aliases,
            description=description,
        )

    def list_prefix(self, prefix: str, cursor: ListCursor | None = None) -> ListPage:
        return self._state.client.list_prefix(prefix, cursor)

    def delete_file(self, path: str, expected_version: VersionToken) -> None:
        self._state.client.delete_file(path, expected_version)

    def get_memory_index(self, scope_map: Mapping[str, str]) -> MemoryIndex:
        return self._state.client.get_memory_index(scope_map)


class _ActiveResolver:
    """Resolves every caller to the active scenario's identity."""

    def __init__(self, state: EvalState) -> None:
        self._state = state

    def resolve(self, credentials: object) -> Identity:
        return self._state.identity


def _no_credentials(ctx: Context[Any, Any]) -> None:
    return None


def _ok(payload: dict[str, object]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=False,
    )


def _error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def build_eval_server(state: EvalState | None = None) -> MCPServer:
    """The eval server: memory tools on state's active store, plus the harness tools."""
    state = EvalState() if state is None else state
    server = MCPServer(
        "wenchang", instructions=EVAL_SERVER_INSTRUCTIONS, version=wenchang.__version__
    )
    register_memory_tools(
        server,
        prompt=build_memory_prompt(REFERENCE_SLOTS),
        client=_ActiveClient(state),
        resolver=_ActiveResolver(state),
        policy=REFERENCE_POLICY,
        credentials_from_context=_no_credentials,
        source=EVAL_SOURCE,
        product=REFERENCE_PRODUCT,
        on_call=state.record_call,
    )

    def eval_reset(scenario_path: str, trial_dir: str) -> CallToolResult:
        try:
            scenario = load_scenario(Path(scenario_path))
            state.reset(scenario, Path(trial_dir))
        except (ScenarioError, ValueError) as exc:
            return _error(str(exc))
        return _ok(
            {
                "scenario": scenario.id,
                "identity": scenario.identity_name,
                "seeded": len(scenario.seed_files),
                "trial_dir": str(state.resolve_trial_dir(Path(trial_dir))),
            }
        )

    def eval_record_turn(
        session: int, turn: int, user: str, reply: str, agent_id: str | None = None
    ) -> CallToolResult:
        state.record_turn(session, turn, user, reply, agent_id)
        return _ok({"session": session, "turn": turn})

    def eval_dump() -> CallToolResult:
        try:
            return _ok(state.dump())
        except RuntimeError as exc:
            return _error(str(exc))

    server.add_tool(
        eval_reset,
        name="eval_reset",
        description=(
            "Harness only. Start a trial: load the scenario file, replace the store with "
            "its seeds under its identity, and clear the trace and transcript. trial_dir "
            "must be under evals/runs/."
        ),
    )
    server.add_tool(
        eval_record_turn,
        name="eval_record_turn",
        description=(
            "Harness only. Record one turn's user message and the agent's verbatim reply. "
            "Memory calls started before this call belong to this turn."
        ),
    )
    server.add_tool(
        eval_dump,
        name="eval_dump",
        description=(
            "Harness only. Write store.json, trace.json, and transcript.json to the trial dir."
        ),
    )
    return server


def main(argv: Sequence[str] | None = None) -> None:
    """Serve the eval server over stdio."""
    parser = argparse.ArgumentParser(prog="python -m evals.server")
    parser.add_argument("--runs-root", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    build_eval_server(EvalState(runs_root=args.runs_root)).run("stdio")


if __name__ == "__main__":
    main()
