"""Regression: the argv the supervisor detaches for its own loop must parse.

`supervise start` / `resume` / `decide` spawn the persistent loop through
`research_workflow.supervisor.cli._detach_loop`. Every verb of the thin entrypoint
(`scripts/research_supervisor.py`) lives under the `supervise` group, so an argv that
omits that token dies immediately with `invalid choice: 'loop'` -- while `start` still
reports STATUS OK and a `loop_pid`, i.e. the supervisor silently never ticks.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_workflow.supervisor import cli as supervisor_cli  # noqa: E402


def _captured_loop_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> List[str]:
    captured: Dict[str, Any] = {}

    def fake_spawn(cmd, cwd=None, log_path=None, env=None):  # noqa: ANN001, ARG001
        captured["cmd"] = list(cmd)
        return 4242

    monkeypatch.setattr("research_workflow.supervisor.procs.spawn_detached", fake_spawn)
    monkeypatch.setattr(supervisor_cli.S, "study_state_dir", lambda study_id: tmp_path / study_id)
    (tmp_path / "demo_study" / "logs").mkdir(parents=True, exist_ok=True)

    out = supervisor_cli._detach_loop(ROOT, "demo_study")
    assert out["loop_pid"] == 4242
    return captured["cmd"]


def test_detached_loop_argv_parses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cmd = _captured_loop_argv(monkeypatch, tmp_path)
    assert Path(cmd[1]).name == "research_supervisor.py"
    argv = cmd[2:]
    assert argv[:2] == ["supervise", "loop"], f"detached loop argv must name the supervise group: {argv}"

    import argparse

    from research_workflow.supervisor.cli import add_supervise_parser

    ap = argparse.ArgumentParser(prog="research_supervisor")
    sub = ap.add_subparsers(dest="group", required=True)
    add_supervise_parser(sub, ROOT)
    ns = ap.parse_args(argv)  # SystemExit(2) before the fix
    assert ns.cmd == "loop"
    assert ns.study == ["demo_study"]
