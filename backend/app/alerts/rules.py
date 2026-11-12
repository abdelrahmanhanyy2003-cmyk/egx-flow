"""Alert rule catalogue with default, user-configurable thresholds."""

from __future__ import annotations

from typing import Any

RULES: dict[str, dict[str, Any]] = {
    "large_trade": {"label": "Large transaction detected", "severity": "info",
                    "params": {"min_value": 1_000_000}},
    "large_buy": {"label": "Large buy detected", "severity": "info", "params": {"min_value": 2_000_000}},
    "large_sell": {"label": "Large sell detected", "severity": "info", "params": {"min_value": 2_000_000}},
    "wall_new_bid": {"label": "New large bid wall", "severity": "info", "params": {"min_value": 2_000_000}},
    "wall_new_ask": {"label": "New large ask wall", "severity": "info", "params": {"min_value": 2_000_000}},
    "liquidity_removal": {"label": "Significant liquidity removal", "severity": "warning",
                          "params": {"min_value": 2_000_000}},
    "imbalance_extreme": {"label": "Extreme order-book imbalance", "severity": "warning",
                          "params": {"threshold": 0.6, "cooldown_min": 10}},
    "unusual_volume": {"label": "Unusual volume", "severity": "warning", "params": {"rvol": 2.0, "cooldown_min": 30}},
    "cvd_divergence": {"label": "CVD divergence", "severity": "warning", "params": {"cooldown_min": 15}},
    "absorption": {"label": "Potential absorption", "severity": "info", "params": {"min_confidence": 0.5}},
    "iceberg": {"label": "Potential iceberg activity", "severity": "info", "params": {"min_confidence": 0.45}},
    "price_change": {"label": "Significant price change", "severity": "warning",
                     "params": {"pct": 3.0, "cooldown_min": 30}},
    "portfolio_pnl": {"label": "Position P&L threshold", "severity": "critical",
                      "params": {"pct": 5.0, "cooldown_min": 60}},
    "price_alert": {"label": "Custom price alert", "severity": "critical", "params": {"above": None, "below": None}},
}


def default_params(rule: str) -> dict[str, Any]:
    return dict(RULES[rule]["params"])
