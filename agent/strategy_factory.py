"""NL Strategy Parser — converts natural language (Chinese) into strategy config.

Supports:
  - "帮我创建一个BTC的4H级别趋势跟随策略，用EMA金叉进场，RSI过滤"
  - "DOGE的1H动量突破策略，RSI在55-65之间做多，止损2%"
  - "ETH的震荡策略，布林带下轨买入上轨卖出"

Pattern-based (no LLM required) — matches keywords against known strategy templates.
"""
from dataclasses import dataclass, field
from typing import Optional
import re


# ═══════════════════════════════════════════════════════════════════════════
# Known templates
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATES = {
    "trend_following": {
        "name": "Trend Following",
        "indicators": ["ema", "macd", "adx"],
        "entry_logic": "EMA trend alignment + MACD conviction + ADX filter",
        "exit_logic": "Any single confirmation breaks → exit immediately",
        "risk_profile": "moderate",
    },
    "momentum_breakout": {
        "name": "Momentum Breakout",
        "indicators": ["rsi", "macd", "volume"],
        "entry_logic": "RSI momentum zone + MACD acceleration + volume surge",
        "exit_logic": "RSI exits momentum zone → scale out 50% at 1.5R, rest trailing",
        "risk_profile": "aggressive",
    },
    "mean_reversion": {
        "name": "Mean Reversion (Bollinger)",
        "indicators": ["bollinger", "rsi"],
        "entry_logic": "Price at BB lower + RSI oversold → long; price at BB upper + RSI overbought → short",
        "exit_logic": "Price returns to BB middle band → exit",
        "risk_profile": "moderate",
    },
    "grid_trading": {
        "name": "Range Grid",
        "indicators": ["bollinger", "atr"],
        "entry_logic": "Price within range, buy near support, sell near resistance",
        "exit_logic": "Price breaks range → stop",
        "risk_profile": "conservative",
    },
}


SYMBOL_MAP = {
    "btc": "BTCUSDT", "比特币": "BTCUSDT", "大饼": "BTCUSDT",
    "eth": "ETHUSDT", "以太坊": "ETHUSDT", "以太": "ETHUSDT",
    "doge": "DOGEUSDT", "狗狗": "DOGEUSDT", "狗狗币": "DOGEUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT",
    "bnb": "BNBUSDT",
    "xrp": "XRPUSDT",
}

TIMEFRAME_MAP = {
    "1h": "1H", "1小时": "1H", "一小时": "1H", "小时": "1H",
    "4h": "4H", "4小时": "4H", "四小时": "4H",
    "1d": "1D", "日线": "1D", "日": "1D", "一天": "1D", "每日": "1D",
    "1w": "1W", "周线": "1W",
    "5min": "5min", "5m": "5min", "5分钟": "5min",
    "15m": "15min", "15分钟": "15min",
    "30m": "30min", "30分钟": "30min",
}

DIRECTION_MAP = {
    "做多": "long", "多头": "long", "long": "long", "多": "long",
    "做空": "short", "空头": "short", "short": "short", "空": "short",
    "双向": "both", "both": "both", "多空": "both",
}


@dataclass
class ParsedStrategy:
    """Result of NL parsing."""
    raw_input: str
    template: str = "trend_following"   # template key
    symbol: str = "BTCUSDT"
    timeframe: str = "4H"
    direction: str = "both"
    indicators: list = field(default_factory=list)
    extra_params: dict = field(default_factory=dict)
    entry_desc: str = ""
    exit_desc: str = ""
    position_pct: float = 2.0
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    leverage: int = 3
    confidence: float = 0.0            # how well we matched
    parsed_ok: bool = True
    note: str = ""


def parse_strategy(text: str) -> ParsedStrategy:
    """Parse Chinese natural language into a structured strategy config.

    Returns ParsedStrategy with template, params, and confidence score.
    """
    text_lower = text.lower().replace(" ", "")

    result = ParsedStrategy(raw_input=text)
    match_count = 0
    total_checks = 6

    # ── 1. Detect strategy type ───────────────────────────────────────
    if any(kw in text_lower for kw in ["趋势", "跟随", "ema", "金叉", "死叉", "smc"]):
        result.template = "trend_following"
        result.entry_desc = "EMA趋势对齐 + MACD方向确认"
        result.exit_desc = "任一确认破坏即出场"
        match_count += 1
    elif any(kw in text_lower for kw in ["动量", "突破", "momentum", "加速", "放量"]):
        result.template = "momentum_breakout"
        result.entry_desc = "RSI动量区间 + MACD加速 + 成交量激增"
        result.exit_desc = "分批止盈: 50%@1.5R + 剩余跟踪止盈"
        match_count += 1
    elif any(kw in text_lower for kw in ["布林", "bollinger", "震荡", "回归", "抄底", "摸顶"]):
        result.template = "mean_reversion"
        result.entry_desc = "价格触及布林下轨+RSI超卖→做多；上轨+RSI超买→做空"
        result.exit_desc = "价格回归布林中轨出场"
        match_count += 1
    elif any(kw in text_lower for kw in ["网格", "区间", "grid", "range"]):
        result.template = "grid_trading"
        result.entry_desc = "区间内低买高卖"
        result.exit_desc = "突破区间止损"
        match_count += 1
    else:
        result.template = "trend_following"  # default
        result.note = "No specific strategy type detected, using trend_following as default"

    # ── 2. Detect symbol ──────────────────────────────────────────────
    for key, val in SYMBOL_MAP.items():
        if key in text_lower:
            result.symbol = val
            match_count += 1
            break

    # ── 3. Detect timeframe ───────────────────────────────────────────
    for key, val in sorted(TIMEFRAME_MAP.items(), key=lambda x: -len(x[0])):
        if key in text_lower:
            result.timeframe = val
            match_count += 1
            break

    # ── 4. Detect direction ───────────────────────────────────────────
    for key, val in DIRECTION_MAP.items():
        if key in text_lower:
            result.direction = val
            match_count += 1
            break

    # ── 5. Detect risk params ─────────────────────────────────────────
    sl_match = re.search(r"止损\s*(\d+\.?\d*)\s*%", text)
    if sl_match:
        result.stop_loss_pct = float(sl_match.group(1))
        match_count += 1

    tp_match = re.search(r"止盈\s*(\d+\.?\d*)\s*%", text)
    if tp_match:
        result.take_profit_pct = float(tp_match.group(1))
        match_count += 1

    pos_match = re.search(r"仓位\s*(\d+\.?\d*)\s*%", text)
    if pos_match:
        result.position_pct = float(pos_match.group(1))

    lev_match = re.search(r"(\d+)\s*[xX倍]", text)
    if lev_match:
        result.leverage = int(lev_match.group(1))

    # ── 6. Detect indicator overrides ─────────────────────────────────
    rsi_match = re.search(r"rsi\s*[=:：]?\s*(\d+)", text_lower)
    if rsi_match:
        result.extra_params["rsi_period"] = int(rsi_match.group(1))
        match_count += 1

    ema_match = re.search(r"ema\s*[=:：]?\s*(\d+)", text_lower)
    if ema_match:
        result.extra_params["ema_period"] = int(ema_match.group(1))

    # ── Compute confidence ────────────────────────────────────────────
    result.confidence = min(1.0, match_count / total_checks)
    result.parsed_ok = match_count >= 2

    if match_count < 2:
        result.note = "Too few keywords matched — using defaults. Try: 'BTC 4H趋势策略 EMA金叉进场 RSI过滤 止损2%'"

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Strategy Config Generator
# ═══════════════════════════════════════════════════════════════════════════

def generate_config_yaml(parsed: ParsedStrategy) -> str:
    """Generate a config.yaml string from a ParsedStrategy."""
    ind = _build_indicator_config(parsed)
    risk = _build_risk_config(parsed)

    return f"""# Auto-generated strategy config from NL description
# Input: "{parsed.raw_input}"
# Template: {parsed.template} | Confidence: {parsed.confidence:.0%}

strategy:
  name: "{TEMPLATES[parsed.template]['name']} ({parsed.symbol} {parsed.timeframe})"
  symbols: ["{parsed.symbol}"]
  timeframes: ["{parsed.timeframe}"]

  indicators:
{ind}

  signal:
    min_confidence: 0.60
    require_multi_tf: false
    sentiment_filter: true

risk:
{risk}

execution:
  mode: "demo"
  trade_size_usdt: 100
  leverage: {parsed.leverage}
  interval: "{parsed.timeframe.lower().replace('min', 'm').replace('min', 'm').replace('h', 'h').replace('d', 'd')}"
  dry_run: true
"""


def _build_indicator_config(parsed: ParsedStrategy) -> str:
    t = parsed.template
    ep = parsed.extra_params
    lines = []

    rsi_p = ep.get("rsi_period", 14)
    lines.append(f"    rsi_period: {rsi_p}")
    lines.append(f"    rsi_oversold: 30")
    lines.append(f"    rsi_overbought: 70")

    ema_p = ep.get("ema_period", 20)
    lines.append(f"    ema_fast: {ema_p}")
    lines.append(f"    ema_slow: {ema_p * 2 + 6}")

    lines.append(f"    macd_fast: 12")
    lines.append(f"    macd_slow: 26")
    lines.append(f"    macd_signal: 9")

    if t == "trend_following":
        lines.append(f"    adx_period: 14")
        lines.append(f"    adx_threshold: 25")
    elif t == "momentum_breakout":
        lines.append(f"    adx_period: 14")
        lines.append(f"    adx_threshold: 20")

    lines.append(f"    atr_period: 14")
    lines.append(f"    bb_period: 20")
    lines.append(f"    bb_std: 2.0")

    return "\n".join(lines)


def _build_risk_config(parsed: ParsedStrategy) -> str:
    sl = parsed.stop_loss_pct or 5.0
    tp = parsed.take_profit_pct or 10.0
    pos = parsed.position_pct

    rr = tp / sl if sl > 0 else 2.0

    return f"""    position_pct: {pos}
    exposure_pct: 30.0
    daily_loss_pct: {sl}
    min_rr: {rr:.1f}
    atr_stop_mult: 2.0
    atr_tp_mult: {rr * 2:.1f}"""


# ═══════════════════════════════════════════════════════════════════════════
# Playbook Packager
# ═══════════════════════════════════════════════════════════════════════════

def generate_playbook_manifest(parsed: ParsedStrategy) -> str:
    """Generate manifest.yaml for GetAgent Playbook from parsed strategy."""
    t = TEMPLATES[parsed.template]
    name_slug = f"{parsed.symbol.lower()}-{parsed.template.replace('_', '-')}-{parsed.timeframe.lower()}"

    return f"""name: {name_slug}
display_name: "{t['name']} ({parsed.symbol} {parsed.timeframe})"
version: "1.0.0"
description: "Auto-generated strategy from NL: {parsed.raw_input[:80]}"
long_description: |
  This strategy was auto-generated from a natural language description:

  "{parsed.raw_input}"

  Strategy type: {t['name']}
  Entry logic: {parsed.entry_desc}
  Exit logic: {parsed.exit_desc}
  Risk profile: {t['risk_profile']}

  Auto-generated by Adaptive Trading Agent for Bitget Hackathon Track 1.

market_type: contract
trading_symbols: ["{parsed.symbol}"]
tags: ["auto-generated", "{parsed.template.replace('_', '-')}", "{parsed.symbol.lower()}"]

decision_mode: deterministic
backtest_support: full
runtime_profile: deterministic
execution_mode: signal_only
follow_trade_supported: false

strategy_config:
  trading_symbols: ["{parsed.symbol}"]
  fast_ema_period: 12
  slow_ema_period: 26
  rsi_period: 14
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  adx_period: 14
  adx_threshold: 25.0
  leverage: {parsed.leverage}
  margin_budget: "100"
  trade_size: "0.10"
"""


def generate_playbook_main_py(parsed: ParsedStrategy) -> str:
    """Generate src/main.py for GetAgent Playbook."""
    interval = parsed.timeframe.lower().replace("min", "m")
    if not interval.endswith("m") and not interval.endswith("h") and not interval.endswith("d"):
        interval = "4h"

    return f'''"""Auto-generated Playbook: {TEMPLATES[parsed.template]["name"]} ({parsed.symbol} {parsed.timeframe})

NL input: "{parsed.raw_input}"
"""
import math
from typing import Any
from getagent import backtest, data, runtime


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {{}}) or {{}}
    symbols = cfg.get("trading_symbols") or ["{parsed.symbol}"]
    symbol = symbols[0]

    bars = data.crypto.futures.kline(
        symbol=symbol,
        interval="{interval}",
        limit=2000,
    )
    replay_frame = backtest.prepare_frame(bars, datetime_index="date")

    if replay_frame.empty:
        runtime.emit_signal(
            action="watch",
            symbol=symbol,
            confidence=0.0,
            meta={{"reason": "no historical bars returned"}},
        )
        return

    instrument_key = f"{{symbol}}.BINANCE"
    result = backtest.run(
        ohlcv_data={{{{instrument_key}}: replay_frame}},
        spec=runtime.backtest_spec,
    )

    summary = result.summary or {{}}
    net_pnl_raw = summary.get("net_pnl", 0)
    try:
        net_pnl = float(net_pnl_raw or 0)
    except (TypeError, ValueError):
        net_pnl = 0.0

    action = "long" if net_pnl > 0 else "watch"

    runtime.emit_signal(
        action=action,
        symbol=symbol,
        confidence=_sanitize(result.win_rate) or 0.0,
        metrics={{
            "total_return_pct": _sanitize(result.total_return_pct),
            "net_pnl": net_pnl,
            "sharpe_ratio": _sanitize(result.sharpe_ratio),
            "max_drawdown_pct": _sanitize(result.max_drawdown_pct),
            "win_rate": _sanitize(result.win_rate),
            "total_trades": result.total_trades,
            "profit_factor": _sanitize(result.profit_factor),
        }},
        meta={{
            "signal_logic": "{parsed.template}",
            "interval": "{interval}",
            "source": "nl-generated",
        }},
    )


if __name__ == "__main__":
    run()
'''
