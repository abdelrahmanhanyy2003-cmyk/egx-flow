"""Alert engine.

* Rules are global defaults overridable per symbol (``alert_rules`` table).
* Every alert has a deterministic ``dedup_key`` built from the rule, symbol and
  the natural identity of the triggering event (trade id, wall id, price level)
  or a cooldown time bucket for continuous conditions. The key is unique in the
  database, so the same event can never produce two notifications - even across
  restarts.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from app.alerts.rules import RULES, default_params
from app.core.timeutil import now_ms

Persist = Callable[[dict[str, Any]], dict[str, Any] | None]


class AlertEngine:
    def __init__(self, persist: Persist | None = None) -> None:
        self.persist = persist
        self.overrides: dict[tuple[str, str | None], dict[str, Any]] = {}
        self._recent: OrderedDict[str, None] = OrderedDict()
        self.quality = "live"

    # ---------------------------------------------------------- rules
    def load_rules(self, rows: list[dict[str, Any]]) -> None:
        self.overrides = {(r["rule"], r["symbol"]): r for r in rows}

    def rule_cfg(self, rule: str, symbol: str | None) -> dict[str, Any]:
        cfg = {"enabled": True, "sound": True, "params": default_params(rule)}
        for key in ((rule, None), (rule, symbol)):
            o = self.overrides.get(key)
            if o:
                cfg["enabled"] = o["enabled"]
                cfg["sound"] = o["sound"]
                cfg["params"] = {**cfg["params"], **{k: v for k, v in (o.get("params") or {}).items() if v is not None}}
        return cfg

    # ---------------------------------------------------------- firing
    def _fire(self, rule: str, symbol: str | None, ident: str, message: str, payload: dict[str, Any] | None,
              ts: int | None = None) -> dict[str, Any] | None:
        cfg = self.rule_cfg(rule, symbol)
        if not cfg["enabled"]:
            return None
        key = f"{rule}|{symbol or '*'}|{ident}"
        if key in self._recent:
            return None
        self._recent[key] = None
        if len(self._recent) > 20000:
            self._recent.popitem(last=False)
        alert = {
            "ts": ts or now_ms(), "symbol": symbol, "rule": rule, "severity": RULES[rule]["severity"],
            "message": message, "payload": payload, "dedup_key": key, "quality": self.quality,
        }
        if self.persist is not None:
            stored = self.persist(alert)
            if stored is None:
                return None  # already present in DB (e.g. after restart)
            alert = stored
        alert["sound"] = cfg["sound"]
        alert["label"] = RULES[rule]["label"]
        return alert

    @staticmethod
    def _bucket(ts: int, minutes: float) -> int:
        return int(ts // (max(minutes, 0.1) * 60_000))

    # ---------------------------------------------------------- inputs
    def on_event(self, ev: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        t = ev.get("type")
        sym = ev.get("symbol")
        if t == "large_trade":
            v = ev["value"]
            side = ev.get("side")
            est = " (side estimated)" if ev.get("estimated") else ""
            msg = f"{sym} {side.upper() if side else ''} {ev['quantity']:,.0f} @ {ev['price']} = EGP {v:,.0f}{est}"
            if v >= self.rule_cfg("large_trade", sym)["params"]["min_value"]:
                a = self._fire("large_trade", sym, ev["trade_id"], f"Large trade: {msg}", ev, ev["ts"])
                if a:
                    out.append(a)
            rule = "large_buy" if side == "buy" else "large_sell" if side == "sell" else None
            if rule and v >= self.rule_cfg(rule, sym)["params"]["min_value"]:
                a = self._fire(rule, sym, ev["trade_id"], f"{RULES[rule]['label']}: {msg}", ev, ev["ts"])
                if a:
                    out.append(a)
        elif t == "wall":
            w = ev["wall"]
            val = w["price"] * max(w["qty"], w.get("max_qty", 0))
            kind = ev["kind"]
            if kind == "new":
                rule = "wall_new_bid" if w["side"] == "bid" else "wall_new_ask"
                if val >= self.rule_cfg(rule, sym)["params"]["min_value"]:
                    a = self._fire(rule, sym, w["id"],
                                   f"{sym} new {w['side']} wall {w['qty']:,.0f} @ {w['price']} (EGP {val:,.0f})", ev, ev["ts"])
                    if a:
                        out.append(a)
            elif kind == "pulled":
                if val >= self.rule_cfg("liquidity_removal", sym)["params"]["min_value"]:
                    a = self._fire("liquidity_removal", sym, w["id"],
                                   f"{sym} {w['side']} wall pulled: {w['max_qty']:,.0f} @ {w['price']} removed without execution",
                                   ev, ev["ts"])
                    if a:
                        out.append(a)
        elif t == "iceberg":
            if ev["confidence"] >= self.rule_cfg("iceberg", sym)["params"]["min_confidence"]:
                a = self._fire("iceberg", sym, f"{ev['side']}:{ev['price']}:{ev['first_ts']}",
                               f"{sym} potential iceberg on {ev['side']} @ {ev['price']}: executed {ev['executed']:,.0f} "
                               f"vs max displayed {ev['max_displayed']:,.0f} (est., conf {ev['confidence']:.0%})", ev, ev["last_ts"])
                if a:
                    out.append(a)
        elif t == "absorption":
            if ev["confidence"] >= self.rule_cfg("absorption", sym)["params"]["min_confidence"]:
                a = self._fire("absorption", sym, f"{ev['kind']}:{ev['price']}:{ev['window_start']}",
                               f"{sym} {ev['label']} @ {ev['price']} (EGP {ev['aggressive_value']:,.0f})", ev, ev["ts"])
                if a:
                    out.append(a)
        elif t == "cvd_divergence":
            cd = self.rule_cfg("cvd_divergence", sym)["params"]["cooldown_min"]
            a = self._fire("cvd_divergence", sym, f"{ev['kind']}:{self._bucket(ev['ts'], cd)}",
                           f"{sym} {ev['kind']} price/CVD divergence (strength {ev.get('strength', 0):.2f})",
                           ev, ev["ts"])
            if a:
                out.append(a)
        return out

    def on_stats(self, sym: str, stats: dict[str, Any], ts: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        imb = stats.get("imbalance")
        if imb:
            p = self.rule_cfg("imbalance_extreme", sym)["params"]
            if abs(imb["imbalance"]) >= p["threshold"]:
                side = "bid" if imb["imbalance"] > 0 else "ask"
                a = self._fire("imbalance_extreme", sym, f"{side}:{self._bucket(ts, p['cooldown_min'])}",
                               f"{sym} book imbalance {imb['imbalance']:+.0%} toward {side}s (top {imb['levels']} levels)",
                               {"imbalance": imb}, ts)
                if a:
                    out.append(a)
        rv = stats.get("rvol")
        if rv:
            p = self.rule_cfg("unusual_volume", sym)["params"]
            if rv >= p["rvol"]:
                a = self._fire("unusual_volume", sym, f"{self._bucket(ts, p['cooldown_min'])}",
                               f"{sym} unusual volume: RVOL {rv:.1f}x (time-adjusted)", {"rvol": rv}, ts)
                if a:
                    out.append(a)
        chg = stats.get("change_pct")
        if chg is not None:
            p = self.rule_cfg("price_change", sym)["params"]
            if abs(chg) >= p["pct"]:
                direction = "up" if chg > 0 else "down"
                a = self._fire("price_change", sym, f"{direction}:{self._bucket(ts, p['cooldown_min'])}",
                               f"{sym} {direction} {chg:+.2f}% vs previous close", {"change_pct": chg}, ts)
                if a:
                    out.append(a)
        last = stats.get("last")
        if last is not None:
            p = self.rule_cfg("price_alert", sym)["params"]
            if p.get("above") is not None and last >= float(p["above"]):
                a = self._fire("price_alert", sym, f"above:{p['above']}", f"{sym} traded at/above {p['above']} (last {last})",
                               {"last": last, "above": p["above"]}, ts)
                if a:
                    out.append(a)
            if p.get("below") is not None and last <= float(p["below"]):
                a = self._fire("price_alert", sym, f"below:{p['below']}", f"{sym} traded at/below {p['below']} (last {last})",
                               {"last": last, "below": p["below"]}, ts)
                if a:
                    out.append(a)
        return out

    def on_position(self, pos: dict[str, Any], ts: int) -> list[dict[str, Any]]:
        sym = pos["symbol"]
        pct = pos.get("unrealized_pnl_pct")
        if pct is None:
            return []
        p = self.rule_cfg("portfolio_pnl", sym)["params"]
        if abs(pct) < p["pct"]:
            return []
        d = "gain" if pct > 0 else "loss"
        a = self._fire("portfolio_pnl", sym, f"{d}:{self._bucket(ts, p['cooldown_min'])}",
                       f"Your {sym} position unrealized {d} {pct:+.2f}% (threshold {p['pct']}%)",
                       {"position": pos}, ts)
        return [a] if a else []
