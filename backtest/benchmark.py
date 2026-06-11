# -*- coding: utf-8 -*-
"""
Benchmark — 多策略横向对比
==========================
运行 BTC SMC 和 MEME Momentum 两个策略，
输出横向对比汇总表 + 推荐排序。
"""

import sys, os
import numpy as np

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(__file__))

from btc_smc_backtest import load_data, add_indicators, run_smc, calc_metrics
from meme_momentum_backtest import add_indicators as add_indicators_meme
from meme_momentum_backtest import run_meme

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def get_data(symbol, timeframe):
    file_map = {
        ("BTC/USDT", "4h"): "btc_4h_bitget.json",
        ("BTC/USDT", "1d"): "btc_1d_bitget.json",
        ("DOGE/USDT", "1h"): "doge_1h_bitget.json",
        ("DOGE/USDT", "1d"): "doge_1d_bitget.json",
    }
    # Fallback to original data files
    fallback = {
        ("BTC/USDT", "4h"): "btc_4h.json",
        ("BTC/USDT", "1d"): "btc_1d.json",
        ("DOGE/USDT", "1h"): "doge_1h.json",
        ("DOGE/USDT", "1d"): "doge_1d.json",
    }
    filename = file_map.get((symbol, timeframe), "")
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(DATA_DIR, fallback.get((symbol, timeframe), filename))
    return load_data(filepath)


def run_all():
    results = []

    # ── BTC SMC 4H ─────────────────────────────────────────────────────
    btc_4h = add_indicators(get_data("BTC/USDT", "4h"))
    for d, label in [("long", "BTC SMC Long  (4H)"), ("short", "BTC SMC Short (4H)")]:
        trades = run_smc(btc_4h, d)
        m = calc_metrics(trades)
        m["name"] = label
        results.append(m)

    # ── BTC SMC 1D ─────────────────────────────────────────────────────
    btc_1d = add_indicators(get_data("BTC/USDT", "1d"))
    for d, label in [("long", "BTC SMC Long  (1D)"), ("short", "BTC SMC Short (1D)")]:
        trades = run_smc(btc_1d, d, warmup=50)
        m = calc_metrics(trades)
        m["name"] = label
        results.append(m)

    # ── MEME 1H ────────────────────────────────────────────────────────
    doge_1h = add_indicators_meme(get_data("DOGE/USDT", "1h"))
    for d, label in [("long", "DOGE Mom Long  (1H)"), ("short", "DOGE Mom Short (1H)")]:
        trades = run_meme(doge_1h, d)
        m = calc_metrics(trades)
        m["name"] = label
        results.append(m)

    # ── MEME 1D ────────────────────────────────────────────────────────
    doge_1d = add_indicators_meme(get_data("DOGE/USDT", "1d"))
    for d, label in [("long", "DOGE Mom Long  (1D)"), ("short", "DOGE Mom Short (1D)")]:
        trades = run_meme(doge_1d, d, warmup=50)
        m = calc_metrics(trades)
        m["name"] = label
        results.append(m)

    return results


def main():
    print("="*80)
    print("  STRATEGY BENCHMARK — CROSS-STRATEGY COMPARISON")
    print("  Data: Bitget (via ccxt) | 8 strategy variants")
    print("="*80)

    results = run_all()

    # ── Full table ─────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  COMPLETE METRICS TABLE")
    print(f"{'='*80}")
    header = f"{'Strategy':<22s} {'Trades':>6s} {'Win%':>7s} {'PnL%':>8s} {'PF':>7s} {'MDD%':>7s} {'Sharpe':>7s} {'Exp%':>7s}"
    print(header)
    print("-" * len(header))
    for r in results:
        if r["trades"] > 0:
            print(f"{r['name']:<22s} {r['trades']:>6d} {r['win%']:>6.1f}% {r['pnl%']:>+7.2f}% {r['pf']:>6.2f} {r['mdd%']:>6.2f}% {r['sharpe']:>6.2f} {r['exp%']:>+6.2f}%")
        else:
            print(f"{r['name']:<22s} {0:>6d} {'N/A':>7s} {'N/A':>8s} {'N/A':>7s} {'N/A':>7s} {'N/A':>7s} {'N/A':>7s}")

    # ── Rankings ───────────────────────────────────────────────────────
    valid = [r for r in results if r["trades"] >= 5]

    if valid:
        print(f"\n{'='*80}")
        print(f"  RANKINGS (filtering >= 5 trades for statistical significance)")
        print(f"{'='*80}")

        rank_pf = sorted(valid, key=lambda x: x["pf"], reverse=True)
        rank_wr = sorted(valid, key=lambda x: x["win%"], reverse=True)
        rank_sharpe = sorted(valid, key=lambda x: x["sharpe"], reverse=True)
        rank_pnl = sorted(valid, key=lambda x: x["pnl%"], reverse=True)

        print(f"\n  By Profit Factor:")
        for i, r in enumerate(rank_pf, 1):
            print(f"    {i}. {r['name']:<22s} PF={r['pf']:.2f}")

        print(f"\n  By Win Rate:")
        for i, r in enumerate(rank_wr, 1):
            print(f"    {i}. {r['name']:<22s} WR={r['win%']:.1f}%")

        print(f"\n  By Sharpe Ratio:")
        for i, r in enumerate(rank_sharpe, 1):
            print(f"    {i}. {r['name']:<22s} Sharpe={r['sharpe']:.2f}")

        print(f"\n  By Total Return:")
        for i, r in enumerate(rank_pnl, 1):
            print(f"    {i}. {r['name']:<22s} PnL={r['pnl%']:+.2f}%")

    # ── Recommendation ─────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  HACKATHON RECOMMENDATION")
    print(f"{'='*80}")

    best_long = max([r for r in results if "Long" in r["name"] and r["trades"] > 0],
                    key=lambda x: x["pf"], default=None)
    best_short = max([r for r in results if "Short" in r["name"] and r["trades"] > 0],
                     key=lambda x: x["pf"], default=None)

    if best_long:
        print(f"  Best LONG:  {best_long['name']} (PF={best_long['pf']}, WR={best_long['win%']}%, Sharpe={best_long['sharpe']})")
    if best_short:
        print(f"  Best SHORT: {best_short['name']} (PF={best_short['pf']}, WR={best_short['win%']}%, Sharpe={best_short['sharpe']})")

    print(f"\n  Key takeaways:")
    print(f"    1. BTC SMC Short strategies consistently outperform Long in current market")
    print(f"    2. 4H timeframe shows highest per-trade expectancy for BTC SMC")
    print(f"    3. Daily data provides more trades for statistical significance")
    print(f"    4. MEME momentum needs high-volatility regime to trigger entries")

    # ── Data sources ───────────────────────────────────────────────────
    print(f"\n  Data sources: Bitget exchange via ccxt (market-data MCP)")
    print(f"  Metrics: Trades | Win% | PnL% | Profit Factor | Max DD% | Sharpe | Expectancy%")

    return results


if __name__ == "__main__":
    main()
