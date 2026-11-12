"""DEMO instrument universe.

Tickers and company names are real EGX listings so the UI feels familiar, but
ALL prices, sizes, tick sizes and activity produced from this file are
SIMULATED. They are configuration for the simulator, not market data.
"""

from __future__ import annotations

# symbol, name, sector, demo start price, demo tick size, demo avg daily volume (shares)
DEMO_UNIVERSE: list[tuple[str, str, str, float, float, float]] = [
    ("COMI", "Commercial International Bank (Egypt)", "Banks", 82.50, 0.01, 6_500_000),
    ("ETEL", "Telecom Egypt", "Telecommunications", 41.20, 0.01, 2_200_000),
    ("FWRY", "Fawry for Banking Technology", "Technology", 8.35, 0.01, 28_000_000),
    ("EGAL", "Egypt Aluminum", "Basic Resources", 152.00, 0.01, 900_000),
    ("HRHO", "EFG Holding", "Non-bank Financial Services", 25.40, 0.01, 7_800_000),
    ("TMGH", "Talaat Moustafa Group Holding", "Real Estate", 61.80, 0.01, 5_100_000),
    ("SWDY", "Elsewedy Electric", "Industrial Goods", 76.10, 0.01, 3_300_000),
    ("EAST", "Eastern Company", "Food & Beverage", 31.70, 0.01, 4_400_000),
    ("ABUK", "Abu Qir Fertilizers", "Basic Resources", 56.30, 0.01, 1_600_000),
    ("ORAS", "Orascom Construction", "Construction", 305.00, 0.01, 250_000),
    ("ESRS", "Ezz Steel", "Basic Resources", 101.50, 0.01, 1_900_000),
    ("JUFO", "Juhayna Food Industries", "Food & Beverage", 19.85, 0.01, 2_600_000),
    ("PHDC", "Palm Hills Development", "Real Estate", 7.12, 0.001, 45_000_000),
    ("EFIH", "e-finance for Digital and Financial Investments", "Technology", 21.30, 0.01, 3_700_000),
    ("CIEB", "Credit Agricole Egypt", "Banks", 22.60, 0.01, 1_400_000),
    ("ORWE", "Oriental Weavers", "Textiles", 19.40, 0.01, 1_200_000),
]

DEMO_INDEX_NAME = "EGX30 (DEMO)"
DEMO_INDEX_BASE = 31_250.0
