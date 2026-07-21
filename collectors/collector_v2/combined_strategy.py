"""CombinedStrategy — bar-4 all-flips NT strategy: Model B pQF entry gate +
per-bar KNN hC trade management. Reuses CollectorV2 plumbing (regime engine,
registry, aggregator, 1s entry-submission machinery) but REPLACES the V_A
confirmed-entry path with a clean bar-4 all-flips entry.

Architecture (per user spec):
  - detect every 1m regime flip (regime engine)
  - at bar-3 close (bars_in_regime==4): apply Model B pQF gate (lookup by regime_start_ts)
  - enter at bar-4 open / next causal 1s event (GTC market order)
  - manage per-bar with KNN hC state (lookup by (regime_start_ts, bars_in_regime))
  - exit on continuous opposing nonzero regime (state-gated, every 1m close)

Execution: standard GTC market orders only (NO FOK/IOC). State-gated exits.
Audit invariant: no open trade may remain open > 1 completed 1m bar after an
opposing nonzero regime appears. Tracks max_bars_after_opposite_regime, count_delay_gt_1.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from nautilus_trader.model.enums import OrderSide, TimeInForce  # noqa: E402
from nautilus_trader.model.identifiers import InstrumentId       # noqa: E402
from nautilus_trader.model.objects import Quantity               # noqa: E402

from collectors.collector_v2.strategy import (                   # noqa: E402
    CollectorV2Strategy, CollectorV2Config)


class CombinedConfig(CollectorV2Config, frozen=True):
    pqf_mapping_path: str = ""
    hc_perbar_mapping_path: str = ""
    pqf_threshold: float = -1.0       # <0 = no ML filter; else reject if pQF >= threshold
    base_position_size: int = 2
    hc_sizing: str = "none"           # none | discrete | conservative   (RG1)
    enable_add: bool = False          # RG2 high-health HardStall add
    collapse_action: str = "none"     # none | reduce | exit             (RG3)
    deter_action: str = "none"        # none | reduce_if_profit | exit_if_hc_neg  (RG4)


class CombinedStrategy(CollectorV2Strategy):
    def __init__(self, config: CombinedConfig):
        super().__init__(config)
        self._cfg = config
        # --- load mappings ---
        self._pqf: dict[int, float] = {}
        self._hc: dict[tuple[int, int], tuple] = {}
        if config.pqf_mapping_path and Path(config.pqf_mapping_path).exists():
            m = pd.read_parquet(config.pqf_mapping_path)
            self._pqf = dict(zip(m.regime_start_ts.astype("int64"), m.pQF))
            print(f"[Combined] loaded {len(self._pqf)} pQF records")
        if config.hc_perbar_mapping_path and Path(config.hc_perbar_mapping_path).exists():
            h = pd.read_parquet(config.hc_perbar_mapping_path)
            self._hc = {(int(r.regime_start_ts), int(r.bars_in_regime)):
                        (float(r.hC), float(r.dhC) if pd.notna(r.dhC) else float("nan"), r.state)
                        for r in h.itertuples(index=False)}
            print(f"[Combined] loaded {len(self._hc)} per-bar hC records")

        self._cur_regime_start_ts: int = 0
        self._child_orders: dict[str, tuple] = {}   # cid -> (qty, signed_dir)
        self._audit = {
            "bar4_flips_total": 0, "bar4_flips_mapped": 0,
            "entries_rejected_pqf": 0, "entries_unmapped_skipped": 0,
            "opposite_regime_seen_count": 0, "exit_submitted_count": 0,
            "exit_filled_count": 0, "max_bars_after_opposite_regime": 0,
            "count_delay_gt_1": 0, "add_count": 0, "reduce_count": 0,
            "sizing_count": 0, "fok_count": 0, "ioc_count": 0,
        }

    # ---------- entry path (REPLACES V_A confirmation) ----------
    def _on_1m_bucket_closed(self, decision_ts: int):
        s_1m = self._registry.get("1m")
        if s_1m is None:
            return
        bar_data = self._latest_1m_bar_data
        if bar_data is None or bar_data["ts_init"] != s_1m.close_ts:
            return
        new_regime = int(s_1m.regime)
        bir = int(s_1m.bars_in_regime)

        flipped = (new_regime != 0 and self._prev_1m_regime != 0
                   and new_regime != self._prev_1m_regime)
        first_regime = (new_regime != 0 and self._prev_1m_regime == 0)
        if flipped or first_regime:
            self._cur_regime_start_ts = int(s_1m.close_ts)

        # --- STATE-GATED EXIT (every 1m close) ---
        t = self._trade
        if t is not None and t.get("entry_ts") is not None:
            cur = new_regime
            if cur != 0 and cur != t["direction"]:
                if t.get("opp_first_seen_ts") is None:
                    t["opp_first_seen_ts"] = int(decision_ts)
                    self._audit["opposite_regime_seen_count"] += 1
                else:
                    t["opp_delay_bars"] = t.get("opp_delay_bars", 0) + 1
                    if t["opp_delay_bars"] > self._audit["max_bars_after_opposite_regime"]:
                        self._audit["max_bars_after_opposite_regime"] = t["opp_delay_bars"]
                    if t["opp_delay_bars"] > 1:
                        self._audit["count_delay_gt_1"] += 1
                if t.get("exit_order_id") is None:
                    self._submit_exit(reason="regime")

        # --- per-bar hC management ---
        if (t is not None and t.get("entry_ts") is not None
                and t.get("exit_order_id") is None):
            self._manage(t, s_1m, decision_ts)

        # --- BAR-4 ENTRY GATE at bar-3 close (bars_in_regime==4) ---
        if (self._trade is None and self._pending_entry is None
                and new_regime != 0 and bir == 4 and self._cur_regime_start_ts != 0):
            self._try_enter(new_regime, decision_ts)

        if new_regime != 0:
            self._prev_1m_regime = new_regime

    def _try_enter(self, direction: int, decision_ts: int):
        rst = self._cur_regime_start_ts
        pqf = self._pqf.get(rst)
        if self._cfg.pqf_threshold >= 0:          # ML filter active
            if pqf is None:
                self._audit["entries_unmapped_skipped"] += 1
                return
            if pqf >= self._cfg.pqf_threshold:
                self._audit["entries_rejected_pqf"] += 1
                return
        self._audit["bar4_flips_total"] += 1
        self._audit["bar4_flips_mapped"] += int(pqf is not None)
        self._pending_entry = {
            "fill_ts_target": int(decision_ts),
            "direction": int(direction),
            "decision_ts": int(decision_ts),
            "decision_event_id": 0,
            "atr_at_signal": float(self._registry.get("1m").atr or float("nan")),
            "regime_start_ts": int(rst),
            "pQF": float(pqf) if pqf is not None else float("nan"),
        }

    # ---------- GTC order helpers ----------
    def _market(self, side, qty, reduce_only=False):
        return self.order_factory.market(
            instrument_id=InstrumentId.from_str(self._cfg.instrument_id),
            order_side=side, quantity=Quantity.from_int(int(qty)),
            time_in_force=TimeInForce.GTC, reduce_only=reduce_only)

    def _submit_entry(self):
        pe = self._pending_entry
        d = pe["direction"]
        side = OrderSide.BUY if d == 1 else OrderSide.SELL
        order = self._market(side, self._cfg.base_position_size)
        self._trade = {
            "direction": int(d),
            "regime_start_ts": int(pe["regime_start_ts"]),
            "pQF": float(pe["pQF"]),
            "decision_ts": int(pe["decision_ts"]),
            "decision_event_id": 0,
            "atr_at_signal": float(pe["atr_at_signal"]),
            "entry_order_id": order.client_order_id.value,
            "fill_price": None, "entry_ts": None,
            "exit_order_id": None, "exit_price": None, "exit_ts": None,
            "exit_reason": None,
            "target": int(self._cfg.base_position_size),  # intended size for mgmt
            "pos": 0.0,                # actual net filled contracts (>=0 in trade dir)
            "entry_contracts": 0.0,    # cumulative contracts bought into the position
            "cash_flows": [],
            "order_dir": {order.client_order_id.value: +1},  # cid -> +1 increase / -1 decrease
            "sized": False, "added": False,
            "collapsed": False, "deter_acted": False,
            "last_close": float("nan"),
            "opp_first_seen_ts": None, "opp_delay_bars": 0,
            # fields the parent _on_1s_bar / _update_open_trade touch:
            "running_mfe": 0.0, "running_mae": 0.0, "next_path_cp_ts": 0,
            "hhll_armed": False, "hhll_protect_px": None,
            "hhll_protect_order_id": None,
        }
        self._pending_entry = None
        self.submit_order(order)

    def _submit_exit(self, reason="regime"):
        t = self._trade
        if t is None or t.get("exit_order_id") is not None:
            return
        qty = int(round(t["pos"]))
        if qty <= 0:
            return
        d = t["direction"]
        side = OrderSide.SELL if d == 1 else OrderSide.BUY
        order = self._market(side, qty, reduce_only=True)
        t["exit_order_id"] = order.client_order_id.value
        t["order_dir"][order.client_order_id.value] = -1
        t["exit_reason"] = reason
        self._audit["exit_submitted_count"] += 1
        self.submit_order(order)

    def _submit_child(self, signed: int, qty: int, tag: str):
        """signed=+1 add (same dir), -1 reduce. qty contracts."""
        t = self._trade
        if qty <= 0 or t is None:
            return
        d = t["direction"]
        if signed > 0:
            side = OrderSide.BUY if d == 1 else OrderSide.SELL
            order = self._market(side, qty, reduce_only=False)
        else:
            side = OrderSide.SELL if d == 1 else OrderSide.BUY
            order = self._market(side, qty, reduce_only=True)
        t["order_dir"][order.client_order_id.value] = int(signed)
        self.submit_order(order)

    # ---------- per-bar hC management ----------
    def _manage(self, t, s_1m, decision_ts):
        bir = int(s_1m.bars_in_regime)
        rec = self._hc.get((t["regime_start_ts"], bir))
        if rec is None:
            return
        hC, dhC, state = rec
        d = t["direction"]
        ep = t.get("fill_price")
        atr = t.get("atr_at_signal") or float("nan")
        close = float(s_1m.close)
        t["last_close"] = close
        open_pts = (close - ep) * d if ep is not None else 0.0
        open_atr = open_pts / atr if (atr and atr == atr and atr > 0) else 0.0

        cur = int(round(t["pos"]))   # current net contracts

        # RG1 — sizing at first hC (bar-4 close = bars_in_regime 5), once
        if (not t["sized"] and bir == 5 and self._cfg.hc_sizing != "none" and cur > 0):
            base = self._cfg.base_position_size
            if self._cfg.hc_sizing == "discrete":
                f = 2.0 if hC >= 0.5 else (1.0 if hC >= 0.1 else 0.5)
            else:  # conservative
                f = 1.0 if hC >= 0.1 else 0.5
            target = max(1, int(round(base * f)))
            diff = target - cur
            t["sized"] = True
            if diff != 0:
                self._audit["sizing_count"] += 1
                self._submit_child(1 if diff > 0 else -1, abs(diff), "size")
                return

        # RG2 — high-health HardStall add (once)
        if (self._cfg.enable_add and not t["added"]
                and state == "HardStall" and hC >= 0.5
                and dhC == dhC and dhC < -0.05 and open_pts >= 0):
            t["added"] = True
            self._audit["add_count"] += 1
            self._submit_child(+1, 1, "add")
            return

        # RG3 — low-health collapse protection
        if (self._cfg.collapse_action != "none" and not t["collapsed"]
                and state == "HardStall" and hC < 0.1
                and dhC == dhC and dhC < -0.05 and cur > 0):
            t["collapsed"] = True
            if self._cfg.collapse_action == "exit":
                self._submit_exit(reason="collapse")
                return
            if self._cfg.collapse_action == "reduce":
                self._audit["reduce_count"] += 1
                self._submit_child(-1, max(1, cur // 2), "collapse_reduce")
                return

        # RG4 — DETER handling
        if (self._cfg.deter_action != "none" and not t["deter_acted"]
                and state == "DETER" and cur > 0):
            if self._cfg.deter_action == "reduce_if_profit" and open_atr > 0.5:
                t["deter_acted"] = True
                self._audit["reduce_count"] += 1
                self._submit_child(-1, max(1, cur // 2), "deter_reduce")
                return
            if self._cfg.deter_action == "exit_if_hc_neg" and hC < 0.0:
                t["deter_acted"] = True
                self._submit_exit(reason="deter")
                return

    # ---------- fills (cash-flow PnL across variable size) ----------
    # Market orders may PARTIAL-FILL into multiple OrderFilled events; we
    # accumulate per-fill quantity (event.last_qty) into a net-position counter
    # and append one cash-flow leg per fill. Finalize only when net pos == 0.
    def on_order_filled(self, event):
        cid = event.client_order_id.value
        t = self._trade
        if t is None:
            return
        d = t["direction"]
        px = float(event.last_px)
        q = float(event.last_qty)
        sgn = t["order_dir"].get(cid)
        if sgn is None:
            return
        if sgn > 0:                       # increase position (entry / add)
            if t["entry_ts"] is None:
                t["entry_ts"] = int(event.ts_event)
                t["fill_price"] = px
                t["next_path_cp_ts"] = int(event.ts_event) + 30 * 1_000_000_000
                self._diag["entries_filled"] += 1
            t["pos"] += q
            t["entry_contracts"] += q
            t["cash_flows"].append((q, px, -d))
        else:                             # decrease position (exit / reduce)
            t["pos"] -= q
            t["cash_flows"].append((q, px, d))
            t["exit_price"] = px
            t["exit_ts"] = int(event.ts_event)
            if t["pos"] <= 1e-9:          # fully flat -> finalize
                self._audit["exit_filled_count"] += 1
                self._finalize_trade()

    def on_order_rejected(self, event):
        cid = event.client_order_id.value
        t = self._trade
        if t is None:
            return
        if cid == t.get("entry_order_id") and t["pos"] <= 1e-9:
            self._trade = None            # entry never filled -> discard
        elif cid == t.get("exit_order_id"):
            t["exit_order_id"] = None     # retry next 1m close
        t.get("order_dir", {}).pop(cid, None)

    def on_order_canceled(self, event):
        self.on_order_rejected(event)

    def on_order_expired(self, event):
        self.on_order_rejected(event)

    def _finalize_trade(self):
        t = self._trade
        total_cf = sum(q * p * s for q, p, s in t["cash_flows"])
        gross = total_cf * self._cfg.multiplier
        # commission + slippage: round-trip per contract actually traded in
        contracts = max(1, int(round(t["entry_contracts"])))
        cost = (self._cfg.commission_per_rt + self._cfg.tick_dollar) * contracts
        t["size"] = contracts
        t["gross_pnl"] = gross
        t["net_pnl"] = gross - cost
        t["hold_s"] = ((t["exit_ts"] - t["entry_ts"]) / 1e9
                       if t.get("exit_ts") and t.get("entry_ts") else 0.0)
        t["session"] = ("RTH" if (t.get("entry_ts") and self._is_rth_minute(t["entry_ts"]))
                        else "ETH")
        t.pop("order_dir", None)
        self._trades.append(dict(t))
        self._trade = None
