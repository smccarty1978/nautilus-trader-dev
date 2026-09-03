"""NEW ATTACK N3 (pass 03): the C-B fix measures the strict-branch gap as
`horizon_end - prev_ts > max_gap`. When `horizon_seconds <= max_gap_seconds` that span can NEVER
exceed max_gap, so a tape that observes NOTHING inside the horizon still resolves through the
horizon-expiry policy. Also probes the first_bar_at_or_after mirror and the entry-adjacent case
where prev_ts is still the entry instant."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a8_gap_precedence import bar, run_kernel, run_oracle, NS, T0  # noqa

res = []


def probe(case, expected, *, note="", **kw):
    k = run_kernel(**kw)
    o = run_oracle(**{x: y for x, y in kw.items() if x != "same_bar"})
    agree = (k["disposition"] == o["disposition"]) and ((k["censor_reason"] or None) == (o["censor_reason"] or None))
    got = (k["disposition"], k["censor_reason"] or None)
    ok = got == expected and agree
    out = (f"kernel={k['disposition']}/{k['censor_reason']} oracle={o['disposition']}/{o['censor_reason']} "
           f"parity={agree} expected={expected} {note}")
    res.append({"case": case, "outcome": out, "verdict": "BLOCKED" if ok else "BYPASSED"})
    print(f"[{'BLOCKED' if ok else 'BYPASSED'}] {case}\n    {out}")


# Entry bar closes at T0+1s (its ts_event = T0 -> entry_ts = T0). The next observation the tape
# offers is 400s later. max_gap = 30s.
entry = bar(T0 + 1 * NS, 100.0, 100.0, 100.0, 100.0)
far = bar(T0 + 400 * NS, 100.0, 100.0, 100.0, 100.0)

# --- N3a: horizon 10s <= max_gap 30s. Nothing at all is observed inside the horizon. ---
probe("N3a strict, horizon 10s <= max_gap 30s, no observation inside the horizon, expiry=negative",
      ("CENSORED", "GAP"), horizon_s=10, expiry="negative", end_rule="strict", max_gap_s=30,
      bars=[entry, far], session_close=None,
      note="(unobserved span entry->next bar = 399s; horizon_end - prev_ts = 10s <= max_gap)")

probe("N3a' same tape with expiry=censor (censoring taxonomy: GAP vs TIMEOUT)",
      ("CENSORED", "GAP"), horizon_s=10, expiry="censor", end_rule="strict", max_gap_s=30,
      bars=[entry, far], session_close=None)

# --- N3b: first_bar_at_or_after mirror at the same parameters ---
probe("N3b first_bar_at_or_after, horizon 10s <= max_gap 30s, same tape, expiry=negative",
      ("CENSORED", "GAP"), horizon_s=10, expiry="negative", end_rule="first_bar_at_or_after",
      max_gap_s=30, bars=[entry, far], session_close=None)

# --- N3c: control, horizon 61s > max_gap 30s (the case pass 02 fixed) ---
probe("N3c control strict, horizon 61s > max_gap 30s, same tape (the C-B case)",
      ("CENSORED", "GAP"), horizon_s=61, expiry="negative", end_rule="strict", max_gap_s=30,
      bars=[entry, far], session_close=None)

# --- N3d: horizon exactly == max_gap (boundary) ---
probe("N3d strict, horizon 30s == max_gap 30s, no observation inside the horizon",
      ("CENSORED", "GAP"), horizon_s=30, expiry="negative", end_rule="strict", max_gap_s=30,
      bars=[entry, far], session_close=None)

# --- N3e: horizon 31s == max_gap+1 (just over) ---
probe("N3e strict, horizon 31s = max_gap+1s, no observation inside the horizon",
      ("CENSORED", "GAP"), horizon_s=31, expiry="negative", end_rule="strict", max_gap_s=30,
      bars=[entry, far], session_close=None)

# --- N3f: a dense in-horizon tape at horizon 10s is a genuine expiry (must NOT be a gap) ---
dense = [entry] + [bar(T0 + s * NS, 100.0, 100.0, 100.0, 100.0) for s in range(2, 14)]
probe("N3f control: dense 1s tape through a 10s horizon, expiry=negative -> genuine NEGATIVE",
      ("NEGATIVE", None), horizon_s=10, expiry="negative", end_rule="strict", max_gap_s=30,
      bars=dense, session_close=None)

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("n3_results.json").write_text(json.dumps(res, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] == "BYPASSED"], indent=1))
