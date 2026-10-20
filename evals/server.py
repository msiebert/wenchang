"""The eval MCP server: the memory tools over an in-memory store, plus harness tools.

The seven memory tools are mounted with wenchang.mcp.register_memory_tools and
act as the active scenario's reference identity. Three harness tools, which
the eval agent's allowlist excludes, let the runner reset and seed the store,
record each turn, and dump the store, trace, and transcript as JSON.

Run over stdio: python -m evals.server [--runs-root PATH] [--transcripts-root PATH]
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
from evals.subagent_transcript import (
    PermanentTranscriptError,
    SubagentTranscriptError,
    default_projects_root,
    find_subagent_transcript,
    text_blocks_from_transcript,
)
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
# Neutral on purpose: the memory prompt reaches the agent through its definition,
# and nothing here should tell the agent it is being evaluated. register_memory_tools
# therefore logs its "instructions lack the prompt" warning at every start.
EVAL_SERVER_INSTRUCTIONS: Final[str] = "Memory tools for this workspace."
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


def _new_store(index_max_bytes: int | None = None) -> MemoryStore:
    if index_max_bytes is None:
        return MemoryStore(InMemoryStorage(), scope_priority=REFERENCE_SCOPE_PRIORITY)
    return MemoryStore(
        InMemoryStorage(),
        scope_priority=REFERENCE_SCOPE_PRIORITY,
        index_max_bytes=index_max_bytes,
    )


def _squash(text: str) -> str:
    return " ".join(text.split())


class EvalState:
    """The active trial: client, identity, trace, transcript, and trial dir.

    Times are milliseconds on clock (monotonic seconds by default) since the
    state was created; resets do not move that baseline.
    """

    def __init__(
        self,
        runs_root: Path = RUNS_DIR,
        clock: Callable[[], float] = time.monotonic,
        transcripts_root: Path | None = None,
        transcript_retry_s: float = 2.0,
    ) -> None:
        self._transcripts_root = transcripts_root
        self._transcript_retry_s = transcript_retry_s
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
        client = InProcessClient(_new_store(scenario.index_max_bytes))
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
        self._write_transcript(resolved, ())

    def _write_transcript(self, trial_dir: Path, turns: Sequence[TranscriptTurn]) -> None:
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "transcript.json").write_text(json.dumps(transcript_to_json(turns), indent=2))

    def record_call(self, record: ToolCallRecord) -> None:
        """The on_call observer: stamp the record and append it to the trace.

        completed_ms is stamped when the record arrives, a little after the
        wrapper finished, so started_ms (completed_ms minus duration_s) lags
        the true start by the same small amount for every call.
        """
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
        """Close the time window for (session, turn), keep the exchange, and
        rewrite transcript.json so the runner can build the next turn's prompt.

        With a transcripts root, the recorded reply is the subagent's full text
        from its transcript and reply is kept as agent_result. Raises
        SubagentTranscriptError, recording nothing, if that text is unavailable
        or its last block is not in reply.
        """
        at_ms = self._now_ms()
        recorded = TranscriptTurn(session, turn, user, reply, agent_id)
        if self._transcripts_root is not None:
            if agent_id is None or not agent_id.strip():
                raise SubagentTranscriptError("agent_id is required: pass the token after agentId:")
            normalized = agent_id.strip().split()[0]
            full = self._read_full_reply(self._transcripts_root, normalized, reply)
            recorded = TranscriptTurn(session, turn, user, full, normalized, reply)
        with self._lock:
            self._boundaries.append(_Boundary(at_ms, session, turn))
            self._turns.append(recorded)
            trial_dir, turns = self._trial_dir, tuple(self._turns)
        if trial_dir is not None:
            self._write_transcript(trial_dir, turns)

    def _read_full_reply(self, root: Path, agent_id: str, agent_result: str) -> str:
        """The transcript's reply, re-read until its last block is in agent_result."""
        deadline = time.monotonic() + self._transcript_retry_s
        wanted = _squash(agent_result)
        while True:
            try:
                blocks = text_blocks_from_transcript(find_subagent_transcript(root, agent_id))
                if _squash(blocks[-1]) in wanted:
                    return "\n\n".join(blocks)
                error = SubagentTranscriptError(
                    f"the last text in the transcript for agent_id {agent_id} was not in the "
                    "Agent result; pass the Agent result verbatim"
                )
            except PermanentTranscriptError:
                raise
            except SubagentTranscriptError as exc:
                error = exc
            if time.monotonic() >= deadline:
                raise error
            time.sleep(0.1)

    def _snapshot(self) -> "_Snapshot":
        with self._lock:
            return _Snapshot(
                client=self._client,
                identity=self._identity,
                trial_dir=self._trial_dir,
                records=tuple(self._records),
                boundaries=tuple(self._boundaries),
                turns=tuple(self._turns),
            )

    def trace(self) -> tuple[TraceCall, ...]:
        return self._snapshot().trace()

    def transcript(self) -> tuple[TranscriptTurn, ...]:
        return self._snapshot().turns

    def store_dump(self) -> StoreDump:
        """Every file under the identity's entities, with content and metadata."""
        return self._snapshot().store_dump()

    def dump(self) -> dict[str, object]:
        """Write store.json, trace.json, and transcript.json to the trial dir.

        All three come from one snapshot of the trial. Raises RuntimeError if
        no trial has been started with reset.
        """
        snap = self._snapshot()
        if snap.trial_dir is None:
            raise RuntimeError("no trial in progress: call eval_reset first")
        store, trace = snap.store_dump(), snap.trace()
        snap.trial_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "store": snap.trial_dir / "store.json",
            "trace": snap.trial_dir / "trace.json",
            "transcript": snap.trial_dir / "transcript.json",
        }
        paths["store"].write_text(json.dumps(store_dump_to_json(store), indent=2))
        paths["trace"].write_text(json.dumps(trace_to_json(trace), indent=2))
        paths["transcript"].write_text(json.dumps(transcript_to_json(snap.turns), indent=2))
        return {
            **{key: str(path) for key, path in paths.items()},
            "files": len(store.files),
            "calls": len(trace),
        }


@dataclass(frozen=True)
class _Snapshot:
    """One consistent view of a trial, taken under the state lock."""

    client: InProcessClient
    identity: Identity
    trial_dir: Path | None
    records: tuple[_Record, ...]
    boundaries: tuple[_Boundary, ...]
    turns: tuple[TranscriptTurn, ...]

    def _tag(self, started_ms: float) -> tuple[int, int]:
        for boundary in self.boundaries:
            if started_ms < boundary.at_ms:
                return boundary.session, boundary.turn
        return 0, 0

    def trace(self) -> tuple[TraceCall, ...]:
        calls: list[TraceCall] = []
        for r in self.records:
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

    def store_dump(self) -> StoreDump:
        files: list[StoredFile] = []
        for scope, entity in sorted(self.identity.scope_map.items()):
            cursor: ListCursor | None = None
            while True:
                page = self.client.list_prefix(build_prefix(scope, entity), cursor)
                for entry in page.entries:
                    files.append(_stored(self.client.read_file(entry.path)))
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
        return StoreDump(tuple(sorted(files, key=lambda f: f.path)))


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
        try:
            state.record_turn(session, turn, user, reply, agent_id)
        except SubagentTranscriptError as exc:
            return _error(str(exc))
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
            "Harness only. Record one turn's user message and the Agent result. The server "
            "reads the subagent's full reply from its Claude Code transcript by agent_id "
            "(required) and keeps the passed text as agent_result. Memory calls started "
            "before this call belong to this turn."
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
    parser.add_argument("--transcripts-root", type=Path, default=default_projects_root())
    args = parser.parse_args(argv)
    state = EvalState(runs_root=args.runs_root, transcripts_root=args.transcripts_root)
    build_eval_server(state).run("stdio")


if __name__ == "__main__":
    main()
