"""Auto-generated Playbook: Trend Following (BTCUSDT 4H)

NL input: "BTC 4H趋势策略 EMA金叉 止损2% 3x"
"""
import math
from typing import Any
from getagent import backtest, data, runtime


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    symbols = cfg.get("trading_symbols") or ["BTCUSDT"]
    symbol = symbols[0]

    bars = data.crypto.futures.kline(
        symbol=symbol,
        interval="4h",
        limit=2000,
    )
    replay_frame = backtest.prepare_frame(bars, datetime_index="date")

    if replay_frame.empty:
        runtime.emit_signal(
            action="watch",
            symbol=symbol,
            confidence=0.0,
            meta={"reason": "no historical bars returned"},
        )
        return

    instrument_key = f"{symbol}.BINANCE"
    result = backtest.run(
        ohlcv_data={{instrument_key}: replay_frame},
        spec=runtime.backtest_spec,
    )

    summary = result.summary or {}
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
        metrics={
            "total_return_pct": _sanitize(result.total_return_pct),
            "net_pnl": net_pnl,
            "sharpe_ratio": _sanitize(result.sharpe_ratio),
            "max_drawdown_pct": _sanitize(result.max_drawdown_pct),
            "win_rate": _sanitize(result.win_rate),
            "total_trades": result.total_trades,
            "profit_factor": _sanitize(result.profit_factor),
        },
        meta={
            "signal_logic": "trend_following",
            "interval": "4h",
            "source": "nl-generated",
        },
    )


if __name__ == "__main__":
    run()
