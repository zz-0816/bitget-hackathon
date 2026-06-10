"""Perception layer: data structures and technical indicator calculation."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import numpy as np
import pandas as pd


# ── Data Structures ────────────────────────────────────────────────────────

@dataclass
class MarketData:
    """OHLCV snapshot for a single symbol/timeframe."""
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime
    # Computed indicators are added by the perception layer
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    atr: Optional[float] = None
    ema_fast: Optional[float] = None
    ema_mid: Optional[float] = None
    ema_slow: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    volume_surge: bool = False


@dataclass
class SentimentSnapshot:
    """Aggregated sentiment data from external sources."""
    fear_greed_index: int = 50
    fear_greed_label: str = "neutral"
    social_volume_change: float = 0.0
    long_short_ratio: float = 1.0
    taker_buy_ratio: float = 0.5
    reddit_trending: bool = False
    source_timestamp: Optional[datetime] = None


@dataclass
class MacroSnapshot:
    """Macro-economic indicators snapshot."""
    cpi_yoy: Optional[float] = None
    fed_funds_rate: Optional[float] = None
    dxy: Optional[float] = None
    gold_price: Optional[float] = None
    btc_dominance: Optional[float] = None
    us10y_yield: Optional[float] = None
    source_timestamp: Optional[datetime] = None


@dataclass
class PerceptionReport:
    """Complete perception output fed into the decision layer."""
    timestamp: datetime
    primary: MarketData
    secondary: Optional[MarketData] = None  # higher timeframe confirmation
    sentiment: Optional[SentimentSnapshot] = None
    macro: Optional[MacroSnapshot] = None
    # Summary flags
    trend_bullish: bool = False
    trend_bearish: bool = False
    volatility_regime: str = "normal"  # low / normal / high
    volume_regime: str = "normal"      # low / normal / surge / climax


# ── Indicator Functions ────────────────────────────────────────────────────

def calc_ema(series: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    alpha = 2 / (period + 1)
    result = np.zeros_like(series)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result


def calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    delta = np.diff(close, prepend=close[0])
    gain = np.maximum(delta, 0)
    loss = np.maximum(-delta, 0)
    avg_gain = np.zeros_like(close)
    avg_loss = np.zeros_like(close)
    avg_gain[period] = np.mean(gain[1:period + 1])
    avg_loss[period] = np.mean(loss[1:period + 1])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - 100 / (1 + rs)
    rsi[:period] = 50  # neutral before warmup
    return rsi


def calc_macd(close: np.ndarray, fast: int = 12, slow: int = 26,
              signal: int = 9) -> tuple:
    """MACD line, signal line, histogram."""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = calc_ema(macd_line, signal)
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist


def calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
             period: int = 14) -> np.ndarray:
    """Average True Range."""
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close),
                               np.abs(low - prev_close)))
    atr = np.zeros_like(close)
    atr[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, len(close)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    atr[:period] = tr[:period]  # raw TR before warmup
    return atr


def calc_bollinger(close: np.ndarray, period: int = 20,
                   std_mult: float = 2.0) -> tuple:
    """Bollinger Bands: upper, middle, lower."""
    sma = np.zeros_like(close)
    upper = np.zeros_like(close)
    lower = np.zeros_like(close)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1:i + 1]
        sma[i] = np.mean(window)
        std = np.std(window)
        upper[i] = sma[i] + std_mult * std
        lower[i] = sma[i] - std_mult * std
    return upper, sma, lower


def detect_volume_regime(volume: np.ndarray, period: int = 20,
                         surge_mult: float = 1.5) -> np.ndarray:
    """Classify volume regime: 0=normal, 1=surge, 2=climax."""
    vol_ma = calc_ema(volume, period)
    ratio = np.divide(volume, vol_ma, out=np.ones_like(volume, dtype=float), where=vol_ma > 0)
    regime = np.zeros(len(volume), dtype=int)
    regime[ratio > surge_mult] = 1     # surge
    regime[ratio > surge_mult * 1.5] = 2  # climax
    return regime


def compute_all_indicators(df: pd.DataFrame, config) -> pd.DataFrame:
    """Add all technical indicators to a DataFrame.

    Works on DataFrames with columns: open, high, low, close, volume.
    Uses configuration from AgentConfig for periods.
    """
    c, h, l, v = df["close"].values, df["high"].values, df["low"].values, df["volume"].values

    df = df.copy()
    df["ema_fast"] = calc_ema(c, config.btc_ema_fast)
    df["ema_mid"] = calc_ema(c, config.btc_ema_mid)
    df["ema_slow"] = calc_ema(c, 200)
    df["rsi"] = calc_rsi(c, config.btc_rsi_period)
    macd, macd_sig, macd_hist = calc_macd(
        c, config.btc_macd_fast, config.btc_macd_slow, config.btc_macd_signal)
    df["macd"] = macd
    df["macd_signal"] = macd_sig
    df["macd_hist"] = macd_hist
    df["atr"] = calc_atr(h, l, c, config.btc_atr_period)
    bb_u, bb_m, bb_l = calc_bollinger(c)
    df["bb_upper"] = bb_u
    df["bb_middle"] = bb_m
    df["bb_lower"] = bb_l
    vol_regime = detect_volume_regime(v)
    df["volume_regime"] = vol_regime
    df["volume_surge"] = vol_regime >= 1

    # Derived signals
    df["ema_bull"] = (df["ema_fast"] > df["ema_mid"]) & (c > df["ema_mid"])
    df["ema_bear"] = (df["ema_fast"] < df["ema_mid"]) & (c < df["ema_mid"])
    df["macd_bull"] = macd > macd_sig
    df["macd_bear"] = macd < macd_sig
    df["rsi_rising"] = df["rsi"] > df["rsi"].shift(1)

    return df


def build_perception_report(df: pd.DataFrame, symbol: str, timeframe: str,
                            sentiment: Optional[SentimentSnapshot] = None,
                            macro: Optional[MacroSnapshot] = None,
                            secondary_df: Optional[pd.DataFrame] = None,
                            secondary_tf: str = "1d") -> PerceptionReport:
    """Build a PerceptionReport from indicator-rich DataFrame and optional data."""
    latest = df.iloc[-1]
    primary = MarketData(
        symbol=symbol, timeframe=timeframe,
        open=float(latest["open"]), high=float(latest["high"]),
        low=float(latest["low"]), close=float(latest["close"]),
        volume=float(latest["volume"]),
        timestamp=df.index[-1] if hasattr(df.index[-1], 'to_pydatetime')
        else datetime.now(),
        rsi=float(latest.get("rsi", 0)),
        macd=float(latest.get("macd", 0)),
        macd_signal=float(latest.get("macd_signal", 0)),
        macd_hist=float(latest.get("macd_hist", 0)),
        atr=float(latest.get("atr", 0)),
        ema_fast=float(latest.get("ema_fast", 0)),
        ema_mid=float(latest.get("ema_mid", 0)),
        ema_slow=float(latest.get("ema_slow", 0)),
        bb_upper=float(latest.get("bb_upper", 0)),
        bb_middle=float(latest.get("bb_middle", 0)),
        bb_lower=float(latest.get("bb_lower", 0)),
        volume_surge=bool(latest.get("volume_surge", False)),
    )

    secondary = None
    if secondary_df is not None and len(secondary_df) > 0:
        s = secondary_df.iloc[-1]
        secondary = MarketData(
            symbol=symbol, timeframe=secondary_tf,
            open=float(s["open"]), high=float(s["high"]),
            low=float(s["low"]), close=float(s["close"]),
            volume=float(s["volume"]),
            timestamp=secondary_df.index[-1] if hasattr(secondary_df.index[-1], 'to_pydatetime')
            else datetime.now(),
        )

    trend_bullish = bool(latest.get("ema_bull", False))
    trend_bearish = bool(latest.get("ema_bear", False))

    vr = latest.get("volume_regime", 0)
    vol_map = {0: "normal", 1: "surge", 2: "climax"}
    volume_regime = vol_map.get(int(vr), "normal")

    atr_pct = float(latest.get("atr", 0)) / float(latest["close"]) * 100 if float(latest["close"]) > 0 else 0
    if atr_pct < 1:
        volatility_regime = "low"
    elif atr_pct < 3:
        volatility_regime = "normal"
    else:
        volatility_regime = "high"

    return PerceptionReport(
        timestamp=datetime.now(),
        primary=primary,
        secondary=secondary,
        sentiment=sentiment,
        macro=macro,
        trend_bullish=trend_bullish,
        trend_bearish=trend_bearish,
        volatility_regime=volatility_regime,
        volume_regime=volume_regime,
    )
