"""Reconcile broker-reported orders with the local trade journal.

Matching key is the broker order id stored on journal rows. A broker fill that
is already journaled is never imported again (no double counting); the DB also
enforces uniqueness of ``broker_order_id``.
"""

from __future__ import annotations

from typing import Any

from app.domain.models import BrokerOrder

FILLED_WORDS = ("fill", "execut", "complete", "done")


def is_filled(o: BrokerOrder) -> bool:
    s = (o.status or "").lower()
    return any(w in s for w in FILLED_WORDS)


def broker_side(o: BrokerOrder) -> str | None:
    s = (o.side or "").strip().lower()
    if s.startswith("b"):
        return "buy"
    if s.startswith("s"):
        return "sell"
    return None


def reconcile(broker: list[BrokerOrder], journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {j["broker_order_id"]: j for j in journal if j.get("broker_order_id")}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for o in broker:
        if not is_filled(o):
            continue
        seen.add(o.order_id)
        j = by_id.get(o.order_id)
        bq = o.filled_quantity or o.quantity
        bp = o.avg_price or o.price
        if j is None:
            rows.append({"status": "broker_only", "broker": o.to_dict(), "journal": None,
                         "note": "Filled at broker, not yet in journal"})
            continue
        issues = []
        if bq is not None and abs(float(bq) - float(j["quantity"])) > 1e-9:
            issues.append(f"quantity broker {bq} vs journal {j['quantity']}")
        if bp is not None and abs(float(bp) - float(j["price"])) > 1e-6:
            issues.append(f"price broker {bp} vs journal {j['price']}")
        bs = broker_side(o)
        if bs and bs != j["side"]:
            issues.append(f"side broker {bs} vs journal {j['side']}")
        rows.append({"status": "mismatch" if issues else "matched", "broker": o.to_dict(), "journal": j,
                     "note": "; ".join(issues)})
    for j in journal:
        bid = j.get("broker_order_id")
        if bid and bid not in seen:
            rows.append({"status": "journal_only", "broker": None, "journal": j,
                         "note": "Journal references a broker order not found in broker history"})
        elif not bid:
            rows.append({"status": "manual", "broker": None, "journal": j, "note": "Manual entry (no broker link)"})
    return rows


def importable(broker: list[BrokerOrder], journal: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Journal rows to create for filled broker orders not yet journaled."""
    have = {j["broker_order_id"] for j in journal if j.get("broker_order_id")}
    out = []
    for o in broker:
        if not is_filled(o) or o.order_id in have:
            continue
        side = broker_side(o)
        qty = o.filled_quantity or o.quantity
        px = o.avg_price or o.price
        if side is None or not qty or not px or not o.symbol:
            continue
        from app.core.timeutil import cairo_iso

        out.append({
            "symbol": o.symbol, "side": side, "trade_date": cairo_iso(o.ts) if o.ts else "",
            "quantity": float(qty), "price": float(px), "fees": 0.0, "notes": "Imported from broker order history",
            "thesis": None, "tags": None, "broker_order_id": o.order_id, "origin": "broker",
        })
    return out
