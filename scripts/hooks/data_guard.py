#!/usr/bin/env python3
"""Claude Code PreToolUse hook: fail-closed filesystem guard for live research data.

Two incidents destroyed live data the same way (2026-08-17, 179 GB; 2026-10-08, the NQ_1S_V2_GLOBEX and
NQ_v0_2020_2026 catalogs): an agent linked live data into a disposable worktree with a directory junction, then a
forced/recursive removal of that worktree deleted through the junction. AGENTS.md section 7 already forbade it in
prose; the second incident was a subagent that had read the rule. This hook makes the rule mechanical.

It blocks (exit 2, reason on stderr -- Claude Code refuses the tool call and shows the reason to the agent):

  LINK       any symlink / junction / hard-link creation, in a command or in a script the command executes
  DELETE     recursive or forced tree deletion (rm -r, Remove-Item -Recurse, rd /s, shutil.rmtree, robocopy /MIR,
             git clean -d, find -delete, git worktree remove ...) -- use scripts/safe_cleanup.py instead
  PROTECTED  mutating commands or Write/Edit aimed at live data (data/raw, data/catalog, configured catalog_roots)
             or at committed DatasetSpecs (research/datasets/)
  ACL        icacls / Set-Acl / takeown / attrib changes, and protect_live_data.py remove (human-only)

There is deliberately no agent-side override (an override an agent can set is not a guard). A human can run a
blocked command directly with the `!` prefix. Any internal error blocks (fail closed).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

I = re.IGNORECASE
SEG = r"[^;&|\n]*"  # stay inside one shell command segment

LINK_PATTERNS = [
    (r"\bmklink\b", "mklink"),
    (r"-(Item)?Type\s+['\"]?(Junction|SymbolicLink|HardLink)\b", "New-Item link"),
    (r"\bCreate(Junction|SymbolicLink|HardLink)\b", "Create*Link API"),
    (r"\bos\.(symlink|link)\s*\(", "os.symlink/os.link"),
    (r"\.(symlink_to|hardlink_to)\s*\(", "Path.symlink_to/hardlink_to"),
    (r"(?<![\w-])ln\b" + SEG + r"\s(-[a-zA-Z]*s[a-zA-Z]*|--symbolic)\b", "ln -s"),
    (r"\bfsutil\s+(reparsepoint|hardlink)\b", "fsutil reparse/hardlink"),
]

DELETE_PATTERNS = [
    (r"\bgit\b" + SEG + r"\bworktree\s+remove\b", "git worktree remove"),
    (r"(?<![\w-])(?<!git )rm\b" + SEG + r"\s(-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b", "rm -r"),
    (r"(?<![\w-])(?<!git )\b(Remove-Item|ri|rmdir|rd|del|erase|rm)\b" + SEG + r"\s-(Recurse|Recurs|Recur|Rec|Re|r)\b",
     "PowerShell -Recurse delete"),
    (r"\b(rmdir|rd|del|erase)\b" + SEG + r"\s/[sS]\b", "cmd recursive delete (/s)"),
    (r"\b(shutil\.)?rmtree\s*\(", "shutil.rmtree"),
    (r"\brobocopy\b" + SEG + r"\s/(MIR|PURGE)\b", "robocopy /MIR|/PURGE"),
    (r"\bgit\b" + SEG + r"\bclean\b" + SEG + r"\s-[a-zA-Z]*d", "git clean -d"),
    (r"\bfind\b" + SEG + r"\s-delete\b", "find -delete"),
    (r"Directory\]::Delete\s*\([^)]*,\s*\$?true", "[IO.Directory]::Delete(recursive)"),
    (r"\.Delete\s*\(\s*\$true\s*\)", "DirectoryInfo.Delete($true)"),
]

ACL_PATTERNS = [
    (r"\bicacls\b" + SEG + r"\s/(remove|reset|grant|deny|setowner|inheritance|setintegritylevel|restore)", "icacls change"),
    (r"\bSet-Acl\b", "Set-Acl"),
    (r"\btakeown\b", "takeown"),
    (r"\battrib\b" + SEG + r"\s-[rRhHsS]\b", "attrib clear"),
    (r"protect_live_data\.py\b" + SEG + r"\b(remove|unprotect)\b", "protect_live_data remove (human-only)"),
]

MUTATE_VERBS = (r"\b(Remove-Item|ri|rm|del|erase|rmdir|rd|mv|Move-Item|move|ren|Rename-Item|Set-Content|Add-Content|"
                r"Out-File|Clear-Content|Clear-Item|New-Item|truncate|shred|tee)\b")  # ACL tools: ACL_PATTERNS
PROTECTED_TEXT = [r"(^|[\\/\s'\"])data[\\/]+(raw|catalog|canonical)([\\/'\"\s]|$)", r"research[\\/]+datasets([\\/'\"\s]|$)"]

# Files that legitimately contain link-creation code: the guard itself and its tests.
SELF_ALLOW = ("scripts/hooks/data_guard.py", "scripts/safe_cleanup.py", "scripts/protect_live_data.py",
              "scripts/tests/test_safe_cleanup.py", "scripts/tests/test_data_guard_hook.py",
              "scripts/tests/test_protect_live_data.py")
SCRIPT_EXT = (".py", ".cmd", ".bat", ".ps1", ".sh", ".psm1")
SANCTIONED = re.compile(r"scripts[\\/]+(safe_cleanup|protect_live_data)\.py", I)


def _norm(p: str) -> str:
    return p.replace("\\", "/").lower()


def _catalog_roots() -> List[str]:
    """Configured live catalog roots (~/.nt_research/config.yaml or $NT_RESEARCH_CONFIG); best effort."""
    cfg = os.environ.get("NT_RESEARCH_CONFIG") or str(Path.home() / ".nt_research" / "config.yaml")
    roots: List[str] = []
    try:
        text = Path(cfg).read_text(encoding="utf-8")
    except OSError:
        return roots
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        for r in data.get("catalog_roots") or []:
            roots.append(_norm(str(r.get("path") if isinstance(r, dict) else r)).rstrip("/"))
    except Exception:
        for m in re.finditer(r"^\s*-\s*(?:path:\s*)?['\"]?([A-Za-z]:[\\/][^'\"\n]+)", text, re.M):
            roots.append(_norm(m.group(1).strip()).rstrip("/"))
    return [r for r in roots if r]


def _is_self_allowed(path: str) -> bool:
    n = _norm(path)
    return any(n.endswith(a) for a in SELF_ALLOW)


def _match(patterns: Iterable[Tuple[str, str]], text: str) -> Optional[str]:
    for pat, label in patterns:
        if re.search(pat, text, I | re.M):
            return label
    return None


def _touches_protected(text: str) -> bool:
    n = _norm(text)
    if any(re.search(p, text, I) for p in PROTECTED_TEXT):
        return True
    return any(r in n for r in _catalog_roots())


def _referenced_scripts(command: str, cwd: str) -> List[Path]:
    toks = re.findall(r"\"([^\"]+)\"|'([^']+)'|(\S+)", command)
    out = []
    for groups in toks:
        t = next(g for g in groups if g)
        if not t.lower().endswith(SCRIPT_EXT):
            continue
        p = Path(t)
        if not p.is_absolute():
            p = Path(cwd or os.getcwd()) / p
        try:
            if p.is_file() and p.stat().st_size < 2_000_000:
                out.append(p)
        except OSError:
            continue
    return out


def check_command(command: str, cwd: str = "") -> Optional[str]:
    lab = _match(LINK_PATTERNS, command)
    if lab:
        return (f"DATA_GUARD_LINK_CREATION_BLOCKED ({lab}). Links into or out of worktrees caused two live-data losses. "
                "Point code at catalogs through ~/.nt_research/config.yaml catalog_roots or NT_RESEARCH_CONFIG; copy small "
                "fixtures instead of linking.")
    for s in _referenced_scripts(command, cwd):
        if _is_self_allowed(str(s)):
            continue
        try:
            body = s.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lab = _match(LINK_PATTERNS, body)
        if lab:
            return f"DATA_GUARD_LINK_CREATION_BLOCKED ({lab} inside executed script {s}). Link creation is not allowed."
    if not SANCTIONED.search(command):
        lab = _match(DELETE_PATTERNS, command)
        if lab:
            return (f"DATA_GUARD_RECURSIVE_DELETE_BLOCKED ({lab}). Use `python scripts/safe_cleanup.py delete --target <dir> "
                    "--disposable-root <root>` or `python scripts/safe_cleanup.py worktree-remove <path>`; both inspect "
                    "for reparse points and fail closed.")
    lab = _match(ACL_PATTERNS, command)
    if lab:
        return f"DATA_GUARD_ACL_CHANGE_BLOCKED ({lab}). Permission changes on data are human-only."
    for seg in re.split(r"[;&|\n]", command):
        if re.search(MUTATE_VERBS, seg, I) and _touches_protected(seg):
            return ("DATA_GUARD_PROTECTED_PATH_BLOCKED: mutating command aimed at live data (data/raw, data/catalog, "
                    "catalog_roots) or committed DatasetSpecs (research/datasets). Human-only.")
    return None


def check_file_write(path: str, content: str) -> Optional[str]:
    n = _norm(path)
    if re.search(r"(^|/)data/(raw|catalog|canonical)/", n) or re.search(r"(^|/)research/datasets/", n) or \
            any(n.startswith(r + "/") for r in _catalog_roots()):
        return ("DATA_GUARD_PROTECTED_PATH_BLOCKED: writes to live data or committed DatasetSpecs are human-only "
                f"({path}).")
    if content and not _is_self_allowed(path):
        lab = _match(LINK_PATTERNS, content)
        if lab:
            return f"DATA_GUARD_LINK_CREATION_BLOCKED ({lab} written into {path}). Link creation is not allowed."
    return None


def evaluate(event: dict) -> Optional[str]:
    tool = event.get("tool_name") or ""
    ti = event.get("tool_input") or {}
    if tool in ("Bash", "PowerShell"):
        return check_command(str(ti.get("command") or ""), str(event.get("cwd") or ""))
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(ti.get("file_path") or ti.get("notebook_path") or "")
        content = str(ti.get("content") or ti.get("new_string") or ti.get("new_source") or "")
        if tool == "MultiEdit":
            content = "\n".join(str(e.get("new_string") or "") for e in ti.get("edits") or [])
        return check_file_write(path, content)
    return None


def _log(event: dict, reason: str) -> None:
    try:
        d = Path.home() / ".nt_research"
        d.mkdir(exist_ok=True)
        with open(d / "data_guard.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "session": event.get("session_id"),
                                "tool": event.get("tool_name"), "reason": reason[:300],
                                "input": json.dumps(event.get("tool_input"))[:1000]}) + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        reason = evaluate(event)
    except Exception as exc:  # fail closed
        print(f"DATA_GUARD_INTERNAL_ERROR (blocking, fail closed): {exc!r}", file=sys.stderr)
        return 2
    if reason:
        _log(event, reason)
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
