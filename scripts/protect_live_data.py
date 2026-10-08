#!/usr/bin/env python3
"""Make live research data read-only at the filesystem level (Windows NTFS deny ACEs).

The PreToolUse hook (scripts/hooks/data_guard.py) only sees the command line an agent types. This layer holds
whatever process does the deleting -- git, a Python script, a junction followed from a disposable worktree.

Windows grants a delete when EITHER the object grants DELETE OR its parent grants FILE_DELETE_CHILD, so both are
denied:

  catalog root (e.g. data/catalog)   this-folder-only deny  DC                (no catalog can be deleted/renamed)
  each catalog directory             inheritable deny       DE,DC,WD,AD,WA,WEA (no file/dir inside can be
                                                                                 deleted, written, added, renamed)
  raw dir (data/raw)                 this-folder-only deny  DC                (new raw files may still be added)
  each existing raw file             deny                   DE,WD,AD,WA,WEA

Reads are unaffected. The deny ACEs name Everyone (S-1-1-0), so they bind every account and token, elevated or
sandboxed; WRITE_DAC is not denied, so the owner can still lift them with `remove`. A new catalog is built into its own new directory (adding is allowed) and protected afterwards with `apply`.

  apply   add the deny ACEs (idempotent) and record what was protected in ~/.nt_research/protected_paths.json
  verify  fail unless every target carries its deny ACE (exit 1 on any gap)
  remove  human-only (the hook blocks it for agents): strip the deny ACEs, e.g. to rebuild a catalog in place
  restore human-only: reinstate the exact original descriptors saved by `apply` (--backup-dir)

`apply` first saves every target's original security descriptor (icacls /save, catalog trees with /T; SDDL copied
into backup_manifest.json) and only then adds ACEs; existing ACL entries are never removed or edited.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DIR_RIGHTS = "(OI)(CI)(DE,DC,WD,AD,WA,WEA)"
ROOT_RIGHTS = "(DC)"
FILE_RIGHTS = "(DE,WD,AD,WA,WEA)"
STATE = Path.home() / ".nt_research" / "protected_paths.json"


class ProtectionError(RuntimeError):
    pass


EVERYONE_SID = "S-1-1-0"


def current_sid() -> str:
    """The deny ACEs name Everyone, not the current user: sandboxed agents run as other accounts (e.g. members of
    CodexSandboxUsers hold Modify on the repo), and a deny for one user SID would not bind them."""
    return EVERYONE_SID


def main_repo() -> Path:
    here = Path(__file__).resolve().parents[1]
    common = subprocess.run(["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def default_targets() -> Dict[str, List[str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hooks.data_guard import _catalog_roots  # type: ignore

    repo = main_repo()
    roots = {os.path.normcase(str(Path(r).resolve())) for r in _catalog_roots()}
    roots.add(os.path.normcase(str((repo / "data" / "catalog").resolve())))
    return {"catalog_roots": sorted(r for r in roots if Path(r).is_dir()), "raw_dirs": [str(repo / "data" / "raw")]}


def plan(catalog_roots: List[str], raw_dirs: List[str]) -> List[Dict[str, str]]:
    """Every (path, rights) pair the protection consists of."""
    items: List[Dict[str, str]] = []
    for root in catalog_roots:
        rp = Path(root)
        items.append({"path": str(rp), "rights": ROOT_RIGHTS, "kind": "catalog_root"})
        for d in sorted(p for p in rp.iterdir() if p.is_dir()):
            items.append({"path": str(d), "rights": DIR_RIGHTS, "kind": "catalog"})
    for raw in raw_dirs:
        rp = Path(raw)
        if not rp.is_dir():
            continue
        items.append({"path": str(rp), "rights": ROOT_RIGHTS, "kind": "raw_dir"})
        for f in sorted(p for p in rp.iterdir() if p.is_file()):
            items.append({"path": str(f), "rights": FILE_RIGHTS, "kind": "raw_file"})
    return items


def _icacls(*args: str) -> str:
    res = subprocess.run(["icacls", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise ProtectionError(f"icacls {' '.join(args)} failed: {res.stdout.strip()} {res.stderr.strip()}")
    return res.stdout


def _rights_set(rights: str) -> set:
    return set(re.findall(r"[A-Z]+", rights.rsplit("(", 1)[-1]))


def has_deny(path: str, sid: str, rights: str) -> bool:
    """True when ``path`` carries an explicit (non-inherited) deny ACE with at least ``rights``.

    icacls prints account names, not SIDs, and this tool is the only writer of explicit deny ACEs on these paths,
    so any explicit DENY entry covering the wanted rights counts.
    """
    out = _icacls(path)
    want = _rights_set(rights)
    for line in out.splitlines():
        if "(DENY)" not in line or "(I)" in line:
            continue
        if want <= _rights_set(line.rstrip()):
            return True
    return False


def normalize_sddl(sddl: str) -> str:
    """DACL SDDL with the AI (auto-inherited) control flag removed; ACEs, order and the P flag are kept exactly."""
    m = re.match(r"^(.*?D:)([A-Z]*)(\(.*)?$", sddl)
    if not m:
        return sddl
    flags = m.group(2).replace("AI", "")
    return f"{m.group(1)}{flags}{m.group(3) or ''}"


def _read_save(path: Path) -> List[List[str]]:
    """icacls /save output: UTF-16 text, alternating <relative name>, <SDDL> lines."""
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:4] else raw.decode("utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [lines[i:i + 2] for i in range(0, len(lines) - 1, 2)]


def backup(items: List[Dict[str, str]], backup_dir: Path) -> Dict[str, object]:
    """Save the ORIGINAL security descriptor of every item before any change (icacls /save; catalog trees with /T).

    Each save file is restorable with ``icacls <parent> /restore <file>``; the SDDL text is also copied into the
    manifest so the pre-protection state is human-readable."""
    backup_dir.mkdir(parents=True, exist_ok=False)
    entries = []
    for i, it in enumerate(items):
        f = backup_dir / f"{i:05d}.acl"
        args = [it["path"], "/save", str(f)] + (["/T"] if it["kind"] == "catalog" else [])
        _icacls(*args)
        entries.append({"path": it["path"], "parent": str(Path(it["path"]).parent), "kind": it["kind"],
                        "save_file": f.name, "descriptors": _read_save(f)})
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "entries": entries}
    (backup_dir / "backup_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


_RESTORE_PS = r"""
$ErrorActionPreference = 'Stop'
$items = Get-Content -LiteralPath $env:PROTECT_RESTORE_PLAN -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($it in $items) {
  $p = $it.path
  if (Test-Path -LiteralPath $p -PathType Container) { $s = New-Object System.Security.AccessControl.DirectorySecurity }
  elseif (Test-Path -LiteralPath $p -PathType Leaf) { $s = New-Object System.Security.AccessControl.FileSecurity }
  else { continue }
  $s.SetSecurityDescriptorSddlForm($it.sddl, [System.Security.AccessControl.AccessControlSections]::Access)
  (Get-Item -LiteralPath $p -Force).SetAccessControl($s)
}
"""


def restore(backup_dir: Path) -> int:
    """Human-only: reinstate the exact original DACLs recorded by ``backup``.

    ``icacls /restore`` needs SeRestorePrivilege (elevation); setting only the DACL section from the recorded SDDL
    needs nothing beyond the owner's WRITE_DAC, so a non-elevated owner can always roll back. Entries are applied
    in save order (parents before children) per item, items in reverse order."""
    manifest = json.loads((backup_dir / "backup_manifest.json").read_text(encoding="utf-8"))
    todo = []
    for e in reversed(manifest["entries"]):
        for name, sddl in e["descriptors"]:
            todo.append({"path": str(Path(e["parent"]) / name), "sddl": sddl})
    spec = backup_dir / "restore_plan.json"
    spec.write_text(json.dumps(todo), encoding="utf-8")
    res = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _RESTORE_PS],
                         capture_output=True, text=True, env={**os.environ, "PROTECT_RESTORE_PLAN": str(spec)})
    if res.returncode != 0:
        raise ProtectionError(f"restore failed: {res.stderr.strip()[:800]}")
    return len(todo)


def apply(items: List[Dict[str, str]], sid: str) -> List[Dict[str, str]]:
    done = []
    for it in items:
        if not has_deny(it["path"], sid, it["rights"]):
            _icacls(it["path"], "/deny", f"*{sid}:{it['rights']}")
        done.append(it)
    return done


def verify(items: List[Dict[str, str]], sid: str) -> List[Dict[str, str]]:
    return [it for it in items if not Path(it["path"]).exists() or not has_deny(it["path"], sid, it["rights"])]


def remove(items: List[Dict[str, str]], sid: str) -> None:
    for it in reversed(items):
        if Path(it["path"]).exists():
            _icacls(it["path"], "/remove:d", f"*{sid}")


def main(argv: Optional[List[str]] = None) -> int:
    if os.name != "nt":
        print("protect_live_data: NTFS ACLs only; nothing to do on this platform", file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["apply", "verify", "remove", "restore", "plan"])
    ap.add_argument("--catalog-root", action="append", help="override: a directory whose children are catalogs")
    ap.add_argument("--raw-dir", action="append", help="override: a directory of raw source files")
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--backup-dir", help="apply: where original descriptors are saved (default "
                                         "~/.nt_research/acl_backups/<utc>); restore: the backup to reinstate")
    a = ap.parse_args(argv)
    if a.action == "restore":
        if not a.backup_dir:
            print("restore needs --backup-dir", file=sys.stderr)
            return 2
        try:
            n = restore(Path(a.backup_dir))
        except ProtectionError as exc:
            print(f"[PROTECT_LIVE_DATA_ERROR] {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"STATUS": "RESTORED", "entries": n}))
        return 0
    if a.catalog_root or a.raw_dir:
        tg = {"catalog_roots": a.catalog_root or [], "raw_dirs": a.raw_dir or []}
    else:
        tg = default_targets()
    sid = current_sid()
    items = plan(tg["catalog_roots"], tg["raw_dirs"])
    try:
        if a.action == "plan":
            print(json.dumps({"sid": sid, "targets": tg, "items": items}, indent=1))
        elif a.action == "apply":
            bdir = Path(a.backup_dir) if a.backup_dir else (
                Path.home() / ".nt_research" / "acl_backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            backup(items, bdir)  # before ANY change; refuses to reuse an existing backup dir
            apply(items, sid)
            gaps = verify(items, sid)
            Path(a.state).parent.mkdir(parents=True, exist_ok=True)
            Path(a.state).write_text(json.dumps({"applied_at_utc": datetime.now(timezone.utc).isoformat(), "sid": sid,
                                                 "backup_dir": str(bdir), "targets": tg, "items": items, "gaps": gaps},
                                                indent=1), encoding="utf-8")
            print(json.dumps({"STATUS": "PROTECTED" if not gaps else "PARTIAL", "items": len(items), "gaps": gaps}))
            return 0 if not gaps else 1
        elif a.action == "verify":
            gaps = verify(items, sid)
            print(json.dumps({"STATUS": "PROTECTED" if not gaps else "UNPROTECTED", "items": len(items), "gaps": gaps}))
            return 0 if not gaps else 1
        else:
            remove(items, sid)
            print(json.dumps({"STATUS": "REMOVED", "items": len(items)}))
    except ProtectionError as exc:
        print(f"[PROTECT_LIVE_DATA_ERROR] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
