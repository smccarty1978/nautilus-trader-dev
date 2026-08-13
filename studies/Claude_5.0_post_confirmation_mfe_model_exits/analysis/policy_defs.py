"""Frozen policy grid and model-threshold contract for the post-confirmation study.

Prespecified. Do not expand after seeing results.
"""
from __future__ import annotations

# ---------------------------------------------------------------- thresholds
# Frozen model-contract thresholds, membership operator ">=".
# Source: studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/
#         thresholds.json and studies/full_trade_path_builder/config/phase_d.yaml
BULLISH_THRESHOLDS = {
    "top_10": 0.43167249785595935,
    "top_5": 0.5067081427626979,
    "top_2_5": 0.5697449423968936,
}
BEARISH_THRESHOLDS = {
    "top_10": None,  # BEARISH_TOP_10_NOT_FROZEN
    "top_5": 0.5084619230529974,
    "top_2_5": 0.5641320087327389,
}

THRESHOLD_NAMES = ["top_10", "top_5", "top_2_5"]
# A threshold is usable for a trade direction only if the *opposing* channel has
# it frozen. SHORT opposes the bearish channel; LONG opposes the bullish channel.
THRESHOLD_SCOPE = {
    "top_10": "LONG_ONLY",  # bearish top_10 not frozen -> unsupported for SHORT
    "top_5": "ALL",
    "top_2_5": "ALL",
}

INITIAL_STOPS = [0.75, 1.00, 1.25]
PERSISTENCE_K = [1, 2, 3]

# ------------------------------------------------------------------ branch A
A1_ACTIVATIONS = [0.75, 1.00, 1.50, 2.00]
A1_FLOORS = [0.00, 0.25, 0.50]

A2_ACTIVATIONS = [0.75, 1.00, 1.50, 2.00]
A2_GIVEBACKS = [0.50, 0.75, 1.00]

A3_ACTIVATIONS = [1.00, 1.50, 2.00]
A3_RETENTIONS = [0.25, 0.50, 0.75]


def _fmt(x: float) -> str:
    return f"{x:.2f}".replace(".", "_")


def price_policies() -> list[dict]:
    """Return the 33 prespecified price-management rules (stop-independent)."""
    out: list[dict] = []
    for a in A1_ACTIVATIONS:
        for f in A1_FLOORS:
            out.append({
                "policy_id": f"A1_act{_fmt(a)}_floor{_fmt(f)}",
                "policy_family": "A1_FIXED_FLOOR",
                "activation_mfe_atr": a,
                "kind": "fixed",
                "param": f,
            })
    for a in A2_ACTIVATIONS:
        for g in A2_GIVEBACKS:
            out.append({
                "policy_id": f"A2_act{_fmt(a)}_give{_fmt(g)}",
                "policy_family": "A2_PEAK_GIVEBACK",
                "activation_mfe_atr": a,
                "kind": "giveback",
                "param": g,
            })
    for a in A3_ACTIVATIONS:
        for r in A3_RETENTIONS:
            out.append({
                "policy_id": f"A3_act{_fmt(a)}_ret{int(r*100)}",
                "policy_family": "A3_FRACTIONAL_RETENTION",
                "activation_mfe_atr": a,
                "kind": "retention",
                "param": r,
            })
    return out


# ------------------------------------------------------------- branch C reps
REPRESENTATIVE_PRICE_RULES = {
    "P1": {"kind": "fixed", "activation_mfe_atr": 1.00, "param": 0.25},
    "P2": {"kind": "fixed", "activation_mfe_atr": 1.50, "param": 0.50},
    "P3": {"kind": "giveback", "activation_mfe_atr": 1.50, "param": 0.75},
}


def all_policies() -> list[dict]:
    """Full frozen policy list (61 per initial stop)."""
    out: list[dict] = [{
        "policy_id": "BASE",
        "policy_family": "BASELINE",
        "policy_scope": "ALL",
        "activation_mfe_atr": None,
        "kind": "baseline",
        "param": None,
        "threshold_name": None,
        "persistence_k": None,
        "price_rule": None,
    }]
    for p in price_policies():
        out.append({**p, "policy_scope": "ALL", "threshold_name": None,
                    "persistence_k": None, "price_rule": None})
    for t in THRESHOLD_NAMES:
        for k in PERSISTENCE_K:
            out.append({
                "policy_id": f"B_{t}_k{k}",
                "policy_family": "B_MODEL_EXIT",
                "policy_scope": THRESHOLD_SCOPE[t],
                "activation_mfe_atr": None,
                "kind": "model_exit",
                "param": None,
                "threshold_name": t,
                "persistence_k": k,
                "price_rule": None,
            })
    for pname, prule in REPRESENTATIVE_PRICE_RULES.items():
        for t in THRESHOLD_NAMES:
            out.append({
                "policy_id": f"C1_{pname}_{t}",
                "policy_family": "C1_FIRST_EVENT_WINS",
                "policy_scope": THRESHOLD_SCOPE[t],
                "activation_mfe_atr": prule["activation_mfe_atr"],
                "kind": prule["kind"],
                "param": prule["param"],
                "threshold_name": t,
                "persistence_k": 1,
                "price_rule": pname,
            })
    for pname, prule in REPRESENTATIVE_PRICE_RULES.items():
        for t in THRESHOLD_NAMES:
            out.append({
                "policy_id": f"C2_{pname}_{t}",
                "policy_family": "C2_WARNING_ARMS_TRAIL",
                "policy_scope": THRESHOLD_SCOPE[t],
                "activation_mfe_atr": prule["activation_mfe_atr"],
                "kind": prule["kind"],
                "param": prule["param"],
                "threshold_name": t,
                "persistence_k": 1,
                "price_rule": pname,
            })
    return out


OUTCOME_CLASSES = [
    "STOPPED BEFORE CONFIRMATION",
    "STOPPED AFTER CONFIRMATION",
    "PRICE MANAGEMENT EXIT",
    "MODEL WARNING EXIT",
    "REGIME-FLIP EXIT FOR PROFIT",
    "REGIME-FLIP EXIT FOR LOSS",
    "REGIME-FLIP EXIT FLAT",
    "CENSORED / UNRESOLVED",
    "AMBIGUOUS EVENT ORDER",
]

FLAT_TOLERANCE_POINTS = 0.125
