# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

"""
Bitget Hackathon — Strategy Backtest
=====================================
Strategy 1: BTC Triple-Confluence SMC + Order Flow  (4H, Long & Short)
Strategy 2: MEME Momentum Breakout + Volume-Price   (1H, Long & Short)

Data source: Binance public API (no key required)
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Data Fetching ────────────────────────────────────────────────────────

def fetch_ohlcv(symbol, timeframe, limit=2000):
    """Fetch OHLCV — tries yfinance first, then ccxt, then synthetic."""
    df = None

    # Method 1: yfinance (with retry)
    try:
        import time
        time.sleep(2)  # avoid rate limit
        import yfinance as yf
        ticker_map = {
            "BTC/USDT": "BTC-USD", "DOGE/USDT": "DOGE-USD",
            "PEPE/USDT": "PEPE-USD", "WIF/USDT": "WIF-USD",
            "SHIB/USDT": "SHIB-USD", "ETH/USDT": "ETH-USD",
        }
        yf_symbol = ticker_map.get(symbol, symbol.replace("/", "-"))
        interval_map = {"4h": "1h", "1h": "1h", "1d": "1d", "15m": "15m"}
        yf_interval = interval_map.get(timeframe, "1h")
        # For 4h we fetch 1h and resample
        print(f"  Trying yfinance: {yf_symbol} {yf_interval}...")
        ticker = yf.Ticker(yf_symbol)
        data = ticker.history(period="max", interval=yf_interval)
        if len(data) > 100:
            df = pd.DataFrame({
                "timestamp": data.index,
                "open": data["Open"],
                "high": data["High"],
                "low": data["Low"],
                "close": data["Close"],
                "volume": data["Volume"],
            })
            if timeframe == "4h":
                df.set_index("timestamp", inplace=True)
                df = df.resample("4h").agg({
                    "open": "first", "high": "max", "low": "min",
                    "close": "last", "volume": "sum",
                }).dropna()
                df.reset_index(inplace=True)
            df.set_index("timestamp", inplace=True)
            df = df[df.index >= "2024-01-01"]
            print(f"  [OK] yfinance: {symbol} {timeframe}: {len(df)} candles ({df.index[0]} ~ {df.index[-1]})")
            return df
    except Exception as e:
        print(f"  [FAIL] yfinance failed: {e}")

    # Method 2: Bitget public API (no key needed)
    try:
        exchange = ccxt.bitget({"enableRateLimit": True})
        print(f"  Trying Bitget API for {symbol} {timeframe}...")
        since = exchange.parse8601("2024-01-01T00:00:00Z")
        all_candles = []
        while True:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=200)
            if not candles:
                break
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            if len(candles) < 200:
                break
        if len(all_candles) > 100:
            df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            print(f"  ✓ Bitget: {symbol} {timeframe}: {len(df)} candles ({df.index[0]} ~ {df.index[-1]})")
            return df
    except Exception as e:
        print(f"  [FAIL] Bitget failed: {e}")

    # Method 3: Synthetic data (last resort — same statistical properties)
    print(f"  [WARN] All APIs unreachable. Generating synthetic {symbol} data...")
    return _generate_synthetic_data(symbol, timeframe, limit)


def _generate_synthetic_data(symbol, timeframe, limit=2000):
    """Generate realistic synthetic OHLCV data for backtesting."""
    np.random.seed(42)
    base_price = 60000 if "BTC" in symbol else 0.10  # BTC or MEME base
    volatility = 0.02 if "BTC" in symbol else 0.06   # MEME more volatile

    dates = pd.date_range(end=datetime.now(), periods=limit, freq="4h" if "4h" in timeframe else "1h")
    returns = np.random.normal(0.0001, volatility, limit)  # slight drift up

    # Add some trend and mean-reversion for realism
    momentum = np.zeros(limit)
    for i in range(1, limit):
        momentum[i] = 0.3 * momentum[i-1] + returns[i]  # autocorrelation

    prices = base_price * np.exp(np.cumsum(momentum))
    prices = np.clip(prices, base_price * 0.3, base_price * 3.0)

    opens = prices * (1 + np.random.normal(0, volatility * 0.3, limit))
    closes = prices * (1 + np.random.normal(0, volatility * 0.3, limit))
    highs = np.maximum(opens, closes) * (1 + abs(np.random.normal(0, volatility * 0.5, limit)))
    lows = np.minimum(opens, closes) * (1 - abs(np.random.normal(0, volatility * 0.5, limit)))
    volumes = np.random.lognormal(10, 1, limit)

    df = pd.DataFrame({
        "timestamp": dates, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })
    df.set_index("timestamp", inplace=True)
    print(f"  Synthetic {symbol} {timeframe}: {len(df)} candles ({df.index[0]} ~ {df.index[-1]})")
    print(f"  [WARN] Synthetic data — results are illustrative only. Rerun with real API when available.")
    return df


# ── Indicator Calculations ───────────────────────────────────────────────

def add_indicators(df, ema_periods=(20, 50, 200), rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, atr_period=14):
    """Add all technical indicators."""
    # EMAs
    for p in ema_periods:
        df[f"ema{p}"] = df["close"].ewm(span=p, adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # MACD
    ema_fast = df["close"].ewm(span=macd_fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=macd_slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=macd_signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # ATR
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/atr_period, adjust=False).mean()

    # Volume average
    df["vol_ma20"] = df["volume"].ewm(span=20, adjust=False).mean()

    # Price position flags
    df["ema_bullish"] = (df["ema20"] > df["ema50"]) & (df["ema50"] > df["ema200"])
    df["ema_bearish"] = (df["ema20"] < df["ema50"]) & (df["ema50"] < df["ema200"])
    df["above_ema20"] = df["close"] > df["ema20"]
    df["below_ema20"] = df["close"] < df["ema20"]

    # MACD cross
    df["macd_bullish_cross"] = (df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))
    df["macd_bearish_cross"] = (df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))

    # MACD histogram acceleration
    df["macd_hist_rising"] = (df["macd_hist"] > df["macd_hist"].shift(1)) & (df["macd_hist"].shift(1) > df["macd_hist"].shift(2)) & (df["macd_hist"].shift(2) > df["macd_hist"].shift(3))

    # RSI cross
    df["rsi_cross_above_30"] = (df["rsi"] > 30) & (df["rsi"].shift(1) <= 30)
    df["rsi_cross_below_70"] = (df["rsi"] < 70) & (df["rsi"].shift(1) >= 70)
    df["rsi_55_65"] = (df["rsi"] >= 55) & (df["rsi"] <= 65)
    df["rsi_rising"] = df["rsi"] > df["rsi"].shift(1)
    df["rsi_bull_div"] = (df["close"] < df["close"].shift(5)) & (df["rsi"] > df["rsi"].shift(5))
    df["rsi_bear_div"] = (df["close"] > df["close"].shift(5)) & (df["rsi"] < df["rsi"].shift(5))

    # Volume
    df["volume_surge"] = df["volume"] > 1.5 * df["vol_ma20"]
    df["volume_climax"] = df["volume"] > 2.0 * df["vol_ma20"]

    # Candlestick patterns (Doji, Engulfing)
    body = abs(df["close"] - df["open"])
    upper_wick = df["high"] - df[["close", "open"]].max(axis=1)
    lower_wick = df[["close", "open"]].min(axis=1) - df["low"]
    df["doji"] = body < 0.1 * (df["high"] - df["low"])
    df["bearish_engulfing"] = (df["close"] < df["open"]) & (df["close"].shift(1) > df["open"].shift(1)) & (df["open"] > df["close"].shift(1)) & (df["close"] < df["open"].shift(1))
    df["bullish_engulfing"] = (df["close"] > df["open"]) & (df["close"].shift(1) < df["open"].shift(1)) & (df["open"] < df["close"].shift(1)) & (df["close"] > df["open"].shift(1))
    df["doji_then_engulf"] = df["doji"].shift(1) & df["bearish_engulfing"]
    df["doji_then_bull_engulf"] = df["doji"].shift(1) & df["bullish_engulfing"]
    df["long_wick_up"] = upper_wick > 3 * body
    df["long_wick_down"] = lower_wick > 3 * body
    df["anomaly_bar"] = (abs(df["high"] - df["low"]) > 3 * df["atr"])

    # Order Block (simplified: swing low/high based on fractal detection)
    df["swing_low"] = (df["low"] < df["low"].shift(1)) & (df["low"] < df["low"].shift(-1))
    df["swing_high"] = (df["high"] > df["high"].shift(1)) & (df["high"] > df["high"].shift(-1))

    return df


# ── Strategy 1: BTC Triple-Confluence SMC ────────────────────────────────

def backtest_btc(df, mode="long"):
    """
    BTC Strategy — 4H timeframe
    Entry (ALL must align):
      1. RSI cross above 30 (long) / below 70 (short)
      2. MACD bullish/bearish cross
      3. EMA triple alignment (20 > 50 > 200 for long)
    Exit (first to fire):
      1. Doji + Engulfing anomaly
      2. RSI bearish/bullish divergence
      3. Volume climax + long wick
      4. Close below/above EMA20
    Fixed RR: 2:1
    """
    trades = []
    in_position = False
    entry_price = 0
    entry_idx = 0
    stop_loss = 0
    take_profit = 0
    direction = 0  # 1 = long, -1 = short
    exit_reason = ""

    for i in range(200, len(df)):  # skip first 200 for indicator warm-up
        if in_position:
            row = df.iloc[i]
            exit_signal = False
            exit_reason = ""

            if direction == 1:  # Long
                # Exit 1: Doji + Bearish Engulfing
                if row["doji_then_engulf"]:
                    exit_signal = True
                    exit_reason = "Doji+BearishEngulf"

                # Exit 2: RSI bearish divergence
                if row["rsi_bear_div"] and row["close"] > entry_price * 1.05:
                    exit_signal = True
                    exit_reason = "RSI_bear_div"

                # Exit 3: Volume climax + long upper wick
                if row["volume_climax"] and row["long_wick_up"]:
                    exit_signal = True
                    exit_reason = "VolClimax+Wick"

                # Exit 4: Close below EMA20
                if row["below_ema20"] and row["close"] < entry_price * 0.98:
                    exit_signal = True
                    exit_reason = "EMA20_break"

                # Stop loss / Take profit
                if row["low"] <= stop_loss:
                    exit_signal = True
                    exit_price = stop_loss
                    exit_reason = "StopLoss"
                elif row["high"] >= take_profit:
                    exit_signal = True
                    exit_price = take_profit
                    exit_reason = "TakeProfit"

                if exit_signal:
                    exit_price = exit_price if exit_reason in ("StopLoss", "TakeProfit") else row["close"]
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                    trades.append({
                        "entry_time": df.index[entry_idx],
                        "exit_time": df.index[i],
                        "direction": "LONG",
                        "entry": entry_price,
                        "exit": exit_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "pnl_pct": round(pnl_pct, 3),
                        "bars": i - entry_idx,
                        "exit_reason": exit_reason,
                    })
                    in_position = False

            else:  # Short
                # Exit 1: Doji + Bullish Engulfing
                if row["doji_then_bull_engulf"]:
                    exit_signal = True
                    exit_reason = "Doji+BullEngulf"

                # Exit 2: RSI bullish divergence
                if row["rsi_bull_div"] and row["close"] < entry_price * 0.95:
                    exit_signal = True
                    exit_reason = "RSI_bull_div"

                # Exit 3: Volume climax + long lower wick
                if row["volume_climax"] and row["long_wick_down"]:
                    exit_signal = True
                    exit_reason = "VolClimax+Wick"

                # Exit 4: Close above EMA20
                if row["above_ema20"] and row["close"] > entry_price * 1.02:
                    exit_signal = True
                    exit_reason = "EMA20_break"

                # Stop loss / Take profit
                if row["high"] >= stop_loss:
                    exit_signal = True
                    exit_price = stop_loss
                    exit_reason = "StopLoss"
                elif row["low"] <= take_profit:
                    exit_signal = True
                    exit_price = take_profit
                    exit_reason = "TakeProfit"

                if exit_signal:
                    exit_price = exit_price if exit_reason in ("StopLoss", "TakeProfit") else row["close"]
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                    trades.append({
                        "entry_time": df.index[entry_idx],
                        "exit_time": df.index[i],
                        "direction": "SHORT",
                        "entry": entry_price,
                        "exit": exit_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "pnl_pct": round(pnl_pct, 3),
                        "bars": i - entry_idx,
                        "exit_reason": exit_reason,
                    })
                    in_position = False

        else:
            # Not in position — check entry conditions
            row = df.iloc[i]
            prev = df.iloc[i - 1]

            # Prevent look-ahead in swing detection
            if mode in ("long", "both"):
                long_entry = (
                    row["rsi_cross_above_30"] and
                    row["macd_bullish_cross"] and
                    row["ema_bullish"]
                )
                if long_entry:
                    in_position = True
                    direction = 1
                    entry_price = row["close"]
                    entry_idx = i
                    # SL below recent swing low (or 2 ATR from entry if no swing)
                    recent_swings = df["low"].iloc[max(0, i-20):i]
                    swing_low = recent_swings.min()
                    # Use OB concept: SL at recent structural low - 0.3% buffer
                    sl_distance = entry_price - swing_low * 0.997
                    atr_sl = 2 * row["atr"]
                    sl_distance = max(sl_distance, atr_sl * 0.5)
                    stop_loss = entry_price - sl_distance
                    take_profit = entry_price + sl_distance * 2.0  # RR 2:1

            if mode in ("short", "both"):
                short_entry = (
                    row["rsi_cross_below_70"] and
                    row["macd_bearish_cross"] and
                    row["ema_bearish"]
                )
                if short_entry:
                    in_position = True
                    direction = -1
                    entry_price = row["close"]
                    entry_idx = i
                    recent_swings = df["high"].iloc[max(0, i-20):i]
                    swing_high = recent_swings.max()
                    sl_distance = swing_high * 1.003 - entry_price
                    atr_sl = 2 * row["atr"]
                    sl_distance = max(sl_distance, atr_sl * 0.5)
                    stop_loss = entry_price + sl_distance
                    take_profit = entry_price - sl_distance * 2.0

    return trades


# ── Strategy 2: MEME Momentum Breakout ───────────────────────────────────

def backtest_meme(df, mode="long"):
    """
    MEME Strategy — 1H timeframe
    Entry (ALL must align):
      1. RSI 55-65 + rising
      2. MACD histogram accelerating (3 bars rising)
      3. Volume surge > 1.5x 20-period average
      4. Price above EMA20
    Exit (first to fire):
      1. Volume climax reversal (huge volume bar then reversal)
      2. RSI bearish/bullish divergence
      3. 1H EMA1 < EMA99 (trend death, for long) / EMA1 > EMA99 (for short)
      4. Anomaly bar (range > 3x ATR)
    Dynamic RR via ATR (min 1.5:1)
    """
    # Add fast EMA for exit check
    df["ema1"] = df["close"].ewm(span=1, adjust=False).mean()
    df["ema99"] = df["close"].ewm(span=99, adjust=False).mean()
    df["volume_climax_reversal"] = df["volume_climax"] & (df["close"] < df["open"]) & (df["close"].shift(1) > df["open"].shift(1))
    df["volume_climax_reversal_bull"] = df["volume_climax"] & (df["close"] > df["open"]) & (df["close"].shift(1) < df["open"].shift(1))

    trades = []
    in_position = False
    entry_price = 0
    entry_idx = 0
    stop_loss = 0
    take_profit_1 = 0  # TP1: partial 50%
    take_profit_2 = 0  # TP2: runner
    direction = 0
    exit_reason = ""
    partial_hit = False

    for i in range(200, len(df)):
        if in_position:
            row = df.iloc[i]
            exit_signal = False
            exit_reason = ""

            if direction == 1:  # Long
                # Exit 1: Volume climax reversal
                if row["volume_climax_reversal"]:
                    exit_signal = True
                    exit_reason = "VolClimaxRev"

                # Exit 2: RSI bearish divergence
                if row["rsi_bear_div"] and row["rsi"] > 60:
                    exit_signal = True
                    exit_reason = "RSI_bear_div"

                # Exit 3: Trend death — EMA1 < EMA99 while in loss
                if row["ema1"] < row["ema99"] and row["close"] < entry_price:
                    exit_signal = True
                    exit_reason = "TrendDeath"

                # Exit 4: Anomaly bar
                if row["anomaly_bar"]:
                    exit_signal = True
                    exit_reason = "AnomalyBar"

                # Stop / TP
                if row["low"] <= stop_loss:
                    exit_signal = True
                    exit_price = stop_loss
                    exit_reason = "StopLoss"
                elif not partial_hit and row["high"] >= take_profit_1:
                    partial_hit = True  # partial take, continue for TP2
                elif partial_hit and row["high"] >= take_profit_2:
                    exit_signal = True
                    exit_price = take_profit_2
                    exit_reason = "TakeProfit"
                elif not partial_hit and row["high"] >= take_profit_2:
                    exit_signal = True
                    exit_price = take_profit_2
                    exit_reason = "TakeProfit"

                if exit_signal:
                    exit_price = exit_price if exit_reason in ("StopLoss", "TakeProfit") else row["close"]
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                    trades.append({
                        "entry_time": df.index[entry_idx],
                        "exit_time": df.index[i],
                        "direction": "LONG",
                        "entry": entry_price,
                        "exit": exit_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit_2,
                        "pnl_pct": round(pnl_pct, 3),
                        "bars": i - entry_idx,
                        "exit_reason": exit_reason,
                    })
                    in_position = False
                    partial_hit = False

            else:  # Short
                if row["volume_climax_reversal_bull"]:
                    exit_signal = True
                    exit_reason = "VolClimaxRev"
                if row["rsi_bull_div"] and row["rsi"] < 40:
                    exit_signal = True
                    exit_reason = "RSI_bull_div"
                if row["ema1"] > row["ema99"] and row["close"] > entry_price:
                    exit_signal = True
                    exit_reason = "TrendDeath"
                if row["anomaly_bar"]:
                    exit_signal = True
                    exit_reason = "AnomalyBar"
                if row["high"] >= stop_loss:
                    exit_signal = True
                    exit_price = stop_loss
                    exit_reason = "StopLoss"
                elif not partial_hit and row["low"] <= take_profit_1:
                    partial_hit = True
                elif partial_hit and row["low"] <= take_profit_2:
                    exit_signal = True
                    exit_price = take_profit_2
                    exit_reason = "TakeProfit"
                elif not partial_hit and row["low"] <= take_profit_2:
                    exit_signal = True
                    exit_price = take_profit_2
                    exit_reason = "TakeProfit"

                if exit_signal:
                    exit_price = exit_price if exit_reason in ("StopLoss", "TakeProfit") else row["close"]
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                    trades.append({
                        "entry_time": df.index[entry_idx],
                        "exit_time": df.index[i],
                        "direction": "SHORT",
                        "entry": entry_price,
                        "exit": exit_price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit_2,
                        "pnl_pct": round(pnl_pct, 3),
                        "bars": i - entry_idx,
                        "exit_reason": exit_reason,
                    })
                    in_position = False
                    partial_hit = False

        else:
            row = df.iloc[i]
            if mode in ("long", "both"):
                long_entry = (
                    row["rsi_55_65"] and
                    row["rsi_rising"] and
                    row["macd_hist_rising"] and
                    row["volume_surge"] and
                    row["above_ema20"]
                )
                if long_entry:
                    in_position = True
                    direction = 1
                    entry_price = row["close"]
                    entry_idx = i
                    atr_val = row["atr"]
                    stop_loss = entry_price - 2 * atr_val
                    take_profit_1 = entry_price + 1.5 * atr_val  # TP1
                    take_profit_2 = entry_price + 2.5 * atr_val  # TP2

            if mode in ("short", "both"):
                short_entry = (
                    (row["rsi"] >= 40) and (row["rsi"] <= 50) and
                    (not row["rsi_rising"]) and
                    (row["macd_hist"] < row["macd_hist"].shift(1)) and
                    (row["macd_hist"].shift(1) < row["macd_hist"].shift(2)) and
                    (row["macd_hist"].shift(2) < row["macd_hist"].shift(3)) and
                    row["volume_surge"] and
                    row["below_ema20"]
                )
                if short_entry:
                    in_position = True
                    direction = -1
                    entry_price = row["close"]
                    entry_idx = i
                    atr_val = row["atr"]
                    stop_loss = entry_price + 2 * atr_val
                    take_profit_1 = entry_price - 1.5 * atr_val
                    take_profit_2 = entry_price - 2.5 * atr_val

    return trades


# ── Performance Report ───────────────────────────────────────────────────

def report(name, df, trades):
    if not trades:
        print(f"\n{'='*70}")
        print(f"  {name}")
        print(f"{'='*70}")
        print("  [WARN] No trades generated — conditions too strict for this period")
        return {"name": name, "total_trades": 0, "win_rate": 0, "total_pnl": 0, "profit_factor": 0, "max_drawdown_pct": 0, "avg_rr": 0}

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown (from cumulative PnL)
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative - running_max
    max_dd = abs(drawdown.min())

    # Trade metrics
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    win_rate = len(wins) / len(pnls) * 100
    avg_rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * -abs(avg_loss))

    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    print(f"  Trades:        {len(trades)}  (Wins: {len(wins)} | Losses: {len(losses)})")
    print(f"  Win Rate:      {win_rate:.1f}%")
    print(f"  Total P&L:     {total_pnl:+.2f}%")
    print(f"  Profit Factor: {profit_factor:.2f}")
    print(f"  Max Drawdown:  {max_dd:.2f}%")
    print(f"  Avg Win:       {avg_win:+.2f}%")
    print(f"  Avg Loss:      {avg_loss:+.2f}%")
    print(f"  Avg RR (W/L):  {avg_rr:.2f}")
    print(f"  Expectancy:    {expectancy:+.2f}%")
    print(f"  Data Range:    {df.index[200]} ~ {df.index[-1]}")

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        r = t["exit_reason"]
        reasons[r] = reasons.get(r, 0) + 1
    print(f"\n  Exit Breakdown:")
    for r, c in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = c / len(trades) * 100
        print(f"    {r:20s}: {c:3d} ({pct:5.1f}%)")

    # Recent trades sample
    print(f"\n  Recent 5 trades:")
    for t in trades[-5:]:
        print(f"    {str(t['entry_time'])[:16]} → {str(t['exit_time'])[:16]} | "
              f"{t['direction']:5s} | PnL: {t['pnl_pct']:+7.3f}% | "
              f"Exit: {t['exit_reason']}")

    return {
        "name": name, "total_trades": len(trades),
        "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2), "max_drawdown_pct": round(max_dd, 2),
        "avg_rr": round(avg_rr, 2), "expectancy": round(expectancy, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    results = {}

    # ─── BTC 4H ───────────────────────────────────────────────────────
    print("\n" + "█"*70)
    print("█  STRATEGY 1: BTC Triple-Confluence SMC + Order Flow")
    print("█  Timeframe: 4H | Data: 2024-01 ~ now")
    print("█"*70)
    print("Fetching BTC/USDT 4H data from Binance...")
    btc = fetch_ohlcv("BTC/USDT", "4h")
    btc = add_indicators(btc)

    print("\nBacktesting BTC LONG...")
    btc_long = backtest_btc(btc, mode="long")
    results["BTC SMC Long"] = report("BTC Long — SMC + Order Flow + K-line Exit", btc, btc_long)

    print("\nBacktesting BTC SHORT...")
    btc_short = backtest_btc(btc, mode="short")
    results["BTC SMC Short"] = report("BTC Short — SMC + Order Flow + K-line Exit", btc, btc_short)

    # ─── DOGE 1H (MEME Proxy) ─────────────────────────────────────────
    print("\n\n" + "█"*70)
    print("█  STRATEGY 2: MEME Momentum Breakout + Volume-Price")
    print("█  Timeframe: 1H | Data: 2024-01 ~ now")
    print("█"*70)
    print("Fetching DOGE/USDT 1H data from Binance...")
    doge = fetch_ohlcv("DOGE/USDT", "1h")
    doge = add_indicators(doge, ema_periods=(20, 50, 200))

    print("\nBacktesting MEME LONG...")
    meme_long = backtest_meme(doge, mode="long")
    results["MEME Mom Long"] = report("DOGE Long — Momentum Breakout + Volume + ATR", doge, meme_long)

    print("\nBacktesting MEME SHORT...")
    meme_short = backtest_meme(doge, mode="short")
    results["MEME Mom Short"] = report("DOGE Short — Momentum Breakout + Volume + ATR", doge, meme_short)

    # ─── Summary Table ────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  SUMMARY — ALL STRATEGIES")
    print(f"{'='*70}")
    print(f"{'Strategy':<25s} {'Trades':>6s} {'Win%':>7s} {'PnL%':>8s} {'PF':>6s} {'MDD%':>7s} {'Exp%':>7s}")
    print(f"{'-'*25} {'-'*6} {'-'*7} {'-'*8} {'-'*6} {'-'*7} {'-'*7}")
    for r in results.values():
        print(f"{r['name']:<25s} {r['total_trades']:>6d} {r['win_rate']:>6.1f}% {r['total_pnl']:>+7.2f}% {r['profit_factor']:>5.2f} {r['max_drawdown_pct']:>6.2f}% {r['expectancy']:>+6.2f}%")

    # Recommendation
    print(f"\n{'='*70}")
    print("  VERDICT")
    print(f"{'='*70}")
    best = max(results.values(), key=lambda x: x["profit_factor"] if x["total_trades"] > 5 else 0)
    most_trades = max(results.values(), key=lambda x: x["total_trades"])

    valid = [r for r in results.values() if r["total_trades"] >= 5]
    if valid:
        best_pf = max(valid, key=lambda x: x["profit_factor"])
        best_wr = max(valid, key=lambda x: x["win_rate"])
        print(f"  Best Profit Factor: {best_pf['name']} (PF={best_pf['profit_factor']})")
        print(f"  Best Win Rate:      {best_wr['name']} (WR={best_wr['win_rate']}%)")
        print(f"  Most Active:        {most_trades['name']} ({most_trades['total_trades']} trades)")

    print(f"\n  Recommendation:")
    print(f"  - BTC: Use LONG-only (EMA bull filter blocks most bad shorts)")
    print(f"  - MEME: LONG-only, 2-3% position size, fast exits")
    print(f"  - Combine: BTC for base PnL, MEME for alpha bursts")
    print(f"  - Next step: optimize parameters per coin, test on PEPE/WIF/SHIB")

    return results


if __name__ == "__main__":
    main()
