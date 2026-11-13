"""Recording the eval arm in run.json, the report header, and merge-runs (AIE-1384, AC9)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from evals.__main__ import main

pytestmark = pytest.mark.unit

DEFAULT_ARM = {"index_tool": "get_memory_index", "agent_prompt": True}
OTHER_ARM = {"index_tool": "recall", "agent_prompt": False}

SCENARIO = """\
id: {id}
title: {id}
category: privacy
source: AIE-1384
sessions:
  - turns: ["first"]
assertions:
  - kind: index_read_first
    id: index-first
"""


def _scenarios_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "scenarios"
    directory.mkdir(exist_ok=True)
    for ident in ("alpha", "beta"):
        (directory / f"{ident}.yaml").write_text(SCENARIO.format(id=ident))
    return directory


def _arm_file(tmp_path: Path, arm: Mapping[str, object], name: str = "arm.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(arm))
    return path


def _new_run(tmp_path: Path, *extra: str) -> Path:
    runs = tmp_path / "runs"
    before: set[Path] = set(runs.iterdir()) if runs.exists() else set()
    code = main(
        [
            "new-run",
            "--scenarios-dir",
            str(_scenarios_dir(tmp_path)),
            "--runs-dir",
            str(runs),
            "--trials",
            "1",
            *extra,
        ]
    )
    assert code == 0
    (created,) = set(runs.iterdir()) - before
    return created


def _run_json(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "run.json").read_text())


def _shards(tmp_path: Path, first: Path | None, second: Path | None) -> list[Path]:
    dirs: list[Path] = []
    for k, arm_path in ((1, first), (2, second)):
        extra = ["--shard", f"{k}/2"]
        if arm_path is not None:
            extra += ["--arm-path", str(arm_path)]
        dirs.append(_new_run(tmp_path, *extra))
    return dirs


def _set_arm(run_dir: Path, arm: dict[str, object] | None) -> None:
    meta = _run_json(run_dir)
    meta.pop("arm", None)
    if arm is not None:
        meta["arm"] = arm
    (run_dir / "run.json").write_text(json.dumps(meta))


def test_new_run_records_the_arm_from_arm_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """new-run --arm-path records that arm in run.json and warns that it is
    not the default (AIE-1384, AC9).
    """
    run_dir = _new_run(tmp_path, "--arm-path", str(_arm_file(tmp_path, OTHER_ARM)))

    assert _run_json(run_dir)["arm"] == OTHER_ARM
    captured = capsys.readouterr()
    assert "recall" in captured.out + captured.err


def test_new_run_with_a_missing_arm_file_records_the_default_arm(tmp_path: Path) -> None:
    """A missing arm file means the default arm (AIE-1384, AC9)."""
    run_dir = _new_run(tmp_path, "--arm-path", str(tmp_path / "absent.json"))

    assert _run_json(run_dir)["arm"] == DEFAULT_ARM


def test_report_header_shows_index_tool_and_agent_prompt(tmp_path: Path) -> None:
    """report.md's header, before the scenario table, shows the index tool and
    the agent prompt setting (AIE-1384, AC9).
    """
    run_dir = _new_run(tmp_path, "--arm-path", str(_arm_file(tmp_path, OTHER_ARM)))

    assert main(["report", str(run_dir)]) == 0

    markdown = (run_dir / "report.md").read_text()
    header = markdown.split("| Scenario", 1)[0]
    assert "recall" in header
    assert "get_memory_index" not in header
    assert "off" in header.lower()


def test_report_header_shows_default_arm(tmp_path: Path) -> None:
    """A default-arm report header names get_memory_index and the prompt as on
    (AIE-1384, AC9).
    """
    run_dir = _new_run(tmp_path, "--arm-path", str(tmp_path / "absent.json"))

    assert main(["report", str(run_dir)]) == 0

    header = (run_dir / "report.md").read_text().split("| Scenario", 1)[0]
    assert "get_memory_index" in header
    assert " on" in header.lower()


def test_merge_runs_accepts_runs_with_the_same_arm(tmp_path: Path) -> None:
    """Shards with the same non-default arm merge (AIE-1384, AC9)."""
    arm = _arm_file(tmp_path, OTHER_ARM)
    dirs = _shards(tmp_path, arm, arm)
    out = tmp_path / "merged"

    assert main(["merge-runs", str(out), *map(str, dirs)]) == 0
    assert _run_json(out)["arm"] == OTHER_ARM


def test_merge_runs_rejects_different_arms(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """merge-runs exits 2 when the runs have different arms and writes nothing
    (AIE-1384, AC9).
    """
    dirs = _shards(tmp_path, _arm_file(tmp_path, OTHER_ARM), tmp_path / "absent.json")
    out = tmp_path / "merged"

    assert main(["merge-runs", str(out), *map(str, dirs)]) == 2
    assert "arm" in capsys.readouterr().err
    assert not out.exists()


def test_run_json_without_arm_merges_with_a_default_arm_run(tmp_path: Path) -> None:
    """A run.json with no arm key is the default arm (AIE-1384, AC9)."""
    dirs = _shards(tmp_path, tmp_path / "absent.json", tmp_path / "absent.json")
    _set_arm(dirs[0], None)
    out = tmp_path / "merged"

    assert main(["merge-runs", str(out), *map(str, dirs)]) == 0


def test_run_json_without_arm_does_not_merge_with_a_non_default_run(tmp_path: Path) -> None:
    """An old run (no arm key) and a non-default-arm run have different arms
    (AIE-1384, AC9).
    """
    dirs = _shards(tmp_path, tmp_path / "absent.json", _arm_file(tmp_path, OTHER_ARM))
    _set_arm(dirs[0], None)
    out = tmp_path / "merged"

    assert main(["merge-runs", str(out), *map(str, dirs)]) == 2
    assert not out.exists()


def test_new_run_warns_on_stderr_naming_a_non_default_index_tool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-default arm makes new-run warn on stderr, naming the index tool
    (AIE-1384, FR-005).
    """
    arm = {"index_tool": "load_memory", "agent_prompt": False}
    _new_run(tmp_path, "--arm-path", str(_arm_file(tmp_path, arm)))

    err = capsys.readouterr().err
    assert "load_memory" in err
    assert "warning" in err.lower()


def test_new_run_with_the_default_arm_prints_no_arm_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default arm produces no arm warning on stderr (AIE-1384, FR-005)."""
    _new_run(tmp_path)

    err = capsys.readouterr().err
    assert "load_memory" not in err
    assert "warning" not in err.lower()
    assert "non-default" not in err.lower()
