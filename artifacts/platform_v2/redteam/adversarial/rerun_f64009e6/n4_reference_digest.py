"""NEW ATTACK N4 (pass 03): the W-3 fix now verifies the aggregate reference_digest over the
FULL catalog build_manifest, unconditionally. Two questions: (1) does that still validate the
REAL committed dataset specs (a fix-induced regression would fail every existing v2 study), and
(2) can a manifest listing EXTRA tables, or self-consistently rewritten entries, still bind?
Read-only against data/catalog; all mutation happens on copies in tmp."""
from __future__ import annotations
import hashlib, json, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
import yaml  # noqa
from research_workflow import dataset_v2  # noqa

REAL_CATALOG_PARENT = Path(r"C:\Users\Scott McCarty\Projects\Nautilus Trader\data\catalog")
res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})
    print(f"[{verdict}] {case}\n    {str(outcome)[:400]}")


def agg(ref_manifest):
    return hashlib.sha256(json.dumps({n: (ref_manifest.get(n) or {}).get("sha256") for n in sorted(ref_manifest)},
                                     sort_keys=True).encode()).hexdigest()


# ---- (1) regression: the committed specs vs the real catalogs ----
for spec_name in ("NQ_1S_V2", "ES_1S_V2"):
    spec = yaml.safe_load((ROOT / "research" / "datasets" / f"{spec_name}.yaml").read_text(encoding="utf-8"))
    declared = list(spec.get("reference_tables") or [])
    cat = REAL_CATALOG_PARENT / spec_name
    bm = cat / "build_manifest.json"
    if not bm.is_file():
        rec(f"N4-reg {spec_name}: committed reference_digest recomputes under the new full-manifest formula",
            f"SKIPPED: {bm} not present", "SKIPPED")
        continue
    ref_manifest = (json.loads(bm.read_text(encoding="utf-8")).get("reference_tables") or {})
    computed = agg(ref_manifest)
    declared_digest = spec.get("reference_digest")
    rec(f"N4-reg {spec_name}: committed reference_digest recomputes under the new full-manifest formula",
        f"declared={declared_digest} computed={computed} manifest_tables={sorted(ref_manifest)} "
        f"spec_declares={declared} match={computed == declared_digest}",
        "BLOCKED" if computed == declared_digest else "BYPASSED")
    # and the real load path, read-only, over the declared subset
    try:
        tables = dataset_v2.load_reference_tables(cat, declared, declared_digest)
        rec(f"N4-reg {spec_name}: load_reference_tables(real catalog, declared, committed digest)",
            f"loaded={sorted(tables)} rows={{{', '.join(f'{k}:{len(v)}' for k, v in tables.items())}}}", "BLOCKED")
    except Exception as exc:
        rec(f"N4-reg {spec_name}: load_reference_tables(real catalog, declared, committed digest)",
            f"{type(exc).__name__}: {exc}", "BYPASSED")

# ---- (2) adversarial variants on a COPY of the real catalog's reference/ + manifest ----
src = REAL_CATALOG_PARENT / "NQ_1S_V2"
TD = Path(tempfile.mkdtemp())
cat = TD / "cat"
(cat / "reference").mkdir(parents=True)
for p in (src / "reference").glob("*.parquet"):
    shutil.copyfile(p, cat / "reference" / p.name)
base_manifest = json.loads((src / "build_manifest.json").read_text(encoding="utf-8"))
ref0 = dict(base_manifest.get("reference_tables") or {})
(cat / "build_manifest.json").write_text(json.dumps({"reference_tables": ref0}), encoding="utf-8")
good = agg(ref0)
declared = ["sessions"]

try:
    dataset_v2.load_reference_tables(cat, declared, good)
    rec("N4a control: subset declaration + correct full-manifest digest", "loaded", "OK")
except Exception as exc:
    rec("N4a control: subset declaration + correct full-manifest digest", f"{type(exc).__name__}: {exc}", "UNEXPECTED_REJECT")

# N4b: manifest lists an EXTRA table that does not exist on disk; attacker keeps the digest consistent
ref_extra = dict(ref0)
ref_extra["phantom"] = {"sha256": "f" * 64}
(cat / "build_manifest.json").write_text(json.dumps({"reference_tables": ref_extra}), encoding="utf-8")
try:
    dataset_v2.load_reference_tables(cat, declared, good)
    rec("N4b manifest gains a phantom table; study still declares only ['sessions'], old digest",
        "LOADED - the aggregate no longer binds", "BYPASSED")
except Exception as exc:
    rec("N4b manifest gains a phantom table; study still declares only ['sessions'], old digest",
        f"{type(exc).__name__}: {exc}", "BLOCKED")

# N4c: attacker rewrites the manifest AND its self-computed digest, but the SPEC digest is committed
try:
    dataset_v2.load_reference_tables(cat, declared, agg(ref_extra))
    rec("N4c attacker recomputes the aggregate over the tampered manifest (NOT a bypass: the digest "
        "argument comes from the COMMITTED DatasetSpec, which the attacker cannot rewrite without a commit)",
        "LOADED with an attacker-supplied digest - expected; documents where the anchor actually is", "OK")
except Exception as exc:
    rec("N4c attacker recomputes the aggregate over the tampered manifest (anchor location probe)",
        f"{type(exc).__name__}: {exc}", "BLOCKED")

# N4d: swap a DECLARED table's bytes while keeping the manifest+digest self-consistent
(cat / "build_manifest.json").write_text(json.dumps({"reference_tables": ref0}), encoding="utf-8")
sp = cat / "reference" / "sessions.parquet"
import pandas as pd  # noqa
_df = pd.read_parquet(sp)
_df.iloc[:-1].to_parquet(sp, index=False)     # a VALID parquet with a tampered session calendar
newsha = hashlib.sha256(sp.read_bytes()).hexdigest()
ref_swapped = dict(ref0)
ref_swapped["sessions"] = {**ref0["sessions"], "sha256": newsha}
(cat / "build_manifest.json").write_text(json.dumps({"reference_tables": ref_swapped}), encoding="utf-8")
try:
    dataset_v2.load_reference_tables(cat, declared, good)
    rec("N4d declared sessions.parquet bytes swapped + manifest sha refreshed, COMMITTED spec digest",
        "LOADED", "BYPASSED")
except Exception as exc:
    rec("N4d declared sessions.parquet bytes swapped + manifest sha refreshed, COMMITTED spec digest",
        f"{type(exc).__name__}: {exc}", "BLOCKED")

# N4e: readiness R1's catalog digest still ignores reference/ and build_manifest.json (W-3 second half)
from research_workflow.roots import compute_catalog_digest  # noqa
import inspect  # noqa
srcx = inspect.getsource(compute_catalog_digest)
covers_reference = "reference" in srcx or "build_manifest" in srcx
rec("N4e compute_catalog_digest (readiness R1) covers <catalog>/reference and build_manifest.json",
    f"scope='data/' only: {not covers_reference}; the committed DatasetSpec.reference_digest remains the sole anchor",
    "BLOCKED" if covers_reference else "BYPASSED")

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("n4_results.json").write_text(json.dumps({"results": res, "tmp": str(TD)}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] == "BYPASSED"], indent=1))
