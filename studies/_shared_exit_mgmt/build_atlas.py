"""Phase 1 (part 2): build the corrected weakness checkpoint atlas from
already-completed NT trades/checkpoints output.

Population-agnostic: operates purely on trades.parquet/checkpoints.parquet
produced by ANY ExitManagementBaseStrategy subclass. Caller supplies the
population label and the raw-output directory.

IMPORTANT -- this is OFFLINE, POST-HOC LABEL CONSTRUCTION, not a live
feature computation:
  - Every "eventual_*"/"remaining_*"/"terminal_weakness_label" field is
    computed strictly from a trade's OWN already-closed path (the trade
    has already exited by the time this script runs). This is the
    standard supervised-learning label-construction pattern CLAUDE.md's
    "ML MODEL REQUIREMENTS" section explicitly sanctions ("Labels MUST
    come from NT backtest outcomes... future outcomes used only as
    labels/evaluation").
  - These forward-looking columns MUST NEVER be joined back into any
    live decision-time feature set (Phase 3 model training must treat
    them purely as targets/diagnostics, never as inputs at a causal
    checkpoint_ts). Enforced by naming convention (remaining_/eventual_/
    terminal_ prefixes) -- Phase 3's feature-family definitions must
    exclude these prefixes from any W0-W4 input feature list.

Label definitions (documented explicitly since the study spec does not
pin exact semantics):
  - remaining_mfe_atr[i]  = final_mfe_atr - mfe_atr_from_entry[i]
        (mfe is a running max, so this is "how much higher will MFE
        still go after this checkpoint" -- always >= 0)
  - eventual_new_mfe[i]   = remaining_mfe_atr[i] > 1e-9
  - eventual_recovery_to_prior_mfe[i] = does current_pnl_atr_from_entry
        reach >= mfe_atr_from_entry[i] (the level ALREADY achieved by
        this checkpoint) at any LATER checkpoint of the same trade?
        (True whenever eventual_new_mfe is True, since exceeding the
        prior level is a strict form of reaching it; can also be True
        without eventual_new_mfe, if price retraces exactly back up to
        the old high without exceeding it.)
  - remaining_mae_before_next_mfe_atr[i] = worst per-bar adverse
        excursion (recomputed fresh from checkpoint_high/low, NOT the
        cumulative running mae) occurring strictly after checkpoint i,
        up to and including the first future checkpoint that sets a
        NEW mfe high. NaN if no future new high ever occurs (i.e. this
        checkpoint's plateau is the trade's final one).
  - terminal_weakness_label[i]: NEW_MFE / RECOVERED_ONLY /
        TERMINAL_WEAKNESS, a 3-way partition using the two booleans
        above (mutually exclusive, exhaustive).
  - eventual_opposite_flip[i]: per-trade constant, True iff the trade's
        exit_reason == "opposite_flip" (broadcast from trades.parquet).
        Trivially True for every trade in this baseline (Phase 0/1) since
        no other exit path exists yet -- becomes meaningful once Phase
        5/6 stop policies introduce early exits.
"""
from __future__ import annotations
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import numpy as np
import pandas as pd

REQUIRED_ATLAS_COLUMNS = [
    "trade_id", "population", "direction", "entry_ts", "entry_px",
    "checkpoint_ts", "checkpoint_price", "regime_start_ts",
    "opposite_flip_ts", "atr_at_entry", "age_seconds",
    "current_pnl_atr_from_entry", "mfe_atr_from_entry",
    "mae_atr_from_entry", "giveback_atr_from_entry",
    "distance_from_mfe_atr", "remaining_mfe_atr",
    "remaining_mae_before_next_mfe_atr", "eventual_new_mfe",
    "eventual_recovery_to_prior_mfe", "eventual_opposite_flip",
    "terminal_weakness_label",
]


def _label_one_trade(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("checkpoint_ts").reset_index(drop=True)
    n = len(g)
    mfe = g["mfe_atr_from_entry"].to_numpy(dtype=float)
    pnl = g["current_pnl_atr_from_entry"].to_numpy(dtype=float)
    direction = int(g["direction"].iloc[0])
    entry_px = float(g["entry_px"].iloc[0])
    atr = float(g["atr_at_entry"].iloc[0])
    safe_atr = atr if atr and atr == atr and atr > 0 else 1.0
    high = g["checkpoint_high"].to_numpy(dtype=float)
    low = g["checkpoint_low"].to_numpy(dtype=float)

    # Fresh per-bar (NOT cumulative) adverse-excursion contribution,
    # canonicalized positive per studies/_shared_exit_mgmt/mfe_mae.py
    if direction == 1:
        mae_bar = (entry_px - low) / safe_atr
    else:
        mae_bar = (high - entry_px) / safe_atr
    mae_bar = np.maximum(mae_bar, 0.0)

    final_mfe = mfe[-1] if n else 0.0
    remaining_mfe_atr = final_mfe - mfe
    eventual_new_mfe = remaining_mfe_atr > 1e-9

    # forward_max_after[i] = max(pnl[i+1:]), -inf if no future rows
    forward_max_after = np.empty(n)
    running = -np.inf
    for k in range(n - 1, -1, -1):
        forward_max_after[k] = running
        if pnl[k] > running:
            running = pnl[k]
    eventual_recovery_to_prior_mfe = forward_max_after >= (mfe - 1e-9)

    # j_star[i] = first index j>i with mfe[j] > mfe[i] (mfe is
    # non-decreasing, so searchsorted gives this directly); n means
    # "no such future index" (this checkpoint is in the final plateau).
    j_star = np.searchsorted(mfe, mfe, side="right")

    remaining_mae_before_next_mfe = np.full(n, np.nan)
    i = 0
    while i < n:
        plateau_end = i
        while (plateau_end + 1 < n
                 and mfe[plateau_end + 1] == mfe[i]):
            plateau_end += 1
        js = int(j_star[i])
        if js < n:
            window = mae_bar[i + 1: js + 1]
            if len(window):
                suffix_max = np.maximum.accumulate(window[::-1])[::-1]
                for row in range(i, plateau_end + 1):
                    t = row - i
                    remaining_mae_before_next_mfe[row] = (
                        suffix_max[t] if t < len(suffix_max) else 0.0)
            else:
                remaining_mae_before_next_mfe[i:plateau_end + 1] = 0.0
        # else: stays NaN -- no future new high from this plateau
        i = plateau_end + 1

    terminal_weakness_label = np.where(
        eventual_new_mfe, "NEW_MFE",
        np.where(eventual_recovery_to_prior_mfe,
                    "RECOVERED_ONLY", "TERMINAL_WEAKNESS"))

    g["remaining_mfe_atr"] = remaining_mfe_atr
    g["remaining_mae_before_next_mfe_atr"] = remaining_mae_before_next_mfe
    g["eventual_new_mfe"] = eventual_new_mfe
    g["eventual_recovery_to_prior_mfe"] = eventual_recovery_to_prior_mfe
    g["terminal_weakness_label"] = terminal_weakness_label
    return g


_INT64_COLS = {"trade_id", "entry_ts", "checkpoint_ts", "regime_start_ts",
                  "opposite_flip_ts"}
_FLOAT32_SAFE_COLS = {
    "atr_at_entry", "age_seconds", "current_pnl_atr_from_entry",
    "mfe_atr_from_entry", "mae_atr_from_entry", "giveback_atr_from_entry",
    "distance_from_mfe_atr", "remaining_mfe_atr",
    "remaining_mae_before_next_mfe_atr",
}


def _downcast_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Reduce memory footprint for a ~30-45M row combined atlas.
    Timestamps and prices stay at full precision (int64/float64);
    only the small-magnitude ATR-ratio diagnostic columns go to
    float32, and repeated string columns become 'category'."""
    for c in _FLOAT32_SAFE_COLS:
        if c in df.columns:
            df[c] = df[c].astype("float32")
    for c in ("direction",):
        if c in df.columns:
            df[c] = df[c].astype("int8")
    for c in ("terminal_weakness_label", "population"):
        if c in df.columns:
            df[c] = df[c].astype("category")
    for c in ("eventual_new_mfe", "eventual_recovery_to_prior_mfe",
                 "eventual_opposite_flip"):
        if c in df.columns:
            df[c] = df[c].astype("bool")
    return df


def build_atlas(work_root: Path, population_label: str,
                    years: list[int] | None = None) -> pd.DataFrame:
    """work_root: e.g. studies/f2_confirmed_exit_management/_work/nt_raw
    Reads <work_root>/<year>/{trades,checkpoints}.parquet for each year
    found, labels each trade's checkpoint path, and returns a single
    concatenated DataFrame with a globally-unique trade_id (year-offset)."""
    year_dirs = sorted(
        [p for p in work_root.iterdir() if p.is_dir() and p.name.isdigit()],
        key=lambda p: int(p.name))
    if years is not None:
        year_dirs = [p for p in year_dirs if int(p.name) in years]

    all_labeled = []
    for yd in year_dirs:
        year = int(yd.name)
        trades_p, cp_p = yd / "trades.parquet", yd / "checkpoints.parquet"
        if not trades_p.exists() or not cp_p.exists():
            print(f"  [{year}] skip -- missing trades/checkpoints parquet")
            continue
        trades = pd.read_parquet(trades_p)
        cps = pd.read_parquet(cp_p)
        if len(trades) == 0 or len(cps) == 0:
            print(f"  [{year}] skip -- empty trades/checkpoints")
            continue

        # Global trade_id: year-offset (assumes < 1,000,000 trades/year)
        trades = trades.copy()
        cps = cps.copy()
        trades["global_trade_id"] = year * 1_000_000 + trades["trade_id"]
        cps["global_trade_id"] = year * 1_000_000 + cps["trade_id"]

        trade_meta = trades.set_index("global_trade_id")[
            ["opposite_flip_ts", "exit_reason"]]

        labeled_groups = []
        for gtid, g in cps.groupby("global_trade_id", sort=False):
            g = _label_one_trade(g)
            g["global_trade_id"] = gtid
            labeled_groups.append(g)
        year_labeled = pd.concat(labeled_groups, ignore_index=True)

        year_labeled = year_labeled.merge(
            trade_meta, left_on="global_trade_id", right_index=True,
            how="left")
        year_labeled["eventual_opposite_flip"] = (
            year_labeled["exit_reason"] == "opposite_flip")
        year_labeled["population"] = population_label
        year_labeled = year_labeled.drop(columns=["trade_id"]).rename(
            columns={"global_trade_id": "trade_id"})
        year_labeled = year_labeled.drop(columns=["exit_reason"])
        year_labeled = _downcast_dtypes(year_labeled)
        all_labeled.append(year_labeled)
        print(f"  [{year}] labeled {len(trades):,} trades, "
                 f"{len(year_labeled):,} checkpoint rows")

    if not all_labeled:
        return pd.DataFrame(columns=REQUIRED_ATLAS_COLUMNS)
    atlas = pd.concat(all_labeled, ignore_index=True)
    missing = [c for c in REQUIRED_ATLAS_COLUMNS if c not in atlas.columns]
    assert not missing, f"Atlas missing required columns: {missing}"
    return atlas[REQUIRED_ATLAS_COLUMNS
                    + [c for c in atlas.columns
                          if c not in REQUIRED_ATLAS_COLUMNS]]


def integrity_report(atlas: pd.DataFrame) -> dict:
    """Checks mandated by the study spec's Phase 1 requirements."""
    out = {}
    if len(atlas) == 0:
        return {"n_rows": 0}
    out["n_rows"] = int(len(atlas))
    out["n_trades"] = int(atlas["trade_id"].nunique())
    out["n_checkpoint_before_entry"] = int(
        (atlas["checkpoint_ts"] < atlas["entry_ts"]).sum())
    out["n_negative_mfe"] = int((atlas["mfe_atr_from_entry"] < -1e-9).sum())
    out["n_negative_mae"] = int((atlas["mae_atr_from_entry"] < -1e-9).sum())
    out["n_negative_giveback"] = int(
        (atlas["giveback_atr_from_entry"] < -1e-9).sum())
    # checkpoint after terminal opposite flip: only meaningful for rows
    # where the trade actually terminated via opposite flip
    of_rows = atlas[atlas["opposite_flip_ts"].notna()]
    if len(of_rows):
        out["n_checkpoint_after_opposite_flip"] = int(
            (of_rows["checkpoint_ts"] > of_rows["opposite_flip_ts"]
                + 5_000_000_000).sum())  # 5s tolerance for exit-fill lag
    else:
        out["n_checkpoint_after_opposite_flip"] = 0
    out["terminal_label_counts"] = (
        atlas["terminal_weakness_label"].value_counts().to_dict())
    return out
