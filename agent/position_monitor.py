"""Position Monitor — continuous monitoring of open positions using Skills data.

After entering a trade, this module:
  1. Periodically receives market snapshots (from Skills)
  2. Checks for exit conditions, anomalies, risk events
  3. Alerts user on significant changes
  4. Recommends exit when conditions warrant
  5. Generates trade summary upon position close
"""

import json, os, sys, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .strategy_factory import ParsedStrategy
from .market_snapshot import MarketSnapshot
from .strategy_executor import (
    evaluate_exit_conditions, ExitCheckResult,
    generate_trade_summary, print_trade_summary, TradeSummary,
)


@dataclass
class MonitorState:
    """Tracks the state of a monitored position across checks."""
    position: dict = field(default_factory=dict)
    parsed_strategy: Optional[ParsedStrategy] = None
    entry_time: str = ""
    check_count: int = 0
    market_history: list = field(default_factory=list)  # last N market snapshots
    exit_history: list = field(default_factory=list)     # last N exit checks
    alerts: list = field(default_factory=list)            # risk alerts raised
    closed: bool = False
    trade_summary: Optional[TradeSummary] = None


class PositionMonitor:
    """Monitors open positions using market data from Skills.

    Usage:
        monitor = PositionMonitor(parsed_strategy)
        monitor.start(position, entry_time)

        # Each cycle (Claude Code calls Skills, then):
        market = build_market_snapshot_from_skills(...)
        result = monitor.check(market)

        if result.should_exit:
            # Close position, then:
            summary = monitor.close(result)
            print_trade_summary(summary)
    """

    MAX_HISTORY = 50

    def __init__(self, parsed: ParsedStrategy):
        self.parsed = parsed
        self.state = MonitorState(parsed_strategy=parsed)

    def start(self, position: dict, entry_time: str = ""):
        """Initialize monitoring for a new position."""
        self.state.position = position
        self.state.entry_time = entry_time or datetime.now(timezone.utc).isoformat()
        self.state.check_count = 0
        self.state.market_history = []
        self.state.exit_history = []
        self.state.alerts = []
        self.state.closed = False
        self.state.trade_summary = None

        direction = position.get("holdSide", "long")
        entry_price = float(position.get("openPriceAvg", 0))
        size = position.get("total", "?")
        print(f"\n  [持仓监控] 开始监控 {direction.upper()} 仓位")
        print(f"  入场价: {entry_price:.2f} | 数量: {size}")
        print(f"  策略: {self.parsed.template} | 止损: {self.parsed.stop_loss_pct}% | 止盈: {self.parsed.take_profit_pct}%")

    def check(self, market: MarketSnapshot) -> ExitCheckResult:
        """Run one monitoring cycle with fresh market data.

        Args:
            market: Fresh MarketSnapshot from Skills

        Returns:
            ExitCheckResult with should_exit, urgency, reason, alerts
        """
        if self.state.closed:
            return ExitCheckResult(
                should_exit=False,
                reason="Position already closed",
            )

        self.state.check_count += 1

        # Keep history bounded
        self.state.market_history.append(market.to_dict())
        if len(self.state.market_history) > self.MAX_HISTORY:
            self.state.market_history = self.state.market_history[-self.MAX_HISTORY:]

        # Evaluate exit conditions
        result = evaluate_exit_conditions(
            self.state.position, market, self.parsed,
        )

        self.state.exit_history.append(result)
        if len(self.state.exit_history) > self.MAX_HISTORY:
            self.state.exit_history = self.state.exit_history[-self.MAX_HISTORY:]

        # Collect alerts
        for alert in result.risk_alerts:
            self.state.alerts.append({
                "check": self.state.check_count,
                "time": datetime.now(timezone.utc).isoformat(),
                "alert": alert,
                "urgency": result.urgency,
            })

        # Print monitoring status
        self._print_status(market, result)

        return result

    def _print_status(self, market: MarketSnapshot, result: ExitCheckResult):
        """Print one-line monitoring status."""
        t = market.technical
        pnl = result.pnl_pct
        pnl_str = f"+{pnl:.1f}%" if pnl >= 0 else f"{pnl:.1f}%"
        urgency_icon = {"none": "-", "alert": "!", "warning": "!!", "immediate": "!!!"}

        status_line = (
            f"  [Check #{self.state.check_count}] "
            f"Price={t.close:.1f} | RSI={t.rsi:.0f}" if t.rsi else f"  [Check #{self.state.check_count}] Price={t.close:.1f}"
        ) + (
            f" | PnL={pnl_str} | "
            f"{urgency_icon.get(result.urgency, '-')} {result.urgency.upper()}"
        )

        print(status_line)

        if result.risk_alerts:
            for alert in result.risk_alerts:
                print(f"    [ALERT] {alert}")

        if result.should_exit:
            print(f"    [EXIT] 建议平仓: {result.reason}")

    def close(self, exit_result: ExitCheckResult, exit_price: float = 0.0,
              monitoring_log: list = None) -> TradeSummary:
        """Close monitoring and generate trade summary.

        Args:
            exit_result: The exit check that triggered close
            exit_price: Actual exit price from exchange
            monitoring_log: Optional list of all monitoring check summaries

        Returns:
            TradeSummary
        """
        self.state.closed = True

        # Update exit price
        if exit_price > 0:
            exit_result.exit_price = exit_price

        summary = generate_trade_summary(
            position=self.state.position,
            exit_check=exit_result,
            parsed=self.parsed,
            entry_time=self.state.entry_time,
            monitoring_log=monitoring_log or [
                {"check": i, "urgency": e.urgency, "reason": e.reason}
                for i, e in enumerate(self.state.exit_history)
            ],
        )

        self.state.trade_summary = summary
        return summary

    def status_summary(self) -> dict:
        """Get a quick status summary of the monitored position."""
        p = self.state.position
        direction = p.get("holdSide", "long")
        entry_price = float(p.get("openPriceAvg", 0))
        mark_price = float(p.get("markPrice", 0))
        if entry_price > 0:
            pnl = (mark_price - entry_price) / entry_price * 100
            if direction == "short":
                pnl = -pnl
        else:
            pnl = 0

        return {
            "symbol": p.get("symbol", self.parsed.symbol),
            "direction": direction,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "pnl_pct": round(pnl, 2),
            "checks": self.state.check_count,
            "alerts": len(self.state.alerts),
            "closed": self.state.closed,
        }

    def to_dict(self) -> dict:
        """Serialize monitor state for logging."""
        return {
            "position": self.state.position,
            "strategy": {
                "symbol": self.parsed.symbol,
                "template": self.parsed.template,
                "timeframe": self.parsed.timeframe,
                "direction": self.parsed.direction,
            },
            "entry_time": self.state.entry_time,
            "checks": self.state.check_count,
            "alerts": self.state.alerts[-20:],
            "closed": self.state.closed,
            "summary": self.state.trade_summary.__dict__ if self.state.trade_summary else None,
        }


def print_monitor_status(monitor: PositionMonitor):
    """Print current monitoring status for the user."""
    s = monitor.status_summary()
    direction = "LONG" if s["direction"] == "long" else "SHORT"
    pnl_icon = "+" if s["pnl_pct"] >= 0 else ""
    print(f"\n  [持仓状态] {s['symbol']} {direction}")
    print(f"  入场价: {s['entry_price']:.2f} | 标记价: {s['mark_price']:.2f}")
    print(f"  浮动盈亏: {pnl_icon}{s['pnl_pct']:.2f}%")
    print(f"  监控周期: {s['checks']} | 风险预警: {s['alerts']} 次")
    print(f"  状态: {'已平仓' if s['closed'] else '持仓中'}")
