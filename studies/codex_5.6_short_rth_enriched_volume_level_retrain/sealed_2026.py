"""Stage-2-only sealed holdout baseline dependencies. Never import in stage 1."""
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "studies/fable5_short_rth_threshold_ladder/results/w4_short_rth_threshold_ladder_manifest.json"
MANIFEST_SHA256 = "c0f9b02f65283f2acded498361e7f7cef10252e5b748ca9893bd118f5fb97443"
TRADES = ROOT / "studies/fable5_short_rth_threshold_ladder/results/w4_short_rth_threshold_ladder_results.parquet"
TRADES_SHA256 = "4c62c48fe1081229e336872b1c5f44e9b1e6d63bc7f38bdf01579e2c553c766d"
BASELINE_2026 = {"per_trade":31.010157560766373,"pf":1.1413873411764168,"dd":11876.201662272433,"prestop":.3153153153153153,"oppflip_pnl":41580.,"prestop_pnl":-31331.524840407583}
class ParityError(RuntimeError): pass
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()
def load_baseline():
    if sha(MANIFEST)!=MANIFEST_SHA256: raise ParityError("2026 baseline manifest hash")
    raw=json.loads(MANIFEST.read_text()); row=next((r for r in raw["summary"] if r["threshold"]==raw["control"] and r["basis"]=="candidate" and r["split"]=="2026"),None)
    if row is None: raise ParityError("2026 baseline row missing")
    actual={"per_trade":float(row["per_trade"]),"pf":float(row["profit_factor"]),"dd":float(row["max_closed_dd"]),"prestop":float(row["pre_align_stop_rate"]),"oppflip_pnl":float(row["opposing_flip_pnl"]),"prestop_pnl":float(row["exit_reason_pnl"]["preflip_policy_stop"])}
    if any(not np.isclose(actual[k],v,rtol=0,atol=1e-8) for k,v in BASELINE_2026.items()): raise ParityError("2026 baseline metric reconciliation")
    if not np.isclose(float(row["net_pnl"]),6884.254978490135,rtol=0,atol=1e-8): raise ParityError("2026 baseline net reconciliation")
    return BASELINE_2026
def load_trades():
    if sha(TRADES)!=TRADES_SHA256: raise ParityError("2026 baseline trades hash")
    df=pd.read_parquet(TRADES); out=df[(df.threshold==.6883498713708196)&(df.basis=="candidate")&(df.year==2026)].copy()
    if len(out)!=222 or out.regime_start_ns.duplicated().any() or not np.isclose(out.net_pnl.sum(),6884.254978490135,atol=1e-8): raise ParityError("2026 baseline trade reconciliation")
    return out
