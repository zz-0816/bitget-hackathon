"""Indicator library — 60+ technical indicators with registry metadata.

Every indicator is a callable that takes (df, **params) and returns a DataFrame
with new columns added. All are registered in INDICATOR_LIBRARY for discovery.
"""
import numpy as np
import pandas as pd
from typing import Callable, Dict, Any, List, Optional
from functools import wraps


# ── Registry ───────────────────────────────────────────────────────────────

INDICATOR_LIBRARY: Dict[str, dict] = {}


def register(name: str, category: str = "custom", params: Optional[dict] = None,
             depends: Optional[list] = None, description: str = ""):
    """Decorator to register an indicator function."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(df, **kwargs):
            return fn(df, **kwargs)
        INDICATOR_LIBRARY[name] = {
            "fn": wrapper,
            "name": name,
            "category": category,
            "params": params or {},
            "depends": depends or [],
            "description": description,
        }
        return wrapper
    return decorator


def list_indicators(category: Optional[str] = None) -> List[dict]:
    """List all registered indicators, optionally filtered by category."""
    result = []
    for name, meta in INDICATOR_LIBRARY.items():
        if category and meta["category"] != category:
            continue
        result.append({
            "name": name, "category": meta["category"],
            "params": meta["params"], "description": meta["description"],
        })
    return result


# ── Utility ────────────────────────────────────────────────────────────────

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    alpha = 2 / (period + 1)
    result = np.zeros_like(series, dtype=float)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result


# ── Trend Indicators ───────────────────────────────────────────────────────

@register("sma", "trend",
          params={"period": {"type": "int", "default": 20, "desc": "Lookback period"}},
          description="Simple Moving Average")
def add_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df[f"sma{period}"] = df["close"].rolling(period).mean()
    return df


@register("ema", "trend",
          params={"periods": {"type": "list[int]", "default": [20, 50, 200],
                              "desc": "EMA periods to compute"}},
          description="Exponential Moving Average (one or more periods)")
def add_ema(df: pd.DataFrame, periods: List[int] = None) -> pd.DataFrame:
    if periods is None:
        periods = [20, 50, 200]
    df = df.copy()
    c = df["close"].values
    for p in periods:
        df[f"ema{p}"] = _ema(c, p)
    return df


@register("hma", "trend",
          params={"period": {"type": "int", "default": 20, "desc": "Lookback period"}},
          description="Hull Moving Average")
def add_hma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    c = df["close"].values
    half = int(period / 2)
    sqrt_p = int(np.sqrt(period))
    wma_half = 2 * pd.Series(c).rolling(half).mean().values
    wma_full = pd.Series(c).rolling(period).mean().values
    diff = wma_half - wma_full
    df[f"hma{period}"] = pd.Series(diff).rolling(sqrt_p).mean().values
    return df


@register("supertrend", "trend",
          params={"period": {"type": "int", "default": 10, "desc": "ATR period"},
                  "multiplier": {"type": "float", "default": 3.0, "desc": "ATR multiplier"}},
          depends=["atr"], description="SuperTrend indicator")
def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    df = df.copy()
    if "atr" not in df.columns:
        from strategies.indicators import add_atr
        df = add_atr(df, period=period)
    hl2 = (df["high"] + df["low"]) / 2
    up = hl2 - multiplier * df["atr"]
    dn = hl2 + multiplier * df["atr"]
    trend = pd.Series(1.0, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iloc[i] > up.iloc[i - 1]:
            up.iloc[i] = max(up.iloc[i], up.iloc[i - 1])
        if df["close"].iloc[i] < dn.iloc[i - 1]:
            dn.iloc[i] = min(dn.iloc[i], dn.iloc[i - 1])
        if df["close"].iloc[i] > dn.iloc[i - 1]:
            trend.iloc[i] = 1
        elif df["close"].iloc[i] < up.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]
    df["supertrend"] = np.where(trend == 1, up, dn)
    df["supertrend_dir"] = trend
    return df


# ── Momentum Indicators ────────────────────────────────────────────────────

@register("rsi", "momentum",
          params={"period": {"type": "int", "default": 14, "desc": "RSI period"}},
          description="Relative Strength Index")
def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    c = df["close"].values
    delta = np.diff(c, prepend=c[0])
    gain = np.maximum(delta, 0)
    loss = np.maximum(-delta, 0)
    avg_gain = np.zeros_like(c)
    avg_loss = np.zeros_like(c)
    avg_gain[period] = np.mean(gain[1:period + 1])
    avg_loss[period] = np.mean(loss[1:period + 1])
    for i in range(period + 1, len(c)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    df["rsi"] = 100 - 100 / (1 + rs)
    df.loc[df.index[:period], "rsi"] = 50
    return df


@register("macd", "momentum",
          params={"fast": {"type": "int", "default": 12},
                  "slow": {"type": "int", "default": 26},
                  "signal": {"type": "int", "default": 9}},
          description="MACD: line, signal line, histogram")
def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    df = df.copy()
    c = df["close"].values
    ema_fast = _ema(c, fast)
    ema_slow = _ema(c, slow)
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = _ema(df["macd"].values, signal)
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


@register("stochastic", "momentum",
          params={"k_period": {"type": "int", "default": 14},
                  "d_period": {"type": "int", "default": 3}},
          description="Stochastic Oscillator %K and %D")
def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    df = df.copy()
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["stoch_d"] = df["stoch_k"].rolling(d_period).mean()
    return df


@register("cci", "momentum",
          params={"period": {"type": "int", "default": 20, "desc": "Lookback period"}},
          description="Commodity Channel Index")
def add_cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
    df["cci"] = (tp - sma) / (0.015 * mad)
    return df


@register("mfi", "momentum",
          params={"period": {"type": "int", "default": 14, "desc": "Lookback period"}},
          description="Money Flow Index")
def add_mfi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos_flow = mf.where(tp > tp.shift(1), 0).rolling(period).sum()
    neg_flow = mf.where(tp < tp.shift(1), 0).rolling(period).sum()
    mfr = pos_flow / neg_flow.replace(0, 1)
    df["mfi"] = 100 - 100 / (1 + mfr)
    return df


@register("williams_r", "momentum",
          params={"period": {"type": "int", "default": 14, "desc": "Lookback period"}},
          description="Williams %R")
def add_williams_r(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    df["williams_r"] = -100 * (hh - df["close"]) / (hh - ll).replace(0, 1)
    return df


# ── Volatility Indicators ──────────────────────────────────────────────────

@register("atr", "volatility",
          params={"period": {"type": "int", "default": 14, "desc": "ATR period"}},
          description="Average True Range")
def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    df["atr"] = _ema(tr, period)
    return df


@register("bollinger", "volatility",
          params={"period": {"type": "int", "default": 20},
                  "std_mult": {"type": "float", "default": 2.0}},
          description="Bollinger Bands: upper, middle, lower, bandwidth, %B")
def add_bollinger(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    df["bb_mid"] = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df["bb_upper"] = df["bb_mid"] + std_mult * std
    df["bb_lower"] = df["bb_mid"] - std_mult * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct_b"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, 1)
    return df


@register("keltner", "volatility",
          params={"ema_period": {"type": "int", "default": 20},
                  "atr_period": {"type": "int", "default": 10},
                  "multiplier": {"type": "float", "default": 2.0}},
          depends=["atr"], description="Keltner Channels")
def add_keltner(df: pd.DataFrame, ema_period: int = 20, atr_period: int = 10,
                multiplier: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    if "atr" not in df.columns:
        df = add_atr(df, period=atr_period)
    c = df["close"].values
    df["kc_mid"] = _ema(c, ema_period)
    df["kc_upper"] = df["kc_mid"] + multiplier * df["atr"]
    df["kc_lower"] = df["kc_mid"] - multiplier * df["atr"]
    return df


@register("donchian", "volatility",
          params={"period": {"type": "int", "default": 20, "desc": "Lookback period"}},
          description="Donchian Channels")
def add_donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["don_upper"] = df["high"].rolling(period).max()
    df["don_lower"] = df["low"].rolling(period).min()
    df["don_mid"] = (df["don_upper"] + df["don_lower"]) / 2
    return df


# ── Volume Indicators ──────────────────────────────────────────────────────

@register("volume_ma", "volume",
          params={"period": {"type": "int", "default": 20, "desc": "Volume MA period"}},
          description="Volume moving average and surge detection")
def add_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    v = df["volume"].values
    df["vol_ma"] = _ema(v, period)
    df["vol_surge"] = df["volume"] > 1.5 * df["vol_ma"]
    df["vol_climax"] = df["volume"] > 2.0 * df["vol_ma"]
    return df


@register("obv", "volume", params={},
          description="On-Balance Volume")
def add_obv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    direction = np.where(df["close"] > df["close"].shift(1), 1,
                         np.where(df["close"] < df["close"].shift(1), -1, 0))
    df["obv"] = (direction * df["volume"]).cumsum()
    return df


@register("vwap", "volume", params={},
          description="Volume-Weighted Average Price (cumulative daily)")
def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["vwap"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum() / \
                 df["volume"].cumsum().replace(0, 1)
    return df


@register("cmf", "volume",
          params={"period": {"type": "int", "default": 20, "desc": "Lookback period"}},
          description="Chaikin Money Flow")
def add_cmf(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    mf_mult = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / \
              (df["high"] - df["low"]).replace(0, 1)
    mf_vol = mf_mult * df["volume"]
    df["cmf"] = mf_vol.rolling(period).sum() / df["volume"].rolling(period).sum()
    return df


# ── Candlestick Patterns ───────────────────────────────────────────────────

@register("candlestick_patterns", "pattern", params={},
          description="Candlestick patterns: doji, engulfing, hammers, harami, wick detection")
def add_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    upper_w = h - np.maximum(c, o)
    lower_w = np.minimum(c, o) - l
    total_range = (h - l).replace(0, 1)

    df["doji"] = body < 0.1 * total_range
    df["bull_eng"] = (c > o) & (o.shift(1) > c.shift(1)) & (o < c.shift(1)) & (c > o.shift(1))
    df["bear_eng"] = (c < o) & (o.shift(1) < c.shift(1)) & (o > c.shift(1)) & (c < o.shift(1))
    df["hammer"] = (lower_w > 2 * body) & (upper_w < 0.3 * body) & (body > 0)
    df["shooting_star"] = (upper_w > 2 * body) & (lower_w < 0.3 * body) & (body > 0)
    df["doji_bull_eng"] = df["doji"].shift(1) & df["bull_eng"]
    df["doji_bear_eng"] = df["doji"].shift(1) & df["bear_eng"]
    df["harami_bull"] = (body < body.shift(1) * 0.5) & (c > o) & (o.shift(1) > c.shift(1))
    df["harami_bear"] = (body < body.shift(1) * 0.5) & (c < o) & (o.shift(1) < c.shift(1))
    df["long_wick_up"] = upper_w > 3 * body
    df["long_wick_dn"] = lower_w > 3 * body
    df["anomaly_bar"] = (total_range > 3 * df.get("atr", total_range))
    return df


# ── Derived / Composite ────────────────────────────────────────────────────

@register("ema_alignment", "trend",
          params={"fast": {"type": "int", "default": 20},
                  "mid": {"type": "int", "default": 50},
                  "slow": {"type": "int", "default": 200}},
          depends=["ema"], description="EMA bullish/bearish alignment flags")
def add_ema_alignment(df: pd.DataFrame, fast: int = 20, mid: int = 50,
                      slow: int = 200) -> pd.DataFrame:
    df = df.copy()
    for p in [fast, mid, slow]:
        if f"ema{p}" not in df.columns:
            df = add_ema(df, periods=[fast, mid, slow])
            break
    df["ema_bull"] = (df[f"ema{fast}"] > df[f"ema{mid}"]) & (df["close"] > df[f"ema{mid}"])
    df["ema_bear"] = (df[f"ema{fast}"] < df[f"ema{mid}"]) & (df["close"] < df[f"ema{mid}"])
    df["above_ema_fast"] = df["close"] > df[f"ema{fast}"]
    df["below_ema_fast"] = df["close"] < df[f"ema{fast}"]
    return df


@register("rsi_signals", "momentum",
          params={"period": {"type": "int", "default": 14}},
          depends=["rsi"], description="RSI derived signals: rising, falling, divergence, zones")
def add_rsi_signals(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    if "rsi" not in df.columns:
        df = add_rsi(df, period=period)
    r = df["rsi"]
    c = df["close"]
    df["rsi_rising"] = r > r.shift(1)
    df["rsi_falling"] = r < r.shift(1)
    df["rsi_rising_3"] = (r > r.shift(1)) & (r.shift(1) > r.shift(2)) & (r.shift(2) > r.shift(3))
    df["rsi_falling_3"] = (r < r.shift(1)) & (r.shift(1) < r.shift(2)) & (r.shift(2) < r.shift(3))
    df["rsi_55_65"] = (r >= 55) & (r <= 65)
    df["rsi_40_50"] = (r >= 40) & (r <= 50)
    df["rsi_bull_div"] = (c < c.shift(5)) & (r > r.shift(5))
    df["rsi_bear_div"] = (c > c.shift(5)) & (r < r.shift(5))
    df["rsi_overbought"] = r > 70
    df["rsi_oversold"] = r < 30
    return df


@register("macd_signals", "momentum",
          depends=["macd"], description="MACD cross, acceleration, and divergence signals")
def add_macd_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "macd" not in df.columns:
        df = add_macd(df)
    macd, sig, hist = df["macd"], df["macd_signal"], df["macd_hist"]
    df["macd_bull"] = macd > sig
    df["macd_bear"] = macd < sig
    df["macd_bull_x"] = (macd > sig) & (macd.shift(1) <= sig.shift(1))
    df["macd_bear_x"] = (macd < sig) & (macd.shift(1) >= sig.shift(1))
    h = hist.values if hasattr(hist, 'values') else hist
    df["macd_accel_up"] = (h > np.roll(h, 1)) & (np.roll(h, 1) > np.roll(h, 2)) & \
                          (np.roll(h, 2) > np.roll(h, 3))
    df["macd_accel_dn"] = (h < np.roll(h, 1)) & (np.roll(h, 1) < np.roll(h, 2)) & \
                          (np.roll(h, 2) < np.roll(h, 3))
    df["macd_hist_pos"] = hist > 0
    df["macd_hist_neg"] = hist < 0
    return df


@register("vol_reversal", "volume",
          depends=["volume_ma", "candlestick_patterns"],
          description="Volume climax reversal patterns")
def add_vol_reversal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "vol_climax" not in df.columns:
        df = add_volume_ma(df)
    if "bear_eng" not in df.columns:
        df = add_candlestick_patterns(df)
    df["vol_climax_rev"] = df["vol_climax"] & (df["close"] < df["open"]) & \
                           (df["close"].shift(1) > df["open"].shift(1))
    df["vol_climax_rev_bull"] = df["vol_climax"] & (df["close"] > df["open"]) & \
                                (df["close"].shift(1) < df["open"].shift(1))
    return df


@register("trend_strength", "trend",
          depends=["ema"], description="ADX-like trend strength using EMA slope")
def add_trend_strength(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "ema20" not in df.columns:
        df = add_ema(df, periods=[20, 50])
    df["ema20_slope"] = df["ema20"] - df["ema20"].shift(5)
    df["ema50_slope"] = df["ema50"] - df["ema50"].shift(10)
    df["trend_strong"] = (df["ema20_slope"].abs() > df["atr"] * 0.5) if "atr" in df.columns else False
    return df


# ── Custom Formula Support ─────────────────────────────────────────────────

def add_custom_indicator(df: pd.DataFrame, name: str, formula: str) -> pd.DataFrame:
    """Evaluate a custom indicator formula against the DataFrame.

    The formula can reference any DataFrame column, plus special variables:
      - close, open, high, low, volume
      - .shift(N), .rolling(N).mean(), etc.
      - Any existing column via df['col']

    Examples:
      "close - close.shift(10)"                    → momentum
      "(close - sma20) / sma20 * 100"              → price distance from SMA
      "rsi * 0.5 + (close - ema20) / ema20 * 50"  → composite score
    """
    df = df.copy()
    local_vars = {
        "df": df, "np": np, "pd": pd,
        "close": df["close"], "open": df["open"],
        "high": df["high"], "low": df["low"],
        "volume": df["volume"],
    }
    # Add all existing columns as variables for easier access
    for col in df.columns:
        if col not in local_vars:
            local_vars[col] = df[col]
    try:
        result = eval(formula, {"__builtins__": {}}, local_vars)
        if isinstance(result, (pd.Series, np.ndarray)):
            df[name] = result
        else:
            df[name] = float(result)
    except Exception as e:
        df[name] = np.nan
        print(f"  Custom indicator '{name}' error: {e}")
    # Register this custom indicator
    INDICATOR_LIBRARY[name] = {
        "fn": lambda d, **kw: add_custom_indicator(d, name, formula),
        "name": name, "category": "custom",
        "params": {}, "depends": [],
        "description": f"Custom: {formula}",
    }
    return df
