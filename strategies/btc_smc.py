"""BTC Triple-Confluence SMC Strategy.

4H timeframe. Entry requires three confirmations:
  1. EMA alignment — EMA20 > EMA50 and price > EMA50 (bullish)
  2. MACD direction — MACD line > signal line (bullish)
  3. Volume surge — volume > 1.5x average

Exit on: RSI overbought/oversold, MACD cross, or EMA flip.
"""

import numpy as np
import pandas as pd
from typing import Optional, List

from .base import Strategy, Signal, SignalType
from .indicators import add_ema, add_rsi, add_macd, add_atr, add_volume_ma, add_ema_alignment


class BTCSMCStrategy(Strategy):
    """BTC Smart Money Concepts — triple-confluence entry on 4H.

    Parameters:
        ema_fast: fast EMA period (20)
        ema_mid:  mid EMA period (50)
        rsi_period: RSI period (14)
        rsi_long_min: RSI must be above this for long (45)
        rsi_short_max: RSI must be below this for short (55)
        macd_fast/slow/signal: MACD periods (12/26/9)
        atr_period: ATR period for stop/target calc (14)
        atr_sl_mult: stop-loss ATR multiplier (1.0)
        atr_tp_mult: take-profit ATR multiplier (2.0)
        vol_surge_mult: volume surge threshold (1.5)
    """

    name = "BTC_SMC"
    timeframe = "4h"
    params = {
        "ema_fast": 20, "ema_mid": 50,
        "rsi_period": 14, "rsi_long_min": 45, "rsi_short_max": 55,
        "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "atr_period": 14, "atr_sl_mult": 1.0, "atr_tp_mult": 2.0,
        "vol_surge_mult": 1.5,
    }

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return (df
                .pipe(add_ema, periods=[self.ema_fast, self.ema_mid, 200])
                .pipe(add_rsi, period=self.rsi_period)
                .pipe(add_macd, fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
                .pipe(add_atr, period=self.atr_period)
                .pipe(add_volume_ma, period=20)
                .pipe(add_ema_alignment, fast=self.ema_fast, mid=self.ema_mid, slow=200))

    @property
    def requires_indicators(self) -> List[str]:
        return ["ema", "rsi", "macd", "atr", "volume_ma", "ema_alignment"]

    def evaluate(self, df: pd.DataFrame,
                 positions: Optional[List[dict]] = None) -> Signal:
        latest = df.iloc[-1]
        has_position = any(
            pos.get("symbol") == self.symbol and float(pos.get("total", 0)) > 0
            for pos in (positions or [])
        )

        if not has_position:
            return self._check_entry(latest, df)

        return self._check_exit(latest, df, positions)

    def _check_entry(self, latest, df) -> Signal:
        close = float(latest["close"])
        rsi = float(latest.get("rsi", 50))
        macd = float(latest.get("macd", 0))
        macd_signal = float(latest.get("macd_signal", 0))
        atr = float(latest.get("atr", 0))
        ema_bull = bool(latest.get("ema_bull", False))
        ema_bear = bool(latest.get("ema_bear", False))
        vol_surge = bool(latest.get("vol_surge", False))

        # ── Long entry ────────────────────────────────────────────
        if (rsi >= self.rsi_long_min and rsi <= 65 and
                macd > macd_signal and ema_bull and vol_surge):
            sl = close - self.atr_sl_mult * atr if atr > 0 else close * 0.98
            tp = close + self.atr_tp_mult * atr if atr > 0 else close * 1.04
            rr = (tp - close) / (close - sl) if (close - sl) > 0 else 0
            confidence = min(0.9, 0.5 + 0.1 * rr + 0.1 * (rsi - 45) / 20)
            if self._higher_tf_confirms(df):
                confidence = min(1.0, confidence + 0.1)
            return Signal(
                type=SignalType.ENTRY_LONG, symbol=self.symbol,
                confidence=round(confidence, 2),
                reason=f"BTC SMC: RSI={rsi:.1f}, MACD bullish, EMA aligned, vol surge",
                entry_price=close, stop_loss=round(sl, 1),
                take_profit=round(tp, 1), strategy=self.name,
            )

        # ── Short entry ───────────────────────────────────────────
        if (rsi <= self.rsi_short_max and rsi >= 35 and
                macd < macd_signal and ema_bear and vol_surge):
            sl = close + self.atr_sl_mult * atr if atr > 0 else close * 1.02
            tp = close - self.atr_tp_mult * atr if atr > 0 else close * 0.96
            rr = (close - tp) / (sl - close) if (sl - close) > 0 else 0
            confidence = min(0.9, 0.5 + 0.1 * rr + 0.1 * (55 - rsi) / 20)
            if self._higher_tf_bearish(df):
                confidence = min(1.0, confidence + 0.1)
            return Signal(
                type=SignalType.ENTRY_SHORT, symbol=self.symbol,
                confidence=round(confidence, 2),
                reason=f"BTC SMC: RSI={rsi:.1f}, MACD bearish, EMA aligned, vol surge",
                entry_price=close, stop_loss=round(sl, 1),
                take_profit=round(tp, 1), strategy=self.name,
            )

        return Signal(
            type=SignalType.NO_TRADE, symbol=self.symbol, confidence=0.0,
            reason="BTC SMC: no entry conditions met", strategy=self.name,
        )

    def _check_exit(self, latest, df, positions) -> Signal:
        rsi = float(latest.get("rsi", 50))
        macd = float(latest.get("macd", 0))
        macd_signal = float(latest.get("macd_signal", 0))
        ema_bull = bool(latest.get("ema_bull", False))
        ema_bear = bool(latest.get("ema_bear", False))
        close = float(latest["close"])

        for pos in positions:
            if pos.get("symbol") != self.symbol:
                continue
            hold_side = pos.get("holdSide", "")

            if hold_side == "long":
                reasons = []
                if rsi > 70:
                    reasons.append(f"RSI overbought ({rsi:.1f})")
                if macd < macd_signal:
                    reasons.append("MACD bearish cross")
                if ema_bear:
                    reasons.append("EMA bearish flip")
                if reasons:
                    return Signal(
                        type=SignalType.EXIT_LONG, symbol=self.symbol,
                        confidence=0.7, reason="; ".join(reasons),
                        entry_price=close, strategy=self.name,
                    )

            elif hold_side == "short":
                reasons = []
                if rsi < 30:
                    reasons.append(f"RSI oversold ({rsi:.1f})")
                if macd > macd_signal:
                    reasons.append("MACD bullish cross")
                if ema_bull:
                    reasons.append("EMA bullish flip")
                if reasons:
                    return Signal(
                        type=SignalType.EXIT_SHORT, symbol=self.symbol,
                        confidence=0.7, reason="; ".join(reasons),
                        entry_price=close, strategy=self.name,
                    )

        return Signal(
            type=SignalType.HOLD, symbol=self.symbol, confidence=0.5,
            reason="Position active, no exit conditions met", strategy=self.name,
        )

    def _higher_tf_confirms(self, df) -> bool:
        """Check if daily EMA trend is also bullish (for confidence boost)."""
        if "ema50" in df.columns and len(df) > 1:
            return float(df.iloc[-1]["close"]) > float(df.iloc[-1].get("ema50", 0))
        return False

    def _higher_tf_bearish(self, df) -> bool:
        if "ema50" in df.columns and len(df) > 1:
            return float(df.iloc[-1]["close"]) < float(df.iloc[-1].get("ema50", 0))
        return False
