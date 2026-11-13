# Implementation Plan: Eval arms for index tool names (AIE-1384)

Linear: AIE-1384. Spec: `spec.md`. Detailed enough to write tests without
reading `src/`. For run formats (`trace.json`, `store.json`, `run.json`),
test-writer should inspect the existing run fixtures in `tests/`.

All work is under `evals/`, plus `.claude/agents/wenchang-eval.md`,
`.claude/commands/run-evals.md`, `.gitignore`, and `tests/`. No change to
`src/`.

## Public interface

### `evals/arm.py` (new)

```python
DEFAULT_INDEX_TOOL: Final = "get_memory_index"
ARM_PATH: Path  # evals/arm.json, next to the module


class ArmError(ValueError): ...


@dataclass(frozen=True)
class Arm:
    index_tool: str = DEFAULT_INDEX_TOOL
    agent_prompt: bool = True

    def __post_init__(self) -> None: ...  # validates; raises ArmError

    @property
    def is_default(self) -> bool: ...

    def to_json(self) -> dict[str, object]: ...

    @classmethod
    def from_json(cls, data: object) -> "Arm": ...  # unknown keys / wrong types -> ArmError


def load_arm(path: Path = ARM_PATH) -> Arm: ...  # missing file -> Arm(); bad JSON -> ArmError
def save_arm(arm: Arm, path: Path = ARM_PATH) -> None: ...
def rename_index_tool(text: str, arm: Arm) -> str: ...
```

- Valid `index_tool`: matches `^[a-z][a-z0-9_]{0,63}$`, and is not another
  memory tool name (the other six of `wenchang.tools.TOOL_NAMES`) or a harness
  tool name (the three in the eval server).
- `rename_index_tool` replaces every `get_memory_index` with `arm.index_tool`.
  For the default arm it returns the text unchanged.
- `to_json` is `{"index_tool": ..., "agent_prompt": ...}`.

### `evals/agent.py` (changed)

```python
def agent_tools(arm: Arm = Arm()) -> tuple[str, ...]: ...
def render_agent_body(arm: Arm = Arm()) -> str: ...
def render_agent_file(arm: Arm = Arm()) -> str: ...
```

- Defaults keep current output byte for byte.
- `agent_tools`: same order as today, with `mcp__wenchang__<index_tool>` in the
  index tool's position.
- `render_agent_body`: with `agent_prompt` true, preamble, blank line, memory
  prompt, passed through `rename_index_tool`. With false, `EVAL_AGENT_PREAMBLE`
  only.

### `evals/server.py` (changed)

```python
def build_eval_server(state: EvalState | None = None, arm: Arm | None = None) -> MCPServer: ...
```

- `arm=None` means `load_arm()`. `main()` uses `load_arm()`, so a bad
  `arm.json` fails startup with `ArmError`.
- The registered index tool is renamed to `arm.index_tool`. Tool descriptions
  and the result's prompt block go through `rename_index_tool`.
- The `on_call` observer and trace still use the canonical `get_memory_index`.
- `instructions` stay `EVAL_SERVER_INSTRUCTIONS`.
- The implementer may use `MCPServer` private managers to rename the tool, as
  `register_memory_tools` already does under the `mcp<3` pin.

### `evals/__main__.py` (changed)

```
python -m evals set-arm --index-tool NAME [--no-agent-prompt] [--arm-path PATH] [--agent-out PATH]
python -m evals set-arm --reset [--arm-path PATH] [--agent-out PATH]
python -m evals compare OUT_FILE RUN_DIR... [--baseline RUN_DIR]
python -m evals new-run ... [--arm-path PATH]   # default ARM_PATH
```

- `set-arm` validates, writes `arm.json` (`--reset` deletes it), and rewrites
  the agent file (`--agent-out` defaults to `.claude/agents/wenchang-eval.md`).
  On an invalid name it exits 2, prints the problem, and writes nothing.
- `new-run` loads the arm from `--arm-path`, records it in `run.json` as
  `"arm"`, and prints a warning when it is not the default.
- `report.md` header shows index tool and agent prompt on/off.
- `merge-runs` exits 2 when runs have different arms. A `run.json` without
  `"arm"` is the default arm.
- `compare` writes `OUT_FILE`; exits 2 on bad input or differing scenario sets.
- Exit codes: 0 ok, 2 user error.

### `evals/compare.py` (new)

```python
@dataclass(frozen=True)
class ArmMetrics:
    run_dir: Path
    index_tool: str
    agent_prompt: bool
    model: str
    trials: int
    sessions: int
    first_call_index: int  # sessions whose first memory-tool call is the index tool
    no_memory_call: int  # sessions with no memory-tool call
    index_first_passes: int  # index_read_first assertion passes
    index_first_total: int
    added_fact_lines: int
    labeled_fact_lines: int
    assertion_passes: int  # overall deterministic assertions
    assertion_total: int
    judge_passes: int  # 0 when unjudged
    judge_total: int  # 0 when unjudged


def compute_metrics(run_dir: Path) -> ArmMetrics: ...
def compare_runs(run_dirs: Sequence[Path], baseline: Path | None = None) -> str: ...  # markdown
```

- Both raise `GradeInputError` (from `evals/graders.py`) on bad input,
  including differing scenario sets.
- "Memory tool" means one of the seven `TOOL_NAMES`, by canonical name in the
  trace. "Session" is one subject session in the trace.
- Added fact line: a line in the trial's final `store.json` that is not in the
  scenario's seed files, starts with `- ` after leading whitespace, and does
  not contain `[system]`. Labeled: contains `[stated]`, `[observed]`, or
  `[inferred]`.
- Table: one row per run, columns as in AC10. Rates show `%` and `k/n`. The
  baseline is `--baseline` or the first run; other rows show deltas in
  percentage points. A rate with a zero denominator shows `n/a` and no delta.

## Order of work

Arm validation first (T1), then agent rendering and CLI (T2), server (T3),
run recording (T4), compare (T5), docs and ignore rules (T6, T7). Live runs
come after.

## Tests

- `tests/test_evals_arm.py`: validation, `load_arm`, `save_arm`,
  `rename_index_tool` (AC4, AC4b).
- `tests/test_evals_agent.py` (or the existing agent test module): default
  output unchanged, arm rendering, `set-arm` (AC1 to AC3).
- `tests/test_evals_server.py`: new tests for AC5 to AC8. Existing tests stay
  as they are.
- Run-recording and report tests: AC9.
- `tests/test_evals_compare.py`: AC10 with small fixture runs.
- A test that `.claude/commands/run-evals.md` names the arm procedure (AC11),
  if the existing tests already check that file.

## Constraints surfaced from the code

- `evals/graders.py` has `INDEX_TOOL = "get_memory_index"` and
  `_index_read_first`. They stay canonical and need no change, because the
  trace keeps the canonical name.
- `.claude/commands/run-evals.md` preflight hardcodes "Call get_memory_index
  first". It changes to the arm's index tool.
- The committed `.claude/agents/wenchang-eval.md` must stay the default-arm
  output. `set-arm` rewrites it, so `set-arm --reset` restores it.
