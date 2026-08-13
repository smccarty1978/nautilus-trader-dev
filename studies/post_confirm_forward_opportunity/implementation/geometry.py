"""Phase 11 (placebo diagnosis) and Phase 12 (harvest geometry), per trade.

Both are *diagnostics*, and the distinction matters enough to state twice:

* The random exit is **not a strategy**. It is the instrument that showed the
  accepted natural exit is worth less than chance. Its support depends on the
  realised trade length, which is future information -- permissible for a
  benchmark, fatal for a rule. A second, **length-blind** placebo is therefore
  reported alongside: it draws an offset from the frozen dense grid without
  knowing how long the trade will live, so it is causally implementable, and any
  gap between the two is itself informative about how much of the "edge" of a
  random exit is really knowledge of the lifetime.

* Harvest geometry is **not a multi-contract simulation**. It measures whether
  the path is shaped like a ladder, and it charges a full round turn to EVERY
  unit. Per unit the cost is identical to holding full size, so the comparison
  is not tilted by the cost convention in either direction.
"""
from __future__ import annotations

import numpy as np

from studies.model_driven_entry_exit_discovery.implementation.engine import (
    COST_POINTS, NS,
)
from .engine import DENSE_OFFSETS_S, HARVEST_RUNGS, TradeForward, tag

N_PLACEBO = 20
SEED = 20260811


def _first(mask: np.ndarray) -> int:
    hit = np.flatnonzero(mask)
    return int(hit[0]) if hit.size else -1


# --------------------------------------------------------------- Phase 11

def placebo(fwd: TradeForward, rng: np.random.Generator) -> dict:
    """Random / length-blind / natural / MaxMFE, and the terminal-latency cost."""
    w = fwd.w
    ci, nat, unc = w.ci, w.nat_i, w.unc_i
    cost = COST_POINTS / w.atr

    # (a) lifetime-uniform placebo -- the predecessor's instrument, reproduced.
    if nat > ci:
        draws = rng.integers(ci, nat, size=N_PLACEBO)
    else:
        draws = np.full(N_PLACEBO, ci)
    rand_vals = np.array([w.realise(int(k), True) for k in draws])

    # (b) length-blind placebo -- draws a GRID OFFSET, not an index. It cannot
    #     know the trade's length. If the drawn offset lands past the trade's own
    #     stop-live terminal, the trade was already over: the realised outcome is
    #     the natural exit, exactly as a live rule would experience it.
    offs = rng.choice(np.array(DENSE_OFFSETS_S), size=N_PLACEBO)
    blind_vals = []
    for L in offs:
        j = w.index_at_offset(int(L))
        if j < 0 or j > nat:
            blind_vals.append(fwd.nat_ret)
        else:
            blind_vals.append(w.realise(j, True))
    blind_vals = np.array(blind_vals)

    # terminal latency: how long after the favorable peak does the exit arrive
    ev = fwd.eventual_max_mfe
    k_max = int(np.argmax(w.run_mfe[:unc + 1] >= ev - 1e-12))
    k_max_nat = int(np.argmax(w.run_mfe[:nat + 1] >= fwd.nat_max_mfe - 1e-12))

    return {
        "n_placebo_draws": N_PLACEBO,
        "random_exit_return_atr": float(rand_vals.mean()),
        "random_exit_return_sd": float(rand_vals.std(ddof=0)),
        "blind_exit_return_atr": float(blind_vals.mean()),
        "opposing_flip_return_atr": float(fwd.nat_ret),
        "opposing_flip_return_unc_atr": float(fwd.unc_ret),
        "max_mfe_atr": float(ev),
        "nat_max_mfe_atr": float(fwd.nat_max_mfe),
        "d_random_minus_flip": float(rand_vals.mean() - fwd.nat_ret),
        "d_blind_minus_flip": float(blind_vals.mean() - fwd.nat_ret),
        "d_maxmfe_minus_random": float(ev - rand_vals.mean()),
        "d_maxmfe_minus_flip": float(ev - fwd.nat_ret),
        "net_random_atr": float(rand_vals.mean() - cost),
        "net_blind_atr": float(blind_vals.mean() - cost),
        "net_flip_atr": float(fwd.nat_ret - cost),
        "secs_maxmfe_to_unc_terminal": float((int(w.ts[unc]) - int(w.ts[k_max])) / NS),
        "secs_maxmfe_to_nat_terminal": float(
            (int(w.ts[nat]) - int(w.ts[k_max_nat])) / NS),
        "giveback_after_max_unc_atr": float(ev - fwd.unc_ret),
        "giveback_after_max_nat_atr": float(fwd.nat_max_mfe - fwd.nat_ret),
        "post_confirm_bars": int(unc - ci + 1),
    }


# --------------------------------------------------------------- Phase 12

def harvest(fwd: TradeForward) -> list[dict]:
    """Rung-by-rung ladder geometry, one row per achieved rung.

    A rung is "achieved" the first bar whose favorable extreme touches it. The
    harvest fills at the FOLLOWING bar's open -- the rung price is never
    credited, which is the single most-repeated defect in this repository's
    history (H4).
    """
    w = fwd.w
    unc, nat, ci = w.unc_i, w.nat_i, w.ci
    cost = COST_POINTS / w.atr
    rows = []
    for R in HARVEST_RUNGS:
        r = _first(w.bar_hi[:unc + 1] >= R)
        row = {
            "rung_atr": R,
            "achieved": r >= 0,
            "achieved_pre_confirm": bool(r >= 0 and r < ci),
            "stop_live_reachable": bool(r >= 0 and r <= nat),
        }
        if r < 0:
            rows.append(row)
            continue

        row["secs_confirm_to_rung"] = float((int(w.ts[r]) - w.confirm_ns) / NS)
        suffix_hi = w.bar_hi[r + 1:unc + 1]
        suffix_lo = w.bar_lo[r + 1:unc + 1]
        for step in (0.50, 1.00):
            nxt = _first(suffix_hi >= R + step) if suffix_hi.size else -1
            t = f"next_{tag(step)}"
            row[f"{t}_reached"] = nxt >= 0
            if nxt >= 0:
                row[f"{t}_secs"] = float((int(w.ts[r + 1 + nxt]) - int(w.ts[r])) / NS)
                # adverse excursion between the rung and the next rung, measured
                # DOWN FROM THE RUNG PRICE
                row[f"{t}_mae_before_atr"] = float(R - suffix_lo[:nxt + 1].min())
            else:
                row[f"{t}_secs"] = None
                row[f"{t}_mae_before_atr"] = None
        # censored companion: how far it fell after the rung when the next rung
        # never came. Reported separately so the achieved-only MAE is not read
        # as if it covered the whole population.
        row["mae_after_rung_to_terminal_atr"] = (
            float(R - suffix_lo.min()) if suffix_lo.size else 0.0)

        # ---- the two-unit hypothetical (NOT a strategy) -------------------
        harvested = w.realise(r, True)
        row["harvest_unit_return_atr"] = float(harvested)
        # (a) retained unit holds to the accepted stop-live natural exit
        ret_a = fwd.nat_ret
        # (b) retained unit's stop moves to entry once the rung is taken
        be = _first(suffix_lo <= 0.0) if suffix_lo.size else -1
        cap_b = min(r + 1 + be, nat) if be >= 0 else nat
        ret_b = (w.realise(cap_b, True) if (be >= 0 and r + 1 + be <= nat)
                 else fwd.nat_ret)
        # (c) retained unit's stop sits at the rung level
        rk = _first(suffix_lo <= R) if suffix_lo.size else -1
        ret_c = (w.realise(r + 1 + rk, True) if (rk >= 0 and r + 1 + rk <= nat)
                 else fwd.nat_ret)
        for name, ret in (("a", ret_a), ("b", ret_b), ("c", ret_c)):
            row[f"retained_return_variant_{name}_atr"] = float(ret)
            # Per unit, two units pay two round turns and one unit pays one, so
            # the per-unit cost is identical and the comparison is cost-neutral.
            row[f"blended_net_variant_{name}_atr"] = float(
                0.5 * (harvested + ret) - cost)
        row["full_size_net_atr"] = float(fwd.nat_ret - cost)
        rows.append(row)
    return rows
