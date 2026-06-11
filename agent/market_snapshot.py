"""Market data snapshot — unified structure for all external data sources.

Receives data from Skills (technical-analysis, sentiment-analyst, macro-analyst,
news-briefing) and provides a single source of truth for strategy condition evaluation.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TechnicalSnapshot:
    """Technical indicators snapshot for one symbol/timeframe."""
    symbol: str = ""
    timeframe: str = ""
    close: float = 0.0
    rsi: Optional[float] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None
    macd_hist: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    atr: Optional[float] = None
    adx: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_lower: Optional[float] = None
    volume_surge: bool = False
    trend_direction: str = "neutral"  # "up" / "down" / "neutral"
    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)


@dataclass
class SentimentSnapshot:
    """Market sentiment data."""
    fear_greed_index: int = 50
    fear_greed_label: str = "neutral"  # "extreme fear" / "fear" / "neutral" / "greed" / "extreme greed"
    long_short_ratio: float = 1.0
    taker_buy_ratio: float = 0.5
    open_interest_change: float = 0.0


@dataclass
class MacroSnapshot:
    """Macro environment data."""
    regime: str = "neutral"  # "risk_on" / "risk_off" / "neutral"
    fed_funds_rate: Optional[float] = None
    dxy: Optional[float] = None
    btc_nasdaq_correlation: Optional[float] = None
    notes: str = ""


@dataclass
class NewsSnapshot:
    """News and event data."""
    has_major_event: bool = False
    event_summary: str = ""
    bias: str = "neutral"  # "positive" / "negative" / "neutral"


@dataclass
class MarketSnapshot:
    """Complete market snapshot from all data sources."""
    timestamp: datetime = field(default_factory=datetime.now)
    technical: TechnicalSnapshot = field(default_factory=TechnicalSnapshot)
    sentiment: SentimentSnapshot = field(default_factory=SentimentSnapshot)
    macro: MacroSnapshot = field(default_factory=MacroSnapshot)
    news: NewsSnapshot = field(default_factory=NewsSnapshot)

    def summary(self) -> str:
        """One-line market condition summary."""
        tech = self.technical
        sent = self.sentiment
        macro = self.macro
        return (
            f"{tech.symbol} {tech.timeframe} | "
            f"Close={tech.close:.1f} | "
            f"RSI={tech.rsi:.0f}" if tech.rsi else f"{tech.symbol} {tech.timeframe} | Close={tech.close:.1f}"
        ) + (
            f" | MACD={'bullish' if (tech.macd_dif or 0) > (tech.macd_dea or 0) else 'bearish'}"
            f" | Trend={tech.trend_direction}"
            f" | FG={sent.fear_greed_index}/100"
            f" | Macro={macro.regime}"
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "technical": {
                "symbol": self.technical.symbol,
                "timeframe": self.technical.timeframe,
                "close": self.technical.close,
                "rsi": self.technical.rsi,
                "macd_dif": self.technical.macd_dif,
                "macd_dea": self.technical.macd_dea,
                "macd_hist": self.technical.macd_hist,
                "ema_12": self.technical.ema_12,
                "ema_26": self.technical.ema_26,
                "ema_20": self.technical.ema_20,
                "ema_50": self.technical.ema_50,
                "atr": self.technical.atr,
                "adx": self.technical.adx,
                "bb_upper": self.technical.bb_upper,
                "bb_mid": self.technical.bb_mid,
                "bb_lower": self.technical.bb_lower,
                "volume_surge": self.technical.volume_surge,
                "trend_direction": self.technical.trend_direction,
                "support": self.technical.support_levels,
                "resistance": self.technical.resistance_levels,
            },
            "sentiment": {
                "fear_greed_index": self.sentiment.fear_greed_index,
                "fear_greed_label": self.sentiment.fear_greed_label,
                "long_short_ratio": self.sentiment.long_short_ratio,
                "taker_buy_ratio": self.sentiment.taker_buy_ratio,
            },
            "macro": {
                "regime": self.macro.regime,
                "fed_funds_rate": self.macro.fed_funds_rate,
                "dxy": self.macro.dxy,
                "btc_nasdaq_correlation": self.macro.btc_nasdaq_correlation,
            },
            "news": {
                "has_major_event": self.news.has_major_event,
                "bias": self.news.bias,
                "summary": self.news.event_summary,
            },
        }
