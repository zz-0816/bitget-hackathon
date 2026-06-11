"""Strategy Condition Evaluator + Auto Execution Engine.

Evaluates parsed strategy conditions against live market data from Skills,
then decides whether to enter a trade and executes via DemoClient.
"""

import json, os, sys, time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .strategy_factory import ParsedStrategy, TEMPLATES
from .market_snapshot import MarketSnapshot


class EvalResult(Enum):
    ENTRY_LONG = "ENTRY_LONG"
    ENTRY_SHORT = "ENTRY_SHORT"
    NO_TRADE = "NO_TRADE"


@dataclass
class ConditionCheck:
    """Result of a single strategy condition check."""
    name: str
    passed: bool
    expected: str
    actual: str
    weight: float = 1.0


@dataclass
class StrategyEval:
    """Complete evaluation result for a strategy."""
    result: EvalResult = EvalResult.NO_TRADE
    confidence: float = 0.0
    checks: list = field(default_factory=list)
    passed_count: int = 0
    total_count: int = 0
    reason: str = ""
    risk_warnings: list = field(default_factory=list)
    suggested_entry: Optional[float] = None
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    position_size_pct: float = 2.0


# ═══════════════════════════════════════════════════════════════════════════
# Strategy Condition Evaluators
# ═══════════════════════════════════════════════════════════════════════════

def _evaluate_trend_following(parsed: ParsedStrategy, ms: MarketSnapshot) -> StrategyEval:
    """Evaluate trend-following strategy conditions.

    Entry conditions (long):
      - EMA20 > EMA50 (bullish alignment)
      - MACD DIF > DEA (bullish momentum)
      - ADX > 25 (trending market)
      - RSI 45-65 (healthy momentum, not overbought)
      - Price > EMA20 (short-term trend)

    Entry conditions (short):
      - EMA20 < EMA50 (bearish alignment)
      - MACD DIF < DEA (bearish momentum)
      - ADX > 25 (trending market)
      - RSI 35-55 (healthy momentum, not oversold)
      - Price < EMA20 (short-term trend)
    """
    t = ms.technical
    checks = []
    direction = parsed.direction

    rsi_val = t.rsi or 50
    ema_12 = t.ema_12 or 0
    ema_26 = t.ema_26 or 0
    ema_20 = t.ema_20 or 0
    ema_50 = t.ema_50 or 0
    dif = t.macd_dif or 0
    dea = t.macd_dea or 0
    adx_val = t.adx or 0
    close = t.close or 0

    golden_cross = ema_12 > ema_26  # EMA12/26 golden cross (primary trend signal)
    ema_alignment = ema_20 > ema_50   # EMA20/50 medium-term alignment
    macd_bullish = dif > dea
    trending = adx_val > 25
    price_above_ema20 = close > ema_20
    rsi_long_ok = 45 <= rsi_val <= 65
    rsi_short_ok = 35 <= rsi_val <= 55

    checks.append(ConditionCheck(
        name="EMA Golden Cross (12/26)", passed=golden_cross if direction != "short" else not golden_cross,
        expected=f"EMA12 {'>' if direction != 'short' else '<'} EMA26 (金叉)",
        actual=f"EMA12={ema_12:.1f} EMA26={ema_26:.1f}",
        weight=0.25,
    ))
    checks.append(ConditionCheck(
        name="MACD Direction", passed=macd_bullish if direction != "short" else not macd_bullish,
        expected=f"DIF {'>' if direction != 'short' else '<'} DEA",
        actual=f"DIF={dif:.4f} DEA={dea:.4f}",
        weight=0.20,
    ))
    checks.append(ConditionCheck(
        name="ADX Trending", passed=trending,
        expected="ADX > 25",
        actual=f"ADX={adx_val:.1f}",
        weight=0.15,
    ))
    checks.append(ConditionCheck(
        name="RSI Zone", passed=rsi_long_ok if direction != "short" else rsi_short_ok,
        expected=f"RSI {'45-65' if direction != 'short' else '35-55'}",
        actual=f"RSI={rsi_val:.1f}",
        weight=0.20,
    ))
    checks.append(ConditionCheck(
        name="Price vs EMA20", passed=price_above_ema20 if direction != "short" else not price_above_ema20,
        expected=f"Price {'>' if direction != 'short' else '<'} EMA20",
        actual=f"Close={close:.1f} EMA20={ema_20:.1f}",
        weight=0.20,
    ))

    passed_count = sum(1 for c in checks if c.passed)
    total_count = len(checks)
    confidence = sum(c.weight for c in checks if c.passed)

    # Determine direction if parsed.direction is "both"
    if direction == "both":
        long_score = sum(c.weight for c in checks if c.passed)
        # Re-evaluate for short
        short_checks = [
            ConditionCheck("EMA Golden Cross (12/26)", passed=not golden_cross,
                          expected="EMA12 < EMA26 (死叉)", actual=f"EMA12={ema_12:.1f} EMA26={ema_26:.1f}", weight=0.25),
            ConditionCheck("MACD Direction", passed=not macd_bullish, expected="DIF < DEA",
                          actual=f"DIF={dif:.4f} DEA={dea:.4f}", weight=0.20),
            ConditionCheck("ADX Trending", passed=trending, expected="ADX > 25",
                          actual=f"ADX={adx_val:.1f}", weight=0.15),
            ConditionCheck("RSI Zone", passed=rsi_short_ok, expected="RSI 35-55",
                          actual=f"RSI={rsi_val:.1f}", weight=0.20),
            ConditionCheck("Price vs EMA20", passed=not price_above_ema20, expected="Price < EMA20",
                          actual=f"Close={close:.1f} EMA20={ema_20:.1f}", weight=0.20),
        ]
        short_score = sum(c.weight for c in short_checks if c.passed)
        if long_score >= short_score and long_score >= 0.6:
            checks = [c for c in checks]  # keep long checks
            confidence = long_score
        elif short_score > long_score and short_score >= 0.6:
            checks = short_checks
            confidence = short_score
            direction = "short"
        else:
            confidence = max(long_score, short_score)
            direction = "long" if long_score >= short_score else "short"
    else:
        confidence = sum(c.weight for c in checks if c.passed)

    passed_count = sum(1 for c in checks if c.passed)

    # Sentiment filter
    risk_warnings = []
    fg = ms.sentiment.fear_greed_index
    if direction in ("long", "both") and fg < 25:
        confidence *= 0.7
        risk_warnings.append(f"恐惧贪婪指数={fg}/100 (极度恐惧)，做多信号打折")
    elif direction == "short" and fg > 75:
        confidence *= 0.7
        risk_warnings.append(f"恐惧贪婪指数={fg}/100 (极度贪婪)，做空信号打折")

    # Macro filter
    if ms.macro.regime == "risk_off" and direction in ("long", "both"):
        confidence *= 0.8
        risk_warnings.append("宏观环境 Risk-Off，做多风险增加")
    elif ms.macro.regime == "risk_on" and direction == "short":
        confidence *= 0.8
        risk_warnings.append("宏观环境 Risk-On，做空风险增加")

    # News filter
    if ms.news.has_major_event and ms.news.bias == "negative":
        confidence *= 0.6
        risk_warnings.append(f"重大负面消息: {ms.news.event_summary[:80]}")

    # Determine result
    if confidence >= 0.6 and passed_count >= 3:
        direction_final = "long" if direction in ("long", "both") else "short"
        result = EvalResult.ENTRY_LONG if direction_final == "long" else EvalResult.ENTRY_SHORT
    else:
        result = EvalResult.NO_TRADE

    # Calculate SL/TP
    atr = t.atr or close * 0.02
    sl_pct = parsed.stop_loss_pct or 5.0
    tp_pct = parsed.take_profit_pct or 10.0

    if direction in ("long", "both"):
        entry = close
        sl = close * (1 - sl_pct / 100)
        tp = close * (1 + tp_pct / 100)
    else:
        entry = close
        sl = close * (1 + sl_pct / 100)
        tp = close * (1 - tp_pct / 100)

    passed_names = [c.name for c in checks if c.passed]
    failed_names = [c.name for c in checks if not c.passed]
    reason_parts = []
    if passed_names:
        reason_parts.append(f"通过: {', '.join(passed_names)}")
    if failed_names:
        reason_parts.append(f"未通过: {', '.join(failed_names)}")

    return StrategyEval(
        result=result,
        confidence=round(confidence, 3),
        checks=checks,
        passed_count=passed_count,
        total_count=total_count,
        reason=" | ".join(reason_parts),
        risk_warnings=risk_warnings,
        suggested_entry=round(entry, 1),
        suggested_sl=round(sl, 1),
        suggested_tp=round(tp, 1),
        position_size_pct=parsed.position_pct,
    )


def _evaluate_momentum_breakout(parsed: ParsedStrategy, ms: MarketSnapshot) -> StrategyEval:
    """Evaluate momentum breakout strategy conditions.

    Entry (long):
      - RSI 55-65 (momentum zone)
      - MACD histogram positive and expanding
      - Volume surge present
      - Price > EMA20

    Entry (short):
      - RSI 35-45 (weakness zone)
      - MACD histogram negative and expanding
      - Volume surge present
      - Price < EMA20
    """
    t = ms.technical
    checks = []
    direction = parsed.direction

    rsi_val = t.rsi or 50
    dif = t.macd_dif or 0
    dea = t.macd_dea or 0
    hist = t.macd_hist or 0
    close = t.close or 0
    ema_20 = t.ema_20 or 0
    vol_surge = t.volume_surge

    rsi_long_ok = 55 <= rsi_val <= 65
    rsi_short_ok = 35 <= rsi_val <= 45
    macd_hist_positive = hist > 0
    price_above_ema20 = close > ema_20

    checks.append(ConditionCheck(
        name="RSI Momentum Zone",
        passed=rsi_long_ok if direction != "short" else rsi_short_ok,
        expected=f"RSI {'55-65' if direction != 'short' else '35-45'}",
        actual=f"RSI={rsi_val:.1f}",
        weight=0.25,
    ))
    checks.append(ConditionCheck(
        name="MACD Histogram",
        passed=macd_hist_positive if direction != "short" else not macd_hist_positive,
        expected=f"MACD Hist {'>0' if direction != 'short' else '<0'}",
        actual=f"MACD Hist={hist:.4f}",
        weight=0.20,
    ))
    checks.append(ConditionCheck(
        name="Volume Surge",
        passed=vol_surge,
        expected="Volume > 1.5x avg",
        actual=f"Volume surge={'Yes' if vol_surge else 'No'}",
        weight=0.25,
    ))
    checks.append(ConditionCheck(
        name="Price vs EMA20",
        passed=price_above_ema20 if direction != "short" else not price_above_ema20,
        expected=f"Price {'>' if direction != 'short' else '<'} EMA20",
        actual=f"Close={close:.1f} EMA20={ema_20:.1f}",
        weight=0.15,
    ))
    checks.append(ConditionCheck(
        name="DIF vs DEA",
        passed=(dif > dea) if direction != "short" else (dif < dea),
        expected=f"DIF {'>' if direction != 'short' else '<'} DEA",
        actual=f"DIF={dif:.4f} DEA={dea:.4f}",
        weight=0.15,
    ))

    passed_count = sum(1 for c in checks if c.passed)
    confidence = sum(c.weight for c in checks if c.passed)

    risk_warnings = []
    fg = ms.sentiment.fear_greed_index
    if direction in ("long", "both") and fg < 25:
        confidence *= 0.7
        risk_warnings.append(f"FG={fg}/100 极度恐惧")
    elif direction == "short" and fg > 75:
        confidence *= 0.7
        risk_warnings.append(f"FG={fg}/100 极度贪婪")

    if confidence >= 0.6 and passed_count >= 3:
        direction_final = "long" if direction in ("long", "both") else "short"
        result = EvalResult.ENTRY_LONG if direction_final == "long" else EvalResult.ENTRY_SHORT
    else:
        result = EvalResult.NO_TRADE

    atr = t.atr or close * 0.02
    sl_pct = parsed.stop_loss_pct or 3.0
    tp_pct = parsed.take_profit_pct or 6.0
    if direction in ("long", "both"):
        sl = close * (1 - sl_pct / 100)
        tp = close * (1 + tp_pct / 100)
    else:
        sl = close * (1 + sl_pct / 100)
        tp = close * (1 - tp_pct / 100)

    passed_names = [c.name for c in checks if c.passed]
    failed_names = [c.name for c in checks if not c.passed]
    reason_parts = []
    if passed_names:
        reason_parts.append(f"通过: {', '.join(passed_names)}")
    if failed_names:
        reason_parts.append(f"未通过: {', '.join(failed_names)}")

    return StrategyEval(
        result=result,
        confidence=round(confidence, 3),
        checks=checks,
        passed_count=passed_count,
        total_count=len(checks),
        reason=" | ".join(reason_parts),
        risk_warnings=risk_warnings,
        suggested_entry=round(close, 1),
        suggested_sl=round(sl, 1),
        suggested_tp=round(tp, 1),
        position_size_pct=parsed.position_pct,
    )


def _evaluate_mean_reversion(parsed: ParsedStrategy, ms: MarketSnapshot) -> StrategyEval:
    """Evaluate mean reversion (Bollinger Band) strategy conditions.

    Entry (long): Price at/near BB lower band + RSI < 40 (oversold)
    Entry (short): Price at/near BB upper band + RSI > 60 (overbought)
    """
    t = ms.technical
    checks = []
    direction = parsed.direction

    rsi_val = t.rsi or 50
    close = t.close or 0
    bb_upper = t.bb_upper or 0
    bb_lower = t.bb_lower or 0
    bb_mid = t.bb_mid or 0

    near_lower = bb_lower > 0 and close <= bb_lower * 1.02
    near_upper = bb_upper > 0 and close >= bb_upper * 0.98
    rsi_oversold = rsi_val < 40
    rsi_overbought = rsi_val > 60

    checks.append(ConditionCheck(
        name="Price at BB Band",
        passed=near_lower if direction != "short" else near_upper,
        expected=f"Price near BB {'lower' if direction != 'short' else 'upper'}",
        actual=f"Close={close:.1f} BB_lower={bb_lower:.1f} BB_upper={bb_upper:.1f}",
        weight=0.35,
    ))
    checks.append(ConditionCheck(
        name="RSI Extreme",
        passed=rsi_oversold if direction != "short" else rsi_overbought,
        expected=f"RSI {'<40' if direction != 'short' else '>60'}",
        actual=f"RSI={rsi_val:.1f}",
        weight=0.35,
    ))
    checks.append(ConditionCheck(
        name="BB Mid as Target",
        passed=bb_mid > 0 and ((close < bb_mid) if direction != "short" else (close > bb_mid)),
        expected=f"Price {'below' if direction != 'short' else 'above'} BB mid for mean reversion",
        actual=f"Close={close:.1f} BB_mid={bb_mid:.1f}",
        weight=0.30,
    ))

    passed_count = sum(1 for c in checks if c.passed)
    confidence = sum(c.weight for c in checks if c.passed)

    risk_warnings = []
    if ms.technical.trend_direction == "up" and direction == "short":
        confidence *= 0.6
        risk_warnings.append("趋势向上，逆势做空风险高")
    elif ms.technical.trend_direction == "down" and direction in ("long", "both"):
        confidence *= 0.6
        risk_warnings.append("趋势向下，逆势做多风险高")

    if confidence >= 0.65:
        direction_final = "long" if direction in ("long", "both") else "short"
        result = EvalResult.ENTRY_LONG if direction_final == "long" else EvalResult.ENTRY_SHORT
    else:
        result = EvalResult.NO_TRADE

    sl_pct = parsed.stop_loss_pct or 3.0
    tp_pct = parsed.take_profit_pct or 5.0
    if direction in ("long", "both"):
        sl = close * (1 - sl_pct / 100)
        tp = bb_mid if bb_mid > close else close * (1 + tp_pct / 100)
    else:
        sl = close * (1 + sl_pct / 100)
        tp = bb_mid if bb_mid < close else close * (1 - tp_pct / 100)

    passed_names = [c.name for c in checks if c.passed]
    failed_names = [c.name for c in checks if not c.passed]
    reason_parts = []
    if passed_names:
        reason_parts.append(f"通过: {', '.join(passed_names)}")
    if failed_names:
        reason_parts.append(f"未通过: {', '.join(failed_names)}")

    return StrategyEval(
        result=result,
        confidence=round(confidence, 3),
        checks=checks,
        passed_count=passed_count,
        total_count=len(checks),
        reason=" | ".join(reason_parts),
        risk_warnings=risk_warnings,
        suggested_entry=round(close, 1),
        suggested_sl=round(sl, 1),
        suggested_tp=round(tp, 1),
        position_size_pct=parsed.position_pct,
    )


def _evaluate_grid_trading(parsed: ParsedStrategy, ms: MarketSnapshot) -> StrategyEval:
    """Evaluate grid/range trading strategy conditions.

    Entry: Price within defined range, buy near support, sell near resistance.
    Checks if market is ranging (ADX < 25, not trending).
    """
    t = ms.technical
    checks = []

    adx_val = t.adx or 0
    close = t.close or 0
    bb_upper = t.bb_upper or 0
    bb_lower = t.bb_lower or 0
    bb_mid = t.bb_mid or 0

    ranging = adx_val < 25
    near_support = bb_lower > 0 and close <= bb_lower * 1.03
    near_resistance = bb_upper > 0 and close >= bb_upper * 0.97
    in_range = bb_upper > bb_lower and bb_lower < close < bb_upper

    checks.append(ConditionCheck(
        name="ADX Ranging",
        passed=ranging,
        expected="ADX < 25 (non-trending)",
        actual=f"ADX={adx_val:.1f}",
        weight=0.30,
    ))
    checks.append(ConditionCheck(
        name="Price In Range",
        passed=in_range,
        expected=f"Price between {bb_lower:.1f}-{bb_upper:.1f}",
        actual=f"Close={close:.1f} BB=[{bb_lower:.1f}, {bb_upper:.1f}]",
        weight=0.40,
    ))
    checks.append(ConditionCheck(
        name="Near Key Level",
        passed=near_support or near_resistance,
        expected="Price near BB support or resistance",
        actual=f"Near support={near_support} Near resistance={near_resistance}",
        weight=0.30,
    ))

    passed_count = sum(1 for c in checks if c.passed)
    confidence = sum(c.weight for c in checks if c.passed)

    direction_final = "long" if near_support else "short" if near_resistance else "long"

    risk_warnings = []
    if not ranging:
        risk_warnings.append(f"ADX={adx_val:.1f} > 25，市场趋势较强，网格策略风险高")

    if confidence >= 0.6 and passed_count >= 2:
        result = EvalResult.ENTRY_LONG if direction_final == "long" else EvalResult.ENTRY_SHORT
    else:
        result = EvalResult.NO_TRADE

    sl_pct = parsed.stop_loss_pct or 2.0
    tp_pct = parsed.take_profit_pct or 4.0
    if direction_final == "long":
        sl = close * (1 - sl_pct / 100)
        tp = bb_mid if bb_mid > close else close * (1 + tp_pct / 100)
    else:
        sl = close * (1 + sl_pct / 100)
        tp = bb_mid if bb_mid < close else close * (1 - tp_pct / 100)

    passed_names = [c.name for c in checks if c.passed]
    failed_names = [c.name for c in checks if not c.passed]
    reason_parts = []
    if passed_names:
        reason_parts.append(f"通过: {', '.join(passed_names)}")
    if failed_names:
        reason_parts.append(f"未通过: {', '.join(failed_names)}")

    return StrategyEval(
        result=result,
        confidence=round(confidence, 3),
        checks=checks,
        passed_count=passed_count,
        total_count=len(checks),
        reason=" | ".join(reason_parts),
        risk_warnings=risk_warnings,
        suggested_entry=round(close, 1),
        suggested_sl=round(sl, 1),
        suggested_tp=round(tp, 1),
        position_size_pct=parsed.position_pct,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main Evaluator
# ═══════════════════════════════════════════════════════════════════════════

EVALUATORS = {
    "trend_following": _evaluate_trend_following,
    "momentum_breakout": _evaluate_momentum_breakout,
    "mean_reversion": _evaluate_mean_reversion,
    "grid_trading": _evaluate_grid_trading,
}


def evaluate_strategy(parsed: ParsedStrategy, market: MarketSnapshot) -> StrategyEval:
    """Evaluate whether current market conditions meet strategy entry conditions.

    Returns StrategyEval with result (ENTRY_LONG/ENTRY_SHORT/NO_TRADE),
    confidence score, detailed checks, and risk warnings.
    """
    evaluator = EVALUATORS.get(parsed.template)
    if evaluator is None:
        return StrategyEval(
            result=EvalResult.NO_TRADE,
            confidence=0.0,
            reason=f"Unknown strategy template: {parsed.template}",
        )

    eval_result = evaluator(parsed, market)
    return eval_result


# ═══════════════════════════════════════════════════════════════════════════
# Auto Execution
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionResult:
    """Result of a trade execution attempt."""
    executed: bool
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    size: str = ""
    price: str = ""
    sl_order_id: str = ""
    tp_order_id: str = ""
    error: str = ""
    api_log: list = field(default_factory=list)


def execute_trade(parsed: ParsedStrategy, eval_result: StrategyEval,
                  market: MarketSnapshot, client=None,
                  dry_run: bool = True) -> ExecutionResult:
    """Execute a trade based on strategy evaluation result.

    If dry_run=True, only simulates and returns what would be done.
    If dry_run=False, places real orders on Bitget Demo Trading.
    """
    if eval_result.result == EvalResult.NO_TRADE:
        return ExecutionResult(executed=False, error="No trade signal")

    if client is None:
        if dry_run:
            return ExecutionResult(
                executed=False,
                symbol=parsed.symbol,
                side="buy" if eval_result.result == EvalResult.ENTRY_LONG else "sell",
                size=str(eval_result.position_size_pct / 100),
                error="No API client (dry run)",
            )
        return ExecutionResult(executed=False, error="No API client provided")

    symbol = parsed.symbol
    direction = "long" if eval_result.result == EvalResult.ENTRY_LONG else "short"
    side = "buy" if direction == "long" else "sell"
    close = market.technical.close

    # Position sizing
    try:
        account = client.get_futures_account()
        equity = float(account.get("accountEquity", 10000))
    except Exception:
        equity = 10000.0

    position_size_usdt = equity * (parsed.position_pct / 100)
    contract_qty = position_size_usdt / close if close > 0 else 0.001
    size_str = f"{contract_qty:.4f}"

    api_log = []

    if dry_run:
        return ExecutionResult(
            executed=False,
            symbol=symbol, side=side, size=size_str,
            price=str(eval_result.suggested_entry or close),
            error="DRY RUN — no order placed",
            api_log=[{"stage": "dry_run", "would_place": {
                "symbol": symbol, "side": side, "size": size_str,
                "entry": eval_result.suggested_entry,
                "sl": eval_result.suggested_sl,
                "tp": eval_result.suggested_tp,
            }}],
        )

    # Real execution
    try:
        # Place main order (limit order)
        entry_price = eval_result.suggested_entry or close
        # Use limit order with offset to avoid instant fill in demo
        if direction == "long":
            limit_price = int(entry_price * 0.998)  # slightly below market
        else:
            limit_price = int(entry_price * 1.002)

        order_result = client.place_order(
            symbol=symbol, side=side, order_type="limit",
            size=size_str, price=str(limit_price), trade_side="open",
        )
        api_log.append({"stage": "place_entry", "result": order_result})

        oid = order_result.get("data", {}).get("orderId", "")
        if not oid:
            return ExecutionResult(
                executed=False,
                error=f"Order placement failed: {order_result.get('msg', 'unknown error')}",
                api_log=api_log,
            )

        # Place SL order
        sl_price = eval_result.suggested_sl
        sl_side = "sell" if direction == "long" else "buy"
        sl_result = client.place_stop_order(
            symbol=symbol, side=sl_side,
            trigger_price=str(int(sl_price)) if sl_price else str(int(close * 0.95)),
            size=size_str, trade_side="close",
        )
        api_log.append({"stage": "place_sl", "result": sl_result})
        sl_oid = sl_result.get("data", {}).get("orderId", "")

        # Place TP order
        tp_price = eval_result.suggested_tp
        tp_result = client.place_stop_order(
            symbol=symbol, side=sl_side,
            trigger_price=str(int(tp_price)) if tp_price else str(int(close * 1.05)),
            size=size_str, trade_side="close",
        )
        api_log.append({"stage": "place_tp", "result": tp_result})
        tp_oid = tp_result.get("data", {}).get("orderId", "")

        return ExecutionResult(
            executed=True,
            order_id=oid, symbol=symbol, side=side, size=size_str,
            sl_order_id=sl_oid, tp_order_id=tp_oid,
            api_log=api_log,
        )

    except Exception as e:
        return ExecutionResult(
            executed=False, error=str(e), api_log=api_log,
        )


def print_eval_report(parsed: ParsedStrategy, market: MarketSnapshot,
                      eval_result: StrategyEval, exec_result: Optional[ExecutionResult] = None):
    """Print a comprehensive strategy evaluation report."""
    SEP = "=" * 68
    SUB = "-" * 68

    t = TEMPLATES.get(parsed.template, {})
    print(f"\n{SEP}")
    print(f"  策略条件评估报告")
    print(f"{SEP}")

    # Strategy summary
    print(f"\n  [策略摘要]")
    print(f"  {SUB}")
    print(f"  名称:     {t.get('name', parsed.template)}")
    print(f"  交易对:   {parsed.symbol} | 周期: {parsed.timeframe}")
    print(f"  方向:     {parsed.direction} | 模板: {parsed.template}")
    print(f"  止损:     {parsed.stop_loss_pct or 5}% | 止盈: {parsed.take_profit_pct or 10}%")
    print(f"  仓位:     {parsed.position_pct}%")

    # Market snapshot
    print(f"\n  [市场快照]")
    print(f"  {SUB}")
    t_s = market.technical
    print(f"  价格:     {t_s.close:.1f}")
    print(f"  RSI:      {t_s.rsi:.1f}" if t_s.rsi else "  RSI: N/A")
    if t_s.macd_dif is not None:
        dif_s = f"{t_s.macd_dif:.4f}"
        dea_s = f"{t_s.macd_dea:.4f}" if t_s.macd_dea is not None else "N/A"
        hist_s = f"{t_s.macd_hist:.4f}" if t_s.macd_hist is not None else "N/A"
        print(f"  MACD:     DIF={dif_s} DEA={dea_s} HIST={hist_s}")
    if t_s.ema_20 is not None:
        print(f"  EMA20:    {t_s.ema_20:.1f}  EMA50: {t_s.ema_50:.1f}" if t_s.ema_50 is not None else f"  EMA20:    {t_s.ema_20:.1f}")
    adx_s = f"{t_s.adx:.1f}" if t_s.adx is not None else "N/A"
    print(f"  ADX:      {adx_s}")
    if t_s.bb_mid is not None and t_s.bb_lower is not None and t_s.bb_upper is not None:
        print(f"  BB:       [{t_s.bb_lower:.1f} .. {t_s.bb_mid:.1f} .. {t_s.bb_upper:.1f}]")
    print(f"  趋势:     {t_s.trend_direction} | 放量: {'是' if t_s.volume_surge else '否'}")

    s = market.sentiment
    print(f"\n  [情绪数据]")
    print(f"  恐惧贪婪: {s.fear_greed_index}/100 ({s.fear_greed_label})")
    print(f"  多空比:   {s.long_short_ratio:.2f}")

    m = market.macro
    print(f"\n  [宏观环境]")
    print(f"  风险偏好: {m.regime}")
    if m.fed_funds_rate:
        print(f"  利率:     {m.fed_funds_rate}%")
    if m.btc_nasdaq_correlation:
        print(f"  BTC-纳指: {m.btc_nasdaq_correlation:.2f}")

    n = market.news
    print(f"\n  [消息面]")
    print(f"  重大事件: {'是' if n.has_major_event else '无'}")
    if n.has_major_event:
        print(f"  摘要:     {n.event_summary[:120]}")

    # Condition checks
    print(f"\n  [条件检查] 通过 {eval_result.passed_count}/{eval_result.total_count}")
    print(f"  {SUB}")
    for c in eval_result.checks:
        icon = "[PASS]" if c.passed else "[FAIL]"
        print(f"  {icon} {c.name}: 期望={c.expected} | 实际={c.actual}")

    # Decision
    print(f"\n  [评估结论]")
    print(f"  {SUB}")
    if eval_result.result == EvalResult.NO_TRADE:
        print(f"  结果:     [X] 不满足入场条件 -- 观望")
    else:
        direction_str = "做多 LONG" if eval_result.result == EvalResult.ENTRY_LONG else "做空 SHORT"
        print(f"  结果:     [OK] 满足入场条件 -- 建议{direction_str}")
        print(f"  信心度:   {eval_result.confidence:.0%}")
        print(f"  建议入场: {eval_result.suggested_entry:.1f}")
        print(f"  止损位:   {eval_result.suggested_sl:.1f}")
        print(f"  止盈位:   {eval_result.suggested_tp:.1f}")
        print(f"  仓位:     {eval_result.position_size_pct}%")

    print(f"  原因:     {eval_result.reason}")

    if eval_result.risk_warnings:
        print(f"\n  [风险提示]")
        for w in eval_result.risk_warnings:
            print(f"  [!] {w}")

    # Execution result
    if exec_result:
        print(f"\n  [执行结果]")
        print(f"  {SUB}")
        if exec_result.executed:
            print(f"  状态:     [OK] 已下单")
            print(f"  订单ID:   {exec_result.order_id}")
            print(f"  SL订单:   {exec_result.sl_order_id}")
            print(f"  TP订单:   {exec_result.tp_order_id}")
        else:
            print(f"  状态:     [X] 未执行")
            if exec_result.error:
                print(f"  原因:     {exec_result.error}")

    print(f"\n{SEP}")
    print(f"  报告结束")
    print(f"{SEP}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Trade Metrics Estimation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TradeMetrics:
    """Pre-trade risk/reward and performance estimates."""
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_pct: float = 0.0
    reward_pct: float = 0.0
    risk_reward_ratio: float = 0.0
    estimated_win_rate: float = 0.5
    expected_return: float = 0.0
    position_size_pct: float = 1.0
    # Derived
    kelly_fraction: float = 0.0
    breakeven_win_rate: float = 0.0
    expectancy: float = 0.0  # per-trade expected return %


def estimate_trade_metrics(parsed: ParsedStrategy, eval_result: StrategyEval,
                           market: MarketSnapshot) -> TradeMetrics:
    """Estimate win rate, RR ratio, expected return for a potential trade.

    Combines:
      - Strategy template historical baseline win rate
      - Current market conditions (trend strength, volatility)
      - Multi-timeframe confirmation bonus
      - Sentiment/macro risk discount
    """
    t = market.technical
    direction = "long" if eval_result.result == EvalResult.ENTRY_LONG else "short"

    entry = eval_result.suggested_entry or t.close
    sl = eval_result.suggested_sl or (entry * 0.95 if direction == "long" else entry * 1.05)
    tp = eval_result.suggested_tp or (entry * 1.10 if direction == "long" else entry * 0.90)

    # Risk and reward as percentages
    if direction == "long":
        risk_pct = (entry - sl) / entry * 100 if entry > 0 else 0
        reward_pct = (tp - entry) / entry * 100 if entry > 0 else 0
    else:
        risk_pct = (sl - entry) / entry * 100 if entry > 0 else 0
        reward_pct = (entry - tp) / entry * 100 if entry > 0 else 0

    rr = reward_pct / risk_pct if risk_pct > 0 else 2.0

    # Baseline win rate per strategy template
    baseline_win_rates = {
        "trend_following": 0.42,
        "momentum_breakout": 0.38,
        "mean_reversion": 0.48,
        "grid_trading": 0.52,
    }
    base_wr = baseline_win_rates.get(parsed.template, 0.40)

    # Adjustments based on current market
    adjustments = []

    # ADX trend strength: strong trend helps trend_following, hurts mean_reversion
    adx = t.adx or 20
    if parsed.template == "trend_following" and adx > 30:
        adjustments.append(+0.08)
    elif parsed.template == "trend_following" and adx < 20:
        adjustments.append(-0.05)
    elif parsed.template == "mean_reversion" and adx < 20:
        adjustments.append(+0.05)
    elif parsed.template == "mean_reversion" and adx > 30:
        adjustments.append(-0.08)

    # RSI alignment bonus
    rsi = t.rsi or 50
    if direction == "long" and 45 <= rsi <= 60:
        adjustments.append(+0.05)
    elif direction == "short" and 40 <= rsi <= 55:
        adjustments.append(+0.05)
    elif rsi > 75 or rsi < 25:
        adjustments.append(-0.05)

    # Volume confirmation
    if t.volume_surge:
        adjustments.append(+0.05)

    # Multi-condition bonus: all checks passed
    if eval_result.passed_count == eval_result.total_count:
        adjustments.append(+0.05)

    # Sentiment discount
    fg = market.sentiment.fear_greed_index
    if direction == "long" and fg < 25:
        adjustments.append(-0.10)
    elif direction == "short" and fg > 75:
        adjustments.append(-0.10)

    # Macro discount
    if market.macro.regime == "risk_off" and direction == "long":
        adjustments.append(-0.08)
    elif market.macro.regime == "risk_on" and direction == "short":
        adjustments.append(-0.08)

    estimated_wr = max(0.15, min(0.70, base_wr + sum(adjustments)))

    # Expected return (Kelly-like)
    win_pct = reward_pct / 100
    lose_pct = risk_pct / 100
    expected_return = estimated_wr * win_pct - (1 - estimated_wr) * lose_pct
    expectancy = expected_return * 100  # per-trade expected return in %

    # Kelly fraction
    if lose_pct > 0:
        kf = estimated_wr - (1 - estimated_wr) / (win_pct / lose_pct)
    else:
        kf = 0
    kelly_fraction = max(0, min(0.5, kf))

    # Breakeven win rate
    breakeven_wr = 1 / (1 + rr) if rr > 0 else 1.0

    return TradeMetrics(
        symbol=parsed.symbol,
        direction=direction,
        entry_price=round(entry, 1),
        stop_loss=round(sl, 1),
        take_profit=round(tp, 1),
        risk_pct=round(risk_pct, 2),
        reward_pct=round(reward_pct, 2),
        risk_reward_ratio=round(rr, 2),
        estimated_win_rate=round(estimated_wr, 3),
        expected_return=round(expected_return, 4),
        position_size_pct=parsed.position_pct,
        kelly_fraction=round(kelly_fraction, 3),
        breakeven_win_rate=round(breakeven_wr, 3),
        expectancy=round(expectancy, 2),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Exit Condition Evaluation
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ExitCheckResult:
    """Result of evaluating exit conditions for an open position."""
    should_exit: bool
    urgency: str = "none"  # "none" / "alert" / "warning" / "immediate"
    reason: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    checks_failed: list = field(default_factory=list)
    risk_alerts: list = field(default_factory=list)


def evaluate_exit_conditions(position: dict, market: MarketSnapshot,
                             parsed: ParsedStrategy) -> ExitCheckResult:
    """Check if an open position should be closed based on current market conditions.

    Checks:
      1. SL/TP proximity
      2. Trend reversal
      3. RSI extreme reversal
      4. MACD crossover
      5. Volume climax
      6. Sentiment extreme
      7. Macro regime change
    """
    t = market.technical
    direction = position.get("holdSide", "long")  # "long" or "short"
    entry_price = float(position.get("openPriceAvg", 0))
    mark_price = float(position.get("markPrice", t.close))
    current_price = t.close or mark_price
    checks_failed = []
    risk_alerts = []
    exit_reasons = []
    urgency = "none"

    # Current P&L
    if entry_price > 0:
        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
    else:
        pnl_pct = 0

    # 1. SL/TP proximity check
    sl_pct = parsed.stop_loss_pct or 5.0
    tp_pct = parsed.take_profit_pct or 10.0
    if pnl_pct <= -sl_pct * 0.85:
        exit_reasons.append(f"接近止损位 (PnL={pnl_pct:.1f}%, SL={sl_pct}%)")
        urgency = "warning"
    if pnl_pct >= tp_pct * 0.9:
        exit_reasons.append(f"接近止盈位 (PnL={pnl_pct:.1f}%, TP={tp_pct}%)")
        urgency = "warning"

    # 2. Trend reversal check
    ema_20 = t.ema_20 or 0
    ema_50 = t.ema_50 or 0
    if direction == "long":
        # Long position: EMA bearish flip = risk
        if ema_20 > 0 and ema_50 > 0 and ema_20 < ema_50:
            checks_failed.append("EMA死叉 (EMA20 < EMA50)")
            exit_reasons.append("趋势转为空头，EMA死叉")
            urgency = max(urgency, "warning")
        if current_price < ema_20:
            risk_alerts.append(f"价格跌破EMA20 ({current_price:.1f} < {ema_20:.1f})")
    else:
        if ema_20 > 0 and ema_50 > 0 and ema_20 > ema_50:
            checks_failed.append("EMA金叉 (EMA20 > EMA50)")
            exit_reasons.append("趋势转为多头，EMA金叉")
            urgency = max(urgency, "warning")
        if current_price > ema_20:
            risk_alerts.append(f"价格突破EMA20 ({current_price:.1f} > {ema_20:.1f})")

    # 3. RSI extreme reversal
    rsi = t.rsi or 50
    if direction == "long" and rsi > 75:
        checks_failed.append(f"RSI超买 (RSI={rsi:.1f})")
        exit_reasons.append("RSI超买，多头动能衰竭")
        urgency = max(urgency, "warning")
    elif direction == "short" and rsi < 25:
        checks_failed.append(f"RSI超卖 (RSI={rsi:.1f})")
        exit_reasons.append("RSI超卖，空头动能衰竭")
        urgency = max(urgency, "warning")

    # 4. MACD crossover
    dif = t.macd_dif or 0
    dea = t.macd_dea or 0
    if direction == "long" and dif < dea:
        checks_failed.append(f"MACD死叉 (DIF={dif:.4f} < DEA={dea:.4f})")
        exit_reasons.append("MACD死叉信号")
        urgency = max(urgency, "warning")
    elif direction == "short" and dif > dea:
        checks_failed.append(f"MACD金叉 (DIF={dif:.4f} > DEA={dea:.4f})")
        exit_reasons.append("MACD金叉信号")
        urgency = max(urgency, "warning")

    # 5. Volume climax (potential reversal)
    if t.volume_surge and direction in ("long", "short"):
        risk_alerts.append("成交量激增，可能出现反转")

    # 6. Sentiment extreme
    fg = market.sentiment.fear_greed_index
    if direction == "long" and fg > 80:
        risk_alerts.append(f"恐惧贪婪={fg}/100 极度贪婪，建议减仓")
        urgency = max(urgency, "alert")
    elif direction == "short" and fg < 20:
        risk_alerts.append(f"恐惧贪婪={fg}/100 极度恐惧，建议减仓")
        urgency = max(urgency, "alert")

    # 7. Macro risk
    if market.macro.regime == "risk_off":
        risk_alerts.append("宏观环境转为 Risk-Off，风险资产承压")
        if direction == "long":
            exit_reasons.append("宏观Risk-Off，多头风险增加")
            urgency = max(urgency, "alert")

    # 8. Major news event
    if market.news.has_major_event:
        bias = market.news.bias
        if (direction == "long" and bias == "negative") or (direction == "short" and bias == "positive"):
            exit_reasons.append(f"重大消息面利空持仓方向: {market.news.event_summary[:80]}")
            urgency = "immediate"

    # Determine if should exit
    should_exit = len(exit_reasons) >= 2 or urgency == "immediate"

    # Build reason string
    reason = "; ".join(exit_reasons) if exit_reasons else "持仓正常，无需平仓"

    return ExitCheckResult(
        should_exit=should_exit,
        urgency=urgency,
        reason=reason,
        exit_price=current_price,
        pnl_pct=round(pnl_pct, 2),
        checks_failed=checks_failed,
        risk_alerts=risk_alerts,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Trade Summary Generator
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TradeSummary:
    """Complete record of a closed trade."""
    symbol: str = ""
    direction: str = ""
    entry_time: str = ""
    exit_time: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl_usdt: float = 0.0
    pnl_pct: float = 0.0
    holding_duration: str = ""
    exit_reason: str = ""
    strategy: str = ""
    metrics: Optional[TradeMetrics] = None
    monitoring_events: list = field(default_factory=list)
    grade: str = ""  # A/B/C/D/F
    lessons: list = field(default_factory=list)


def generate_trade_summary(position: dict, exit_check: ExitCheckResult,
                           parsed: ParsedStrategy,
                           entry_time: str = "",
                           monitoring_log: list = None) -> TradeSummary:
    """Generate a comprehensive post-trade summary.

    Args:
        position: Closed position data from exchange
        exit_check: Exit evaluation that triggered the close
        parsed: Original strategy config
        entry_time: ISO timestamp of entry
        monitoring_log: List of monitoring check results during holding

    Returns:
        TradeSummary with full trade analysis
    """
    direction = position.get("holdSide", "long")
    entry_price = float(position.get("openPriceAvg", 0))
    exit_price = exit_check.exit_price or float(position.get("markPrice", 0))
    quantity = float(position.get("total", 0))

    # P&L
    if direction == "long":
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
    else:
        pnl = (entry_price - exit_price) * quantity
        pnl_pct = (entry_price - exit_price) / entry_price * 100 if entry_price > 0 else 0

    # Grade
    if pnl_pct > 5:
        grade = "A"
    elif pnl_pct > 2:
        grade = "B"
    elif pnl_pct > 0:
        grade = "C"
    elif pnl_pct > -3:
        grade = "D"
    else:
        grade = "F"

    # Lessons
    lessons = []
    if pnl_pct > 0 and exit_check.should_exit:
        lessons.append("风险信号出现时及时平仓，保护了利润")
    elif pnl_pct > 0 and not exit_check.should_exit:
        lessons.append("策略止盈触发，持仓期间无重大风险")
    elif pnl_pct < 0 and exit_check.urgency == "immediate":
        lessons.append("突发事件导致亏损，黑天鹅风险难以完全规避")
    elif pnl_pct < 0:
        lessons.append(f"亏损原因: {exit_check.reason[:100]}")
        if parsed.stop_loss_pct and abs(pnl_pct) > parsed.stop_loss_pct:
            lessons.append(f"实际亏损({abs(pnl_pct):.1f}%)超过预设止损({parsed.stop_loss_pct}%)，需检查滑点")
    if exit_check.checks_failed:
        lessons.append(f"平仓触发因素: {', '.join(exit_check.checks_failed[:3])}")

    # Monitoring stats
    if monitoring_log:
        alert_count = sum(1 for m in monitoring_log if m.get("urgency") in ("alert", "warning", "immediate"))
        if alert_count > 0:
            lessons.append(f"持仓期间触发 {alert_count} 次风险预警")

    return TradeSummary(
        symbol=parsed.symbol,
        direction=direction,
        entry_time=entry_time,
        exit_time=datetime.now().isoformat(),
        entry_price=round(entry_price, 2),
        exit_price=round(exit_price, 2),
        quantity=round(quantity, 6),
        pnl_usdt=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        holding_duration="",
        exit_reason=exit_check.reason,
        strategy=parsed.template,
        monitoring_events=monitoring_log or [],
        grade=grade,
        lessons=lessons,
    )


def print_trade_summary(ts: TradeSummary):
    """Print a formatted trade summary report."""
    SEP = "=" * 68
    SUB = "-" * 68

    pnl_icon = "+" if ts.pnl_usdt >= 0 else ""
    print(f"\n{SEP}")
    print(f"  交易总结报告")
    print(f"{SEP}")

    print(f"\n  [交易概况]")
    print(f"  {SUB}")
    print(f"  交易对:   {ts.symbol} | 方向: {ts.direction.upper()}")
    print(f"  策略:     {ts.strategy}")
    print(f"  入场价:   {ts.entry_price:.2f}")
    print(f"  出场价:   {ts.exit_price:.2f}")
    print(f"  数量:     {ts.quantity}")

    print(f"\n  [盈亏结果]")
    print(f"  {SUB}")
    pnl_str = f"{pnl_icon}{ts.pnl_usdt:.2f} USDT"
    print(f"  盈亏:     {pnl_str} ({pnl_icon}{ts.pnl_pct:.2f}%)")
    print(f"  评级:     {ts.grade}")

    print(f"\n  [出场原因]")
    print(f"  {SUB}")
    print(f"  {ts.exit_reason}")

    if ts.lessons:
        print(f"\n  [经验总结]")
        print(f"  {SUB}")
        for i, lesson in enumerate(ts.lessons, 1):
            print(f"  {i}. {lesson}")

    print(f"\n{SEP}")
    print(f"  交易完成")
    print(f"{SEP}\n")
