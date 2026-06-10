"""Risk layer: position sizing, exposure limits, daily loss circuit breaker, RR filter."""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

from .config import AgentConfig
from .decision import Signal, SignalType


@dataclass
class RiskResult:
    """Output of the risk manager check."""
    approved: bool
    adjusted_size: Optional[float] = None   # position size after risk scaling
    reason: str = ""
    checks: dict = field(default_factory=dict)


class RiskManager:
    """Pre-trade risk checks and position sizing.

    Checks performed in order:
      1. Daily loss circuit breaker (5% of equity)
      2. Maximum position size (2% risk per trade)
      3. Total exposure limit (30% of equity)
      4. Minimum risk/reward ratio (1.5:1)
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self._daily_pnl: float = 0.0
        self._daily_date: date = date.today()
        self._trade_count_today: int = 0

    def check(self, signal: Signal, account_equity: float,
              current_positions: Optional[List[dict]] = None) -> RiskResult:
        """Run all risk checks for a signal.

        Args:
            signal: The trading signal to evaluate.
            account_equity: Current account equity in USDT.
            current_positions: List of position dicts from Bitget API.

        Returns:
            RiskResult with approval status and adjusted position size.
        """
        if current_positions is None:
            current_positions = []

        checks = {}

        # ── 0. Hold / No-Trade pass through ──────────────────────────
        if signal.type in (SignalType.HOLD, SignalType.NO_TRADE):
            return RiskResult(approved=True, reason="Pass-through (no action)", checks={})

        # Exit signals always pass (we always want to be able to exit)
        if signal.is_exit():
            # Use the position's available size for exit
            for pos in current_positions:
                if pos.get("symbol") == signal.symbol:
                    available = float(pos.get("available", 0))
                    return RiskResult(
                        approved=True,
                        adjusted_size=available,
                        reason="Exit signal - always approved",
                        checks={"exit_approved": True},
                    )
            return RiskResult(
                approved=False,
                reason="Exit signal but no matching position found",
                checks={"exit_no_position": True},
            )

        # ── 1. Daily Loss Circuit Breaker ────────────────────────────
        self._reset_daily_if_new_day()
        daily_loss_pct = abs(self._daily_pnl) / account_equity if account_equity > 0 else 0
        cb_ok = daily_loss_pct < self.config.daily_loss_circuit_breaker
        checks["daily_loss_cb"] = {
            "ok": cb_ok,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_loss_pct": round(daily_loss_pct * 100, 2),
            "threshold_pct": round(self.config.daily_loss_circuit_breaker * 100, 2),
        }
        if not cb_ok:
            return RiskResult(
                approved=False,
                reason=f"Daily loss circuit breaker: {daily_loss_pct*100:.1f}% >= "
                       f"{self.config.daily_loss_circuit_breaker*100:.1f}%",
                checks=checks,
            )

        # ── 2. Position Size ─────────────────────────────────────────
        risk_amount = account_equity * self.config.max_position_pct
        checks["max_position"] = {
            "risk_amount_usdt": round(risk_amount, 2),
            "max_pct": round(self.config.max_position_pct * 100, 2),
        }

        # Calculate position size based on stop distance
        if signal.entry_price and signal.stop_loss:
            stop_distance = abs(signal.entry_price - signal.stop_loss)
            stop_pct = stop_distance / signal.entry_price if signal.entry_price > 0 else 0.01
            # Size such that (stop_distance * size) <= risk_amount
            raw_size = risk_amount / (stop_distance * signal.entry_price) if stop_distance > 0 else 0
            # Convert to notional value → contract quantity
            contract_size = risk_amount / signal.entry_price if signal.entry_price > 0 else 0
            # Cap position at 2% risk
            sized_by_risk = risk_amount / signal.entry_price if signal.entry_price > 0 else 0
        else:
            # Default: risk 2% of equity
            contract_size = account_equity * self.config.max_position_pct / (
                signal.entry_price or 1)
            sized_by_risk = contract_size
            stop_pct = 0

        # Apply leverage cap: position notional <= risk_amount * max_leverage
        max_notional = risk_amount * self.config.max_leverage
        position_notional = sized_by_risk * (signal.entry_price or 1)
        if position_notional > max_notional:
            sized_by_risk = max_notional / (signal.entry_price or 1)

        checks["position_sizing"] = {
            "contract_qty": round(sized_by_risk, self.config.size_precision),
            "notional_usdt": round(sized_by_risk * (signal.entry_price or 1), 2),
            "stop_distance_pct": round(stop_pct * 100, 2),
        }

        if sized_by_risk <= 0:
            return RiskResult(
                approved=False,
                reason="Position size too small (check entry price and equity)",
                checks=checks,
            )

        # ── 3. Total Exposure Limit ──────────────────────────────────
        current_exposure = 0.0
        for pos in current_positions:
            total = float(pos.get("total", 0))
            if total > 0:
                # Estimate notional: use mark price or open price avg
                mark = float(pos.get("markPrice", 0) or 0)
                entry = float(pos.get("openPriceAvg", 0) or 0)
                price = mark if mark > 0 else entry
                current_exposure += total * price if price > 0 else 0

        new_exposure = current_exposure + position_notional
        exposure_pct = new_exposure / account_equity if account_equity > 0 else 0
        exposure_ok = exposure_pct <= self.config.max_total_exposure_pct
        checks["total_exposure"] = {
            "ok": exposure_ok,
            "current_usdt": round(current_exposure, 2),
            "new_usdt": round(new_exposure, 2),
            "pct": round(exposure_pct * 100, 2),
            "limit_pct": round(self.config.max_total_exposure_pct * 100, 2),
        }
        if not exposure_ok:
            return RiskResult(
                approved=False,
                reason=f"Total exposure {exposure_pct*100:.1f}% exceeds "
                       f"limit {self.config.max_total_exposure_pct*100:.1f}%",
                checks=checks,
            )

        # ── 4. Risk/Reward Filter ────────────────────────────────────
        if signal.stop_loss and signal.take_profit and signal.entry_price:
            if signal.type == SignalType.ENTRY_LONG:
                risk = signal.entry_price - signal.stop_loss
                reward = signal.take_profit - signal.entry_price
            else:
                risk = signal.stop_loss - signal.entry_price
                reward = signal.entry_price - signal.take_profit
            rr = reward / risk if risk > 0 else 0
            rr_ok = rr >= self.config.min_risk_reward_ratio
            checks["risk_reward"] = {
                "ok": rr_ok,
                "ratio": round(rr, 2),
                "min_required": self.config.min_risk_reward_ratio,
                "risk": round(risk, 2),
                "reward": round(reward, 2),
            }
            if not rr_ok:
                return RiskResult(
                    approved=False,
                    reason=f"Risk/Reward {rr:.1f}:1 < minimum {self.config.min_risk_reward_ratio}:1",
                    checks=checks,
                )
        else:
            checks["risk_reward"] = {"ok": True, "note": "No SL/TP set - using defaults"}

        # ── All checks passed ────────────────────────────────────────
        qty = round(sized_by_risk, self.config.size_precision)
        # Ensure minimum trade size
        if qty < 0.0001:
            qty = 0.0001

        return RiskResult(
            approved=True,
            adjusted_size=qty,
            reason=f"All checks passed | size={qty} | risk={risk_amount:.2f} USDT",
            checks=checks,
        )

    def record_trade_result(self, pnl: float):
        """Record a completed trade's PnL for daily loss tracking."""
        self._reset_daily_if_new_day()
        self._daily_pnl += pnl
        self._trade_count_today += 1

    def _reset_daily_if_new_day(self):
        today = date.today()
        if today != self._daily_date:
            self._daily_pnl = 0.0
            self._daily_date = today
            self._trade_count_today = 0
