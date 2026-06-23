"""Single-cycle entry point for Claude Code orchestration.

Claude Code calls this once per monitoring cycle:
  1. Claude Code fetches OHLCV + Skill data → writes to temp files
  2. Claude Code runs: python agent/claude_cycle.py --strategy "..." --ohlcv-file ... --market-extras-file ... [--live]
  3. This script computes indicators, runs run_cycle(), prints report, saves evidence
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agent.auto_cycle import run_cycle, compute_indicators_from_ohlcv, CycleState
from agent.api_logger import get_api_summary

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
EVIDENCE_FILE = os.path.join(OUTPUT_DIR, "cycle_evidence.jsonl")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_json(filepath: str) -> dict | list:
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def save_cycle_evidence(cycle_result: dict, market_data: dict, strategy_text: str) -> None:
    """Append one cycle's evidence to output/cycle_evidence.jsonl."""
    state = CycleState.load()
    evidence = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle": cycle_result.get("cycle", 0),
        "strategy": strategy_text,
        "status": cycle_result.get("status", "unknown"),
        "signal": cycle_result.get("signal", ""),
        "confidence": cycle_result.get("confidence", 0),
        "checks_passed": cycle_result.get("checks_passed", 0),
        "checks_total": cycle_result.get("checks_total", 0),
        "entry_price": cycle_result.get("entry_price"),
        "stop_loss": cycle_result.get("stop_loss"),
        "take_profit": cycle_result.get("take_profit"),
        "win_rate": cycle_result.get("win_rate"),
        "rr_ratio": cycle_result.get("rr_ratio"),
        "expectancy": cycle_result.get("expectancy"),
        "risk_warnings": cycle_result.get("risk_warnings", []),
        "holding": cycle_result.get("holding", False),
        "pnl_pct": cycle_result.get("pnl_pct"),
        "exit_reason": cycle_result.get("exit_reason", ""),
        "alerts": cycle_result.get("alerts", []),
        "market_snapshot": {
            "technical": {
                "close": market_data.get("technical", {}).get("close"),
                "rsi": market_data.get("technical", {}).get("rsi"),
                "ema_12": market_data.get("technical", {}).get("ema_12"),
                "ema_26": market_data.get("technical", {}).get("ema_26"),
                "macd_dif": market_data.get("technical", {}).get("macd_dif"),
                "macd_dea": market_data.get("technical", {}).get("macd_dea"),
                "macd_hist": market_data.get("technical", {}).get("macd_hist"),
                "adx": market_data.get("technical", {}).get("adx"),
                "atr": market_data.get("technical", {}).get("atr"),
                "bb_upper": market_data.get("technical", {}).get("bb_upper"),
                "bb_mid": market_data.get("technical", {}).get("bb_mid"),
                "bb_lower": market_data.get("technical", {}).get("bb_lower"),
                "trend_direction": market_data.get("technical", {}).get("trend_direction"),
            },
            "sentiment": market_data.get("sentiment", {}),
            "macro": market_data.get("macro", {}),
            "news": market_data.get("news", {}),
        },
        "state": {
            "in_position": state.in_position,
            "cycle_count": state.cycle_count,
            "trades_completed": state.trades_completed,
            "total_pnl": state.total_pnl,
            "trade_history": state.trade_history[-5:] if state.trade_history else [],
        },
    }
    api_summary = get_api_summary() if callable(get_api_summary) else {}
    evidence["api_summary"] = api_summary

    with open(EVIDENCE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(evidence, ensure_ascii=False, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Claude Code single-cycle entry point")
    parser.add_argument("--strategy", required=True, help="NL strategy description")
    parser.add_argument("--ohlcv-file", required=True, help="Path to OHLCV JSON file")
    parser.add_argument("--market-extras-file", required=True, help="Path to sentiment/macro/news JSON file")
    parser.add_argument("--live", action="store_true", help="Place real demo orders (default: dry-run)")
    parser.add_argument("--interval", type=int, default=15, help="Cycle interval in minutes (for display only)")
    args = parser.parse_args()

    # ── Load OHLCV ───────────────────────────────────────────
    ohlcv_list = load_json(args.ohlcv_file)
    if isinstance(ohlcv_list, dict):
        ohlcv_list = ohlcv_list.get("data", ohlcv_list.get("klines", []))
    if not ohlcv_list:
        print("ERROR: No OHLCV data found")
        sys.exit(1)

    indicators = compute_indicators_from_ohlcv(ohlcv_list)

    # ── Load market extras ───────────────────────────────────
    extras = load_json(args.market_extras_file)
    if isinstance(extras, list):
        extras = extras[0] if extras else {}

    market_data = {
        "technical": indicators,
        "sentiment": extras.get("sentiment", {"fear_greed_index": 50, "fear_greed_label": "neutral", "long_short_ratio": 1.0}),
        "macro": extras.get("macro", {"regime": "neutral"}),
        "news": extras.get("news", {"has_major_event": False, "bias": "neutral", "summary": ""}),
    }

    # ── Demo client (if live) ────────────────────────────────
    client = None
    dry_run = not args.live

    if args.live:
        try:
            from demo_trading_test import DemoClient
            mcp_path = os.path.join(PROJECT_DIR, ".mcp.json")
            with open(mcp_path) as f:
                mcp_cfg = json.load(f)
            env = mcp_cfg["mcpServers"]["bitget"]["env"]
            client = DemoClient(
                api_key=env["BITGET_API_KEY"],
                secret=env["BITGET_SECRET_KEY"],
                passphrase=env["BITGET_PASSPHRASE"],
            )
        except Exception as e:
            print(f"WARNING: DemoClient init failed ({e}), falling back to dry-run")
            dry_run = True

    # ── Run cycle ────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"  CYCLE #{CycleState.load().cycle_count + 1} — {now:%Y-%m-%d %H:%M:%S} UTC")
    print(f"  Strategy: {args.strategy}")
    print(f"  Mode: {'LIVE DEMO' if not dry_run else 'DRY-RUN'} | Bar count: {len(ohlcv_list)}")
    print(f"{'='*60}")

    result = run_cycle(
        strategy_text=args.strategy,
        market_data_json=json.dumps(market_data),
        dry_run=dry_run,
        client=client,
    )

    # ── Save evidence ────────────────────────────────────────
    save_cycle_evidence(result, market_data, args.strategy)
    state = CycleState.load()
    print(f"\n  Evidence saved → {os.path.relpath(EVIDENCE_FILE, PROJECT_DIR)}")
    print(f"  State: cycle={state.cycle_count} | "
          f"in_position={state.in_position} | "
          f"trades={state.trades_completed} | "
          f"PnL={state.total_pnl:+.2f}")

    return result


if __name__ == "__main__":
    main()
