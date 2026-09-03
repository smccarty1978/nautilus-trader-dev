"""A7 (CRIT-8 / ETH): calendar session windows, early close, holiday, DST, fail-closed digests,
legacy-ETH close, and the compiler's ETH / missing-sessions-table refusals."""
from __future__ import annotations
import hashlib, json, shutil, sys, tempfile
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from research_workflow.sessions import (session_windows, build_session_table, CalendarSessionTable,  # noqa
                                        LegacySessionTable, SessionCloseUndefinedError, resolve_calendar_session_spec)
from research_workflow import dataset_v2  # noqa

CT = ZoneInfo("America/Chicago")
NS = 1_000_000_000
res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})


def ns(y, m, d, hh, mm, ss=0):
    return int(pd.Timestamp(y, m, d, hh, mm, ss, tz=CT).tz_convert("UTC").value)


def row(d, open_h, open_m, close_h, close_m, *, early=False, halt=None, prev_day=True):
    od = d
    o = int(pd.Timestamp(od.year, od.month, od.day, open_h, open_m, tz=CT).tz_convert("UTC").value)
    if prev_day:
        prev = pd.Timestamp(od) - pd.Timedelta(days=1)
        o = int(pd.Timestamp(prev.year, prev.month, prev.day, open_h, open_m, tz=CT).tz_convert("UTC").value)
    c = int(pd.Timestamp(od.year, od.month, od.day, close_h, close_m, tz=CT).tz_convert("UTC").value)
    hs, he = (None, None)
    if halt:
        hs = int(pd.Timestamp(od.year, od.month, od.day, halt[0], halt[1], tz=CT).tz_convert("UTC").value)
        he = int(pd.Timestamp(od.year, od.month, od.day, halt[2], halt[3], tz=CT).tz_convert("UTC").value)
    return {"session_date": od, "open_ns": o, "close_ns": c, "early_close": bool(early),
            "halt_start_ns": hs, "halt_end_ns": he}


# ---- normal day, early close, holiday gap, DST spring/fall, historical halt ----
days = [
    row(date(2021, 9, 15), 17, 0, 16, 0),                                   # normal
    row(date(2021, 11, 26), 17, 0, 12, 15, early=True),                     # early close (before 15:15)
    # 2021-11-25 Thanksgiving: NO ROW at all (holiday)
    row(date(2021, 3, 15), 17, 0, 16, 0),                                   # after DST spring-forward
    row(date(2021, 11, 8), 17, 0, 16, 0),                                   # after DST fall-back
    row(date(2020, 6, 10), 17, 0, 16, 0, halt=(15, 15, 15, 30)),            # pre-2021-06-28 halt
]
df = pd.DataFrame(days)

rth = session_windows(df, "RTH")
eth = session_windows(df, "ETH")
by_day = {}
for a, b in rth:
    by_day[pd.Timestamp(a, tz="UTC").tz_convert(CT).date()] = (a, b)

ok_normal = by_day[date(2021, 9, 15)] == (ns(2021, 9, 15, 8, 30), ns(2021, 9, 15, 15, 15))
rec("C8 RTH window is (08:30 CT, 15:15 CT] on a normal day",
    "%s" % (str(by_day[date(2021, 9, 15)]),), "BLOCKED" if ok_normal else "BYPASSED")

ok_early = by_day[date(2021, 11, 26)] == (ns(2021, 11, 26, 8, 30), ns(2021, 11, 26, 12, 15))
rec("C8 an early close TIGHTENS the RTH window (never widens it)",
    "%s expected close 12:15 CT" % (str(by_day[date(2021, 11, 26)]),), "BLOCKED" if ok_early else "BYPASSED")

rec("C8 a holiday (no sessions row) contributes NO window",
    "days with an RTH window: %s" % sorted(by_day), "BLOCKED" if date(2021, 11, 25) not in by_day else "BYPASSED")

# DST: the UTC offset of 08:30 CT must differ between March (CDT) and January (CST)
mar = by_day[date(2021, 3, 15)][0]
nov = by_day[date(2021, 11, 8)][0]
mar_h = pd.Timestamp(mar, tz="UTC").hour
nov_h = pd.Timestamp(nov, tz="UTC").hour
rec("C8 DST-safe: 08:30 CT maps to 13:30Z in CDT and 14:30Z in CST",
    "2021-03-15 open=%02d:00Z (CDT) 2021-11-08 open=%02d:00Z (CST)" % (mar_h, nov_h),
    "BLOCKED" if (mar_h == 13 and nov_h == 14) else "BYPASSED")

# ETH post-segment starts at the historical halt end where declared
eth_post_2020 = [w for w in eth if pd.Timestamp(w[0], tz="UTC").tz_convert(CT).date() == date(2020, 6, 10)
                 and w[0] >= ns(2020, 6, 10, 15, 0)]
rec("C8 ETH post segment starts at the declared halt_end (15:30 CT) on a pre-2021-06-28 day",
    "%s expected start %s" % (eth_post_2020, ns(2020, 6, 10, 15, 30)),
    "BLOCKED" if eth_post_2020 and eth_post_2020[0][0] == ns(2020, 6, 10, 15, 30) else "BYPASSED")

# ---- half-open attribution + no overlap ----
tbl = CalendarSessionTable(rth, name="RTH")
o, c = by_day[date(2021, 9, 15)]
rec("C8 half-open (open, close] attribution",
    "in(open)=%s in(open+1s)=%s in(close)=%s in(close+1s)=%s" % (
        tbl.in_session(o), tbl.in_session(o + NS), tbl.in_session(c), tbl.in_session(c + NS)),
    "BLOCKED" if (not tbl.in_session(o) and tbl.in_session(o + NS) and tbl.in_session(c)
                  and not tbl.in_session(c + NS)) else "BYPASSED")

# ---- legacy ETH close fails closed ----
try:
    LegacySessionTable("ETH").session_close(ns(2021, 9, 15, 20, 0))
    rec("ETH LegacySessionTable('ETH').session_close returns a value", "returned", "BYPASSED")
except SessionCloseUndefinedError as exc:
    rec("ETH LegacySessionTable('ETH').session_close fails closed", str(exc)[:180], "BLOCKED")
except Exception as exc:
    rec("ETH LegacySessionTable('ETH').session_close", type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")

# ---- ADJACENT: halt_end BEFORE rth_close -> ETH window overlapping RTH ----
bad = pd.DataFrame([row(date(2020, 6, 11), 17, 0, 16, 0, halt=(14, 0, 14, 30))])
bad_eth = session_windows(bad, "ETH")
bad_rth = session_windows(bad, "RTH")
overlap = [(e, r) for e in bad_eth for r in bad_rth if e[0] < r[1] and r[0] < e[1]]
try:
    CalendarSessionTable(bad_eth + bad_rth, name="MIX")
    combined_raises = False
except ValueError:
    combined_raises = True
rec("C8 ADJACENT: halt_end (14:30 CT) EARLIER than the 15:15 RTH close",
    "eth=%s rth=%s overlapping_pairs=%s (RTH/ETH tables are validated separately, so no overlap error is raised: %s)"
    % (bad_eth, bad_rth, overlap, not combined_raises),
    "BLOCKED" if not overlap else "BYPASSED")

# ---- ADJACENT: a session row with close_ns < open_ns ----
inverted = pd.DataFrame([{"session_date": date(2021, 9, 16),
                          "open_ns": ns(2021, 9, 16, 16, 0), "close_ns": ns(2021, 9, 16, 9, 0),
                          "early_close": False, "halt_start_ns": None, "halt_end_ns": None}])
try:
    w = session_windows(inverted, "RTH")
    we = session_windows(inverted, "ETH")
    rec("C8 ADJACENT: sessions row with close_ns < open_ns",
        "RTH windows=%s ETH windows=%s (empty means the inverted row silently yields no window)" % (w, we),
        "BLOCKED" if not w and not we else "BYPASSED")
except Exception as exc:
    rec("C8 ADJACENT: sessions row with close_ns < open_ns", type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")

# ---- fail-closed reference tables ----
CAT = Path(tempfile.mkdtemp()) / "cat"
(CAT / "reference").mkdir(parents=True)
sess_path = CAT / "reference" / "sessions.parquet"
df.to_parquet(sess_path, index=False)
sha = hashlib.sha256(sess_path.read_bytes()).hexdigest()
agg = hashlib.sha256(json.dumps({"sessions": sha}, sort_keys=True).encode()).hexdigest()
(CAT / "build_manifest.json").write_text(json.dumps({"reference_tables": {"sessions": {"sha256": sha}}}), encoding="utf-8")

try:
    out = dataset_v2.load_reference_tables(CAT, ["sessions"], agg)
    rec("G1 reference tables load with a correct digest (control)", "rows=%d" % len(out["sessions"]), "OK")
except Exception as exc:
    rec("G1 reference tables load with a correct digest (control)", type(exc).__name__ + ": " + str(exc)[:180], "UNEXPECTED_REJECT")

try:
    dataset_v2.load_reference_tables(CAT, ["sessions"], "0" * 64)
    rec("G1 aggregate reference_digest mismatch", "loaded anyway", "BYPASSED")
except Exception as exc:
    rec("G1 aggregate reference_digest mismatch", type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")

tampered = df.copy()
tampered.loc[0, "close_ns"] = int(tampered.loc[0, "close_ns"]) + 3600 * NS
tampered.to_parquet(sess_path, index=False)
try:
    dataset_v2.load_reference_tables(CAT, ["sessions"], agg)
    rec("G1 sessions.parquet bytes tampered after the manifest was written", "loaded anyway", "BYPASSED")
except Exception as exc:
    rec("G1 sessions.parquet bytes tampered after the manifest was written",
        type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")
df.to_parquet(sess_path, index=False)

try:
    dataset_v2.load_reference_tables(CAT, ["sessions", "holidays"], None)
    rec("G1 a declared table that does not exist", "loaded anyway", "BYPASSED")
except Exception as exc:
    rec("G1 a declared table that does not exist", type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")

# ADJACENT: declaring FEWER tables than the manifest built skips the aggregate check
(CAT / "reference" / "holidays.parquet").write_bytes(b"not-a-parquet")
hsha = hashlib.sha256((CAT / "reference" / "holidays.parquet").read_bytes()).hexdigest()
(CAT / "build_manifest.json").write_text(json.dumps({"reference_tables": {
    "sessions": {"sha256": sha}, "holidays": {"sha256": hsha}}}), encoding="utf-8")
try:
    dataset_v2.load_reference_tables(CAT, ["sessions"], agg)
    rec("G1 ADJACENT: declaring a SUBSET of the manifest's tables skips the aggregate-digest check",
        "loaded with the stale single-table aggregate digest %s -- no REFERENCE_DIGEST_MISMATCH" % agg[:12],
        "BYPASSED")
except Exception as exc:
    rec("G1 ADJACENT: declaring a SUBSET of the manifest's tables skips the aggregate-digest check",
        type(exc).__name__ + ": " + str(exc)[:180], "BLOCKED")

# ---- compiler refusals ----
from research_workflow.grammar import compile_study, load_spec  # noqa
GOLDEN = ROOT / "fixtures" / "golden"
from research_workflow.tests.synthetic_primitives import SYNTHETIC_BINDINGS  # noqa

TD = Path(tempfile.mkdtemp())
DS = TD / "datasets"
shutil.copytree(GOLDEN / "datasets", DS)
base_spec = (GOLDEN / "study_barrier.yaml").read_text(encoding="utf-8")


def compile_variant(name, spec_text, ds_dir=DS):
    d = TD / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.yaml").write_text(spec_text, encoding="utf-8")
    out = compile_study(load_spec(d), repo_root=ROOT, datasets_dir=ds_dir, extra_bindings=SYNTHETIC_BINDINGS)
    if out.ok:
        return True, out.plan.card()
    return False, out.gaps.to_dict()


eth_spec = base_spec.replace("  session: RTH\n", "  session: RTH\n").replace(
    "outcome:\n  kind: label", "outcome:\n  session: ETH\n  session_end: censor\n  kind: label")
ok, info = compile_variant("eth_legacy", eth_spec)
rec("C8 compiler refuses ETH session-end censoring on a LEGACY (non-calendar) dataset",
    "compiled=%s %s" % (ok, json.dumps(info)[:300]), "BYPASSED" if ok else "BLOCKED")

# dataset declaring reference_tables WITHOUT a sessions table, while the outcome censors on session end
ds = (DS / "SYN_A.yaml").read_text(encoding="utf-8")
(DS / "SYN_A.yaml").write_text(ds + "\nreference_tables: [holidays, maintenance]\nreference_digest: deadbeef\n", encoding="utf-8")
ok, info = compile_variant("no_sessions_table", base_spec)
rec("C8 compiler refuses reference_tables WITHOUT 'sessions' while the outcome censors on session close",
    "compiled=%s %s" % (ok, json.dumps(info)[:300]), "BYPASSED" if ok else "BLOCKED")
(DS / "SYN_A.yaml").write_text(ds, encoding="utf-8")

# control: unchanged golden spec still compiles
ok, info = compile_variant("control", base_spec)
rec("C8 control: the unchanged golden spec still compiles", "compiled=%s" % ok, "OK" if ok else "UNEXPECTED_REJECT")

print(json.dumps(res, indent=1))
Path(__file__).with_name("a7_results.json").write_text(json.dumps({"results": res}, indent=1, default=str))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
