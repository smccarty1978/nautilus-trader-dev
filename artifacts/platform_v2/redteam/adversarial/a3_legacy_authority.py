"""A3 (CRIT-7): spoofed legacy authority against research_workflow.policy.assert_old_runtime_allowed.
Everything runs inside a throwaway git repo under tempfile; the real repo is never touched."""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from research_workflow.policy import assert_old_runtime_allowed, OldRuntimePolicyError  # noqa
from research_workflow.seal import seal_body_hash  # noqa

res = []


def t(name, fn, expect_reject=True):
    try:
        out = fn()
        res.append({"case": name, "outcome": "GRANTED " + json.dumps(out, default=str)[:200],
                    "verdict": "BYPASSED" if expect_reject else "OK"})
    except Exception as exc:
        res.append({"case": name, "outcome": type(exc).__name__ + ": " + str(exc)[:220],
                    "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT"})


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def make_study(repo, sid, *, file_hashes=None, composite=None, manifest_composite=None,
               study_name=None, empty_seal=False, no_manifest=False, closure=None):
    d = repo / "studies" / sid
    (d / "artifacts").mkdir(parents=True, exist_ok=True)
    (d / "audit").mkdir(parents=True, exist_ok=True)
    fh = file_hashes if file_hashes is not None else {
        "research_workflow/generic_collector.py": "a" * 64, "features/engine.py": "b" * 64}
    seal = {} if empty_seal else {
        "schema_version": 1, "study_name": study_name or sid, "file_hashes": fh,
        "sealed_at_utc": "2026-01-01T00:00:00+00:00"}
    if not empty_seal:
        seal["composite_seal_hash"] = composite if composite is not None else seal_body_hash(seal)
    (d / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(seal, indent=1), encoding="utf-8")
    if not no_manifest:
        mc = manifest_composite if manifest_composite is not None else seal.get("composite_seal_hash")
        (d / "audit" / "frozen_execution_manifest.json").write_text(
            json.dumps({"frozen_execution_composite_sha256": mc, "files": fh}, indent=1), encoding="utf-8")
    if closure is not None:
        (d / "artifacts" / "study_closure.json").write_text(json.dumps(closure, indent=1), encoding="utf-8")
    return d


TD = Path(tempfile.mkdtemp())
repo = TD / "repo"
(repo / "studies").mkdir(parents=True)
git(repo, "init", "-q")
git(repo, "config", "user.email", "rt@example.com")
git(repo, "config", "user.name", "rt")
(repo / "README.md").write_text("x\n", encoding="utf-8")
git(repo, "add", "-A")
git(repo, "commit", "-qm", "init")

# (a) empty seal, committed
d = make_study(repo, "v1_empty_seal", empty_seal=True)
git(repo, "add", "-A"); git(repo, "commit", "-qm", "a")
t("(a) empty seal, git-committed", lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (b) foreign seal copied from another study
good = make_study(repo, "v1_good")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "good")
t("(b0) legitimate self-consistent committed study (control)",
  lambda: assert_old_runtime_allowed(good, repo_root=repo), expect_reject=False)
foreign = make_study(repo, "v1_foreign")
shutil.copy(good / "artifacts" / "preexec_audit_seal.json", foreign / "artifacts" / "preexec_audit_seal.json")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "b")
t("(b) foreign seal copied verbatim into another study dir",
  lambda: assert_old_runtime_allowed(foreign, repo_root=repo))

# (c) stale seal: manifest composite != seal composite
d = make_study(repo, "v1_stale", manifest_composite="c" * 64)
git(repo, "add", "-A"); git(repo, "commit", "-qm", "c")
t("(c) stale seal (manifest composite mismatch)", lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (d) valid-looking but entirely untracked
d = make_study(repo, "v1_untracked")
t("(d) self-consistent seal, never added to git", lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (e) tracked seal + tracked manifest but composite mismatch (seal not self-consistent)
d = make_study(repo, "v1_badcomposite", composite="d" * 64, manifest_composite="d" * 64)
git(repo, "add", "-A"); git(repo, "commit", "-qm", "e")
t("(e) seal composite does not match its own file_hashes", lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (f) tracked seal with edited study id
d = make_study(repo, "v1_wrongid", study_name="some_other_study")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "f")
t("(f) seal study_name != directory name", lambda: assert_old_runtime_allowed(d, repo_root=repo))

# ---------------- adjacent bypasses ----------------
# (g) fabricated study, `git add` only -- NEVER committed
d = make_study(repo, "v1_index_only")
git(repo, "add", "studies/v1_index_only")
print("index-only ls-files:", git(repo, "ls-files", "studies/v1_index_only").stdout.strip())
t("(g) ADJACENT: fabricated self-consistent seal, `git add` only (never committed)",
  lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (h) committed legitimate study, then seal+manifest REWRITTEN in the working tree
#     (self-consistently) after the commit -- content is read from the worktree, HEAD is never consulted
d = make_study(repo, "v1_worktree_swap")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "h")
head_seal = git(repo, "show", "HEAD:studies/v1_worktree_swap/artifacts/preexec_audit_seal.json").stdout
forged_fh = {"research_workflow/generic_collector.py": "f" * 64,
             "features/engine.py": "e" * 64,
             "research_workflow/BACKDOOR.py": "0" * 64}
forged = {"schema_version": 1, "study_name": "v1_worktree_swap", "file_hashes": forged_fh,
          "sealed_at_utc": "2026-01-01T00:00:00+00:00"}
forged["composite_seal_hash"] = seal_body_hash(forged)
(d / "artifacts" / "preexec_audit_seal.json").write_text(json.dumps(forged, indent=1), encoding="utf-8")
(d / "audit" / "frozen_execution_manifest.json").write_text(
    json.dumps({"frozen_execution_composite_sha256": forged["composite_seal_hash"], "files": forged_fh}, indent=1),
    encoding="utf-8")
print("HEAD composite:", json.loads(head_seal)["composite_seal_hash"][:16],
      "worktree composite:", forged["composite_seal_hash"][:16])
t("(h) ADJACENT: committed study whose seal+manifest were rewritten in the working tree after commit",
  lambda: assert_old_runtime_allowed(d, repo_root=repo))

# (i) branch-only: seal committed on another branch, deleted from the current branch's HEAD but
#     still present + staged in the worktree
d = make_study(repo, "v1_branch_only")
git(repo, "checkout", "-q", "-b", "sidebranch")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "i-side")
git(repo, "checkout", "-q", "master") if git(repo, "rev-parse", "--verify", "-q", "master").returncode == 0 else git(repo, "checkout", "-q", "main")
print("after checkout back, seal exists on disk:", (d / "artifacts" / "preexec_audit_seal.json").is_file())
if not (d / "artifacts" / "preexec_audit_seal.json").is_file():
    make_study(repo, "v1_branch_only")
    git(repo, "add", "studies/v1_branch_only")
t("(i) ADJACENT: seal committed only on a different branch (restored+staged on this one)",
  lambda: assert_old_runtime_allowed(repo / "studies" / "v1_branch_only", repo_root=repo))

# (j) junction/symlink from inside the repo to a real historical study outside the repo
outside = TD / "outside"
real = make_study(outside, "v1_real_outside")
link = repo / "studies" / "v1_linked"
linked_ok = False
try:
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)], capture_output=True, text=True)
        linked_ok = r.returncode == 0
    else:
        os.symlink(real, link); linked_ok = True
except Exception as exc:
    print("link failed:", exc)
if linked_ok:
    t("(j) ADJACENT: junction inside the repo pointing at a study outside it",
      lambda: assert_old_runtime_allowed(link, repo_root=repo))
else:
    res.append({"case": "(j) ADJACENT junction", "outcome": "SKIPPED: could not create junction", "verdict": "N/A"})

# (k) nested path shaped like a real study
nested = make_study(repo, "outer/studies/v1_good")
git(repo, "add", "-A"); git(repo, "commit", "-qm", "k")
t("(k) ADJACENT: nested studies/outer/studies/v1_good (name collision with a real study)",
  lambda: assert_old_runtime_allowed(nested, repo_root=repo), expect_reject=False)

# (l) study_closure.json present but forged
d = make_study(repo, "v1_forged_closure", closure={"outcome": "PROVEN", "closed_at_utc": "2026-01-01T00:00:00+00:00"})
git(repo, "add", "-A"); git(repo, "commit", "-qm", "l")
t("(l) ADJACENT: forged study_closure.json alongside a valid seal",
  lambda: assert_old_runtime_allowed(d, repo_root=repo))

print(json.dumps(res, indent=1))
Path(__file__).with_name("a3_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
