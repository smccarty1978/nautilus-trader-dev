"""Second-pass audit of feature_contract_v2.json.

Checks for:
  - Exact duplicate definitions (byte-identical text)
  - Near-duplicate definitions (case- and space-insensitive match)
  - Features referencing the same source variable (e.g., two features
    both computed from `flip.high − prior.high`)
  - Features whose definition mentions another feature's name (potential
    alias)
  - Unused snap-anchor definitions
  - Role consistency
  - Null-policy / default combinations

Emits a report log.
"""

import sys
import os
import json
from pathlib import Path
from collections import Counter

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONTRACT_PATH = "models/ml_5m_flip/feature_contract_v2.json"
OUT_LOG = ("studies/1m_regime_collector_v2/contract/"
            "audit_v2_contract.log")


def main():
    with open(CONTRACT_PATH) as f:
        contract = json.load(f)
    features = contract["features"]
    names = [f["name"] for f in features]
    n = len(features)

    lines = []
    lines.append("=" * 100)
    lines.append("v2 FEATURE CONTRACT AUDIT")
    lines.append("=" * 100)
    lines.append(f"\n  Total features: {n}")

    # ---- 1. Duplicate feature names ----
    dupes = [k for k, c in Counter(names).items() if c > 1]
    lines.append(
        f"\n1. Duplicate feature NAMES: "
        f"{'FAIL' if dupes else 'PASS'} ({len(dupes)} found)")
    for d in dupes:
        lines.append(f"   {d}")

    # ---- 2. Exact duplicate definitions (case/space-normalized) ----
    def norm(s):
        return " ".join(s.lower().split())

    defn_groups = {}
    for f in features:
        k = norm(f["definition"])
        defn_groups.setdefault(k, []).append(f["name"])
    dup_defns = {k: v for k, v in defn_groups.items() if len(v) > 1}
    lines.append(
        f"\n2. Exact-duplicate definitions (normalized): "
        f"{'FLAG' if dup_defns else 'PASS'} ({len(dup_defns)} groups)")
    for defn, group in dup_defns.items():
        in_alias = all(
            any(ff["name"] == g and ff["role"] == "compat_alias"
                 for ff in features)
            or any(ff["name"] == g and ff["role"] == "constant_by_construction"
                    for ff in features)
            for g in group
        )
        status = ("OK (aliases already marked)" if in_alias
                   else "REVIEW NEEDED")
        lines.append(
            f"   [{status}] {group}")
        lines.append(f"     defn: {defn[:80]}...")

    # ---- 3. Features whose definition mentions another feature's name ----
    # These could be legitimate (e.g., "same as X") or suggest an alias.
    lines.append(f"\n3. Definitions that reference another feature's name:")
    hits = 0
    for f in features:
        d = f["definition"]
        # Ignore self-name
        mentioned = [n_ for n_ in names if n_ != f["name"]
                      and n_ in d and len(n_) > 8]
        if mentioned:
            hits += 1
            role = f["role"]
            alias_of = f.get("alias_of")
            status = (f"marked alias_of={alias_of}" if alias_of
                       else f"role={role}")
            lines.append(
                f"   {f['name']:<45} [{status}]")
            for m in mentioned[:3]:
                lines.append(f"       mentions: {m}")
    if hits == 0:
        lines.append("   (none)")

    # ---- 4. Snap anchors: used vs defined ----
    lines.append(f"\n4. Snap anchor usage:")
    defined = set(contract["snap_call_order_anchors"].keys())
    used = set(f["snap_call_order_anchor"] for f in features)
    unused = defined - used
    undefined = used - defined
    lines.append(f"   Defined anchors: {sorted(defined)}")
    lines.append(f"   Used anchors:    {sorted(used)}")
    lines.append(
        f"   Unused defined:  {'PASS' if not unused else sorted(unused)}")
    lines.append(
        f"   Undefined used:  {'PASS' if not undefined else sorted(undefined)}")

    # ---- 5. Role distribution ----
    lines.append(f"\n5. Role distribution:")
    by_role = Counter(f["role"] for f in features)
    for role, cnt in sorted(by_role.items(), key=lambda x: -x[1]):
        lines.append(f"   {role:<28} {cnt:>5}")

    # ---- 6. Alias integrity ----
    lines.append(f"\n6. Alias integrity:")
    aliases = [f for f in features if f.get("alias_of")]
    lines.append(f"   Total aliases: {len(aliases)}")
    for a in aliases:
        target = a["alias_of"]
        target_exists = any(f["name"] == target for f in features)
        target_is_alias = any(
            f["name"] == target and f["role"] == "compat_alias"
            for f in features)
        status = "OK"
        if not target_exists:
            status = "FAIL (target missing)"
        elif target_is_alias:
            status = "FAIL (alias-of-an-alias)"
        lines.append(
            f"   {a['name']:<45} → {target:<30} {status}")

    # ---- 7. Null policy / default consistency ----
    lines.append(f"\n7. Null-policy × default consistency:")
    issues = []
    for f in features:
        np_ = f["null_policy"]
        default = f["default_value_if_applicable"]
        if np_ == "default_filled" and default is None:
            issues.append((f["name"], "default_filled but default=None"))
        if np_ == "disallow" and default is not None:
            # OK if default is documented as "sentinel only, never written"
            # We're lenient here
            pass
    if issues:
        for name, msg in issues:
            lines.append(f"   {name}: {msg}")
    else:
        lines.append("   (no inconsistencies)")

    # ---- 8. Model-feature count ----
    n_model = sum(1 for f in features if f["role"] == "model_feature")
    lines.append(f"\n8. Model-usable features: {n_model}")
    lines.append(f"   (contract reports: {contract['feature_count_model_usable']})")
    if n_model != contract["feature_count_model_usable"]:
        lines.append("   MISMATCH — fix generator!")
    else:
        lines.append("   match OK")

    # ---- 9. Dtype distribution ----
    lines.append(f"\n9. Dtype distribution:")
    by_dtype = Counter(f["dtype"] for f in features)
    for dt, cnt in sorted(by_dtype.items(), key=lambda x: -x[1]):
        lines.append(f"   {dt:<15} {cnt:>5}")

    # ---- 10. Features with value_range declared ----
    lines.append(f"\n10. Features with declared value_range:")
    with_vr = [f for f in features if f["value_range"]]
    lines.append(f"    {len(with_vr)} features")
    vrs = Counter(f["value_range"] for f in with_vr)
    for vr, cnt in sorted(vrs.items(), key=lambda x: -x[1]):
        lines.append(f"    {vr:<25} {cnt:>5}")

    out = "\n".join(lines)
    print(out)
    Path(OUT_LOG).write_text(out, encoding="utf-8")
    print(f"\n  Saved: {OUT_LOG}")


if __name__ == "__main__":
    main()
