"""Strategies module — strategy classes, indicators, and the playbook.

Usage:
    from strategies import Playbook, BTCSMCStrategy, MEMEMomentumStrategy

    playbook = Playbook()
    playbook.register(BTCSMCStrategy(symbol="BTCUSDT"))
    df = playbook.prepare_all(ohlcv_df)
    signal = playbook.evaluate_best(df, positions)
"""

from .base import Strategy, Signal, SignalType
from .btc_smc import BTCSMCStrategy
from .meme_momentum import MEMEMomentumStrategy
from .playbook import Playbook, pick_best, create_default_playbook
from .indicators import INDICATOR_LIBRARY, list_indicators, add_custom_indicator

__all__ = [
    # Base
    "Strategy", "Signal", "SignalType",
    # Strategies
    "BTCSMCStrategy", "MEMEMomentumStrategy",
    # Playbook
    "Playbook", "pick_best", "create_default_playbook",
    # Indicators
    "INDICATOR_LIBRARY", "list_indicators", "add_custom_indicator",
]
