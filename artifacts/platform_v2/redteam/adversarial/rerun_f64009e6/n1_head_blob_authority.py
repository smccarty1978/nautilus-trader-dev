"""NEW ATTACK N1 (pass 03): the C-A fix binds authority to the HEAD blob. Attack the
definition of HEAD itself: a detached HEAD parked on a forged commit, a linked worktree of
the same repo whose HEAD carries the forgery, a bare-ref/`refs/` trick, and a study reached
through a path that escapes and re-enters repo_root."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from research_workflow.policy import OldRuntimePolicyError, verify_historical_authority  # noqa
from research_workflow.seal import seal_body_hash  # noqa

res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:260], "verdict": verdict})
    print(f"[{verdict}] {case}\n    {str(outcome)[:260]}")


def git(repo, *a, check=True):
    r = subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {a}: {r.stderr[:300]}")
    return r.stdout.strip()


def try_auth(case, study, repo):
    try:
        out = verify_historical_authority(Path(study), Path(repo))
        rec(case, "GRANTED " + json.dumps(out, default=str)[:200], "BYPASSED")
    except OldRuntimePolicyError as exc:
        rec(case, f"{type(exc).__name__}: {exc}", "BLOCKED")
    except Exception as exc:
        rec(case, f"{type(exc).__name__}: {exc}", "BLOCKED")


def make_study(repo, sid, marker_text):
    d = repo / "studies" / sid
    (d / "artifacts").mkdir(parents=True, exist_ok=True)
    (d / "audit").mkdir(parents=True, exist_ok=True)
    (d / "artifacts" / "study.md").write_text(marker_text, encoding="utf-8")
    fh = {"research_workflow/policy.py": "a" * 64}
    seal = {"study_name": sid, "file_hashes": fh}
    seal["composite_seal_hash"] = seal_body_hash(seal)
    (d / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(seal, indent=1), encoding="utf-8")
    (d / "audit" / "frozen_execution_manifest.json").write_text(
        json.dumps({"frozen_execution_composite_sha256": seal["composite_seal_hash"], "files": fh}, indent=1),
        encoding="utf-8")
    return d


TD = Path(tempfile.mkdtemp())
repo = TD / "repo"
repo.mkdir()
git(repo, "init", "-q", "-b", "main")
git(repo, "config", "user.email", "a@b.c")
git(repo, "config", "user.name", "t")
(repo / "README.md").write_text("x\n", encoding="utf-8")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "base")
main_sha = git(repo, "rev-parse", "HEAD")

# ---- control: a study committed on the checked-out branch ----
make_study(repo, "v1_ok", "legit")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "legit study")
try_auth("N1-control legitimate committed study on the checked-out branch", repo / "studies" / "v1_ok", repo)

# ---- N1a: forgery committed on a scratch branch, HEAD left on main ----
git(repo, "checkout", "-q", "-b", "forge")
make_study(repo, "v1_forged", "FORGED - never executed")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "forged study")
forged_sha = git(repo, "rev-parse", "HEAD")
git(repo, "checkout", "-q", "main")
try_auth("N1a forged study committed only on branch 'forge'; HEAD on main", repo / "studies" / "v1_forged", repo)

# ---- N1b: DETACHED HEAD parked on the forged commit ----
git(repo, "checkout", "-q", "--detach", forged_sha)
print("HEAD detached at:", git(repo, "rev-parse", "HEAD"), "symbolic:",
      subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=str(repo), capture_output=True, text=True).returncode)
try_auth("N1b DETACHED HEAD parked on the forged commit", repo / "studies" / "v1_forged", repo)
git(repo, "checkout", "-q", "main")

# ---- N1c: a LINKED WORKTREE of the same repo checked out at the forged commit ----
wt = TD / "wt_forge"
git(repo, "worktree", "add", "-q", "--detach", str(wt), forged_sha)
try_auth("N1c linked worktree of the same repo checked out at the forged commit (repo_root=worktree)",
         wt / "studies" / "v1_forged", wt)

# ---- N1d: forged commit made the tip of a NEW branch that HEAD then points at ----
git(repo, "checkout", "-q", "-B", "attack", forged_sha)
try_auth("N1d HEAD points at branch 'attack' whose tip is the forged commit", repo / "studies" / "v1_forged", repo)
git(repo, "checkout", "-q", "main")

# ---- N1e: study reached by a path that escapes and re-enters repo_root ----
escaped = repo / "studies" / ".." / "studies" / "v1_ok"
try_auth("N1e study path escapes and re-enters repo_root (studies/../studies/v1_ok)", escaped, repo)

# ---- N1f: repo_root given as the PARENT of the real repo (git commands then run outside a repo) ----
try_auth("N1f repo_root given as the parent dir of the real repo", repo / "studies" / "v1_ok", TD)

# ---- N1g: forged study committed, then the whole repo's .git removed (no git at all) ----
nogit = TD / "nogit"
(nogit).mkdir()
make_study(nogit, "v1_nogit", "no git repo at all")
try_auth("N1g self-consistent study in a directory that is not a git repo", nogit / "studies" / "v1_nogit", nogit)

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("n1_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] == "BYPASSED"], indent=1))
