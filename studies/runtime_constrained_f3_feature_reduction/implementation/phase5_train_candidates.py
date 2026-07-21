"""Phase 5 -- retrain all 8 raw-count candidates from
`results/candidate_feature_sets.json`, identical target/population/
hyperparameters/seed/score-method, persisted per the mandatory contract.
F3_live546_gbt_v1 (the 546-target candidate) is retrained here too (distinct
from the Phase 2 "B_live546" ablation id -- same feature set, same
hyperparameters; Phase 2's B ablation and Phase 5's 546 candidate should be
byte-identical models given identical inputs, which the completion audit can
cross-check by hash).
"""
from __future__ import annotations

import json
import time

from common import RESULTS, train_and_persist

FEATURE_INVENTORY_HASH_FILE = RESULTS / "f3_feature_inventory_v2_summary.json"


def main() -> None:
    candidates = json.loads((RESULTS / "candidate_feature_sets.json").read_text())
    t0 = time.time()
    for model_id, spec in candidates.items():
        train_and_persist(model_id, spec["features"],
                          source_note=f"Phase 5 candidate, raw_target={spec['raw_target']}, "
                                       f"ranked from Phase 3 full_raw_feature_ranking_695.csv restricted to 546 live-ready pool",
                          status="candidate")
    print(f"Phase 5 done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
