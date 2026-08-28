"""Independent bounded target-contract replay oracle (intentionally not TargetRuntime)."""
from __future__ import annotations
from typing import Mapping, Iterable

def replay(contract: Mapping, candidate: Mapping, events: Iterable[Mapping]) -> dict:
    primitive=contract.get("primitive")
    if primitive != "ordered_barrier":
        raise ValueError(f"ORACLE_UNKNOWN_TARGET_PRIMITIVE: {primitive!r}")
    start,end=int(candidate["observation_ts"]),int(candidate["horizon_end_ts"])
    if candidate.get("session_close_ts") is not None and end>int(candidate["session_close_ts"]):
        return {"disposition":"CENSORED","label":None,"censor_reason":"SESSION_END"}
    d=int(candidate["direction"]); entry=float(candidate["entry_price"]); atr=float(candidate["atr"])
    good=entry+d*float(candidate["favorable_atr"])*atr; bad=entry-d*float(candidate["adverse_atr"])*atr
    for event in events:
        ts=int(event["ts"])
        if ts<=start or ts>end: continue
        if event.get("gap"): return {"disposition":"CENSORED","label":None,"censor_reason":"GAP"}
        hi,lo=float(event["high"]),float(event["low"])
        hg=hi>=good if d>0 else lo<=good; hb=lo<=bad if d>0 else hi>=bad
        if hg and hb:return {"disposition":"CENSORED","label":None,"censor_reason":"AMBIGUOUS_SAME_BAR_TOUCH"}
        if hg:return {"disposition":"POSITIVE","label":1,"censor_reason":None}
        if hb:return {"disposition":"NEGATIVE","label":0,"censor_reason":None}
    return {"disposition":"NEGATIVE","label":0,"censor_reason":None}
