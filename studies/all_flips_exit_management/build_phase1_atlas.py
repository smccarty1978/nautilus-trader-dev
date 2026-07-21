"""Phase 1 driver for ALL_FLIPS: build the corrected weakness checkpoint
atlas from the full 2021-2026 NT collection in _work/nt_raw/, and write
this study's required Phase 1 deliverables under results/ and audit/.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import pandas as pd

from studies._shared_exit_mgmt.build_atlas import build_atlas, integrity_report

STUDY_ROOT = Path(__file__).parent
WORK_ROOT = STUDY_ROOT / "_work" / "nt_raw"
RESULTS_ROOT = STUDY_ROOT / "results"
AUDIT_ROOT = STUDY_ROOT / "audit"


def main():
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    atlas = build_atlas(WORK_ROOT, "ALL_FLIPS")
    print(f"Built atlas: {len(atlas):,} rows, "
             f"{atlas['trade_id'].nunique():,} trades, "
             f"{time.time()-t0:.0f}s")
    print(f"Memory: {atlas.memory_usage(deep=True).sum() / 1e9:.2f} GB")

    atlas_path = RESULTS_ROOT / "corrected_weakness_atlas.parquet"
    atlas.to_parquet(atlas_path, index=False)
    print(f"Wrote {atlas_path}")

    # Per-year, per-terminal-label summary (small, not the full atlas)
    atlas["year"] = (pd.to_datetime(atlas["entry_ts"], unit="ns", utc=True)
                        .dt.year)
    summary = (atlas.groupby(["year", "terminal_weakness_label"],
                                 observed=True)
                  .agg(n_checkpoints=("trade_id", "size"),
                          n_trades=("trade_id", "nunique"),
                          mean_mfe_atr=("mfe_atr_from_entry", "mean"),
                          mean_giveback_atr=("giveback_atr_from_entry", "mean"))
                  .reset_index())
    summary_path = RESULTS_ROOT / "atlas_summary.parquet"
    summary.to_parquet(summary_path, index=False)
    print(f"Wrote {summary_path}")

    rep = integrity_report(atlas)
    report_path = AUDIT_ROOT / "atlas_integrity_report.md"
    with open(report_path, "w") as f:
        f.write("# ALL_FLIPS Atlas Integrity Report\n\n")
        f.write(f"Built: {pd.Timestamp.utcnow()}\n\n")
        for k, v in rep.items():
            f.write(f"- **{k}**: {v}\n")
        f.write("\n## Requirements check\n\n")
        f.write("- current_pnl/MFE/MAE/giveback measured from entry_px: "
                    "YES (see studies/_shared_exit_mgmt/mfe_mae.py, "
                    "used identically live and offline)\n")
        f.write(f"- no checkpoint before entry: "
                    f"{'PASS' if rep.get('n_checkpoint_before_entry', 1) == 0 else 'FAIL'}\n")
        f.write(f"- no checkpoint after terminal opposite flip: "
                    f"{'PASS' if rep.get('n_checkpoint_after_opposite_flip', 1) == 0 else 'FAIL'}\n")
        f.write(f"- short trades canonicalized positive MFE/MAE/giveback: "
                    f"{'PASS' if rep.get('n_negative_mfe',1)==0 and rep.get('n_negative_mae',1)==0 and rep.get('n_negative_giveback',1)==0 else 'FAIL'}\n")
    print(f"Wrote {report_path}")
    print("\nIntegrity report:", rep)


if __name__ == "__main__":
    main()
