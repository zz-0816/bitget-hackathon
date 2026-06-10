"""Trading Agent — 感知 → 决策 → 风控 → 执行 四层闭环主控。

Orchestrates the four layers:
  1. Perception   — builds PerceptionReport from market data
  2. Decision     — evaluates strategies, produces Signal
  3. Risk         — checks position size, exposure, daily loss, RR
  4. Execution    — converts approved Signal to Order for Bitget API
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import json

from .config import AgentConfig
from .perception import (
    PerceptionReport, MarketData, SentimentSnapshot, MacroSnapshot,
    compute_all_indicators, build_perception_report,
)
from .decision import DecisionEngine, Signal, SignalType
from .execution import ExecutionEngine, Order
from .risk import RiskManager, RiskResult


@dataclass
class AgentOutput:
    """Structured output of one agent loop iteration."""
    timestamp: datetime = field(default_factory=datetime.now)
    perception: Optional[PerceptionReport] = None
    signal: Optional[Signal] = None
    risk: Optional[RiskResult] = None
    order: Optional[Order] = None
    narrative: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "perception": {
                "trend": "bullish" if self.perception.trend_bullish
                         else "bearish" if self.perception.trend_bearish
                         else "neutral",
                "volatility": self.perception.volatility_regime if self.perception else "N/A",
                "volume": self.perception.volume_regime if self.perception else "N/A",
                "primary": {
                    "symbol": self.perception.primary.symbol if self.perception else "",
                    "close": self.perception.primary.close if self.perception else 0,
                    "rsi": self.perception.primary.rsi if self.perception else None,
                    "macd": self.perception.primary.macd if self.perception else None,
                    "atr": self.perception.primary.atr if self.perception else None,
                } if self.perception else {},
            },
            "signal": self.signal.to_dict() if self.signal else None,
            "risk": {
                "approved": self.risk.approved,
                "reason": self.risk.reason,
                "adjusted_size": self.risk.adjusted_size,
                "checks": self.risk.checks,
            } if self.risk else None,
            "order": self.order.to_dict() if self.order else None,
            "narrative": self.narrative,
        }

    def print_pipeline(self):
        """Pretty-print the full pipeline output for hackathon demo."""
        SEP = "=" * 68
        SUB = "-" * 68

        print(f"\n{SEP}")
        print("  TRADING AGENT - PIPELINE OUTPUT")
        print(SEP)

        # Perception
        print(f"\n  [1] PERCEPTION")
        print(f"  {SUB}")
        if self.perception:
            p = self.perception.primary
            print(f"  Symbol:      {p.symbol} @ {p.timeframe}")
            print(f"  OHLCV:       O={p.open} H={p.high} L={p.low} C={p.close} V={p.volume}")
            print(f"  RSI(14):     {p.rsi:.1f}" if p.rsi else "  RSI:         N/A")
            print(f"  MACD:        {p.macd:.4f}" if p.macd else "")
            print(f"  MACD Signal: {p.macd_signal:.4f}" if p.macd_signal else "")
            print(f"  MACD Hist:   {p.macd_hist:.4f}" if p.macd_hist else "")
            print(f"  ATR(14):     {p.atr:.4f}" if p.atr else "")
            print(f"  EMA(20):     {p.ema_fast:.2f}" if p.ema_fast else "")
            print(f"  EMA(50):     {p.ema_mid:.2f}" if p.ema_mid else "")
            print(f"  Vol Surge:   {p.volume_surge}")
            print(f"  Trend:       {'BULLISH' if self.perception.trend_bullish else 'BEARISH' if self.perception.trend_bearish else 'NEUTRAL'}")
            print(f"  Volatility:  {self.perception.volatility_regime.upper()}")
            print(f"  Volume Reg:  {self.perception.volume_regime.upper()}")
            if self.perception.sentiment:
                s = self.perception.sentiment
                print(f"  Sentiment:   FG={s.fear_greed_index} ({s.fear_greed_label})")
            if self.perception.secondary:
                s = self.perception.secondary
                print(f"  Secondary:   {s.timeframe} C={s.close} V={s.volume}")

        # Decision
        print(f"\n  [2] DECISION")
        print(f"  {SUB}")
        if self.signal:
            print(f"  Signal:      {self.signal.type.value}")
            print(f"  Strategy:    {self.signal.strategy}")
            print(f"  Confidence:  {self.signal.confidence:.0%}")
            print(f"  Reason:      {self.signal.reason}")
            if self.signal.entry_price:
                print(f"  Entry Price: {self.signal.entry_price}")
            if self.signal.stop_loss:
                print(f"  Stop Loss:   {self.signal.stop_loss}")
            if self.signal.take_profit:
                print(f"  Take Profit: {self.signal.take_profit}")
        else:
            print("  Signal:      NONE")

        # Risk
        print(f"\n  [3] RISK")
        print(f"  {SUB}")
        if self.risk:
            approved_str = "APPROVED" if self.risk.approved else "REJECTED"
            print(f"  Status:      {approved_str}")
            print(f"  Reason:      {self.risk.reason}")
            if self.risk.adjusted_size:
                print(f"  Size:        {self.risk.adjusted_size}")
            if self.risk.checks:
                for check_name, check_data in self.risk.checks.items():
                    if isinstance(check_data, dict) and not check_data.get("ok", True):
                        print(f"  FAILED:      {check_name} -> {check_data}")
        else:
            print("  Risk:        SKIPPED")

        # Execution
        print(f"\n  [4] EXECUTION")
        print(f"  {SUB}")
        if self.order and self.risk and self.risk.approved:
            print(f"  Order:       {self.order.side.upper()} {self.order.order_type.upper()}")
            print(f"  Symbol:      {self.order.symbol}")
            print(f"  Size:        {self.order.size}")
            print(f"  Trade Side:  {self.order.trade_side}")
            print(f"  Margin Mode: {self.order.margin_mode}")
            print(f"  MCP Params:  {json.dumps(self.order.to_mcp_params())}")
        elif self.order and not self.risk.approved:
            print(f"  Order:       HELD - risk rejected")
        else:
            print(f"  Order:       NONE")

        print(f"\n  Narrative: {self.narrative}")
        print(f"\n{SEP}")
        print("  PIPELINE COMPLETE")
        print(SEP)


class TradingAgent:
    """Main agent orchestrating the four-layer closed loop.

    Usage:
        config = AgentConfig.from_env()
        agent = TradingAgent(config)
        output = agent.run(market_df, positions, account_equity)
        output.print_pipeline()
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.decision = DecisionEngine(self.config)
        self.execution = ExecutionEngine(self.config)
        self.risk = RiskManager(self.config)
        self.iteration: int = 0

    def run(self, market_df, account_equity: float,
            current_positions: Optional[List[dict]] = None,
            sentiment: Optional[SentimentSnapshot] = None,
            macro: Optional[MacroSnapshot] = None,
            secondary_df=None) -> AgentOutput:
        """Execute one full iteration of the agent loop.

        Args:
            market_df:  OHLCV DataFrame (must have open/high/low/close/volume columns).
            account_equity: Current account equity in USDT.
            current_positions: List of position dicts from Bitget API.
            sentiment: Optional SentimentSnapshot from external source.
            macro: Optional MacroSnapshot from external source.
            secondary_df: Optional higher-timeframe DataFrame for confirmation.

        Returns:
            AgentOutput with full pipeline trace.
        """
        self.iteration += 1
        output = AgentOutput(timestamp=datetime.now())

        # ── Layer 1: Perception ─────────────────────────────────────
        df = compute_all_indicators(market_df, self.config)
        sec_df = None
        if secondary_df is not None:
            sec_df = compute_all_indicators(secondary_df, self.config)
        report = build_perception_report(
            df, self.config.symbol, self.config.timeframe,
            sentiment=sentiment, macro=macro,
            secondary_df=sec_df, secondary_tf=self.config.secondary_tf,
        )
        output.perception = report

        # ── Layer 2: Decision ───────────────────────────────────────
        signal = self.decision.evaluate(report, current_positions)
        output.signal = signal

        # ── Layer 3: Risk ───────────────────────────────────────────
        risk_result = self.risk.check(signal, account_equity, current_positions)
        output.risk = risk_result

        # ── Layer 4: Execution ──────────────────────────────────────
        order = None
        if risk_result.approved and signal.type not in (SignalType.HOLD, SignalType.NO_TRADE):
            order = self.execution.signal_to_order(signal, risk_result.adjusted_size)
        elif signal.is_exit() and not risk_result.approved:
            # Exit rejected but we might still want to try
            pass
        output.order = order

        # ── Narrative ───────────────────────────────────────────────
        output.narrative = self._build_narrative(output)
        return output

    def _build_narrative(self, out: AgentOutput) -> str:
        """Generate a human-readable narrative of the pipeline decision."""
        parts = []

        if out.perception:
            p = out.perception
            parts.append(
                f"[{self.iteration}] {p.primary.symbol} @ {p.primary.close:.1f} | "
                f"Trend: {'bullish' if p.trend_bullish else 'bearish' if p.trend_bearish else 'neutral'} | "
                f"RSI={p.primary.rsi:.0f} | Vol={p.volume_regime}"
            )

        if out.signal:
            if out.signal.is_entry():
                parts.append(f"Signal: {out.signal.type.value} "
                            f"(conf={out.signal.confidence:.0%}, {out.signal.strategy})")
            elif out.signal.is_exit():
                parts.append(f"Signal: {out.signal.type.value} -> {out.signal.reason}")
            else:
                parts.append(f"Signal: {out.signal.type.value}")

        if out.risk:
            parts.append(f"Risk: {'OK' if out.risk.approved else 'REJECTED'} - {out.risk.reason}")

        if out.order:
            parts.append(f"Order: {out.order.side.upper()} {out.order.size} {out.order.order_type} "
                        f"[{out.order.trade_side}]")

        return " | ".join(parts) if parts else "Pipeline idle"
