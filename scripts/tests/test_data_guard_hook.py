"""PreToolUse data guard: replays the commands that destroyed live catalogs on 2026-10-08, plus ordinary commands
that must keep working."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.hooks import data_guard as G

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "data_guard.py"
WT = r"C:\Users\Scott McCarty\Projects\Nautilus Trader-vp_integration_tmp"
LIVE = r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog"

# Verbatim (paths kept) from the incident transcripts, agents a58d76274cd73c891 and abe81ff04c927af66.
INCIDENT = [
    f'cmd.exe /c mklink /J "{WT}\\data\\catalog\\NQ_v0_2020_2026" "{LIVE}\\NQ_v0_2020_2026"',
    f"powershell.exe -NoProfile -Command \"New-Item -ItemType Junction -Path '{WT}\\data\\catalog\\NQ_1S_V2_GLOBEX' "
    f"-Target '{LIVE}\\NQ_1S_V2_GLOBEX'\"",
    f'cd "C:\\Users\\Scott McCarty\\Projects\\Nautilus Trader" && git worktree remove --force "{WT}" 2>&1 | tail -20',
    "python3 -c \"\nimport _winapi\n_winapi.CreateJunction(target1, link1)\n\"",
    'cd "C:\\scratch\\diag" && cmd //c mklinks.cmd',  # script body checked separately below
]

BLOCKED = INCIDENT[:4] + [
    "rm -rf /c/rtwt",                                     # incident 2026-08-17
    "rm -fr build", "rm -r -f x", "rm --recursive x",
    "Remove-Item -Recurse -Force C:\\tmp\\x", "Remove-Item C:\\tmp\\x -Recurse", "rm C:\\x -r",
    "cmd /c rmdir /s /q C:\\tmp\\x", "rd /S /Q x", "del /s /q x",
    "python -c \"import shutil; shutil.rmtree('x')\"",
    "robocopy a b /MIR", "git clean -fdx", "find . -name x -delete",
    "git worktree remove ../wt", "git -C repo worktree remove -f ../wt",
    "[System.IO.Directory]::Delete('x', $true)",
    "ln -s /data x", "New-Item -Type SymbolicLink -Path a -Target b",
    "icacls data\\catalog /remove:d *S-1-1-0", "takeown /f x", "Get-Acl a | Set-Acl b",
    "python scripts/protect_live_data.py remove",
    f"Remove-Item {LIVE}\\NQ_1S_V2\\data\\bar\\x.parquet",
    "mv data/raw/NQ_v0_1s_2022.parquet /tmp/", "Move-Item data\\catalog\\NQ_1S_V2 elsewhere",
    "Set-Content research/datasets/NQ_1S_V2_GLOBEX.yaml 'x'",
]

ALLOWED = [
    "git status", "git worktree list", "git worktree add -b chore/x ../wt main", "git rm --cached -r foo",
    "python -m pytest scripts/tests/test_safe_cleanup.py -q",
    "python scripts/safe_cleanup.py worktree-remove ../wt",
    "python scripts/safe_cleanup.py delete --target C:\\tmp\\x --disposable-root C:\\tmp",
    "python scripts/protect_live_data.py verify", "python scripts/protect_live_data.py apply",
    f"Get-ChildItem {LIVE} -Recurse", "Get-ChildItem -Recurse . | Measure-Object",
    "rm -f single_file.txt", "Remove-Item C:\\tmp\\one.txt", "rmdir C:\\tmp\\empty_or_link",
    "python scripts/research.py study compile --study studies/x",
    "icacls data\\catalog\\NQ_1S_V2",
    "Copy-Item data/catalog/NQ_1S_V2/build_manifest.json C:\\tmp\\",
]


@pytest.mark.parametrize("cmd", BLOCKED)
def test_blocked(cmd):
    assert G.check_command(cmd) is not None, cmd


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd):
    assert G.check_command(cmd) is None, (cmd, G.check_command(cmd))


def test_link_creation_hidden_in_an_executed_script_is_blocked(tmp_path):
    """The diagnosis agent wrote mklink into mklinks.cmd and then ran the file."""
    s = tmp_path / "mklinks.cmd"
    s.write_text(f'mklink /J "C:\\x\\NQ_1S_V2" "{LIVE}\\NQ_1S_V2\\data"\r\n')
    assert "LINK" in G.check_command(f'cmd /c "{s}"')
    py = tmp_path / "link.py"
    py.write_text("import _winapi\n_winapi.CreateJunction(a, b)\n")
    assert "LINK" in G.check_command(f'python "{py}"')


def test_writing_a_link_script_is_blocked():
    r = G.evaluate({"tool_name": "Write", "tool_input": {"file_path": "C:/scratch/mklinks.cmd",
                                                          "content": "mklink /J a b"}})
    assert r and "LINK" in r


def test_writes_to_live_data_and_dataset_specs_are_blocked():
    for p in (f"{LIVE}\\NQ_1S_V2\\dataset_manifest.json", "C:/repo/data/raw/NQ_v0_1s_2022.parquet",
              "C:/Users/x/Projects/Nautilus Trader-wt/research/datasets/NQ_1S_V2_GLOBEX.yaml"):
        for tool in ("Write", "Edit"):
            assert G.evaluate({"tool_name": tool, "tool_input": {"file_path": p, "content": "x", "new_string": "x"}})


def test_guard_files_may_contain_link_code():
    assert G.evaluate({"tool_name": "Write", "tool_input": {
        "file_path": "C:/r/scripts/tests/test_safe_cleanup.py", "content": "mklink /J"}}) is None


def test_ordinary_write_is_allowed():
    assert G.evaluate({"tool_name": "Write", "tool_input": {"file_path": "C:/r/studies/x/study.yaml",
                                                             "content": "outcome: none"}}) is None


def _run_hook(payload: str):
    return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True)


def test_hook_process_exits_2_with_reason_on_incident_command():
    r = _run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": INCIDENT[2]}}))
    assert r.returncode == 2 and "DATA_GUARD_RECURSIVE_DELETE_BLOCKED" in r.stderr


def test_hook_process_allows_ordinary_command():
    r = _run_hook(json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "git status"}}))
    assert r.returncode == 0, r.stderr


def test_hook_fails_closed_on_malformed_input():
    r = _run_hook("{not json")
    assert r.returncode == 2 and "FAIL" in r.stderr.upper()


def test_project_settings_register_the_hook():
    settings = json.loads((Path(__file__).resolve().parents[2] / ".claude" / "settings.json").read_text())
    entries = settings["hooks"]["PreToolUse"]
    cmds = {h["command"] for e in entries for h in e["hooks"]}
    matchers = " ".join(e["matcher"] for e in entries)
    assert any("scripts/hooks/data_guard.py" in c for c in cmds)
    for tool in ("Bash", "PowerShell", "Write", "Edit"):
        assert tool in matchers
