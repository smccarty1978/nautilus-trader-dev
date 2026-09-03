"""A8 (CRIT-9): resolution precedence SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY,
exercised on the real kernel (host/outcomes.LabelOutcomeKernel) and the independent oracle
(target_replay_oracle.replay) over the same sparse tapes."""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from research_workflow.host.interfaces import BarView  # noqa
from research_workflow.host.outcomes import BarrierArm, LabelOutcomeContract, LabelOutcomeKernel  # noqa
from research_workflow.target_replay_oracle import replay  # noqa

NS = 1_000_000_000
res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})


class Sess:
    def __init__(self, close):
        self.close = close

    def in_session(self, ts):
        return True

    def session_close(self, ts):
        return self.close


def bar(ts_close, o, h, l, c, dur=NS):
    return BarView(stream="x", ts_event=ts_close - dur, ts_init=ts_close, open=o, high=h, low=l, close=c, volume=1.0)


T0 = 1_000_000 * NS


def run_kernel(*, horizon_s, expiry, end_rule, max_gap_s, bars, session_close, atr=1.0, fav=1.0, adv=1.0,
               same_bar="ambiguous_censor"):
    arm = BarrierArm(id="a", favorable_atr=fav, adverse_atr=adv, horizon_ns=horizon_s * NS, expiry=expiry, prefix="a")
    c = LabelOutcomeContract(kernel="barrier", direction_ref="d", atr_ref="atr", entry_reference="next_bar_open",
                             session_end_censoring=session_close is not None,
                             max_gap_ns=(max_gap_s * NS if max_gap_s is not None else None),
                             same_bar_rule=same_bar, horizon_end_rule=end_rule, arms=(arm,), primary_arm="a")
    k = LabelOutcomeKernel(c, Sess(session_close))
    k.open({"observation_ts": T0}, T0, 1, atr)
    for b in bars:
        k.on_bar(b)
    k.finalize()
    rows = k.drain_rows()
    r = rows[0]
    # the kernel emits LEGACY disposition names; normalise to the oracle's vocabulary
    unlegacy = {"LABELED_POSITIVE": "POSITIVE", "LABELED_NEGATIVE": "NEGATIVE", "CENSORED": "CENSORED"}
    return {"disposition": unlegacy.get(r["disposition"], r["disposition"]),
            "label": r["target_flip_within_horizon"], "censor_reason": r["censor_reason"]}


def run_oracle(*, horizon_s, expiry, end_rule, max_gap_s, bars, session_close, atr=1.0, fav=1.0, adv=1.0):
    contract = {"primitive": "ordered_barrier",
                "required_forward_outcomes": [{
                    "id": "fo", "entry_reference": "next_bar_open",
                    "session_end_censoring": session_close is not None,
                    "max_gap_seconds": max_gap_s,
                    "ordered_barriers": [{"id": "a", "favorable_atr": fav, "adverse_atr": adv,
                                          "horizon_seconds": horizon_s, "horizon_end_rule": end_rule,
                                          "horizon_expiry_policy": ("negative" if expiry == "negative" else "censor")}],
                }]}
    candidate = {"observation_ts": T0, "atr": atr, "direction": 1, "session_close_ts": session_close}
    events = [{"ts": b.ts_init, "open": b.open, "high": b.high, "low": b.low} for b in bars]
    return replay(contract, candidate, events)


def both(name, expected, *, allow=None, **kw):
    k = run_kernel(**kw)
    o = run_oracle(**{x: y for x, y in kw.items() if x != "same_bar"})
    agree = (k["disposition"] == o["disposition"] and (k["censor_reason"] or None) == (o["censor_reason"] or None))
    ok = k["disposition"] == expected[0] and (k["censor_reason"] or None) == expected[1] and agree
    if allow and (k["disposition"], k["censor_reason"]) in allow:
        ok = agree
    rec(name, "kernel=%s/%s oracle=%s/%s parity=%s expected=%s"
        % (k["disposition"], k["censor_reason"], o["disposition"], o["censor_reason"], agree, expected),
        "BLOCKED" if ok else "BYPASSED")
    return k, o


# entry bar at T0+1s (open 100), no touches (barriers at 101 / 99)
FLAT = lambda ts: bar(ts, 100.0, 100.2, 99.8, 100.0)

# ---------------- a) post-horizon bar beyond max_gap -> CENSORED/GAP ----------------
bars_a = [FLAT(T0 + 1 * NS), FLAT(T0 + 5 * NS), FLAT(T0 + 500 * NS)]
both("A8a first_bar_at_or_after, post-horizon bar beyond max_gap -> GAP",
     ("CENSORED", "GAP"), horizon_s=60, expiry="censor", end_rule="first_bar_at_or_after",
     max_gap_s=30, bars=bars_a, session_close=T0 + 100_000 * NS)
both("A8a' same tape with expiry=negative (must still be GAP, never a manufactured NEGATIVE)",
     ("CENSORED", "GAP"), horizon_s=60, expiry="negative", end_rule="first_bar_at_or_after",
     max_gap_s=30, bars=bars_a, session_close=T0 + 100_000 * NS)

# ---------------- b) expiry negative + session-boundary gap -> CENSORED/SESSION_END ----------------
SC = T0 + 120 * NS
bars_b = [FLAT(T0 + 1 * NS), FLAT(T0 + 5 * NS), FLAT(T0 + 400 * NS)]   # first post-horizon bar is past SC
both("A8b first_bar_at_or_after + expiry=negative, first post-horizon bar past the session close -> SESSION_END",
     ("CENSORED", "SESSION_END"), horizon_s=60, expiry="negative", end_rule="first_bar_at_or_after",
     max_gap_s=30, bars=bars_b, session_close=SC)
both("A8b' same, expiry=censor", ("CENSORED", "SESSION_END"), horizon_s=60, expiry="censor",
     end_rule="first_bar_at_or_after", max_gap_s=30, bars=bars_b, session_close=SC)

# ---------------- c) strict is unchanged ----------------
bars_c = [FLAT(T0 + 1 * NS), FLAT(T0 + 30 * NS), FLAT(T0 + 61 * NS)]
both("A8c strict, dense tape, no touch, expiry=censor -> TIMEOUT",
     ("CENSORED", "TIMEOUT"), horizon_s=60, expiry="censor", end_rule="strict", max_gap_s=30,
     bars=bars_c, session_close=T0 + 100_000 * NS)
both("A8c' strict, dense tape, no touch, expiry=negative -> NEGATIVE",
     ("NEGATIVE", None), horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=30,
     bars=bars_c, session_close=T0 + 100_000 * NS)

# ---------------- ADJACENT 1: strict + a data gap STRADDLING the horizon end ----------------
# last observation at T0+10s, next bar at T0+400s; horizon ends at T0+61s. The interval
# (T0+10s, T0+61s] is NEVER observed, yet the horizon "expires".
bars_d = [FLAT(T0 + 1 * NS), FLAT(T0 + 10 * NS), FLAT(T0 + 400 * NS)]
k, o = both("A8-ADJ1 strict + expiry=negative + a max_gap-exceeding gap straddling the horizon end",
            ("CENSORED", "GAP"), horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=30,
            bars=bars_d, session_close=T0 + 100_000 * NS)
both("A8-ADJ1' same tape with expiry=censor", ("CENSORED", "GAP"), horizon_s=60, expiry="censor",
     end_rule="strict", max_gap_s=30, bars=bars_d, session_close=T0 + 100_000 * NS)

# ---------------- ADJACENT 2: gap exactly == max_gap ----------------
bars_e = [FLAT(T0 + 1 * NS), FLAT(T0 + 31 * NS), FLAT(T0 + 61 * NS)]   # each step exactly 30s
both("A8-ADJ2 gap exactly == max_gap (30s) is NOT a gap (strict >)",
     ("CENSORED", "TIMEOUT"), horizon_s=60, expiry="censor", end_rule="strict", max_gap_s=30,
     bars=bars_e, session_close=T0 + 100_000 * NS)
bars_e2 = [FLAT(T0 + 1 * NS), FLAT(T0 + 32 * NS), FLAT(T0 + 61 * NS)]  # 31s > 30s
both("A8-ADJ2' gap of max_gap+1s IS a gap", ("CENSORED", "GAP"), horizon_s=60, expiry="censor",
     end_rule="strict", max_gap_s=30, bars=bars_e2, session_close=T0 + 100_000 * NS)

# ---------------- ADJACENT 3: a bar with ts EXACTLY == horizon_end ----------------
# entry at T0+1s -> entry_ts = T0; horizon end = T0+60s. A bar closing exactly at T0+60s
# that TOUCHES the favorable barrier must be POSITIVE (the closing bar is touch-eligible).
bars_f = [FLAT(T0 + 1 * NS), bar(T0 + 60 * NS, 100.0, 101.5, 99.9, 101.0)]
both("A8-ADJ3 a bar closing EXACTLY at the horizon end is touch-eligible -> POSITIVE",
     ("POSITIVE", None), horizon_s=60, expiry="censor", end_rule="strict", max_gap_s=300,
     bars=bars_f, session_close=T0 + 100_000 * NS)

# ---------------- ADJACENT 4: the ENTRY bar itself is beyond max_gap from T ----------------
bars_g = [FLAT(T0 + 500 * NS), FLAT(T0 + 501 * NS)]
k4 = run_kernel(horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=30, bars=bars_g,
                session_close=T0 + 100_000 * NS)
o4 = run_oracle(horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=30, bars=bars_g,
                session_close=T0 + 100_000 * NS)
rec("A8-ADJ4 the ENTRY bar itself is 500s after T (far beyond max_gap=30s)",
    "kernel=%s/%s oracle=%s/%s -- the gap from T to the entry bar is not evaluated by either side"
    % (k4["disposition"], k4["censor_reason"], o4["disposition"], o4["censor_reason"]),
    "BLOCKED" if (k4["disposition"] == o4["disposition"] and k4["censor_reason"] == o4["censor_reason"]
                  and k4["disposition"] == "CENSORED") else "BYPASSED")

# ---------------- ADJACENT 5: session close BETWEEN the last in-horizon bar and the horizon end, strict ----------------
bars_h = [FLAT(T0 + 1 * NS), FLAT(T0 + 10 * NS), FLAT(T0 + 400 * NS)]
both("A8-ADJ5 strict, expiry=negative, session close at T0+30s (before the horizon end)",
     ("CENSORED", "SESSION_END"), horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=3000,
     bars=bars_h, session_close=T0 + 30 * NS)

# ---------------- ADJACENT 6: the tape simply ENDS before the horizon (DATA_END) ----------------
bars_i = [FLAT(T0 + 1 * NS), FLAT(T0 + 10 * NS)]
k6 = run_kernel(horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=3000, bars=bars_i,
                session_close=T0 + 100_000 * NS)
o6 = run_oracle(horizon_s=60, expiry="negative", end_rule="strict", max_gap_s=3000, bars=bars_i,
                session_close=T0 + 100_000 * NS)
rec("A8-ADJ6 the tape ENDS before the horizon end, expiry=negative (kernel DATA_END vs oracle policy)",
    "kernel=%s/%s oracle=%s/%s" % (k6["disposition"], k6["censor_reason"], o6["disposition"], o6["censor_reason"]),
    "BLOCKED" if (k6["disposition"] == o6["disposition"] and k6["censor_reason"] == o6["censor_reason"]) else "BYPASSED")

print(json.dumps(res, indent=1))
Path(__file__).with_name("a8_results.json").write_text(json.dumps({"results": res}, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] != "BLOCKED"], indent=1))
