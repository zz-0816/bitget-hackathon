# -*- coding: utf-8 -*-
"""
MEME 动量独立回测
=================
策略: MEME Momentum Breakout + Volume-Price
周期: 1H + 1D
数据: Bitget (via ccxt) 真实历史 K 线
"""

import json, os, sys
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_data(filepath):
    with open(filepath) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


def add_indicators(df):
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    for p in (20, 50, 200):
        df[f"ema{p}"] = c.ewm(span=p, adjust=False).mean()
    df["ema1"] = c.ewm(span=1, adjust=False).mean()
    df["ema99"] = c.ewm(span=99, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_g / avg_l
    df["rsi"] = 100 - 100 / (1 + rs)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()

    df["vol_ma20"] = v.ewm(span=20, adjust=False).mean()
    df["vol_surge"] = v > 1.5 * df["vol_ma20"]
    df["vol_climax"] = v > 2.0 * df["vol_ma20"]

    df["above_ema20"] = c > df["ema20"]
    df["below_ema20"] = c < df["ema20"]

    h0 = df["macd_hist"]
    df["macd_accel_up"] = (h0 > h0.shift(1)) & (h0.shift(1) > h0.shift(2)) & (h0.shift(2) > h0.shift(3))
    df["macd_accel_dn"] = (h0 < h0.shift(1)) & (h0.shift(1) < h0.shift(2)) & (h0.shift(2) < h0.shift(3))

    r = df["rsi"]
    df["rsi_rising"] = r > r.shift(1)
    df["rsi_55_65"] = (r >= 55) & (r <= 65)
    df["rsi_bear_div"] = (c > c.shift(5)) & (r < r.shift(5))
    df["rsi_bull_div"] = (c < c.shift(5)) & (r > r.shift(5))

    body = (c - df["open"]).abs()
    total_range = h - l
    df["anomaly_bar"] = total_range > 3 * df["atr"]
    df["vol_climax_rev"] = df["vol_climax"] & (c < df["open"]) & (c.shift(1) > df["open"].shift(1))
    df["vol_climax_rev_bull"] = df["vol_climax"] & (c > df["open"]) & (c.shift(1) < df["open"].shift(1))

    return df


def run_meme(df, direction="long", warmup=250):
    trades = []
    pos = 0
    entry_px = sl = tp2 = 0
    entry_i = 0
    partial = False

    for i in range(warmup, len(df)):
        row = df.iloc[i]

        if pos != 0:
            exit_px = row["close"]
            reason = ""

            if pos == 1:
                if row["low"] <= sl:
                    exit_px = sl; reason = "StopLoss"
                elif not partial and row["high"] >= row["entry_px_stored"] + 1.5 * row["atr"]:
                    partial = True
                    df.at[df.index[i], "_tp1_hit"] = True
                    continue
                elif row["high"] >= tp2:
                    exit_px = tp2; reason = "TakeProfit"
                elif row["vol_climax_rev"]: reason = "VolClimaxRev"
                elif row["rsi_bear_div"] and row["rsi"] > 60: reason = "RSI_BearDiv"
                elif row["ema1"] < row["ema99"] and row["close"] < entry_px: reason = "TrendDeath"
                elif row["anomaly_bar"]: reason = "AnomalyBar"
                else: continue
            else:
                if row["high"] >= sl:
                    exit_px = sl; reason = "StopLoss"
                elif not partial and row["low"] <= row["entry_px_stored"] - 1.5 * row["atr"]:
                    partial = True; continue
                elif row["low"] <= tp2:
                    exit_px = tp2; reason = "TakeProfit"
                elif row["vol_climax_rev_bull"]: reason = "VolClimaxRev"
                elif row["rsi_bull_div"] and row["rsi"] < 40: reason = "RSI_BullDiv"
                elif row["ema1"] > row["ema99"] and row["close"] > entry_px: reason = "TrendDeath"
                elif row["anomaly_bar"]: reason = "AnomalyBar"
                else: continue

            pnl = (exit_px - entry_px) / entry_px * 100 if pos == 1 else (entry_px - exit_px) / entry_px * 100
            trades.append({
                "entry_t": df.index[entry_i], "exit_t": df.index[i],
                "dir": "LONG" if pos == 1 else "SHORT",
                "entry": entry_px, "exit": exit_px, "pnl%": round(pnl, 3),
                "bars": i - entry_i, "reason": reason,
            })
            pos = 0; partial = False
            continue

        if direction in ("long", "both"):
            if (row["rsi_55_65"] and row["rsi_rising"] and
                row["macd_accel_up"] and row["vol_surge"] and row["above_ema20"]):
                pos, entry_px, entry_i = 1, row["close"], i
                df.at[df.index[i], "entry_px_stored"] = entry_px
                sl = entry_px - 2.0 * row["atr"]
                tp2 = entry_px + 2.5 * row["atr"]

        if direction in ("short", "both") and pos == 0:
            if ((row["rsi"] >= 40) and (row["rsi"] <= 50) and (not row["rsi_rising"]) and
                row["macd_accel_dn"] and row["vol_surge"] and row["below_ema20"]):
                pos, entry_px, entry_i = -1, row["close"], i
                df.at[df.index[i], "entry_px_stored"] = entry_px
                sl = entry_px + 2.0 * row["atr"]
                tp2 = entry_px - 2.5 * row["atr"]

    return trades


def calc_metrics(trades):
    if not trades:
        return {"trades": 0}

    pnls = [t["pnl%"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w = sum(wins) if wins else 0
    gross_l = abs(sum(losses)) if losses else 0.01

    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    mdd = abs((cum - peak).min())

    wr = len(wins) / len(trades) * 100
    avg_w = np.mean(wins) if wins else 0
    avg_l = np.mean(losses) if losses else 0
    pf = gross_w / gross_l
    exp_ret = (wr/100 * avg_w) + ((1-wr/100) * avg_l)

    rets = np.array(pnls) / 100
    if len(rets) > 1 and rets.std() > 0:
        sharpe = rets.mean() / rets.std()
        sharpe_annual = sharpe * np.sqrt(len(trades))
    else:
        sharpe = sharpe_annual = 0

    return {
        "trades": len(trades), "win%": round(wr, 1), "pnl%": round(sum(pnls), 2),
        "pf": round(pf, 2), "mdd%": round(mdd, 2), "sharpe": round(sharpe_annual, 2),
        "avg_w": round(avg_w, 2), "avg_l": round(avg_l, 2), "exp%": round(exp_ret, 2),
    }


def print_report(name, trades, metrics):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    if not trades:
        print("  [NO TRADES] — conditions too strict for this dataset")
        return

    pnls = [t["pnl%"] for t in trades]
    wins = [p for p in pnls if p > 0]
    print(f"  Trades: {len(trades):4d}  | Wins: {len(wins):4d}  | Losses: {len(trades)-len(wins):4d}")
    print(f"  Win Rate:     {metrics['win%']:5.1f}%")
    print(f"  Total P&L:    {metrics['pnl%']:+.2f}%")
    print(f"  Profit Factor:{metrics['pf']:6.2f}")
    print(f"  Max Drawdown: {metrics['mdd%']:5.2f}%")
    print(f"  Sharpe Ratio: {metrics['sharpe']:6.2f}")
    print(f"  Avg Win:      {metrics['avg_w']:+.2f}%  | Avg Loss: {metrics['avg_l']:+.2f}%")
    print(f"  Expectancy:   {metrics['exp%']:+.2f}%/trade")

    reasons = {}
    for t in trades:
        r = t["reason"]
        reasons[r] = reasons.get(r, 0) + 1
    print(f"  Exits:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"    {r:20s}: {c:3d} ({c/len(trades)*100:5.1f}%)")

    print(f"  Sample (last 3):")
    for t in trades[-3:]:
        print(f"    {str(t['entry_t'])[:16]} -> {str(t['exit_t'])[:16]} | "
              f"{t['dir']:5s} | PnL: {t['pnl%']:+7.3f}% | {t['reason']}")


def main():
    print("="*70)
    print("  MEME MOMENTUM STRATEGY — STANDALONE BACKTEST")
    print("  Data: Bitget (via ccxt) | Strategy: Momentum Breakout + Volume-Price")
    print("="*70)

    all_metrics = []

    # ── 1H ──────────────────────────────────────────────────────────────
    doge_1h_path = os.path.join(DATA_DIR, "doge_1h_bitget.json")
    if not os.path.exists(doge_1h_path):
        doge_1h_path = os.path.join(DATA_DIR, "doge_1h.json")
    print(f"\n  Data file: {os.path.basename(doge_1h_path)}")
    doge_1h = load_data(doge_1h_path)
    doge_1h = add_indicators(doge_1h)
    print(f"  DOGE 1H: {len(doge_1h)} bars | {doge_1h.index[0].strftime('%Y-%m-%d')} ~ {doge_1h.index[-1].strftime('%Y-%m-%d')}")

    print("\n  ── DOGE Mom Long (1H) ──")
    trades_l = run_meme(doge_1h, "long")
    m = calc_metrics(trades_l)
    m["name"] = "DOGE Mom Long  (1H)"
    all_metrics.append(m)
    print_report("DOGE Mom Long  (1H)", trades_l, m)

    print("\n  ── DOGE Mom Short (1H) ──")
    trades_s = run_meme(doge_1h, "short")
    m = calc_metrics(trades_s)
    m["name"] = "DOGE Mom Short (1H)"
    all_metrics.append(m)
    print_report("DOGE Mom Short (1H)", trades_s, m)

    # ── 1D ──────────────────────────────────────────────────────────────
    doge_1d_path = os.path.join(DATA_DIR, "doge_1d_bitget.json")
    if not os.path.exists(doge_1d_path):
        doge_1d_path = os.path.join(DATA_DIR, "doge_1d.json")
    print(f"\n  Data file: {os.path.basename(doge_1d_path)}")
    doge_1d = load_data(doge_1d_path)
    doge_1d = add_indicators(doge_1d)
    print(f"  DOGE 1D: {len(doge_1d)} bars | {doge_1d.index[0].strftime('%Y-%m-%d')} ~ {doge_1d.index[-1].strftime('%Y-%m-%d')}")

    print("\n  ── DOGE Mom Long (1D) ──")
    trades_ld = run_meme(doge_1d, "long", warmup=50)
    m = calc_metrics(trades_ld)
    m["name"] = "DOGE Mom Long  (1D)"
    all_metrics.append(m)
    print_report("DOGE Mom Long  (1D)", trades_ld, m)

    print("\n  ── DOGE Mom Short (1D) ──")
    trades_sd = run_meme(doge_1d, "short", warmup=50)
    m = calc_metrics(trades_sd)
    m["name"] = "DOGE Mom Short (1D)"
    all_metrics.append(m)
    print_report("DOGE Mom Short (1D)", trades_sd, m)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  MEME MOMENTUM — METRICS SUMMARY")
    print(f"{'='*70}")
    print(f"{'Strategy':<22s} {'Trades':>6s} {'Win%':>7s} {'PnL%':>8s} {'PF':>6s} {'MDD%':>7s} {'Sharpe':>7s} {'Exp%':>7s}")
    print(f"{'─'*22} {'─'*6} {'─'*7} {'─'*8} {'─'*6} {'─'*7} {'─'*7} {'─'*7}")
    for m in all_metrics:
        print(f"{m['name']:<22s} {m['trades']:>6d} {m['win%']:>6.1f}% {m['pnl%']:>+7.2f}% {m['pf']:>5.2f} {m['mdd%']:>6.2f}% {m['sharpe']:>6.2f} {m['exp%']:>+6.2f}%")

    return all_metrics


if __name__ == "__main__":
    main()
