"""Logs every candidate (not just triggered/selected ones), with full
feature/score/suppression detail, for later reconciliation against the
offline reference."""
from __future__ import annotations

from typing import List


class ParityLogger:
    def __init__(self):
        self.candidates: List[dict] = []

    def log_candidate(self, *, regime_start_ns: int, regime_direction: int,
                      checkpoint_index: int, observation_time_ns: int,
                      established_regime_gate: bool, regime_age_s: float, running_mfe_atr: float,
                      running_mae_atr: float, current_pnl_atr: float,
                      new_progress_windows: int, retained_mfe_ratio: float,
                      decision_rth: bool | None, fill_rth: bool | None, fill_ts: int | None,
                      fill_px: float | None, atr_at_entry: float | None, valid_fill: bool | None,
                      final_candidate_eligible: bool,
                      feature_values: dict | None, null_mask: dict | None,
                      score: float | None, r5_trigger: bool | None, r2_5_trigger: bool | None,
                      suppression_reason: str | None) -> None:
        self.candidates.append({
            "regime_start_ns": regime_start_ns, "regime_direction": regime_direction,
            "checkpoint_index": checkpoint_index, "observation_time_ns": observation_time_ns,
            "established_regime_gate": established_regime_gate, "regime_age_s": regime_age_s,
            "running_mfe_atr": running_mfe_atr, "running_mae_atr": running_mae_atr,
            "current_pnl_atr": current_pnl_atr, "new_progress_windows": new_progress_windows,
            "retained_mfe_ratio": retained_mfe_ratio,
            "decision_rth": decision_rth, "fill_rth": fill_rth, "fill_ts": fill_ts,
            "fill_px": fill_px, "atr_at_entry": atr_at_entry, "valid_fill": valid_fill,
            "final_candidate_eligible": final_candidate_eligible,
            **({f"feat__{k}": v for k, v in (feature_values or {}).items()}),
            **({f"null__{k}": v for k, v in (null_mask or {}).items()}),
            "score": score, "r5_trigger": r5_trigger, "r2_5_trigger": r2_5_trigger,
            "suppression_reason": suppression_reason,
        })

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame(self.candidates)
