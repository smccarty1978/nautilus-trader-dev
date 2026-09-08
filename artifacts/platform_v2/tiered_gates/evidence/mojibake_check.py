"""Diff-hygiene check proof: does a mojibake detector catch the F3 lines, and what is its false-positive rate on main?"""
import re, subprocess, sys
ROOT = r"C:\Users\Scott McCarty\Projects\Nautilus Trader"
# A UTF-8 multibyte sequence mis-decoded as cp1252 and re-encoded: lead byte C2/C3/E2 -> 'Â' 'Ã' 'â', followed by a cp1252 upper-half char.
MOJIBAKE = re.compile("[\u00c2\u00c3\u00e2][\u0080-\u00bf\u20ac\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\u017d\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\u017e\u0178]")


def run(args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


removed = run(["show", "03330576", "--", "research_workflow/grammar/compiler.py", "research_workflow/lifecycle_v2.py"])
bad = [l for l in removed.splitlines() if l.startswith("-") and not l.startswith("---")]
print("F3 removed (corrupted) lines:", len(bad), "| flagged by detector:", sum(1 for l in bad if MOJIBAKE.search(l)))
# would the detector have fired on the branch BEFORE the fix? scan the two files at 5d3aad6a (the Wave 1 gate commit)
for f in ("research_workflow/grammar/compiler.py", "research_workflow/lifecycle_v2.py"):
    t = run(["show", f"5d3aad6a:{f}"])
    print(f"  at 5d3aad6a {f}: {len(MOJIBAKE.findall(t))} mojibake hits")
ls = run(["ls-files", "--", "*.py", "*.md", "*.yaml", "*.json", "*.toml", "*.txt"]).split("\n")
ls = [f for f in ls if f]
fp = []; not_utf8 = []
for f in ls:
    try:
        t = open(f"{ROOT}/{f}", encoding="utf-8").read()
    except UnicodeDecodeError:
        not_utf8.append(f); continue
    except OSError:
        continue
    m = MOJIBAKE.search(t)
    if m:
        fp.append((f, t[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")))
print("tracked text files scanned:", len(ls), "| not UTF-8:", len(not_utf8), "| files with mojibake hits on main:", len(fp))
for f in not_utf8[:10]:
    print("   NOT_UTF8", f)
for f, ctx in fp[:15]:
    print("   HIT", f, repr(ctx))
