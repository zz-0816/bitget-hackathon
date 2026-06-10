"""Agent configuration center — strategy params, risk thresholds, sandbox toggle."""
import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class AgentConfig:
    """Central configuration for the trading agent.

    Reads from environment variables with sensible defaults for the hackathon.
    """

    # ── Sandbox ─────────────────────────────────────────────────────────
    sandbox: bool = True
    paper_trading: bool = True  # PAPTRADING header

    # ── Market ──────────────────────────────────────────────────────────
    product_type: str = "USDT-FUTURES"
    symbol: str = "BTCUSDT"
    margin_coin: str = "USDT"
    margin_mode: str = "isolated"  # demo only supports isolated
    base_url: str = "https://api.bitget.com"
    timeframe: str = "4h"          # primary decision timeframe
    secondary_tf: str = "1d"       # confirmation timeframe

    # ── Strategy: BTC SMC (4H) ─────────────────────────────────────────
    # RSI filter
    btc_rsi_period: int = 14
    btc_rsi_long_min: int = 45     # RSI must be above this for long
    btc_rsi_short_max: int = 55    # RSI must be below this for short
    # EMA alignment
    btc_ema_fast: int = 20
    btc_ema_mid: int = 50
    # MACD
    btc_macd_fast: int = 12
    btc_macd_slow: int = 26
    btc_macd_signal: int = 9
    # ATR (stop-loss multiplier)
    btc_atr_period: int = 14
    btc_atr_sl_mult: float = 1.0
    btc_atr_tp_mult: float = 2.0
    # Volume surge
    btc_vol_surge_mult: float = 1.5

    # ── Strategy: MEME Momentum (1H) ───────────────────────────────────
    meme_rsi_period: int = 14
    meme_rsi_long_low: int = 55
    meme_rsi_long_high: int = 65
    meme_rsi_short_low: int = 40
    meme_rsi_short_high: int = 50
    meme_ema_fast: int = 20
    meme_atr_period: int = 14
    meme_atr_sl_mult: float = 2.0
    meme_atr_tp1_mult: float = 1.5
    meme_atr_tp2_mult: float = 2.5
    meme_vol_surge_mult: float = 1.5

    # ── Risk ───────────────────────────────────────────────────────────
    max_position_pct: float = 0.02       # 2% max per position
    max_total_exposure_pct: float = 0.30 # 30% max total exposure
    daily_loss_circuit_breaker: float = 0.05  # 5% daily loss → halt
    min_risk_reward_ratio: float = 1.5   # minimum RR for entry
    max_slippage_pct: float = 0.001      # 0.1% max slippage
    max_leverage: int = 5
    cooldown_bars: int = 3               # bars to wait after exit before re-entry

    # ── Execution ──────────────────────────────────────────────────────
    default_order_type: str = "market"   # market or limit
    size_precision: int = 4              # decimal places for order size
    price_precision: int = 1             # decimal places for order price

    # ── Sentiment / Macro Filters ──────────────────────────────────────
    fear_greed_oversold: int = 25        # enter long only if FG > this
    fear_greed_overbought: int = 75      # enter short only if FG < this
    sentiment_filter_enabled: bool = True
    macro_filter_enabled: bool = False   # off by default (needs data feed)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Create config from environment variables, with fallbacks."""
        return cls(
            sandbox=os.getenv("BITGET_SANDBOX", "true").lower() == "true",
            paper_trading=os.getenv("PAPER_TRADING", "true").lower() == "true",
            product_type=os.getenv("PRODUCT_TYPE", "USDT-FUTURES"),
            symbol=os.getenv("SYMBOL", "BTCUSDT"),
            margin_coin=os.getenv("MARGIN_COIN", "USDT"),
            margin_mode=os.getenv("MARGIN_MODE", "isolated"),
            timeframe=os.getenv("TIMEFRAME", "4h"),
            max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.02")),
            max_total_exposure_pct=float(os.getenv("MAX_EXPOSURE_PCT", "0.30")),
            daily_loss_circuit_breaker=float(os.getenv("DAILY_LOSS_CB", "0.05")),
            min_risk_reward_ratio=float(os.getenv("MIN_RR", "1.5")),
            max_leverage=int(os.getenv("MAX_LEVERAGE", "5")),
            sentiment_filter_enabled=os.getenv("SENTIMENT_FILTER", "true").lower() == "true",
        )

    def to_dict(self) -> dict:
        """Serialize non-sensitive config for logging."""
        return {
            "sandbox": self.sandbox,
            "product_type": self.product_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "max_position_pct": self.max_position_pct,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "daily_loss_cb": self.daily_loss_circuit_breaker,
            "min_rr": self.min_risk_reward_ratio,
            "max_leverage": self.max_leverage,
        }
