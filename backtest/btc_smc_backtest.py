# -*- coding: utf-8 -*-
"""
BTC SMC 独立回测
================
策略: BTC Triple-Confluence SMC + Order Flow
周期: 4H + 1D
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

    df["ema_bull"] = (df["ema20"] > df["ema50"]) & (c > df["ema50"])
    df["ema_bear"] = (df["ema20"] < df["ema50"]) & (c < df["ema50"])
    df["above_ema20"] = c > df["ema20"]
    df["below_ema20"] = c < df["ema20"]

    df["macd_bull_x"] = (df["macd"] > df["macd_sig"]) & (df["macd"].shift(1) <= df["macd_sig"].shift(1))
    df["macd_bear_x"] = (df["macd"] < df["macd_sig"]) & (df["macd"].shift(1) >= df["macd_sig"].shift(1))
    h0 = df["macd_hist"]
    df["macd_accel_up"] = (h0 > h0.shift(1)) & (h0.shift(1) > h0.shift(2)) & (h0.shift(2) > h0.shift(3))
    df["macd_accel_dn"] = (h0 < h0.shift(1)) & (h0.shift(1) < h0.shift(2)) & (h0.shift(2) < h0.shift(3))

    r = df["rsi"]
    df["rsi_rising"] = r > r.shift(1)
    df["rsi_r3"] = r > r.shift(3)
    df["rsi_f3"] = r < r.shift(3)
    df["rsi_bear_div"] = (c > c.shift(5)) & (r < r.shift(5))
    df["rsi_bull_div"] = (c < c.shift(5)) & (r > r.shift(5))

    body = (c - df["open"]).abs()
    upper_w = h - np.maximum(c, df["open"])
    lower_w = np.minimum(c, df["open"]) - l
    total_range = h - l
    df["doji"] = body < 0.1 * total_range
    df["bear_eng"] = (c < df["open"]) & (c.shift(1) > df["open"].shift(1)) & (df["open"] > c.shift(1)) & (c < df["open"].shift(1))
    df["bull_eng"] = (c > df["open"]) & (c.shift(1) < df["open"].shift(1)) & (df["open"] < c.shift(1)) & (c > df["open"].shift(1))
    df["doji_bear_eng"] = df["doji"].shift(1) & df["bear_eng"]
    df["doji_bull_eng"] = df["doji"].shift(1) & df["bull_eng"]
    df["long_wick_up"] = upper_w > 3 * body
    df["long_wick_dn"] = lower_w > 3 * body
    df["vol_climax_rev"] = df["vol_climax"] & (c < df["open"]) & (c.shift(1) > df["open"].shift(1))

    return df


def run_smc(df, direction="long", warmup=250):
    trades = []
    pos = 0
    entry_px = sl = tp = 0
    entry_i = 0

    for i in range(warmup, len(df)):
        row = df.iloc[i]

        if pos != 0:
            exit_px = row["close"]
            reason = ""

            if pos == 1:
                if row["low"] <= sl:     exit_px = sl; reason = "StopLoss"
                elif row["high"] >= tp:   exit_px = tp; reason = "TakeProfit"
                elif row["doji_bear_eng"]: reason = "Doji+BearEng"
                elif row["rsi_bear_div"] and row["close"] > entry_px * 1.05: reason = "RSI_BearDiv"
                elif row["vol_climax"] and row["long_wick_up"]: reason = "VolClimax+Wick"
                elif row["below_ema20"] and row["close"] < entry_px * 0.98: reason = "EMA20_Break"
                else: continue
            else:
                if row["high"] >= sl:     exit_px = sl; reason = "StopLoss"
                elif row["low"] <= tp:    exit_px = tp; reason = "TakeProfit"
                elif row["doji_bull_eng"]: reason = "Doji+BullEng"
                elif row["rsi_bull_div"] and row["close"] < entry_px * 0.95: reason = "RSI_BullDiv"
                elif row["vol_climax"] and row["long_wick_dn"]: reason = "VolClimax+Wick"
                elif row["above_ema20"] and row["close"] > entry_px * 1.02: reason = "EMA20_Break"
                else: continue

            pnl = (exit_px - entry_px) / entry_px * 100 if pos == 1 else (entry_px - exit_px) / entry_px * 100
            trades.append({
                "entry_t": df.index[entry_i], "exit_t": df.index[i],
                "dir": "LONG" if pos == 1 else "SHORT",
                "entry": entry_px, "exit": exit_px, "pnl%": round(pnl, 3),
                "bars": i - entry_i, "reason": reason,
            })
            pos = 0
            continue

        if direction in ("long", "both"):
            macd_bullish = row["macd"] > row["macd_sig"]
            if row["rsi_r3"] and row["rsi_rising"] and macd_bullish and row["ema_bull"]:
                pos, entry_px, entry_i = 1, row["close"], i
                swing_low = df["low"].iloc[max(0,i-20):i].min()
                sl_dist = max(entry_px - swing_low * 0.997, 1.0 * row["atr"])
                sl, tp = entry_px - sl_dist, entry_px + sl_dist * 2.0

        if direction in ("short", "both") and pos == 0:
            macd_bearish = row["macd"] < row["macd_sig"]
            if row["rsi_f3"] and (not row["rsi_rising"]) and macd_bearish and row["ema_bear"]:
                pos, entry_px, entry_i = -1, row["close"], i
                swing_high = df["high"].iloc[max(0,i-20):i].max()
                sl_dist = max(swing_high * 1.003 - entry_px, 1.0 * row["atr"])
                sl, tp = entry_px + sl_dist, entry_px - sl_dist * 2.0

    return trades


def calc_metrics(trades):
    """Calculate complete backtest metrics including Sharpe ratio."""
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

    # Sharpe ratio (annualized, assuming 0% risk-free rate)
    rets = np.array(pnls) / 100
    if len(rets) > 1 and rets.std() > 0:
        sharpe = (rets.mean() / rets.std())
        # Annualize: 4H ≈ 2190 bars/yr, 1D ≈ 365 bars/yr → use sqrt of trades/day estimate
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
    print("  BTC SMC STRATEGY — STANDALONE BACKTEST")
    print("  Data: Bitget (via ccxt) | Strategy: Triple-Confluence SMC + Order Flow")
    print("="*70)

    all_metrics = []

    # ── 4H ──────────────────────────────────────────────────────────────
    btc_4h_path = os.path.join(DATA_DIR, "btc_4h_bitget.json")
    if not os.path.exists(btc_4h_path):
        btc_4h_path = os.path.join(DATA_DIR, "btc_4h.json")
    print(f"\n  Data file: {os.path.basename(btc_4h_path)}")
    btc_4h = load_data(btc_4h_path)
    btc_4h = add_indicators(btc_4h)
    print(f"  BTC 4H: {len(btc_4h)} bars | {btc_4h.index[0].strftime('%Y-%m-%d')} ~ {btc_4h.index[-1].strftime('%Y-%m-%d')}")

    print("\n  ── BTC SMC Long (4H) ──")
    trades_l = run_smc(btc_4h, "long")
    m = calc_metrics(trades_l)
    m["name"] = "BTC SMC Long  (4H)"
    all_metrics.append(m)
    print_report("BTC SMC Long  (4H)", trades_l, m)

    print("\n  ── BTC SMC Short (4H) ──")
    trades_s = run_smc(btc_4h, "short")
    m = calc_metrics(trades_s)
    m["name"] = "BTC SMC Short (4H)"
    all_metrics.append(m)
    print_report("BTC SMC Short (4H)", trades_s, m)

    # ── 1D ──────────────────────────────────────────────────────────────
    btc_1d_path = os.path.join(DATA_DIR, "btc_1d_bitget.json")
    if not os.path.exists(btc_1d_path):
        btc_1d_path = os.path.join(DATA_DIR, "btc_1d.json")
    print(f"\n  Data file: {os.path.basename(btc_1d_path)}")
    btc_1d = load_data(btc_1d_path)
    btc_1d = add_indicators(btc_1d)
    print(f"  BTC 1D: {len(btc_1d)} bars | {btc_1d.index[0].strftime('%Y-%m-%d')} ~ {btc_1d.index[-1].strftime('%Y-%m-%d')}")

    print("\n  ── BTC SMC Long (1D) ──")
    trades_ld = run_smc(btc_1d, "long", warmup=50)
    m = calc_metrics(trades_ld)
    m["name"] = "BTC SMC Long  (1D)"
    all_metrics.append(m)
    print_report("BTC SMC Long  (1D)", trades_ld, m)

    print("\n  ── BTC SMC Short (1D) ──")
    trades_sd = run_smc(btc_1d, "short", warmup=50)
    m = calc_metrics(trades_sd)
    m["name"] = "BTC SMC Short (1D)"
    all_metrics.append(m)
    print_report("BTC SMC Short (1D)", trades_sd, m)

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  BTC SMC — METRICS SUMMARY")
    print(f"{'='*70}")
    print(f"{'Strategy':<22s} {'Trades':>6s} {'Win%':>7s} {'PnL%':>8s} {'PF':>6s} {'MDD%':>7s} {'Sharpe':>7s} {'Exp%':>7s}")
    print(f"{'─'*22} {'─'*6} {'─'*7} {'─'*8} {'─'*6} {'─'*7} {'─'*7} {'─'*7}")
    for m in all_metrics:
        print(f"{m['name']:<22s} {m['trades']:>6d} {m['win%']:>6.1f}% {m['pnl%']:>+7.2f}% {m['pf']:>5.2f} {m['mdd%']:>6.2f}% {m['sharpe']:>6.2f} {m['exp%']:>+6.2f}%")

    return all_metrics


if __name__ == "__main__":
    main()
