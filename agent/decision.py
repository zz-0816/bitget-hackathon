"""Decision layer: signal types, strategy engines, and the DecisionEngine."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional
import numpy as np

from .perception import PerceptionReport, MarketData
from .config import AgentConfig


class SignalType(Enum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


@dataclass
class Signal:
    """Decision output: a trading signal with metadata."""
    type: SignalType
    symbol: str
    confidence: float          # 0.0 – 1.0
    reason: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    size: Optional[float] = None
    strategy: str = ""          # "BTC_SMC" or "MEME_MOM"
    timestamp: datetime = field(default_factory=datetime.now)

    def is_entry(self) -> bool:
        return self.type in (SignalType.ENTRY_LONG, SignalType.ENTRY_SHORT)

    def is_exit(self) -> bool:
        return self.type in (SignalType.EXIT_LONG, SignalType.EXIT_SHORT)

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "symbol": self.symbol,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "size": self.size,
            "strategy": self.strategy,
        }


# ── Strategy Engines ──────────────────────────────────────────────────────

def btc_smc_signal(report: PerceptionReport, active_positions: list,
                   config: AgentConfig) -> Signal:
    """BTC Triple-Confluence SMC strategy.

    Long:  RSI trending up + MACD bullish + EMA alignment + volume surge
    Short: RSI trending down + MACD bearish + EMA alignment + volume surge
    Exit:  Opposite signal or stop/target hit.
    """
    p = report.primary
    s = report.secondary
    has_position = any(pos.get("symbol") == config.symbol and
                       float(pos.get("total", 0)) > 0
                       for pos in active_positions)

    # ── Entry ───────────────────────────────────────────────────────
    if not has_position:
        # Long conditions
        long_ok = (
            p.rsi is not None and p.rsi >= config.btc_rsi_long_min and
            p.rsi <= 65 and                     # not overbought
            p.macd is not None and p.macd_signal is not None and
            p.macd > p.macd_signal and           # MACD bullish
            report.trend_bullish and             # EMA alignment
            p.volume_surge                       # volume confirmation
        )
        if long_ok:
            sl = p.close - config.btc_atr_sl_mult * p.atr if p.atr else p.close * 0.02
            tp = p.close + config.btc_atr_tp_mult * p.atr if p.atr else p.close * 0.04
            rr = (tp - p.close) / (p.close - sl) if (p.close - sl) > 0 else 0
            confidence = min(0.9, 0.5 + 0.1 * rr + 0.1 * (p.rsi - 45) / 20)
            if s and s.ema_mid and s.close > s.ema_mid:
                confidence += 0.1  # higher TF confirmation
            return Signal(
                type=SignalType.ENTRY_LONG, symbol=config.symbol,
                confidence=round(min(1.0, confidence), 2),
                reason=f"BTC SMC: RSI={p.rsi:.1f}, MACD bullish, EMA aligned, vol surge",
                entry_price=p.close, stop_loss=round(sl, config.price_precision),
                take_profit=round(tp, config.price_precision),
                strategy="BTC_SMC",
            )

        # Short conditions
        short_ok = (
            p.rsi is not None and p.rsi <= config.btc_rsi_short_max and
            p.rsi >= 35 and                     # not oversold
            p.macd is not None and p.macd_signal is not None and
            p.macd < p.macd_signal and           # MACD bearish
            report.trend_bearish and             # EMA alignment
            p.volume_surge
        )
        if short_ok:
            sl = p.close + config.btc_atr_sl_mult * p.atr if p.atr else p.close * 1.02
            tp = p.close - config.btc_atr_tp_mult * p.atr if p.atr else p.close * 0.96
            rr = (p.close - tp) / (sl - p.close) if (sl - p.close) > 0 else 0
            confidence = min(0.9, 0.5 + 0.1 * rr + 0.1 * (55 - p.rsi) / 20)
            if s and s.ema_mid and s.close < s.ema_mid:
                confidence += 0.1
            return Signal(
                type=SignalType.ENTRY_SHORT, symbol=config.symbol,
                confidence=round(min(1.0, confidence), 2),
                reason=f"BTC SMC: RSI={p.rsi:.1f}, MACD bearish, EMA aligned, vol surge",
                entry_price=p.close, stop_loss=round(sl, config.price_precision),
                take_profit=round(tp, config.price_precision),
                strategy="BTC_SMC",
            )

    # ── Exit ───────────────────────────────────────────────────────
    else:
        for pos in active_positions:
            if pos.get("symbol") != config.symbol:
                continue
            hold_side = pos.get("holdSide", "")

            if hold_side == "long":
                exit_reason = []
                if p.rsi and p.rsi > 70:
                    exit_reason.append(f"RSI overbought ({p.rsi:.1f})")
                if p.macd is not None and p.macd_signal is not None and p.macd < p.macd_signal:
                    exit_reason.append("MACD bearish cross")
                if report.trend_bearish:
                    exit_reason.append("EMA bearish flip")
                if exit_reason:
                    return Signal(
                        type=SignalType.EXIT_LONG, symbol=config.symbol,
                        confidence=0.7, reason="; ".join(exit_reason),
                        entry_price=p.close, strategy="BTC_SMC",
                    )

            elif hold_side == "short":
                exit_reason = []
                if p.rsi and p.rsi < 30:
                    exit_reason.append(f"RSI oversold ({p.rsi:.1f})")
                if p.macd is not None and p.macd_signal is not None and p.macd > p.macd_signal:
                    exit_reason.append("MACD bullish cross")
                if report.trend_bullish:
                    exit_reason.append("EMA bullish flip")
                if exit_reason:
                    return Signal(
                        type=SignalType.EXIT_SHORT, symbol=config.symbol,
                        confidence=0.7, reason="; ".join(exit_reason),
                        entry_price=p.close, strategy="BTC_SMC",
                    )

        # Hold existing position
        return Signal(
            type=SignalType.HOLD, symbol=config.symbol, confidence=0.5,
            reason="Position active, no exit conditions met", strategy="BTC_SMC",
        )

    return Signal(
        type=SignalType.NO_TRADE, symbol=config.symbol, confidence=0.0,
        reason="No entry conditions met", strategy="BTC_SMC",
    )


def meme_momentum_signal(report: PerceptionReport, active_positions: list,
                         config: AgentConfig) -> Signal:
    """MEME Momentum Breakout strategy.

    Long:  RSI 55-65 rising + MACD histogram accelerating + volume surge + above EMA20
    Short: RSI 40-50 falling + MACD histogram decelerating + volume surge + below EMA20
    """
    p = report.primary
    has_position = any(pos.get("symbol") == config.symbol and
                       float(pos.get("total", 0)) > 0
                       for pos in active_positions)

    if not has_position:
        # Long conditions
        rsi_in_zone = (p.rsi is not None and
                       config.meme_rsi_long_low <= p.rsi <= config.meme_rsi_long_high)
        long_ok = (
            rsi_in_zone and
            p.ema_fast is not None and p.close > p.ema_fast and
            p.volume_surge
        )
        if long_ok:
            sl = p.close - config.meme_atr_sl_mult * p.atr if p.atr else p.close * 0.03
            tp = p.close + config.meme_atr_tp2_mult * p.atr if p.atr else p.close * 0.06
            confidence = min(0.85, 0.5 + 0.05 * (p.rsi - 55) + 0.2 if p.atr and p.atr > 0 else 0)
            return Signal(
                type=SignalType.ENTRY_LONG, symbol=config.symbol,
                confidence=round(confidence, 2),
                reason=f"MEME Mom: RSI={p.rsi:.1f} in 55-65 zone, vol surge, >EMA20",
                entry_price=p.close, stop_loss=round(sl, config.price_precision),
                take_profit=round(tp, config.price_precision),
                strategy="MEME_MOM",
            )

        # Short conditions
        rsi_in_zone = (p.rsi is not None and
                       config.meme_rsi_short_low <= p.rsi <= config.meme_rsi_short_high)
        short_ok = (
            rsi_in_zone and
            p.ema_fast is not None and p.close < p.ema_fast and
            p.volume_surge
        )
        if short_ok:
            sl = p.close + config.meme_atr_sl_mult * p.atr if p.atr else p.close * 1.03
            tp = p.close - config.meme_atr_tp2_mult * p.atr if p.atr else p.close * 0.94
            confidence = min(0.85, 0.5 + 0.05 * (50 - p.rsi))
            return Signal(
                type=SignalType.ENTRY_SHORT, symbol=config.symbol,
                confidence=round(confidence, 2),
                reason=f"MEME Mom: RSI={p.rsi:.1f} in 40-50 zone, vol surge, <EMA20",
                entry_price=p.close, stop_loss=round(sl, config.price_precision),
                take_profit=round(tp, config.price_precision),
                strategy="MEME_MOM",
            )

    else:
        return Signal(
            type=SignalType.HOLD, symbol=config.symbol, confidence=0.5,
            reason="Position active", strategy="MEME_MOM",
        )

    return Signal(
        type=SignalType.NO_TRADE, symbol=config.symbol, confidence=0.0,
        reason="No entry conditions met", strategy="MEME_MOM",
    )


# ── Decision Engine ────────────────────────────────────────────────────────

class DecisionEngine:
    """Orchestrates strategy evaluation and produces a final trading signal.

    Runs multiple strategies, applies sentiment/macro filters,
    and returns the highest-confidence signal.
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.strategies = [
            ("BTC_SMC", btc_smc_signal),
            ("MEME_MOM", meme_momentum_signal),
        ]

    def evaluate(self, report: PerceptionReport,
                 active_positions: Optional[list] = None) -> Signal:
        """Evaluate all strategies and return the best signal.

        Args:
            report: PerceptionReport from the perception layer.
            active_positions: List of position dicts from Bitget API.

        Returns:
            The highest-confidence Signal, or NO_TRADE.
        """
        if active_positions is None:
            active_positions = []

        signals = []
        for name, strategy_fn in self.strategies:
            signal = strategy_fn(report, active_positions, self.config)
            signals.append(signal)

        # Prefer exit signals over entry, entry over hold, hold over no_trade
        exits = [s for s in signals if s.is_exit()]
        entries = [s for s in signals if s.is_entry()]
        holds = [s for s in signals if s.type == SignalType.HOLD]

        # Apply sentiment filter
        sentiment = report.sentiment

        if sentiment and self.config.sentiment_filter_enabled:
            fg = sentiment.fear_greed_index

            # Filter entries against sentiment
            for s in entries:
                if s.type == SignalType.ENTRY_LONG and fg < self.config.fear_greed_oversold:
                    s.confidence *= 0.5
                    s.reason += f" [FG={fg} weak, confidence halved]"
                elif s.type == SignalType.ENTRY_SHORT and fg > self.config.fear_greed_overbought:
                    s.confidence *= 0.5
                    s.reason += f" [FG={fg} high, confidence halved]"

            # Merge sentiment into exits
            if fg > 70:
                for s in exits:
                    if s.type == SignalType.EXIT_LONG:
                        s.confidence = min(1.0, s.confidence + 0.15)
                        s.reason += f" [FG extreme greed={fg}]"
            elif fg < 30:
                for s in exits:
                    if s.type == SignalType.EXIT_SHORT:
                        s.confidence = min(1.0, s.confidence + 0.15)
                        s.reason += f" [FG extreme fear={fg}]"

        # Priority: exit > entry > hold > no_trade
        if exits:
            return max(exits, key=lambda s: s.confidence)
        if entries:
            return max(entries, key=lambda s: s.confidence)
        if holds:
            return holds[0]

        return Signal(
            type=SignalType.NO_TRADE, symbol=self.config.symbol,
            confidence=0.0, reason="All strategies: no actionable signal",
            strategy="NONE",
        )

    def evaluate_all(self, report: PerceptionReport,
                     active_positions: Optional[list] = None) -> List[Signal]:
        """Return all signals (for debugging / transparency)."""
        if active_positions is None:
            active_positions = []
        return [fn(report, active_positions, self.config)
                for _, fn in self.strategies]
