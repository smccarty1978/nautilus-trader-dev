"""Gates V1-V13 and the computed verdict (SPEC section 8.1).

The verdict is derived from the gate table and the measured quantities. An
unrun gate is a FAILURE, not a pass.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from studies.p90_conditional_losing_5s_exit.implementation.policy import (
    BASELINE_LABELS, CONDITIONAL_LABELS, LOSING_5S_FLIP_EXIT,
)

ARMED_REQUIRED = 8950
ALIGNED_REQUIRED = 8379
SEALED_YEAR = 2026


def _gate(name, expected, observed, ok, note=""):
    return {"gate": name, "expected": expected, "observed": observed,
            "pass": bool(ok), "note": note}


def run_gates(*, arms, lineage, frames: dict, flips: pl.DataFrame,
              placebo_meta: dict) -> list[dict]:
    g: list[dict] = []
    b100, c100 = frames["BASELINE_1.00"], frames["COND_1.00"]
    b075, c075 = frames["BASELINE_0.75"], frames["COND_0.75"]

    g.append(_gate("V1_armed_population", ARMED_REQUIRED, arms.height,
                   arms.height == ARMED_REQUIRED))
    g.append(_gate("V2_full_lifecycle_parity_exact", True,
                   lineage["checks"]["full_lifecycle_parity_exact"]["observed"],
                   bool(lineage["checks"]["full_lifecycle_parity_exact"]["observed"]),
                   "baseline reproduces walks.py::continuation_label on every arm"))
    g.append(_gate("V3_predecessor_entry_population", ALIGNED_REQUIRED,
                   lineage["checks"]["aligned_entries"]["observed"],
                   lineage["checks"]["aligned_entries"]["match"]))
    g.append(_gate("V4_walk_a_mae_references", True,
                   lineage["checks"]["walk_a_confirming_mae"]["match"],
                   lineage["checks"]["walk_a_confirming_mae"]["match"]))

    for name, f in frames.items():
        e = f.filter(pl.col("entered"))
        allowed = CONDITIONAL_LABELS if ("COND" in name or "PLACEBO" in name) else BASELINE_LABELS
        labels = set(e["outcome"].unique().to_list())
        g.append(_gate(f"V5_{name}_outcome_set", sorted(allowed), sorted(labels),
                       labels <= allowed,
                       "a label outside the frozen set means confirmation leaked in"))
        bad = int((e["entry_ns"].to_numpy() <= e["arm_ns"].to_numpy()).sum())
        g.append(_gate(f"V8_{name}_entry_after_decision", 0, bad, bad == 0))
        g.append(_gate(f"V12_{name}_positive_hold", 0,
                       int((e["hold_s"].to_numpy() <= 0).sum()),
                       int((e["hold_s"].to_numpy() <= 0).sum()) == 0))

    # V6: baseline and conditional differ ONLY by the rule. Same entries, and
    # every trade whose conditional outcome is not the new label must be
    # bit-identical to its baseline.
    for stop, b, c in (("1.00", b100, c100), ("0.75", b075, c075)):
        eb = b.filter(pl.col("entered")).select("regime_id", "outcome", "net_atr")
        ec = c.filter(pl.col("entered")).select("regime_id", "outcome", "net_atr")
        same_ids = set(eb["regime_id"]) == set(ec["regime_id"])
        j = eb.join(ec, on="regime_id", how="inner", suffix="_c")
        untouched = j.filter(pl.col("outcome_c") != LOSING_5S_FLIP_EXIT)
        drift = int((np.abs(untouched["net_atr_c"].to_numpy()
                            - untouched["net_atr"].to_numpy()) > 1e-12).sum())
        g.append(_gate(f"V6_{stop}_differs_only_by_the_rule",
                       {"same_entries": True, "untouched_drift": 0},
                       {"same_entries": same_ids, "untouched_drift": drift},
                       same_ids and drift == 0,
                       "trades the rule did not fire on must be identical"))

    # V7: the two stop distances share an identical entry population.
    e1 = set(c100.filter(pl.col("entered"))["regime_id"].to_list())
    e2 = set(c075.filter(pl.col("entered"))["regime_id"].to_list())
    g.append(_gate("V7_stops_share_entries", 0, len(e1 ^ e2), e1 == e2))

    # V9: no conditional exit fills at or before the flip that caused it.
    for name in ("COND_1.00", "COND_0.75"):
        e = frames[name].filter(pl.col("entered")
                                & (pl.col("outcome") == LOSING_5S_FLIP_EXIT))
        fired = e.select("regime_id", "exit_ns", "fired_flip_number").join(
            flips.select("regime_id", "flip_number", "flip_ns"),
            left_on=["regime_id", "fired_flip_number"],
            right_on=["regime_id", "flip_number"], how="left")
        bad = int((fired["exit_ns"].to_numpy() <= fired["flip_ns"].to_numpy()).sum())
        g.append(_gate(f"V9_{name}_exit_after_flip", 0, bad, bad == 0,
                       "exit fills strictly after the flip bucket's close_ts"))

    # V10: the firing flip is the FIRST losing adverse flip of that trade.
    # Checked for BOTH conditional variants -- covering only the 1.00 one left
    # the 0.75 walk unverified (referred by lookahead-auditor pass 1).
    first_losing = (flips.filter(pl.col("is_losing")).sort("flip_number")
                    .group_by("regime_id").agg(first=pl.col("flip_number").first()))
    for name, frame in (("COND_1.00", c100), ("COND_0.75", c075)):
        fired = (frame.filter(pl.col("entered")
                              & (pl.col("outcome") == LOSING_5S_FLIP_EXIT))
                 .select("regime_id", "fired_flip_number")
                 .join(first_losing, on="regime_id", how="left"))
        mism = int((fired["fired_flip_number"].to_numpy()
                    != fired["first"].to_numpy()).sum())
        g.append(_gate(f"V10_{name}_fires_on_first_losing_flip", 0, mism, mism == 0,
                       "SPEC 9.5; a miss means the repeated-flip walk is broken"))

    # V11: 2026 sealed.
    years = sorted(int(y) for y in arms["entry_year"].unique().to_list())
    g.append(_gate("V11_2026_sealed", "max <= 2025", max(years),
                   max(years) < SEALED_YEAR))

    # placebo must not have used future lifetime
    g.append(_gate("V13_placebo_pooled_draws", True,
                   placebo_meta.get("counts_and_times_pooled", False),
                   bool(placebo_meta.get("counts_and_times_pooled", False)),
                   "both k and tau drawn from POOLED distributions"))
    return g


def determine_verdict(*, gates, econ: dict, deltas: dict, harvest: pl.DataFrame,
                      destruction: pl.DataFrame, confusion: pl.DataFrame,
                      by_year: pl.DataFrame, by_side: pl.DataFrame,
                      placebo_delta: dict) -> dict:
    if not gates or not all(x["pass"] for x in gates):
        return {"verdict": "ABORT_LINEAGE_FAILURE",
                "failed_gates": [x["gate"] for x in gates if not x["pass"]]}

    # the better of the two conditional variants, judged per ORIGINAL arm
    best = max(("COND_1.00", "COND_0.75"), key=lambda k: deltas[k]["delta_per_arm"])
    d = deltas[best]
    base = "BASELINE_1.00" if best == "COND_1.00" else "BASELINE_0.75"

    # AMENDMENT, 2026-08-12, recorded rather than silently applied (SPEC 8.2).
    # "Improves" requires the paired delta to be DISTINGUISHABLE FROM ZERO, not
    # merely a positive point estimate. A delta of +0.0043 ATR/arm with a CI of
    # [-0.0222, +0.0295] -- seven times wider than the estimate -- is not an
    # improvement, and treating it as one is what let the original ordering
    # return G2. This is the standard the rest of the project already applies to
    # every placebo comparison. The change makes the verdict STRICTER and moves
    # this study's answer from G2 to G4, i.e. it runs against interest.
    improves = bool(d["delta_per_arm"] > 0 and d["delta_ci_excludes_zero"])
    dd_improves = econ[best]["max_dd_atr"] < econ[base]["max_dd_atr"]

    yb = by_year.filter(pl.col("policy") == best).sort("entry_year")
    yr_base = by_year.filter(pl.col("policy") == base).sort("entry_year")
    yr_delta = (yb["exp_per_arm_net"].to_numpy()
                - yr_base["exp_per_arm_net"].to_numpy())
    years_positive = int((yr_delta > 0).sum())

    sb = by_side.filter(pl.col("policy") == best).sort("side")
    sbase = by_side.filter(pl.col("policy") == base).sort("side")
    side_delta = (sb["exp_per_arm_net"].to_numpy()
                  - sbase["exp_per_arm_net"].to_numpy())
    no_inversion = bool(len(side_delta) == 2 and (side_delta > 0).all()
                        or (side_delta < 0).all())

    beats_placebo = bool(placebo_delta.get("delta_ci_excludes_zero", False)
                         and placebo_delta.get("delta_per_arm", 0) < 0)
    # placebo_delta is (placebo - conditional): the real rule wins if that is
    # negative and its CI excludes zero.

    hrow = harvest.filter(pl.col("policy") == best).to_dicts()[0]
    crow = confusion.filter(pl.col("group") == "ALL").to_dicts()[0]
    interception_strong = (hrow["interception_pct"] >= 0.50
                           and crow["ppv"] > crow["prevalence"])

    facts = {
        "best_variant": best, "baseline": base,
        "improves_definition": ("delta > 0 AND its bootstrap CI excludes zero "
                                "(amended 2026-08-12; see validate.py)"),
        "delta_per_arm": d["delta_per_arm"],
        "delta_ci": [d["delta_ci_low"], d["delta_ci_high"]],
        "delta_ci_excludes_zero": d["delta_ci_excludes_zero"],
        "improves_per_arm": bool(improves),
        "maxdd_improves": bool(dd_improves),
        "years_positive_delta": years_positive,
        "no_side_inversion": no_inversion,
        "beats_matched_placebo": beats_placebo,
        "interception_pct": hrow["interception_pct"],
        "ppv": crow["ppv"], "prevalence": crow["prevalence"],
        "interception_strong": bool(interception_strong),
    }

    # The placebo comes FIRST, because it decides what we are allowed to
    # attribute anything to. If the rule does not separate from a matched
    # losing-state control, no finding may be credited to the 5s FLIP -- the
    # confusion matrix's PPV then describes "the trade is losing", not the
    # regime transition. G3 is a claim about the 5s signal, so it is
    # unreachable while the placebo is unbeaten; that is a property of the
    # question, not an oversight.
    facts["placebo_gates_attribution"] = True
    if not beats_placebo:
        # Only the loss STATE can be credited. Does it actually pay?
        verdict = ("G2_LOSS_STATE_WORKS_5S_FLIP_DOES_NOT" if improves
                   else "G4_NO_USEFUL_EDGE")
    elif improves and dd_improves and years_positive >= 4 and no_inversion:
        verdict = "G1_CONDITIONAL_5S_FAILURE_EXIT_WORKS"
    elif not improves and interception_strong:
        verdict = "G3_5S_INFORMATIVE_THRESHOLD_TOO_CRUDE"
    else:
        verdict = "G4_NO_USEFUL_EDGE"
    return {"verdict": verdict, "facts": facts}
