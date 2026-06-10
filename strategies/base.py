"""Strategy base class and shared signal types.

Every strategy extends `Strategy` and implements:
  - prepare(df) → df with indicators added
  - evaluate(df) → Signal
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
import pandas as pd


class SignalType(Enum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


@dataclass
class Signal:
    """Trading signal produced by a strategy evaluation."""
    type: SignalType
    symbol: str
    confidence: float  # 0.0 – 1.0
    reason: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    size: Optional[float] = None
    strategy: str = ""
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


class Strategy:
    """Abstract base for all trading strategies.

    Subclasses set `name`, `timeframe`, and optionally `symbol` at class level,
    then implement `prepare()` and `evaluate()`.

    Usage:
        class MyStrategy(Strategy):
            name = "my_strat"
            timeframe = "4h"

            def prepare(self, df):
                return add_ema(df, periods=[20, 50]).pipe(add_rsi)

            def evaluate(self, df, positions=None):
                latest = df.iloc[-1]
                if latest["rsi"] < 30:
                    return Signal(type=SignalType.ENTRY_LONG, ...)
                return Signal(type=SignalType.NO_TRADE, ...)
    """

    name: str = "base"
    timeframe: str = "4h"
    symbol: str = "BTCUSDT"
    # Parameter overrides — set in subclass or passed to __init__
    params: dict = {}

    def __init__(self, **kwargs):
        self.params = {**self.__class__.params, **kwargs}
        for k, v in self.params.items():
            setattr(self, k, v)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add required indicators to the DataFrame. Override in subclass."""
        return df

    def evaluate(self, df: pd.DataFrame,
                 positions: Optional[List[dict]] = None) -> Signal:
        """Evaluate the strategy on indicator-rich data. Override in subclass."""
        return Signal(
            type=SignalType.NO_TRADE,
            symbol=self.symbol,
            confidence=0.0,
            reason=f"{self.name}: not implemented",
            strategy=self.name,
        )

    @property
    def requires_indicators(self) -> List[str]:
        """List of indicator names this strategy needs (for documentation)."""
        return []

    def __repr__(self):
        return f"<{self.name} {self.timeframe} {self.symbol}>"
