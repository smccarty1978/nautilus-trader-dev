"""Phase 0. Reproduce the predecessor exactly, or STOP.

Nothing downstream is permitted to run if any of these six quantities fails to
reproduce. A forensic extension that cannot rebuild its own lineage is diagnosing
the wrong thing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .common import (PRIMARY_TARGET, assert_2024_seal, load_full, low_rank,
                     trade_clustered_ci)

# The accepted values, quoted from the predecessor REPORT and its frozen gate output.
ACCEPTED = {
    "n_observations": 2991,
    "n_unique_trades": 781,
    "per_rung": {1.0: 781, 1.5: 658, 2.0: 522, 2.5: 426, 3.0: 356, 4.0: 248},
    "n_oos_observations": 1410,
    "n_oos_trades": 380,
    "baseline_success_pct": 48.4397163,
    "bottom_decile_continue_minus_exit_hwm_atr": -0.7197866,
    "ci95_lo": -1.3032425,
    "ci95_hi": -0.1799056,
}

# Tolerances. Counts are exact. The percentage is quoted to 7 significant figures and
# the ATR quantities to 7 decimals, so they are compared at the precision published.
TOL_PCT = 5e-6
TOL_ATR = 5e-7


def reconcile() -> dict:
    full = load_full()
    assert_2024_seal(full)
    oos = full[full["has_oos"]].reset_index(drop=True)

    per_rung = {float(k): int(v) for k, v in
                full.groupby("rung_atr")["regime_id"].size().items()}

    lab = oos[PRIMARY_TARGET].to_numpy()
    baseline = 100.0 * float((lab == "FAVOURABLE").mean())

    # Gate B-4 verbatim: bottom decile by ASCENDING score, HWM exit basis.
    prob = oos["oos_prob"].to_numpy()
    k = max(1, int(round(0.10 * prob.size)))
    bot = low_rank(prob)[:k]
    diff = oos["cme_hwm"].to_numpy()[bot]
    lo, hi = trade_clustered_ci(diff, oos["regime_id"].to_numpy()[bot])

    checks = [
        _chk("n_observations", ACCEPTED["n_observations"], len(full), 0),
        _chk("n_unique_trades", ACCEPTED["n_unique_trades"],
             int(full["regime_id"].nunique()), 0),
        _chk("n_oos_observations", ACCEPTED["n_oos_observations"], len(oos), 0),
        _chk("n_oos_trades", ACCEPTED["n_oos_trades"],
             int(oos["regime_id"].nunique()), 0),
        _chk("baseline_success_pct", ACCEPTED["baseline_success_pct"], baseline, TOL_PCT),
        _chk("bottom_decile_continue_minus_exit_hwm_atr",
             ACCEPTED["bottom_decile_continue_minus_exit_hwm_atr"],
             float(diff.mean()), TOL_ATR),
        _chk("ci95_lo", ACCEPTED["ci95_lo"], lo, TOL_ATR),
        _chk("ci95_hi", ACCEPTED["ci95_hi"], hi, TOL_ATR),
    ]
    checks += [_chk(f"per_rung_{r}", ACCEPTED["per_rung"][r], per_rung.get(r, 0), 0)
               for r in sorted(ACCEPTED["per_rung"])]

    failed = [c["quantity"] for c in checks if not c["reproduced"]]

    # The amendment (SPEC 3) is measured here so the REPORT can quote it from the
    # reconciliation file rather than from an ad-hoc computation.
    mark_diff = oos["cme_mark"].to_numpy()[bot]
    mlo, mhi = trade_clustered_ci(mark_diff, oos["regime_id"].to_numpy()[bot])

    return {
        "checks": checks,
        "stop_triggered": bool(failed),
        "failed_quantities": failed,
        "bottom_decile_n_obs": int(k),
        "bottom_decile_n_trades": int(pd.unique(oos["regime_id"].to_numpy()[bot]).size),
        "exit_basis_amendment": {
            "rationale": "SPEC 3. current_mfe_atr is the running HWM and is not a "
                         "transactable fill; return_from_entry_atr is the mark.",
            "drawdown_from_hwm_atr_mean": float(oos["drawdown_from_hwm_atr"].mean()),
            "drawdown_from_hwm_atr_median": float(oos["drawdown_from_hwm_atr"].median()),
            "pooled_cme_hwm": float(oos["cme_hwm"].mean()),
            "pooled_cme_mark": float(oos["cme_mark"].mean()),
            "bottom_decile_cme_hwm": float(diff.mean()),
            "bottom_decile_cme_mark": float(mark_diff.mean()),
            "bottom_decile_cme_mark_ci95": [mlo, mhi],
            "share_of_headline_that_is_unexecutable_pct":
                100.0 * (1.0 - float(mark_diff.mean()) / float(diff.mean())),
        },
    }


def _chk(name: str, accepted, reproduced, tol: float) -> dict:
    delta = float(reproduced) - float(accepted)
    return {"quantity": name, "accepted": accepted, "reproduced": reproduced,
            "delta": delta, "tolerance": tol,
            "reproduced_exactly": bool(delta == 0),
            "reproduced": bool(abs(delta) <= tol)}
