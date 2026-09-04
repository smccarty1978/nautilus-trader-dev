"""Antigravity writer identity: deterministic, automatic enough, and fail-closed.

Antigravity IDE is a VS Code fork whose terminals export only the generic ``vscode`` variables, so
the sanctioned launcher ``scripts/launch_antigravity.ps1`` injects ``NT_RESEARCH_AGENT=antigravity``
and a fresh ``NT_RESEARCH_AGENT_SESSION`` UUID per launched instance. These tests exercise the REAL
flow through the operator CLI (``scripts/research.py``) in subprocesses carrying exactly that
environment, on a throwaway git repo and lease dir: two Antigravity sessions, a Claude session and a
Codex session, all under one OS user.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from research_workflow import workspace as ws
from research_workflow.roots import CONFIG_ENV

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "research.py"
LAUNCHER = ROOT / "scripts" / "launch_antigravity.ps1"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "src" / "nt-repo"; repo.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "README.md").write_text("x"); (repo / ".gitignore").write_text("**/runs/\n**/_work/\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"catalog_roots": [str(tmp_path / "roots")], "model_root": str(tmp_path / "models"),
                                   "leases_dir": str(tmp_path / "leases"), "worktree_root": str(tmp_path / "wts")}), encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV, str(cfg))
    monkeypatch.delenv("NT_RESEARCH_MODEL_ROOT", raising=False)
    (tmp_path / "wts").mkdir()
    return _repo(tmp_path)


def _session_env(agent: str, session: str) -> dict:
    """What a correctly launched harness session hands to its shells: launcher env wins over everything.
    Built AFTER the ``env`` fixture ran, so the subprocess inherits the throwaway ``NT_RESEARCH_CONFIG``
    (tmp leases dir + tmp worktree root) and can never touch the machine's real leases."""
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX", "ANTIGRAVITY", "GEMINI", "NT_RESEARCH_AGENT"))}
    assert CONFIG_ENV in e and ("pytest" in e[CONFIG_ENV].lower() or "tmp" in e[CONFIG_ENV].lower()), "test must run under the tmp config"
    e[ws.AGENT_ENV] = agent
    e[ws.AGENT_SESSION_ENV] = session
    return e


def _cli(repo: Path, env: dict, *args: str) -> dict:
    """Run scripts/research.py against the throwaway repo (ROOT is patched via a tiny shim so `study new`
    creates worktrees beside the throwaway repo, not beside the real one)."""
    shim = repo.parent / "shim.py"
    if not shim.exists():
        shim.write_text(
            "import runpy, sys\n"
            "sys.argv = [%r] + sys.argv[1:]\n"
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location('research_cli_shim', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "from pathlib import Path\n"
            "m.ROOT = Path(%r)\n"
            "raise SystemExit(m.main())\n" % (str(CLI), str(CLI), str(repo)), encoding="utf-8")
    r = subprocess.run([sys.executable, str(shim), *args], cwd=str(repo), env=env, capture_output=True, text=True, encoding="utf-8")
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.startswith("{")]
    assert lines, f"no card: rc={r.returncode}\nstdout={r.stdout}\nstderr={r.stderr}"
    card = json.loads(lines[-1]); card["_rc"] = r.returncode
    return card


A_SESSION = str(uuid.uuid4())
B_SESSION = str(uuid.uuid4())


def _sessions() -> tuple[dict, dict, dict, dict]:
    return (_session_env("antigravity", A_SESSION), _session_env("antigravity", B_SESSION),
            _session_env("claude", str(uuid.uuid4())), _session_env("codex", str(uuid.uuid4())))


def test_real_flow_two_antigravity_sessions_plus_claude_and_codex(env: Path):
    ANTI_A, ANTI_B, CLAUDE, CODEX = _sessions()
    # whoami in session A and B: agent antigravity, distinct session ids, --expect passes
    wa = _cli(env, ANTI_A, "ws", "whoami", "--expect", "antigravity")
    wb = _cli(env, ANTI_B, "ws", "whoami", "--expect", "antigravity")
    assert wa["STATUS"] == "OK" and wa["agent"] == "antigravity" and wa["session_id"] == A_SESSION and wa["agent_source"] == "env"
    assert wb["STATUS"] == "OK" and wb["agent"] == "antigravity" and wb["session_id"] == B_SESSION
    assert wa["owner"] == wb["owner"] and wa["session_id"] != wb["session_id"]
    # session A creates + owns study A (asserting its identity)
    a = _cli(env, ANTI_A, "study", "new", "study_a", "--as", "antigravity")
    assert a["STATUS"] == "OK" and a["writer"]["agent"] == "antigravity" and a["writer"]["session_id"] == A_SESSION
    claim_a = _cli(env, ANTI_A, "ws", "claim", "study_a", "--as", "antigravity")
    assert claim_a["STATUS"] == "OK" and claim_a["result"] == "already_owner"
    # session B attempts study A -> refused (same OS user, same agent label, different session)
    b_on_a = _cli(env, ANTI_B, "ws", "claim", "study_a", "--as", "antigravity")
    assert b_on_a["STATUS"] == "FAIL" and b_on_a["blocker_code"] == "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", b_on_a
    assert A_SESSION in b_on_a["error"] and B_SESSION in b_on_a["error"]
    # session B creates + owns study B
    b = _cli(env, ANTI_B, "study", "new", "study_b", "--as", "antigravity")
    assert b["STATUS"] == "OK" and b["writer"]["session_id"] == B_SESSION
    assert _cli(env, ANTI_B, "ws", "claim", "study_b", "--as", "antigravity")["result"] == "already_owner"
    assert _cli(env, ANTI_A, "ws", "claim", "study_b", "--as", "antigravity")["blocker_code"] == "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT"
    # Claude and Codex own C and D concurrently; nobody can take anyone else's
    c = _cli(env, CLAUDE, "study", "new", "study_c", "--as", "claude")
    d = _cli(env, CODEX, "study", "new", "study_d", "--as", "codex")
    assert c["STATUS"] == "OK" and c["writer"]["agent"] == "claude" and d["STATUS"] == "OK" and d["writer"]["agent"] == "codex"
    for who, study in ((CLAUDE, "study_a"), (CODEX, "study_b"), (ANTI_A, "study_c"), (ANTI_B, "study_d")):
        assert _cli(env, who, "ws", "claim", study)["blocker_code"] == "STUDY_WORKTREE_OWNED_BY_ANOTHER_AGENT", (study,)
    listing = _cli(env, ANTI_A, "ws", "list")
    owners = {l["study_id"]: (l["state"], l["owner_agent"], l["owner_session_id"]) for l in listing["leases"]}
    assert owners == {"study_a": ("live", "antigravity", A_SESSION), "study_b": ("live", "antigravity", B_SESSION),
                      "study_c": ("live", "claude", CLAUDE[ws.AGENT_SESSION_ENV]), "study_d": ("live", "codex", CODEX[ws.AGENT_SESSION_ENV])}


def test_ambiguous_or_mismatched_identity_fails_closed(env: Path):
    ANTI_A, ANTI_B, CLAUDE, CODEX = _sessions()
    # a shell with no launcher env and no harness markers resolves as human (or whatever the process tree says):
    # a write-capable Antigravity role asserting itself must be refused, and nothing is created.
    plain = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX", "ANTIGRAVITY", "GEMINI", "NT_RESEARCH_AGENT"))}
    assert CONFIG_ENV in plain
    w = _cli(env, plain, "ws", "whoami", "--expect", "antigravity")
    assert w["STATUS"] == "FAIL" and w["blocker_code"] in {"WRITER_IDENTITY_AMBIGUOUS", "WRITER_IDENTITY_MISMATCH"} and w["agent"] != "antigravity"
    n = _cli(env, plain, "study", "new", "study_x", "--as", "antigravity")
    assert n["STATUS"] == "FAIL" and n["blocker_code"] in {"WRITER_IDENTITY_AMBIGUOUS", "WRITER_IDENTITY_MISMATCH"}
    assert not (env / "studies" / "study_x").exists() and not (env.parent.parent / "wts" / "nt-repo-study_x").exists()
    # a Claude shell claiming to be antigravity is a mismatch
    m = _cli(env, CLAUDE, "ws", "whoami", "--expect", "antigravity")
    assert m["STATUS"] == "FAIL" and m["blocker_code"] == "WRITER_IDENTITY_MISMATCH"
    # explicit human with no --as still works (a researcher at a terminal is not ambiguous to themselves)
    assert _cli(env, plain, "study", "new", "study_h")["STATUS"] == "OK"
    # library-level: human is ambiguous for any asserted agent
    with pytest.raises(ws.WorkspaceError, match="WRITER_IDENTITY_AMBIGUOUS"):
        ws.require_agent({"agent": "human", "agent_source": "default"}, "antigravity")
    with pytest.raises(ws.WorkspaceError, match="WRITER_IDENTITY_MISMATCH"):
        ws.require_agent({"agent": "codex", "agent_source": "env"}, "antigravity")
    assert ws.require_agent({"agent": "antigravity"}, None)["agent"] == "antigravity"


def test_agent_inferred_from_antigravity_process_ancestry(monkeypatch: pytest.MonkeyPatch):
    """Without launcher env, a shell whose ancestry ends at 'antigravity ide.exe' is labelled antigravity by
    the process-tree anchor -- the agent label is automatic; only the per-session id needs the launcher."""
    for var in list(os.environ):
        if var.startswith(("CLAUDE", "CODEX", "ANTIGRAVITY", "GEMINI", "NT_RESEARCH_AGENT")):
            monkeypatch.delenv(var)
    anchor = {"name": "antigravity ide.exe", "pid": 4242, "create_time": 1700000000, "ancestry": ["python.exe", "powershell.exe", "antigravity ide.exe"]}
    monkeypatch.setattr(ws, "_process_anchor", lambda: anchor)
    ident = ws.writer_identity()
    assert ident["agent"] == "antigravity" and ident["agent_source"] == "process_tree"
    assert ident["session_id"] == "antigravity ide.exe:4242:1700000000" and ident["session_source"] == "process_tree"
    # two windows of ONE single-instance Antigravity IDE share that anchor -> the launcher UUID is what separates sessions
    monkeypatch.setenv(ws.AGENT_SESSION_ENV, "launch-uuid-1")
    assert ws.writer_identity()["session_id"] == "launch-uuid-1"


def test_launcher_generates_a_fresh_uuid_per_launch_and_never_a_static_one():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "[guid]::NewGuid()" in src
    assert '$env:NT_RESEARCH_AGENT = "antigravity"' in src and "$env:NT_RESEARCH_AGENT_SESSION = $session" in src
    assert not re.search(r"NT_RESEARCH_AGENT_SESSION\s*=\s*['\"][0-9a-f-]{36}['\"]", src)      # no committed static UUID
    assert "ANTIGRAVITY_INSTANCE_ALREADY_RUNNING" in src and "--user-data-dir" in src           # single-instance caveat handled
    cmd = (ROOT / "scripts" / "launch_antigravity.cmd").read_text(encoding="utf-8")
    assert "launch_antigravity.ps1" in cmd
    if sys.platform == "win32":
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER), "-Path", str(ROOT), "-WhatIf"],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        card = json.loads([ln for ln in r.stdout.strip().splitlines() if ln.startswith("{")][-1])
        assert card["agent"] == "antigravity" and re.fullmatch(r"[0-9a-f-]{36}", card["session_id"])
        r2 = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER), "-Path", str(ROOT), "-WhatIf"],
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
        card2 = json.loads([ln for ln in r2.stdout.strip().splitlines() if ln.startswith("{")][-1])
        assert card2["session_id"] != card["session_id"]                                         # unique per launch
