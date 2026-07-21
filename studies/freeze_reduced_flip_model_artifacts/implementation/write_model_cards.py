"""Write model_card.md for every frozen artifact."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

STUDY = Path(__file__).resolve().parents[1]
ART, RESULTS = STUDY / "artifacts", STUDY / "results"

PURPOSE = {
    "short_bearish_flip_top25_current_reference":
        "The reduced 25-feature short-side model currently bound by the NT parity smoke. "
        "Frozen as the *current reference* so the smoke's inputs cannot drift.",
    "short_bearish_flip_top100_ref":
        "Lineage anchor for the short-side reduction: the 100-raw-feature model the "
        "25-feature model was reduced from. Kept so the reduction can be re-derived.",
    "long_bullish_flip_top25":
        "The selected long-side model (LONG_TOP25_SIGNAL_STRONG_PRESERVATION). 25 features, "
        "logistic regression - small enough to reimplement and audit directly inside NT.",
    "long_bullish_flip_top50":
        "Lineage comparison point between the long TOP25 and TOP100 models.",
    "long_bullish_flip_top100":
        "Long-side reference model (LONG_SURFACE_TOP100_SIGNAL_STRONG_PARITY) that the "
        "reduced sets were measured against.",
}

LIMITS_COMMON = """- **Predicts regime-flip probability, not trade PnL.** No economics, stop, target,
  slippage, or fill model has ever validated this model.
- **Regime-level AUC is ~0.50 (chance).** It does not tell you *which* regimes flip - it
  prices *when*, inside a regime, a flip is imminent (~35-45 s median lead). Any gate must
  read the row-level score, not a regime-aggregated one.
- **No thresholds are implied by the model.** See `threshold_manifest.json`.
- **RTH only, NQ only.** Never evaluated on ETH or another instrument."""

LIMITS_SHORT = """
- **Carries a known 1-second look-ahead** (see Causal convention). Its published metrics are
  therefore mildly optimistic. This was NOT fixed upstream; the long-side models were.
- **Status is PROVISIONAL** where marked: the source manifest says `status: "candidate"` and
  the NT parity smoke consuming it has not published a STUDY_REPORT. Do not treat its
  numbers as final."""

LIMITS_LONG = """
- **Reconstructed, not originally persisted.** No fitted object existed; this artifact is a
  refit that reproduces the source study's stored predictions bit-identically. It is
  equivalent, not the literal original object (none was ever saved).
- 2021-2024 train / 2025 select / 2026 sealed. 2026 was never used to fit, select,
  tune, threshold, or calibrate."""


def main() -> None:
    reg = {r["model_id"]: r for r in json.load(open(RESULTS / "model_registry.json"))["models"]}
    par = pd.read_csv(RESULTS / "parity_checks.csv")

    for mid, r in reg.items():
        man = json.load(open(ART / mid / "manifest.json"))
        thr = json.load(open(ART / mid / "threshold_manifest.json"))
        mp = par[par.model_id == mid]
        is_logreg = man["model_class"] == "Pipeline"

        parity_tbl = "\n".join(
            f"| `{x.check}` | {x.split} | {x.n_rows_compared:,} | {x.max_abs_diff:.3e} | "
            f"{x.tolerance:.0e} | **{x.status}** |" for x in mp.itertuples())

        coef_block = ""
        if is_logreg:
            ic = json.load(open(ART / mid / "intercept.json"))
            coef_block = f"""
## Direct audit without unpickling

This is a logistic regression, so it can be reimplemented in NT from plain numbers:

- `coefficients.csv` — per-feature coefficient, `mean_train`, `std_train`, median-impute fill
- `intercept.json` — `intercept = {ic['intercept']:.17g}`
- `score_formula.md` — the exact transform chain and formula

The formula is verified end-to-end: `parity_checks.csv` recomputes every 2025 row from
`coefficients.csv` + `intercept.json` alone and matches the model's own output
(`manual_formula` check). **You do not need to load the pickle to score this model.**
"""

        onnx_line = (f"`model.onnx` present, parity {r['onnx_status']} "
                     f"(max_abs_diff {r['onnx_max_abs_diff']:.3e} vs joblib)."
                     if r["onnx_status"] in ("PASS", "PASS_RELAXED")
                     else f"**No usable ONNX export** — conversion parity {r['onnx_status']}; "
                          f"the file was deleted rather than shipped. Use joblib.")

        card = f"""# Model card — `{mid}`

**Status: {man['status']}** · provenance `{man['provenance']}` · source of truth **joblib**

## Purpose

{PURPOSE[mid]}

## Target

`{man['target']}` — 1 if the current {'bullish' if man['direction']=='short' else 'bearish'}
RTH regime flips {man['predicted_flip_direction']} within **300 s** of `observation_time`.

- `current_regime_direction` = {man['current_regime_direction']}
- `predicted_flip_direction` = {man['predicted_flip_direction']}
- `entry_interpretation` = {man['entry_interpretation']}
- `exit_warning_interpretation` = {man['exit_warning_interpretation']}

## Population

NQ, RTH only, established regimes, 5 s checkpoint cadence.
Train {man['training_rows']:,} rows (2021-2024) · dev {man['dev_rows']:,} (2025) ·
sealed test {man['test_rows']:,} (2026).

## Feature set

`{man['feature_set_name']}` — {man['n_raw_features']} raw features,
{man['n_model_columns']} model columns.
Order is **significant** and frozen in `feature_order.csv`
(`feature_order_sha256 = {man['feature_order_sha256'][:16]}…`).

## Training split

Train 2021-2024 · select {man['dev_year']} · sealed test {man['test_year']}.
Selected on {man['selected_on']} by: {man['selected_metric']}.

## Selected model

`{man['model_class']}`{' (Pipeline: ' + ' → '.join(man['pipeline_steps']) + ')' if man.get('pipeline_steps') else ''}
Hyperparameters: `{json.dumps(man['hyperparameters'])}`
Calibration: {man['calibration_method'] or 'none (raw `predict_proba`)'}
Scoring: `{man['score_method']}`

## Validation metrics

| | 2025 (dev) | 2026 (sealed) |
|---|---:|---:|
| AUC | {r['2025_auc']} | {r['2026_auc']} |
| Top-decile flip rate | {r['2025_top_decile_flip']} | {r['2026_top_decile_flip']} |

Recomputed from this artifact's own `score_reference_*.parquet`.

## Reproducibility / parity

| check | split | rows | max_abs_diff | tol | status |
|---|---|---:|---:|---:|---|
{parity_tbl}

ONNX: {onnx_line}
{coef_block}
## Thresholds

`threshold_status = {thr['threshold_status']}`.
{('Copied verbatim from `' + str(thr['threshold_source']) + '`; top-5% = '
  + repr(thr['top5_cutoff']) + ', top-2.5% = ' + repr(thr['top2p5_cutoff'])
  + '. ' + thr.get('not_provided_note', ''))
 if thr['threshold_status'] != 'NOT_SELECTED'
 else 'No thresholds have been selected for this model. ' + thr.get('note', '')}

Thresholds are frozen **separately** from the model and were never recomputed here.

## Known limitations

{LIMITS_COMMON}{LIMITS_SHORT if man['direction'] == 'short' else LIMITS_LONG}

## Causal convention

{man['causal_convention']}

## How to load

```python
import joblib, pandas as pd
model = joblib.load("{('artifacts/' + mid + '/model.joblib')}")
order = pd.read_csv("{('artifacts/' + mid + '/feature_order.csv')}")["feature_name"].tolist()
```

> **Trusted-local only.** `joblib`/`pickle` executes code on load. Load this file only from
> this repository, never from an untrusted source.

## How to score

```python
scores = model.predict_proba(df[order])[:, 1]   # positive_class_index = 1
```

Columns **must** be passed in `feature_order.csv` order. Verify against
`score_reference_2025.parquet` before trusting a new integration.

## What not to use it for

- Do **not** use it to decide *whether* to trade a regime — regime-level AUC is chance.
- Do **not** read the probability as an expected-PnL or edge estimate.
- Do **not** apply thresholds from another model; they are model-specific.
- Do **not** use ONNX output as the source of truth — joblib is authoritative.
- Do **not** use it outside NQ RTH.

**This model predicts regime flip probability, not trade PnL.**
"""
        (ART / mid / "model_card.md").write_text(card, encoding="utf-8")
        print(f"wrote {mid}/model_card.md")


if __name__ == "__main__":
    main()
