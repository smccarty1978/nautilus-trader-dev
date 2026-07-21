"""Phase 4 -- candidate feature-set construction. Selects from the Phase 3
ranking RESTRICTED to the 546 live-ready pool (F0 excluded regardless of
rank, per SPEC guardrails). Frozen one-hot policy: complete categorical
dummy groups are always retained together (a raw target of N may therefore
yield a final count slightly >= N once a partial group is completed) --
never a silently-partial dummy group.
"""
from __future__ import annotations

import json

import pandas as pd

from common import RESULTS, CONFIG, DUMMY_SUFFIX_RE, sha256_obj

RAW_TARGETS = [25, 40, 60, 80, 100, 150, 250, 546]


def canonical_base(name: str) -> str:
    m = DUMMY_SUFFIX_RE.match(name)
    return m.group(1) if m else None


def main() -> None:
    ranking = pd.read_csv(RESULTS / "full_raw_feature_ranking_695.csv")
    family_sets = json.loads((RESULTS / "family_ablation_feature_sets.json").read_text())["feature_sets"]
    live546 = set(family_sets["B_live546"])

    ranked_live = ranking[ranking["feature_name"].isin(live546)].sort_values(
        "importance_mean", ascending=False).reset_index(drop=True)
    assert len(ranked_live) == 546, f"expected 546 ranked live features, got {len(ranked_live)}"

    # group membership: dummy siblings, keyed by canonical base
    group_members: dict[str, list[str]] = {}
    for f in live546:
        base = canonical_base(f)
        if base is not None:
            group_members.setdefault(base, []).append(f)

    candidates = {}
    for target_n in RAW_TARGETS:
        selected: list[str] = []
        selected_set: set[str] = set()
        for _, row in ranked_live.iterrows():
            if len(selected) >= target_n and target_n < 546:
                break
            feat = row["feature_name"]
            if feat in selected_set:
                continue
            base = canonical_base(feat)
            if base is not None and base in group_members:
                for sib in group_members[base]:
                    if sib not in selected_set:
                        selected.append(sib)
                        selected_set.add(sib)
            else:
                selected.append(feat)
                selected_set.add(feat)
        # NOTE: the 546-target candidate is versioned _v2, not _v1, because
        # Phase 2's family-ablation "B_live546" already used the model_id
        # F3_live546_gbt_v1 for the SAME 546-feature SET in a DIFFERENT
        # column order (registry/inventory order vs this Phase 3-ranked
        # order -- same set, different hash). Reusing _v1 here made Phase 5
        # crash on common.py's atomic-promotion hash-mismatch guard
        # (caught by the completion-gate audit; see STUDY_REPORT.md #11).
        model_id = f"F3_top{target_n}_gbt_v1" if target_n < 546 else "F3_live546_gbt_v2"
        candidates[model_id] = {
            "raw_target": target_n, "actual_n_features": len(selected),
            "features": selected, "sha256": sha256_obj(selected),
        }
        print(f"{model_id}: target={target_n} actual={len(selected)}")

    (RESULTS / "candidate_feature_sets.json").write_text(json.dumps(candidates, indent=2))
    (CONFIG / "candidate_feature_sets.json").write_text(json.dumps(
        {k: {"raw_target": v["raw_target"], "actual_n_features": v["actual_n_features"], "sha256": v["sha256"]}
         for k, v in candidates.items()}, indent=2))


if __name__ == "__main__":
    main()
