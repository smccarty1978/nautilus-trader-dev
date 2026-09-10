"""For every tracked frozen_execution_manifest.json: which files' V2 hashes match the tree now,
matched on main (9be6eba2) and were moved by this branch."""
import json, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path
ROOT = Path.cwd(); sys.path.insert(0, str(ROOT))
from research_workflow.closure_hash import hash_file_v2
MAIN = "9be6eba2"
manifests = subprocess.run(["git", "ls-files", "studies/*/audit/frozen_execution_manifest.json"], capture_output=True, text=True).stdout.split()
tmp = Path(tempfile.mkdtemp())
cache = {}
def main_hash(rel):
    if rel in cache: return cache[rel]
    blob = subprocess.run(["git", "show", f"{MAIN}:{rel}"], capture_output=True)
    if blob.returncode != 0: cache[rel] = None; return None
    p = tmp / rel.replace("/", "__"); p.write_bytes(blob.stdout); cache[rel] = hash_file_v2(p); return cache[rel]
moved_by_branch = Counter(); summary = {}
for mf in sorted(manifests):
    m = json.loads((ROOT / mf).read_text(encoding="utf-8"))
    files = m.get("files") or {}
    if m.get("hash_algorithm") != "v2" or not isinstance(files, dict): summary[mf] = "not a v2 manifest"; continue
    c = Counter()
    for rel, recorded in files.items():
        p = ROOT / rel
        now = hash_file_v2(p) if p.is_file() else None
        at_main = main_hash(rel)
        if now == recorded: c["match_now"] += 1
        elif at_main == recorded: c["matched_on_main_moved_by_branch"] += 1; moved_by_branch[rel] += 1
        elif now is None: c["missing_now"] += 1
        else: c["already_drifted_on_main"] += 1
    summary[Path(mf).parts[1]] = dict(c)
print(json.dumps(summary, indent=1))
print("files moved by this branch that a sealed manifest pins:", dict(moved_by_branch))
