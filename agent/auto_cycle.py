"""Auto Cycle Engine — single monitoring + trading iteration.

This module is called by Claude Code each cycle:
  1. Claude Code calls 4 Skills → builds market_data JSON
  2. Claude Code calls run_cycle(strategy_text, market_data_json, dry_run)
  3. This module evaluates, executes, monitors, and returns structured results
  4. Claude Code displays results and schedules next cycle

State is persisted to output/auto_trade_state.json across cycles.
"""

import json, os, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .strategy_factory import parse_strategy, ParsedStrategy
from .strategy_executor import (
    evaluate_strategy, EvalResult, StrategyEval,
    estimate_trade_metrics, TradeMetrics,
    evaluate_exit_conditions, ExitCheckResult,
    generate_trade_summary, TradeSummary,
)
from .market_snapshot import MarketSnapshot

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
STATE_FILE = os.path.join(OUTPUT_DIR, "auto_trade_state.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# State persistence
# ═══════════════════════════════════════════════════════════

@dataclass
class CycleState:
    """Persistent state across monitoring cycles."""
    strategy_text: str = ""
    symbol: str = "BTCUSDT"
    timeframe: str = "15min"
    direction: str = "long"
    template: str = "trend_following"
    sl_pct: float = 1.0
    tp_pct: float = 2.0
    position_pct: float = 2.0
    in_position: bool = False
    position: dict = field(default_factory=dict)
    entry_time: str = ""
    cycle_count: int = 0
    trades_completed: int = 0
    total_pnl: float = 0.0
    trade_history: list = field(default_factory=list)
    last_price: float = 0.0
    last_rsi: float = 0.0
    last_macd_state: str = ""

    def save(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def load(cls) -> "CycleState":
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: data.get(k, v) for k, v in cls().__dict__.items()})
        return cls()


# ═══════════════════════════════════════════════════════════
# Market data builder (from Skills JSON)
# ═══════════════════════════════════════════════════════════

def build_market_snapshot_from_json(market_data_json: str) -> MarketSnapshot:
    """Build a MarketSnapshot from Skills-provided JSON.

    Expected JSON structure (built by Claude Code from Skills):
    {
      "technical": { close, rsi, macd_dif, macd_dea, macd_hist,
                     ema_12, ema_26, ema_20, ema_50, atr, adx,
                     bb_upper, bb_mid, bb_lower, volume_surge, trend_direction },
      "sentiment": { fear_greed_index, fear_greed_label, long_short_ratio, ... },
      "macro":     { regime, fed_funds_rate, btc_nasdaq_correlation },
      "news":      { has_major_event, bias, summary }
    }
    """
    data = json.loads(market_data_json) if isinstance(market_data_json, str) else market_data_json
    m = MarketSnapshot()

    tech = data.get("technical", {})
    t = m.technical
    t.symbol = tech.get("symbol", "BTCUSDT")
    t.timeframe = tech.get("timeframe", "15min")
    t.close = tech.get("close", 0)
    t.rsi = tech.get("rsi")
    t.macd_dif = tech.get("macd_dif")
    t.macd_dea = tech.get("macd_dea")
    t.macd_hist = tech.get("macd_hist")
    t.ema_12 = tech.get("ema_12")
    t.ema_26 = tech.get("ema_26")
    t.ema_20 = tech.get("ema_20")
    t.ema_50 = tech.get("ema_50")
    t.atr = tech.get("atr")
    t.adx = tech.get("adx")
    t.bb_upper = tech.get("bb_upper")
    t.bb_mid = tech.get("bb_mid")
    t.bb_lower = tech.get("bb_lower")
    t.volume_surge = tech.get("volume_surge", False)
    t.trend_direction = tech.get("trend_direction", "neutral")

    sent = data.get("sentiment", {})
    m.sentiment.fear_greed_index = sent.get("fear_greed_index", 50)
    m.sentiment.fear_greed_label = sent.get("fear_greed_label", "neutral")
    m.sentiment.long_short_ratio = sent.get("long_short_ratio", 1.0)

    macro = data.get("macro", {})
    m.macro.regime = macro.get("regime", "neutral")
    m.macro.fed_funds_rate = macro.get("fed_funds_rate")
    m.macro.btc_nasdaq_correlation = macro.get("btc_nasdaq_correlation")

    news = data.get("news", {})
    m.news.has_major_event = news.get("has_major_event", False)
    m.news.bias = news.get("bias", "neutral")
    m.news.event_summary = news.get("summary", "")

    return m


# ═══════════════════════════════════════════════════════════
# Core cycle function
# ═══════════════════════════════════════════════════════════

def run_cycle(
    strategy_text: str,
    market_data_json: str = "",
    dry_run: bool = True,
    client: object = None,
) -> dict:
    """Run one complete monitoring + trading cycle.

    This is the single entry point called by Claude Code each iteration.

    Args:
        strategy_text: NL strategy description (e.g. "BTCUSDT 15min EMA金叉做多")
        market_data_json: JSON string with data from all 4 Skills
        dry_run: If True, no real orders placed
        client: DemoClient instance for exchange operations (optional in dry_run)

    Returns:
        dict with cycle results: status, checks, metrics, orders, monitoring_guide
    """
    state = CycleState.load()
    state.cycle_count += 1

    # ── Parse strategy ──────────────────────────────────────
    parsed = parse_strategy(strategy_text)
    state.strategy_text = strategy_text
    state.symbol = parsed.symbol
    state.timeframe = parsed.timeframe
    state.direction = parsed.direction
    state.template = parsed.template
    state.sl_pct = parsed.stop_loss_pct or 1.0
    state.tp_pct = parsed.take_profit_pct or 2.0
    state.position_pct = parsed.position_pct

    # ── Build market snapshot ───────────────────────────────
    market = build_market_snapshot_from_json(market_data_json) if market_data_json else MarketSnapshot()

    state.last_price = market.technical.close
    state.last_rsi = market.technical.rsi or 0
    state.last_macd_state = "BULL" if (market.technical.macd_dif or 0) > (market.technical.macd_dea or 0) else "BEAR"

    # ── Initialize client if needed ─────────────────────────
    if client is None and not dry_run:
        from demo_trading_test import DemoClient
        mcp_path = os.path.join(PROJECT_DIR, ".mcp.json")
        with open(mcp_path) as f:
            mcp_cfg = json.load(f)
        env = mcp_cfg["mcpServers"]["bitget"]["env"]
        client = DemoClient(
            api_key=env["BITGET_API_KEY"],
            secret=env["BITGET_SECRET_KEY"],
            passphrase=env["BITGET_PASSPHRASE"],
        )

    # ── Check for open positions ────────────────────────────
    positions = []
    if client is not None:
        try:
            pos_resp = client.get("/api/v2/mix/position/all-position?"
                                  "productType=USDT-FUTURES&marginCoin=USDT")
            positions = pos_resp.get("data", []) or []
        except Exception:
            pass

    my_positions = [p for p in positions
                    if p.get("symbol") == parsed.symbol
                    and float(p.get("total", 0)) > 0]

    now = datetime.now(timezone.utc)

    # ═══════════════════════════════════════════════════════
    # SCENARIO A: Holding a position → monitor exit
    # ═══════════════════════════════════════════════════════
    if my_positions and state.in_position:
        pos = my_positions[0]
        state.position = pos

        exit_check = evaluate_exit_conditions(pos, market, parsed)

        print(f"\n  [{now:%H:%M:%S}] CYCLE #{state.cycle_count}")
        print(f"  [HOLDING] {pos.get('holdSide', 'long').upper()} "
              f"| Entry={float(pos.get('openPriceAvg', 0)):.1f} "
              f"| Mark={float(pos.get('markPrice', 0)):.1f} "
              f"| PnL={exit_check.pnl_pct:+.2f}%")

        if exit_check.risk_alerts:
            for alert in exit_check.risk_alerts:
                print(f"  [ALERT] {alert}")

        if exit_check.should_exit:
            print(f"  [EXIT TRIGGERED] {exit_check.reason} (urgency={exit_check.urgency})")

            if not dry_run and client:
                try:
                    close_side = "sell" if pos.get("holdSide") == "long" else "buy"
                    close_params = {
                        "symbol": parsed.symbol,
                        "marginCoin": "USDT",
                        "productType": "USDT-FUTURES",
                        "side": close_side,
                        "orderType": "market",
                        "size": pos.get("available", pos.get("total", "0")),
                        "tradeSide": "close",
                    }
                    close_resp = client.post("/api/v2/mix/order/place-order", close_params)
                    print(f"  [CLOSED] {close_resp.get('msg', 'order sent')}")
                except Exception as e:
                    print(f"  [CLOSE FAILED] {e}")

            summary = generate_trade_summary(pos, exit_check, parsed, state.entry_time)

            trade_record = {
                "entry_price": float(pos.get("openPriceAvg", 0)),
                "exit_price": exit_check.exit_price or market.technical.close,
                "pnl_pct": round(exit_check.pnl_pct, 2),
                "pnl_usdt": float(pos.get("unrealizedPL", 0)),
                "grade": summary.grade if summary else "N/A",
                "exit_reason": exit_check.reason,
                "lessons": summary.lessons if summary else [],
                "closed_at": now.isoformat(),
            }
            state.trade_history.append(trade_record)
            state.trades_completed += 1
            state.total_pnl += float(pos.get("unrealizedPL", 0))
            state.in_position = False
            state.position = {}
            state.entry_time = ""

            print(f"  [SUMMARY] PnL={exit_check.pnl_pct:+.2f}% | Grade={trade_record['grade']}")

        state.save()
        return {
            "status": "exit_triggered" if exit_check.should_exit else "monitoring",
            "cycle": state.cycle_count,
            "holding": True,
            "pnl_pct": round(exit_check.pnl_pct, 2),
            "urgency": exit_check.urgency,
            "should_exit": exit_check.should_exit,
            "exit_reason": exit_check.reason if exit_check.should_exit else "",
            "alerts": exit_check.risk_alerts,
            "state": state.__dict__,
        }

    # ═══════════════════════════════════════════════════════
    # SCENARIO B: No position → evaluate entry
    # ═══════════════════════════════════════════════════════
    # If we thought we had a position but exchange says no, fix state
    if state.in_position and not my_positions:
        state.in_position = False
        state.position = {}

    eval_result = evaluate_strategy(parsed, market)

    print(f"\n  [{now:%H:%M:%S}] CYCLE #{state.cycle_count} | "
          f"${market.technical.close:,.1f} | "
          f"EMA={'GOLDEN' if (market.technical.ema_12 or 0) > (market.technical.ema_26 or 0) else 'DEAD'} | "
          f"MACD={'BULL' if (market.technical.macd_dif or 0) > (market.technical.macd_dea or 0) else 'BEAR'} | "
          f"RSI={market.technical.rsi:.0f}")

    # Print checks
    for c in eval_result.checks:
        icon = "[PASS]" if c.passed else "[FAIL]"
        print(f"  {icon} {c.name}: {c.actual}")

    if eval_result.risk_warnings:
        for w in eval_result.risk_warnings:
            print(f"  [!] {w}")

    # ── Entry decision ──────────────────────────────────────
    if eval_result.result != EvalResult.NO_TRADE:
        metrics = estimate_trade_metrics(parsed, eval_result, market)

        # Calculate absolute position size from account equity
        pos_size = 0.0
        if not dry_run and client:
            try:
                acct = client.get_futures_account()
                equity = float(acct.get("available", 0))
                pos_usdt = equity * metrics.position_size_pct / 100
                pos_size = round(pos_usdt / metrics.entry_price, 6)
            except Exception:
                pos_size = 0.0

        print(f"\n  [SIGNAL] {eval_result.result.value} | "
              f"Confidence={eval_result.confidence:.0%} | "
              f"Checks={eval_result.passed_count}/{eval_result.total_count}")
        print(f"  [METRICS] Entry={metrics.entry_price:.1f} | "
              f"SL={metrics.stop_loss:.1f}({metrics.risk_pct}%) | "
              f"TP={metrics.take_profit:.1f}({metrics.reward_pct}%)")
        print(f"  [METRICS] Est.WinRate={metrics.estimated_win_rate:.1%} | "
              f"RR={metrics.risk_reward_ratio:.2f}:1 | "
              f"Expectancy={metrics.expectancy:.2f}%/trade | "
              f"Size={pos_size}BTC")

        if not dry_run and client and pos_size > 0:
            try:
                side = "buy" if eval_result.result == EvalResult.ENTRY_LONG else "sell"

                # Place entry order (market — demo sandbox only supports market)
                entry_params = {
                    "symbol": parsed.symbol,
                    "marginCoin": "USDT",
                    "productType": "USDT-FUTURES",
                    "side": side,
                    "orderType": "market",
                    "size": str(pos_size),
                    "tradeSide": "open",
                    "marginMode": "crossed",
                }
                resp = client.post("/api/v2/mix/order/place-order", entry_params)
                order_id = resp.get("data", {}).get("orderId", "")
                print(f"  [EXECUTED] Entry order: id={order_id} type=market size={pos_size}")

                # Place SL plan order (demo sandbox may reject)
                sl_side = "sell" if side == "buy" else "buy"
                try:
                    sl_params = {
                        "symbol": parsed.symbol,
                        "marginCoin": "USDT",
                        "productType": "USDT-FUTURES",
                        "side": sl_side,
                        "orderType": "market",
                        "size": str(pos_size),
                        "tradeSide": "close",
                        "triggerPrice": str(round(metrics.stop_loss, 1)),
                        "triggerType": "mark_price",
                        "planType": "normal_plan",
                        "marginMode": "crossed",
                    }
                    sl_resp = client.post("/api/v2/mix/order/place-plan-order", sl_params)
                    sl_oid = sl_resp.get("data", {}).get("orderId", "")
                    print(f"  [EXECUTED] SL order: id={sl_oid} trigger={metrics.stop_loss:.1f}")
                except Exception as sl_e:
                    print(f"  [SL FAILED] Demo sandbox rejected plan-order: {sl_e}")

                # Place TP plan order
                try:
                    tp_params = {
                        "symbol": parsed.symbol,
                        "marginCoin": "USDT",
                        "productType": "USDT-FUTURES",
                        "side": sl_side,
                        "orderType": "market",
                        "size": str(pos_size),
                        "tradeSide": "close",
                        "triggerPrice": str(round(metrics.take_profit, 1)),
                        "triggerType": "mark_price",
                        "planType": "normal_plan",
                        "marginMode": "crossed",
                    }
                    tp_resp = client.post("/api/v2/mix/order/place-plan-order", tp_params)
                    tp_oid = tp_resp.get("data", {}).get("orderId", "")
                    print(f"  [EXECUTED] TP order: id={tp_oid} trigger={metrics.take_profit:.1f}")
                except Exception as tp_e:
                    print(f"  [TP FAILED] Demo sandbox rejected plan-order: {tp_e}")

                state.in_position = True
                state.entry_time = now.isoformat()
                state.position = {
                    "symbol": parsed.symbol,
                    "holdSide": side,
                    "openPriceAvg": str(metrics.entry_price),
                    "total": str(pos_size),
                }

            except Exception as e:
                print(f"  [EXECUTION FAILED] {e}")
        else:
            print(f"  [DRY-RUN] Would {eval_result.result.value}: "
                  f"Entry={metrics.entry_price:.1f} SL={metrics.stop_loss:.1f} TP={metrics.take_profit:.1f}")

        state.save()
        return {
            "status": "entry",
            "cycle": state.cycle_count,
            "holding": False,
            "signal": eval_result.result.value,
            "confidence": eval_result.confidence,
            "checks_passed": eval_result.passed_count,
            "checks_total": eval_result.total_count,
            "entry_price": metrics.entry_price,
            "stop_loss": metrics.stop_loss,
            "take_profit": metrics.take_profit,
            "win_rate": metrics.estimated_win_rate,
            "rr_ratio": metrics.risk_reward_ratio,
            "expectancy": metrics.expectancy,
            "risk_warnings": eval_result.risk_warnings,
            "state": state.__dict__,
        }

    # No trade
    print(f"  [NO TRADE] {eval_result.passed_count}/{eval_result.total_count} passed "
          f"(confidence={eval_result.confidence:.0%}, need >=60%)")
    if eval_result.reason:
        print(f"  [REASON] {eval_result.reason}")

    state.save()
    return {
        "status": "no_trade",
        "cycle": state.cycle_count,
        "holding": False,
        "confidence": eval_result.confidence,
        "checks_passed": eval_result.passed_count,
        "checks_total": eval_result.total_count,
        "reason": eval_result.reason,
        "risk_warnings": eval_result.risk_warnings,
        "state": state.__dict__,
    }


# ═══════════════════════════════════════════════════════════
# Indicator computation (for Claude Code to use with Skills OHLCV data)
# ═══════════════════════════════════════════════════════════

def compute_indicators_from_ohlcv(ohlcv_list: list) -> dict:
    """Compute all technical indicators from OHLCV data.

    Args:
        ohlcv_list: List of dicts with {timestamp, open, high, low, close, volume}

    Returns:
        dict with all indicators for the latest bar
    """
    closes = np.array([b["close"] for b in ohlcv_list])
    highs = np.array([b["high"] for b in ohlcv_list])
    lows = np.array([b["low"] for b in ohlcv_list])
    volumes = np.array([b.get("volume", 0) for b in ohlcv_list])
    n = len(closes)
    last = n - 1

    def _ema(arr, period):
        result = np.full(len(arr), np.nan)
        if len(arr) < period:
            return result
        result[period - 1] = np.mean(arr[:period])
        k = 2 / (period + 1)
        for i in range(period, len(arr)):
            result[i] = arr[i] * k + result[i - 1] * (1 - k)
        return result

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    # MACD with proper DEA handling
    dif_raw = ema12 - ema26
    first_dif = 0
    for i in range(n):
        if not np.isnan(dif_raw[i]):
            first_dif = i
            break
    dea = np.full(n, np.nan)
    dea_start = first_dif + 8
    if dea_start < n:
        dea[dea_start] = np.nanmean(dif_raw[first_dif:first_dif + 9])
        k = 0.2
        for i in range(dea_start + 1, n):
            v = dif_raw[i] if not np.isnan(dif_raw[i]) else 0
            dea[i] = v * k + dea[i - 1] * (1 - k)
    hist = 2 * (dif_raw - dea)

    # RSI(14)
    delta = np.diff(closes, prepend=closes[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    rsi14 = np.full(n, np.nan)
    avg_g = np.mean(gain[1:15])
    avg_l = np.mean(loss[1:15])
    rsi14[14] = 100 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))
    for i in range(15, n):
        avg_g = (avg_g * 13 + gain[i]) / 14
        avg_l = (avg_l * 13 + loss[i]) / 14
        rsi14[i] = 100 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))

    # ATR(14)
    tr_arr = np.maximum(highs - lows,
                        np.maximum(np.abs(highs - np.roll(closes, 1)),
                                   np.abs(lows - np.roll(closes, 1))))
    tr_arr[0] = highs[0] - lows[0]
    atr14 = _ema(tr_arr, 14)

    # BB(20,2)
    bb_mid = np.full(n, np.nan)
    bb_upper = np.full(n, np.nan)
    bb_lower = np.full(n, np.nan)
    for i in range(19, n):
        w = closes[i - 19:i + 1]
        m = float(np.mean(w))
        s = float(np.std(w, ddof=0))
        bb_mid[i] = m
        bb_upper[i] = m + 2 * s
        bb_lower[i] = m - 2 * s

    # ADX(14)
    tr_adx = np.maximum(highs - lows,
                        np.maximum(np.abs(highs - np.roll(closes, 1)),
                                   np.abs(lows - np.roll(closes, 1))))
    tr_adx[0] = highs[0] - lows[0]
    up = highs - np.roll(highs, 1); up[0] = 0
    dn = np.roll(lows, 1) - lows; dn[0] = 0
    p_dm = np.where((up > dn) & (up > 0), up, 0)
    m_dm = np.where((dn > up) & (dn > 0), dn, 0)
    tr_e = _ema(tr_adx, 14)
    p_e = _ema(p_dm, 14)
    m_e = _ema(m_dm, 14)
    adx_v = np.full(n, np.nan)
    for i in range(26, n):
        if tr_e[i] == 0 or np.isnan(tr_e[i]):
            continue
        pdi = p_e[i] / tr_e[i] * 100
        mdi = m_e[i] / tr_e[i] * 100
        sm = pdi + mdi
        dx = abs(pdi - mdi) / sm * 100 if sm > 0 else 0
        adx_v[i] = dx if i == 26 else (adx_v[i - 1] * 13 + dx) / 14

    vol_ma = float(np.mean(volumes[-21:-1])) if n > 21 else float(np.mean(volumes))
    vol_surge = bool(volumes[last] > vol_ma * 1.5)

    return {
        "symbol": "BTCUSDT",
        "timeframe": "15min",
        "close": round(float(closes[last]), 2),
        "ema_12": round(float(ema12[last]), 2),
        "ema_26": round(float(ema26[last]), 2),
        "ema_20": round(float(ema20[last]), 2),
        "ema_50": round(float(ema50[last]), 2),
        "rsi": round(float(rsi14[last]), 2),
        "macd_dif": round(float(dif_raw[last]), 2),
        "macd_dea": round(float(dea[last]), 2),
        "macd_hist": round(float(hist[last]), 2),
        "atr": round(float(atr14[last]), 2),
        "adx": round(float(adx_v[last]), 2),
        "bb_upper": round(float(bb_upper[last]), 2),
        "bb_mid": round(float(bb_mid[last]), 2),
        "bb_lower": round(float(bb_lower[last]), 2),
        "volume_surge": vol_surge,
        "trend_direction": "up" if (ema12[last] > ema26[last]) else "down",
    }
