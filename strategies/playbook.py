"""Strategy Playbook — registry, comparison, and backtest orchestration.

The Playbook is the single entry point for discovering and running strategies.
It replaces the inline strategy list in agent/decision.py with a proper registry.

Usage:
    playbook = Playbook()
    playbook.register(BTCSMCStrategy(symbol="BTCUSDT"))
    playbook.register(MEMEMomentumStrategy(symbol="DOGEUSDT"))

    # Run all strategies on the same data
    signals = playbook.evaluate_all(df, positions=[...])

    # Run with a prepared (indicator-rich) DataFrame
    df = playbook.prepare_all(df)
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd

from .base import Strategy, Signal, SignalType


class Playbook:
    """Central strategy registry with batch evaluation and backtest support.

    Attached to DecisionEngine in agent/decision.py to replace inline functions
    with proper Strategy objects.
    """

    def __init__(self):
        self._strategies: Dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> "Playbook":
        """Register a strategy instance. Chainable."""
        if strategy.name in self._strategies:
            existing = self._strategies[strategy.name]
            raise ValueError(
                f"Strategy '{strategy.name}' already registered: {existing}"
            )
        self._strategies[strategy.name] = strategy
        return self

    def unregister(self, name: str) -> "Playbook":
        self._strategies.pop(name, None)
        return self

    def get(self, name: str) -> Optional[Strategy]:
        return self._strategies.get(name)

    def list(self) -> List[dict]:
        """Return metadata for all registered strategies."""
        return [
            {
                "name": s.name,
                "timeframe": s.timeframe,
                "symbol": s.symbol,
                "indicators": s.requires_indicators,
                "params": {k: v for k, v in s.params.items()
                           if not k.startswith("_")},
            }
            for s in self._strategies.values()
        ]

    @property
    def count(self) -> int:
        return len(self._strategies)

    # ── Batch operations ──────────────────────────────────────────────

    def prepare_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all registered strategies' indicator requirements to df."""
        for strat in self._strategies.values():
            df = strat.prepare(df)
        return df

    def evaluate_all(self, df: pd.DataFrame,
                     positions: Optional[List[dict]] = None) -> List[Signal]:
        """Run all registered strategies and return their signals."""
        signals = []
        for name, strat in self._strategies.items():
            signal = strat.evaluate(df, positions)
            signals.append(signal)
        return signals

    def evaluate_best(self, df: pd.DataFrame,
                      positions: Optional[List[dict]] = None) -> Signal:
        """Run all strategies and return the best actionable signal.

        Priority: exit > entry > hold > no_trade.
        Within each category, highest confidence wins.
        """
        signals = self.evaluate_all(df, positions)
        return pick_best(signals)

    # ── Backtest helpers ──────────────────────────────────────────────

    def backtest_config(self) -> dict:
        """Generate a strategy_config dict for the MCP backtest tool."""
        strategies_cfg = []
        for s in self._strategies.values():
            cfg = {
                "name": s.name,
                "timeframe": s.timeframe,
                "params": {k: v for k, v in s.params.items()
                           if not k.startswith("_")},
                "indicators": s.requires_indicators,
            }
            strategies_cfg.append(cfg)
        return {
            "strategies": [s.name for s in self._strategies.values()],
            "strategy_details": strategies_cfg,
        }

    def to_config(self, strategy_names: Optional[List[str]] = None) -> dict:
        """Generate strategy_config JSON for the MCP market-data backtest tool.

        Can include entry/exit conditions derived from strategy parameters.
        """
        names = strategy_names or list(self._strategies.keys())
        config = {"name": "+".join(names), "symbols": [], "timeframe": "4h",
                  "indicators": [], "entry_conditions": [], "exit_conditions": []}

        for name in names:
            s = self._strategies.get(name)
            if s is None:
                continue
            config["symbols"].append(s.symbol)
            config["timeframe"] = s.timeframe
            config["indicators"].extend(s.requires_indicators)

        # Deduplicate
        config["symbols"] = list(set(config["symbols"]))
        config["indicators"] = list(set(config["indicators"]))
        return config

    def __repr__(self):
        names = ", ".join(self._strategies.keys()) or "(empty)"
        return f"<Playbook: {names}>"


def pick_best(signals: List[Signal]) -> Signal:
    """Pick the best signal from a list by priority and confidence.

    Used by both the Playbook and the agent DecisionEngine.
    """
    if not signals:
        return Signal(
            type=SignalType.NO_TRADE, symbol="", confidence=0.0,
            reason="No strategies evaluated", strategy="NONE",
        )

    exits = [s for s in signals if s.is_exit()]
    entries = [s for s in signals if s.is_entry()]
    holds = [s for s in signals if s.type == SignalType.HOLD]

    if exits:
        return max(exits, key=lambda s: s.confidence)
    if entries:
        return max(entries, key=lambda s: s.confidence)
    if holds:
        return holds[0]

    return signals[0]  # NO_TRADE


def create_default_playbook(symbol: str = "BTCUSDT",
                            meme_symbol: str = "DOGEUSDT") -> Playbook:
    """Create a Playbook with the default BTC SMC and MEME Momentum strategies."""
    from .btc_smc import BTCSMCStrategy
    from .meme_momentum import MEMEMomentumStrategy

    return (Playbook()
            .register(BTCSMCStrategy(symbol=symbol))
            .register(MEMEMomentumStrategy(symbol=meme_symbol)))
