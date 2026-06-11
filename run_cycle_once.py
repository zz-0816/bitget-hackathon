"""One-shot cycle runner: compute indicators + run cycle from Skills data."""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from agent.auto_cycle import run_cycle, compute_indicators_from_ohlcv

STRATEGY = "BTCUSDT 15min趋势跟随 EMA金叉进场 MACD上涨确认 做多 止损1%止盈2%"

# Load OHLCV
with open("data/btc_15min_latest.json") as f:
    ohlcv = json.load(f)

# Compute indicators
ind = compute_indicators_from_ohlcv(ohlcv)
print("=== Computed Indicators ===")
for k, v in ind.items():
    print(f"  {k}: {v}")

# Build market data JSON from Skills
market_data = {
    "technical": ind,
    "sentiment": {
        "fear_greed_index": 12,
        "fear_greed_label": "Extreme Fear",
        "long_short_ratio": 1.71,
        "ls_trend": "declining"
    },
    "macro": {
        "regime": "cautious",
        "fed_funds_rate": 3.75,
        "yield_curve_inverted": False,
        "spread_10y2y": 0.42
    },
    "news": {
        "has_major_event": True,
        "bias": "bearish",
        "summary": "BTC ETFs shed $2.1B in June; Iran Hormuz closure; Hungary crypto crackdown reversal"
    }
}

# Run cycle
result = run_cycle(
    strategy_text=STRATEGY,
    market_data_json=json.dumps(market_data),
    dry_run=True,
)

print("\n=== Cycle Result ===")
print(json.dumps({k: v for k, v in result.items() if k != "state"}, indent=2, default=str))
