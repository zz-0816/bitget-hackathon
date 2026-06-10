"""MEME Momentum Breakout Strategy.

1H timeframe. Captures momentum-driven moves in meme/alt coins.
Entry when:
  - RSI in momentum zone (55-65 long, 40-50 short)
  - Price above/below EMA20
  - Volume surge confirmation

Exit: trailing SL via ATR, or opposite RSI zone breach.
"""

from typing import Optional, List
import pandas as pd

from .base import Strategy, Signal, SignalType
from .indicators import add_ema, add_rsi, add_macd, add_atr, add_volume_ma


class MEMEMomentumStrategy(Strategy):
    """MEME Momentum Breakout — captures RSI-driven momentum moves on 1H.

    Parameters:
        rsi_period: RSI period (14)
        rsi_long_low/high: long entry RSI zone (55-65)
        rsi_short_low/high: short entry RSI zone (40-50)
        ema_fast: fast EMA period (20)
        atr_period: ATR period for stop/target (14)
        atr_sl_mult: stop-loss ATR multiplier (2.0)
        atr_tp1_mult: first take-profit ATR multiplier (1.5)
        atr_tp2_mult: second take-profit ATR multiplier (2.5)
        vol_surge_mult: volume surge threshold (1.5)
    """

    name = "MEME_MOM"
    timeframe = "1h"
    params = {
        "rsi_period": 14, "rsi_long_low": 55, "rsi_long_high": 65,
        "rsi_short_low": 40, "rsi_short_high": 50,
        "ema_fast": 20, "atr_period": 14,
        "atr_sl_mult": 2.0, "atr_tp1_mult": 1.5, "atr_tp2_mult": 2.5,
        "vol_surge_mult": 1.5,
    }

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return (df
                .pipe(add_ema, periods=[self.ema_fast])
                .pipe(add_rsi, period=self.rsi_period)
                .pipe(add_macd)
                .pipe(add_atr, period=self.atr_period)
                .pipe(add_volume_ma, period=20))

    @property
    def requires_indicators(self) -> List[str]:
        return ["ema", "rsi", "macd", "atr", "volume_ma"]

    def evaluate(self, df: pd.DataFrame,
                 positions: Optional[List[dict]] = None) -> Signal:
        latest = df.iloc[-1]
        has_position = any(
            pos.get("symbol") == self.symbol and float(pos.get("total", 0)) > 0
            for pos in (positions or [])
        )

        if not has_position:
            return self._check_entry(latest, df)

        return self._check_exit(latest, positions)

    def _check_entry(self, latest, df) -> Signal:
        close = float(latest["close"])
        rsi = float(latest.get("rsi", 50))
        atr = float(latest.get("atr", 0))
        ema_fast = float(latest.get(f"ema{self.ema_fast}", close))
        vol_surge = bool(latest.get("vol_surge", False))
        macd_hist = float(latest.get("macd_hist", 0))

        if not vol_surge:
            return Signal(
                type=SignalType.NO_TRADE, symbol=self.symbol, confidence=0.0,
                reason="MEME Mom: waiting for volume surge", strategy=self.name,
            )

        # ── Long entry ────────────────────────────────────────────
        rsi_in_zone = self.rsi_long_low <= rsi <= self.rsi_long_high
        if rsi_in_zone and close > ema_fast and macd_hist > 0:
            sl = close - self.atr_sl_mult * atr if atr > 0 else close * 0.97
            tp = close + self.atr_tp2_mult * atr if atr > 0 else close * 1.06
            confidence = min(0.85, 0.5 + 0.05 * (rsi - self.rsi_long_low))
            return Signal(
                type=SignalType.ENTRY_LONG, symbol=self.symbol,
                confidence=round(confidence, 2),
                reason=f"MEME Mom: RSI={rsi:.1f} in {self.rsi_long_low}-{self.rsi_long_high} zone, vol surge, >EMA{self.ema_fast}",
                entry_price=close, stop_loss=round(sl, 6),
                take_profit=round(tp, 6), strategy=self.name,
            )

        # ── Short entry ───────────────────────────────────────────
        rsi_in_zone = self.rsi_short_low <= rsi <= self.rsi_short_high
        if rsi_in_zone and close < ema_fast and macd_hist < 0:
            sl = close + self.atr_sl_mult * atr if atr > 0 else close * 1.03
            tp = close - self.atr_tp2_mult * atr if atr > 0 else close * 0.94
            confidence = min(0.85, 0.5 + 0.05 * (self.rsi_short_high - rsi))
            return Signal(
                type=SignalType.ENTRY_SHORT, symbol=self.symbol,
                confidence=round(confidence, 2),
                reason=f"MEME Mom: RSI={rsi:.1f} in {self.rsi_short_low}-{self.rsi_short_high} zone, vol surge, <EMA{self.ema_fast}",
                entry_price=close, stop_loss=round(sl, 6),
                take_profit=round(tp, 6), strategy=self.name,
            )

        return Signal(
            type=SignalType.NO_TRADE, symbol=self.symbol, confidence=0.0,
            reason="MEME Mom: no entry conditions met", strategy=self.name,
        )

    def _check_exit(self, latest, positions) -> Signal:
        rsi = float(latest.get("rsi", 50))
        ema_fast = float(latest.get(f"ema{self.ema_fast}", 0))
        close = float(latest["close"])

        for pos in positions:
            if pos.get("symbol") != self.symbol:
                continue
            hold_side = pos.get("holdSide", "")

            if hold_side == "long":
                reasons = []
                if rsi > 75:
                    reasons.append(f"RSI overbought ({rsi:.1f})")
                if close < ema_fast:
                    reasons.append(f"Price below EMA{self.ema_fast}")
                if reasons:
                    return Signal(
                        type=SignalType.EXIT_LONG, symbol=self.symbol,
                        confidence=0.7, reason="; ".join(reasons),
                        entry_price=close, strategy=self.name,
                    )

            elif hold_side == "short":
                reasons = []
                if rsi < 25:
                    reasons.append(f"RSI oversold ({rsi:.1f})")
                if close > ema_fast:
                    reasons.append(f"Price above EMA{self.ema_fast}")
                if reasons:
                    return Signal(
                        type=SignalType.EXIT_SHORT, symbol=self.symbol,
                        confidence=0.7, reason="; ".join(reasons),
                        entry_price=close, strategy=self.name,
                    )

        return Signal(
            type=SignalType.HOLD, symbol=self.symbol, confidence=0.5,
            reason="Position active", strategy=self.name,
        )
