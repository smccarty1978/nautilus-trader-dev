"""Self-test for the foundation: registry + aggregator + engine.

Mandatory before snapshot/strategy code. Tests:

  T1. Registry rejects non-monotonic updates
  T2. Registry audit_provenance raises on close_ts > decision_ts
  T3. Aggregator never closes a bucket without a NEXT-bucket bar
  T4. Engine writes to registry on bucket close, not before
  T5. Boundary 09:01: 3m/5m have NOT closed since 09:00 — registry
      should hold the 08:57 (3m) and 08:55 (5m) buckets, NOT the
      09:00 in-progress ones. audit_provenance(09:01) passes for
      08:57 and 08:55, but would FAIL if a 09:00 close had leaked.
  T6. Boundary 09:04: 3m bucket [09:00-09:03] should be in registry
      AT decision_ts >= 09:03; in-progress 09:03 bucket NOT.
      5m [09:00-09:05] still open, so registry holds 08:55-09:00.
  T7. Boundary 09:05: 5m bucket [09:00-09:05] is closed; arrives
      in registry only when next 1s bar (in 09:05-09:10) fires the
      callback. At decision_ts EXACTLY 09:05, audit accepts the
      08:55-09:00 bar (already closed) but only after the next bar
      arrives the 09:00-09:05 will appear.
  T8. CompletedBarState is frozen (immutable)
  T9. End-to-end micro-feed: feed 1s bars from 08:54:00 to 09:05:30
      and assert exactly the expected close_ts in registry at each
      moment.

If any test fails the foundation is broken; do not proceed to
snapshot/strategy code.
"""

from __future__ import annotations
import os, sys
from pathlib import Path

# Repo root on path
_repo_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_repo_root))
os.chdir(_repo_root)

import pandas as pd
import pytz

from collectors.collector_v2.registry import (
    CompletedBarRegistry, CompletedBarState, SUPPORTED_TIMEFRAMES,
)
from collectors.collector_v2.aggregator import (
    TimeframeAggregator, BUCKET_NS_30S, BUCKET_NS_1M,
    BUCKET_NS_3M, BUCKET_NS_5M, TIMEFRAME_TO_BUCKET_NS,
)
from collectors.collector_v2.regime_engine import RegimeStateEngine
from utils.causality import CausalityViolation


CT = pytz.timezone("America/Chicago")


def ts(label: str) -> int:
    """Convert 'HH:MM:SS' (assumed CT 2024-01-08) to UTC ns."""
    dt_ct = pd.Timestamp(f"2024-01-08 {label}", tz=CT)
    return int(dt_ct.value)


def make_state(tf: str, close_ts: int, regime: int = 1) -> CompletedBarState:
    bucket = TIMEFRAME_TO_BUCKET_NS[tf]
    open_ts = close_ts - bucket
    return CompletedBarState(
        timeframe=tf, open_ts=open_ts, close_ts=close_ts,
        open=100.0, high=101.0, low=99.0, close=100.5, volume=1.0,
        regime=regime, bars_in_regime=1, atr=1.0,
        ema3_h=100.5, ema9_h=100.5,
        ema3_l=99.5, ema9_l=99.5,
    )


def t1_registry_monotonic():
    print("T1. Registry rejects non-monotonic updates ...", end=" ")
    reg = CompletedBarRegistry()
    s1 = make_state("1m", ts("09:00:00") + BUCKET_NS_1M)
    s2 = make_state("1m", ts("09:01:00") + BUCKET_NS_1M)
    reg.update("1m", s1)
    reg.update("1m", s2)
    # Try to go backwards
    try:
        reg.update("1m", s1)
        print("FAIL — accepted backward update")
        return False
    except ValueError as e:
        if "Non-monotonic" not in str(e):
            print(f"FAIL — wrong error: {e}")
            return False
    print("ok")
    return True


def t2_audit_raises():
    print("T2. audit_provenance raises on close > decision ...",
            end=" ")
    reg = CompletedBarRegistry()
    decision_ts = ts("09:01:00")
    # Bar that closes AFTER decision (would be a leak)
    bad = make_state("5m", decision_ts + 1)
    reg.update("5m", bad)
    try:
        reg.audit_provenance(decision_ts)
        print("FAIL — audit accepted future-closing bar")
        return False
    except CausalityViolation as e:
        if "PROVENANCE VIOLATION" not in str(e):
            print(f"FAIL — wrong error: {e}")
            return False
    # Now move decision_ts forward — should pass
    reg.audit_provenance(decision_ts + 1)
    print("ok")
    return True


def t3_aggregator_never_closes_partial():
    print("T3. Aggregator never closes a bucket without next bar ...",
            end=" ")
    closed: list = []

    def cb(tf, bucket):
        closed.append((tf, bucket.close_ts))

    agg = TimeframeAggregator(on_bucket_closed=cb)
    # Feed three 1s bars all in same minute → no bucket should close
    base = ts("09:00:00")
    for off in (0, 1, 2):
        agg.on_1s_bar(base + off * 1_000_000_000,
                       100.0, 100.5, 99.5, 100.2, 1.0)
    if any(tf == "1m" for tf, _ in closed):
        print(f"FAIL — 1m bucket closed prematurely: {closed}")
        return False
    print("ok")
    return True


def t4_engine_writes_only_on_close():
    print("T4. Engine writes to registry only on bucket close ...",
            end=" ")
    reg = CompletedBarRegistry()
    eng_1m = RegimeStateEngine("1m", reg)
    agg = TimeframeAggregator(
        on_bucket_closed=lambda tf, b: (
            eng_1m.on_bar_closed(b) if tf == "1m" else None))
    base = ts("09:00:00")
    for off in range(60):  # 60 secs in same 1m bucket
        agg.on_1s_bar(base + off * 1_000_000_000,
                       100.0, 100.5, 99.5, 100.2, 1.0)
    if reg.get("1m") is not None:
        print(f"FAIL — registry wrote before bucket close: "
               f"{reg.get('1m')}")
        return False
    # Send one bar from next minute → should now close
    agg.on_1s_bar(base + 60 * 1_000_000_000,
                   100.0, 100.5, 99.5, 100.2, 1.0)
    s = reg.get("1m")
    if s is None:
        print("FAIL — registry empty after next-bucket bar")
        return False
    if s.close_ts != base + 60 * 1_000_000_000:
        print(f"FAIL — wrong close_ts: {s.close_ts}")
        return False
    print("ok")
    return True


def feed_window(start_ct: str, end_ct: str, agg, eng_per_tf,
                  step_s: int = 1):
    """Feed 1s bars in [start_ct, end_ct). All bars constant
    OHLCV for simplicity — we're testing TIMING, not regime."""
    start = ts(start_ct)
    end = ts(end_ct)
    cur = start
    step = step_s * 1_000_000_000
    while cur < end:
        # Aggregator dispatches to engines via the closed-bucket cb
        agg.on_1s_bar(cur, 100.0, 100.5, 99.5, 100.2, 1.0)
        cur += step


def t5_boundary_0901():
    """At decision_ts = 09:01:00 (CT), 3m/5m must reflect bars
    that closed at <= 09:01."""
    print("T5. Boundary 09:01 (3m=08:57 latest closed, "
            "5m=08:55) ...", end=" ")
    reg = CompletedBarRegistry()
    engs = {tf: RegimeStateEngine(tf, reg)
              for tf in SUPPORTED_TIMEFRAMES}

    def cb(tf, bucket):
        engs[tf].on_bar_closed(bucket)

    agg = TimeframeAggregator(on_bucket_closed=cb)
    # Feed from 08:50:00 to 09:01:30 (= 1s bar at 09:01 itself
    # is the decision moment; we feed bars up to 09:01:30 to make
    # sure prior buckets close).
    # CT bucket boundaries (UTC alignment): 30s/1m/3m/5m all use
    # UTC epoch alignment. 2024-01-08 08:55:00 CT = UTC ts; check
    # that the 5m bucket containing 09:00:00 CT is [09:00, 09:05).
    # That bucket closes at 09:05 — NOT yet at 09:01.
    # Feed bars up to but NOT including 09:01:00:
    feed_window("08:50:00", "09:01:00", agg, engs)

    decision_ts = ts("09:01:00")
    # Verify what's in registry at 09:01:00
    s_1m = reg.get("1m")
    s_3m = reg.get("3m")
    s_5m = reg.get("5m")
    # 1m bucket [09:00, 09:01) closes at 09:01 → only closes when
    # a bar from 09:01 arrives, not yet. So latest 1m close should
    # be [08:59, 09:00) → close_ts = 09:00:00.
    expected_1m_close = ts("09:00:00")
    if s_1m is None or s_1m.close_ts != expected_1m_close:
        print(f"FAIL — expected 1m close_ts={expected_1m_close} "
               f"({pd.Timestamp(expected_1m_close, tz='UTC').tz_convert(CT)}), "
               f"got {s_1m.close_ts if s_1m else None}")
        return False
    # 3m: UTC-aligned buckets at 14:51 / 14:54 / 14:57 / 15:00 UTC
    # for CT 08:51 / 08:54 / 08:57 / 09:00. Latest closed at 09:01
    # CT decision: bucket [08:57, 09:00) closes at 09:00 — that one
    # should be in registry (since we fed bars in 09:00-09:01 which
    # closed it).
    expected_3m_close = ts("09:00:00")
    if s_3m is None or s_3m.close_ts != expected_3m_close:
        print(f"FAIL — expected 3m close_ts={expected_3m_close} "
               f"({pd.Timestamp(expected_3m_close, tz='UTC').tz_convert(CT)}), "
               f"got {s_3m.close_ts if s_3m else None}")
        return False
    # 5m: bucket [09:00, 09:05) is in progress, has not closed.
    # Latest closed = [08:55, 09:00) close_ts=09:00.
    expected_5m_close = ts("09:00:00")
    if s_5m is None or s_5m.close_ts != expected_5m_close:
        print(f"FAIL — expected 5m close_ts={expected_5m_close}, "
               f"got {s_5m.close_ts if s_5m else None}")
        return False
    # Audit must pass at decision_ts
    reg.audit_provenance(decision_ts)
    # And must FAIL if we pretend decision was earlier than the
    # 5m close
    try:
        reg.audit_provenance(expected_5m_close - 1)
        print("FAIL — audit accepted decision_ts before 5m close")
        return False
    except CausalityViolation:
        pass
    print("ok")
    return True


def t6_boundary_0904():
    """At decision_ts = 09:04:00 CT, 3m bucket [09:00,09:03) closed
    at 09:03 should be present; 5m [09:00,09:05) NOT present."""
    print("T6. Boundary 09:04 (3m=09:00-09:03 closed, "
            "5m=08:55-09:00 latest) ...", end=" ")
    reg = CompletedBarRegistry()
    engs = {tf: RegimeStateEngine(tf, reg)
              for tf in SUPPORTED_TIMEFRAMES}
    agg = TimeframeAggregator(
        on_bucket_closed=lambda tf, b: engs[tf].on_bar_closed(b))
    # Feed up to 09:04:00 (decision moment)
    feed_window("08:50:00", "09:04:00", agg, engs)
    s_3m = reg.get("3m")
    s_5m = reg.get("5m")
    # 3m: latest closed = [09:00,09:03) → close_ts=09:03
    expected_3m_close = ts("09:03:00")
    if s_3m is None or s_3m.close_ts != expected_3m_close:
        print(f"FAIL — 3m expected close_ts={expected_3m_close} "
               f"({pd.Timestamp(expected_3m_close, tz='UTC').tz_convert(CT)}), "
               f"got {s_3m.close_ts if s_3m else None}")
        return False
    # 5m still [08:55, 09:00) since [09:00,09:05) not closed
    expected_5m_close = ts("09:00:00")
    if s_5m is None or s_5m.close_ts != expected_5m_close:
        print(f"FAIL — 5m expected {expected_5m_close}, "
               f"got {s_5m.close_ts if s_5m else None}")
        return False
    reg.audit_provenance(ts("09:04:00"))
    print("ok")
    return True


def t7_boundary_0905():
    """At decision_ts = 09:05:00 CT, the 5m bucket [09:00,09:05)
    closes when the FIRST 09:05+ bar arrives. Until then, only the
    08:55-09:00 bar is in registry."""
    print("T7. Boundary 09:05 (5m closes only after first 09:05 bar) "
            "...", end=" ")
    reg = CompletedBarRegistry()
    engs = {tf: RegimeStateEngine(tf, reg)
              for tf in SUPPORTED_TIMEFRAMES}
    agg = TimeframeAggregator(
        on_bucket_closed=lambda tf, b: engs[tf].on_bar_closed(b))
    # Feed up to BUT NOT INCLUDING 09:05:00
    feed_window("08:50:00", "09:05:00", agg, engs)
    s_5m = reg.get("5m")
    expected_pre = ts("09:00:00")
    if s_5m is None or s_5m.close_ts != expected_pre:
        print(f"FAIL — pre-09:05: expected 5m close_ts="
               f"{expected_pre}, got "
               f"{s_5m.close_ts if s_5m else None}")
        return False
    # Now feed the first 09:05 1s bar — this should close the
    # [09:00,09:05) bucket and write close_ts=09:05.
    agg.on_1s_bar(ts("09:05:00"), 100.0, 100.5, 99.5, 100.2, 1.0)
    s_5m = reg.get("5m")
    expected_post = ts("09:05:00")
    if s_5m is None or s_5m.close_ts != expected_post:
        print(f"FAIL — post-09:05 first bar: expected "
               f"{expected_post}, got "
               f"{s_5m.close_ts if s_5m else None}")
        return False
    # audit at decision_ts = 09:05:00 must pass
    reg.audit_provenance(ts("09:05:00"))
    # audit at decision_ts = 09:04:59.999... must fail
    try:
        reg.audit_provenance(ts("09:05:00") - 1)
        print("FAIL — audit accepted decision strictly before 5m "
               "close_ts")
        return False
    except CausalityViolation:
        pass
    print("ok")
    return True


def t8_state_frozen():
    print("T8. CompletedBarState is frozen ...", end=" ")
    s = make_state("1m", ts("09:00:00") + BUCKET_NS_1M)
    try:
        s.regime = 999  # type: ignore[misc]
        print("FAIL — was able to mutate frozen state")
        return False
    except Exception:
        pass
    print("ok")
    return True


def t9_micro_feed_close_ts_progression():
    """Feed 1s bars from 08:54:00 to 09:05:30 and assert the
    sequence of registry close_ts values."""
    print("T9. End-to-end micro-feed close_ts progression ...",
            end=" ")
    reg = CompletedBarRegistry()
    engs = {tf: RegimeStateEngine(tf, reg)
              for tf in SUPPORTED_TIMEFRAMES}
    agg = TimeframeAggregator(
        on_bucket_closed=lambda tf, b: engs[tf].on_bar_closed(b))
    feed_window("08:54:00", "09:05:30", agg, engs)
    # Final state should have all TFs populated. Verify each.
    expected = {
        "30s": ts("09:05:00"),
        "1m":  ts("09:05:00"),
        "3m":  ts("09:03:00"),
        "5m":  ts("09:05:00"),
    }
    for tf, want in expected.items():
        got = reg.get(tf)
        if got is None or got.close_ts != want:
            got_v = got.close_ts if got else None
            print(f"FAIL — {tf} expected {want}, got {got_v}")
            return False
    # Audit at decision_ts = 09:05:30 should pass
    reg.audit_provenance(ts("09:05:30"))
    print("ok")
    return True


def t10_nt_arrival_timing():
    """In real NT runtime, the 1s bar with ts_event=09:05:00 is
    delivered to the strategy at ts_init=09:05:01. The 5m bucket
    [09:00, 09:05) is closed only when that trigger bar arrives.

    Verify:
      a) Pre-trigger: registry has 5m close_ts=09:00 (08:55-09:00
         bar). Audit at decision_ts=09:05:00 (= calendar close of
         the 09:00-09:05 bucket but BEFORE NT delivers the trigger
         bar) PASSES on what's there (08:55-09:00) but registry
         does NOT contain the 09:00-09:05 bar.
      b) Trigger bar arrives: ts_event=09:05:00, ts_init=09:05:01.
         Strategy uses decision_ts=09:05:01 (= bar.ts_init).
         Registry now contains 5m close_ts=09:05:00. Audit passes.
      c) Audit invariant: close_ts (09:05:00) <= decision_ts
         (09:05:01) — 1s causality buffer.
    """
    print("T10. NT-arrival timing semantics ...", end=" ")
    reg = CompletedBarRegistry()
    engs = {tf: RegimeStateEngine(tf, reg)
              for tf in SUPPORTED_TIMEFRAMES}
    agg = TimeframeAggregator(
        on_bucket_closed=lambda tf, b: engs[tf].on_bar_closed(b))
    # Feed bars up to BUT NOT INCLUDING the trigger
    feed_window("08:50:00", "09:05:00", agg, engs)

    # (a) Pre-trigger state: 5m at 09:00, no 09:00-09:05 yet
    s_5m_pre = reg.get("5m")
    expected_pre_close = ts("09:00:00")
    if s_5m_pre is None or s_5m_pre.close_ts != expected_pre_close:
        print(f"FAIL — pre-trigger expected 5m close_ts="
               f"{expected_pre_close}, got "
               f"{s_5m_pre.close_ts if s_5m_pre else None}")
        return False
    # If a strategy somehow used decision_ts=09:05:00 here (which
    # would be wrong — should use ts_init not ts_event), the audit
    # would still pass because the only thing in registry is the
    # 09:00 close. But the 09:00-09:05 bar is NOT yet usable.
    reg.audit_provenance(ts("09:05:00"))
    if s_5m_pre.close_ts > ts("09:05:00"):
        print("FAIL — pre-trigger should not contain future bar")
        return False

    # (b) Trigger bar arrives. In NT this is the bar with
    # ts_event=09:05:00 delivered at ts_init=09:05:01. The
    # aggregator uses ts_event for bucket assignment.
    trigger_ts_event = ts("09:05:00")
    trigger_ts_init = trigger_ts_event + 1_000_000_000  # +1s
    agg.on_1s_bar(trigger_ts_event, 100.0, 100.5, 99.5, 100.2, 1.0)

    # Registry should now have the 09:00-09:05 5m bar
    s_5m_post = reg.get("5m")
    expected_post_close = ts("09:05:00")
    if s_5m_post is None or s_5m_post.close_ts != expected_post_close:
        print(f"FAIL — post-trigger expected 5m close_ts="
               f"{expected_post_close}, got "
               f"{s_5m_post.close_ts if s_5m_post else None}")
        return False

    # (c) The strategy's decision_ts is the trigger bar's ts_init
    # (the moment NT delivered it). audit must pass at this point.
    decision_ts = trigger_ts_init  # 09:05:01
    reg.audit_provenance(decision_ts)
    # Verify the 1s causality buffer: close_ts < decision_ts
    if s_5m_post.close_ts >= decision_ts:
        print(f"FAIL — close_ts ({s_5m_post.close_ts}) >= "
               f"decision_ts ({decision_ts}); no causality buffer")
        return False
    if (decision_ts - s_5m_post.close_ts) != 1_000_000_000:
        print(f"FAIL — buffer not exactly 1s: "
               f"{decision_ts - s_5m_post.close_ts} ns")
        return False
    print("ok")
    return True


def main():
    print("=" * 60)
    print("Collector V2 — Foundation self-test")
    print("=" * 60)
    tests = [t1_registry_monotonic, t2_audit_raises,
              t3_aggregator_never_closes_partial,
              t4_engine_writes_only_on_close,
              t5_boundary_0901, t6_boundary_0904, t7_boundary_0905,
              t8_state_frozen, t9_micro_feed_close_ts_progression,
              t10_nt_arrival_timing]
    failures = 0
    for t in tests:
        try:
            ok = t()
            if not ok:
                failures += 1
        except Exception as e:
            print(f"ERROR in {t.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failures += 1
    print("=" * 60)
    if failures == 0:
        print(f"ALL {len(tests)} TESTS PASSED")
        return 0
    else:
        print(f"{failures}/{len(tests)} TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
