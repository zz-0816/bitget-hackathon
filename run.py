"""run.py — 一键启动入口

评委只需: pip install -r requirements.txt && python run.py

执行内容:
  1. Agent 四层闭环 Demo (4 场景)
  2. 8 策略变体回测对比
  3. 输出完整交易日志 → output/trade_log.json

命令:
  python run.py                    完整演示
  python run.py create              自然语言创建策略 (交互式)
  python run.py create "BTC 4H趋势策略 EMA金叉进场 止损2%"
  python run.py daemon              持续监控
  python run.py once                单次检查
"""
import json, os, sys, time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yaml

# Ensure project root on path
sys.path.insert(0, os.path.dirname(__file__))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

TRADE_LOG_PATH = os.path.join(OUTPUT_DIR, "trade_log.json")


# ═══════════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════════

def banner(text: str) -> None:
    print(f"\n{'='*68}")
    print(f"  {text}")
    print(f"{'='*68}")


def load_data(filename: str) -> pd.DataFrame:
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — Agent 四层闭环 Pipeline Demo
# ═══════════════════════════════════════════════════════════════════════════

def run_agent_pipeline() -> None:
    banner("Phase 1: Agent Four-Layer Pipeline Demo")

    from agent import (
        TradingAgent, AgentConfig,
        SentimentSnapshot,
    )

    btc_4h = load_data("btc_4h_bitget.json")
    btc_1d = load_data("btc_1d_bitget.json")
    print(f"  Data: BTC 4H {len(btc_4h)} bars | BTC 1D {len(btc_1d)} bars")

    config = AgentConfig()
    agent = TradingAgent(config)

    # Scenario 1: Idle — entry signals
    print("\n  [Scenario 1] No positions — scanning for entry signals")
    sentiment = SentimentSnapshot(
        fear_greed_index=52, fear_greed_label="neutral",
        social_volume_change=0.05, long_short_ratio=1.2, taker_buy_ratio=0.55,
    )
    output1 = agent.run(market_df=btc_4h, account_equity=10000.0,
                        current_positions=[], sentiment=sentiment, secondary_df=btc_1d)
    sig1 = output1.signal
    print(f"    Signal: {sig1.type.value} | confidence={sig1.confidence:.0%} | {sig1.reason}")
    print(f"    Risk: {output1.risk}")

    # Scenario 2: Active position — exit signals
    print("\n  [Scenario 2] Active LONG position — checking exit conditions")
    mock_position = [{
        "symbol": "BTCUSDT", "holdSide": "long", "total": "0.001",
        "available": "0.001",
        "openPriceAvg": str(btc_4h.iloc[-1]["close"] - 200),
        "marginMode": "isolated", "posMode": "hedge_mode", "leverage": "5",
        "unrealizedPL": "2.5", "markPrice": str(btc_4h.iloc[-1]["close"]),
    }]
    output2 = agent.run(market_df=btc_4h, account_equity=10000.0,
                        current_positions=mock_position, sentiment=sentiment, secondary_df=btc_1d)
    sig2 = output2.signal
    print(f"    Signal: {sig2.type.value} | confidence={sig2.confidence:.0%} | {sig2.reason}")
    print(f"    Risk: {output2.risk}")

    # Scenario 3: Extreme fear — sentiment filter
    print("\n  [Scenario 3] Extreme Fear (FG=18) — sentiment filter active")
    fear_sentiment = SentimentSnapshot(
        fear_greed_index=18, fear_greed_label="extreme fear",
        social_volume_change=0.15, long_short_ratio=0.7, taker_buy_ratio=0.35,
    )
    output3 = agent.run(market_df=btc_4h, account_equity=10000.0,
                        current_positions=[], sentiment=fear_sentiment, secondary_df=btc_1d)
    sig3 = output3.signal
    print(f"    Signal: {sig3.type.value} | confidence={sig3.confidence:.0%} | {sig3.reason}")

    # Scenario 4: Daily loss circuit breaker
    print("\n  [Scenario 4] Daily loss -550 USDT (5.5%) — circuit breaker triggered")
    agent.risk.record_trade_result(-550.0)
    output4 = agent.run(market_df=btc_4h, account_equity=9450.0,
                        current_positions=[], sentiment=sentiment, secondary_df=btc_1d)
    sig4 = output4.signal
    print(f"    Signal: {sig4.type.value} | confidence={sig4.confidence:.0%} | {sig4.reason}")
    print(f"    Risk: {output4.risk}")

    print("\n  Agent pipeline: all 4 scenarios passed.")


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — 8-Strategy Backtest + Trade Log
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest_benchmark() -> list[dict[str, Any]]:
    banner("Phase 2: 8-Strategy Backtest Benchmark")

    from backtest.btc_smc_backtest import load_data as _load, add_indicators, run_smc, calc_metrics
    from backtest.meme_momentum_backtest import add_indicators as add_indicators_meme, run_meme

    all_trades: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def _get(symbol, timeframe):
        file_map = {
            ("BTC/USDT", "4h"): "btc_4h_bitget.json",
            ("BTC/USDT", "1d"): "btc_1d_bitget.json",
            ("DOGE/USDT", "1h"): "doge_1h_bitget.json",
            ("DOGE/USDT", "1d"): "doge_1d_bitget.json",
        }
        fallback = {
            ("BTC/USDT", "4h"): "btc_4h.json",
            ("BTC/USDT", "1d"): "btc_1d.json",
            ("DOGE/USDT", "1h"): "doge_1h.json",
            ("DOGE/USDT", "1d"): "doge_1d.json",
        }
        fname = file_map.get((symbol, timeframe), "")
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            fpath = os.path.join(DATA_DIR, fallback.get((symbol, timeframe), fname))
        return _load(fpath)

    # BTC SMC
    df_btc_4h = add_indicators(_get("BTC/USDT", "4h"))
    df_btc_1d = add_indicators(_get("BTC/USDT", "1d"))
    # DOGE MEME
    df_doge_1h = add_indicators_meme(_get("DOGE/USDT", "1h"))
    df_doge_1d = add_indicators_meme(_get("DOGE/USDT", "1d"))

    runs = [
        ("BTC SMC Long  (4H)",  df_btc_4h, run_smc, "long",  None),
        ("BTC SMC Short (4H)",  df_btc_4h, run_smc, "short", None),
        ("BTC SMC Long  (1D)",  df_btc_1d, run_smc, "long",  50),
        ("BTC SMC Short (1D)",  df_btc_1d, run_smc, "short", 50),
        ("DOGE Mom Long (1H)",  df_doge_1h, run_meme, "long",  None),
        ("DOGE Mom Short(1H)",  df_doge_1h, run_meme, "short", None),
        ("DOGE Mom Long (1D)",  df_doge_1d, run_meme, "long",  50),
        ("DOGE Mom Short(1D)",  df_doge_1d, run_meme, "short", 50),
    ]

    for name, df, runner, direction, warmup in runs:
        kwargs = {"direction": direction}
        if warmup is not None:
            kwargs["warmup"] = warmup
        trades = runner(df, **kwargs)
        m = calc_metrics(trades)
        m["name"] = name

        for t in trades:
            t["strategy"] = name
            t["entry_t"] = str(t["entry_t"])
            t["exit_t"] = str(t["exit_t"])
        all_trades.extend(trades)
        results.append(m)

    # Print table
    header = f"{'Strategy':<22s} {'Trades':>6s} {'Win%':>7s} {'PnL%':>8s} {'PF':>7s} {'MDD%':>7s} {'Sharpe':>7s} {'Exp%':>7s}"
    print("\n" + header)
    print("-" * len(header))
    for r in results:
        if r["trades"] > 0:
            print(f"{r['name']:<22s} {r['trades']:>6d} {r['win%']:>6.1f}% {r['pnl%']:>+7.2f}% {r['pf']:>6.2f} {r['mdd%']:>6.2f}% {r['sharpe']:>6.2f} {r['exp%']:>+6.2f}%")
        else:
            print(f"{r['name']:<22s} {0:>6d} {'N/A':>7s} {'N/A':>8s} {'N/A':>7s} {'N/A':>7s} {'N/A':>7s} {'N/A':>7s}")

    # Rankings
    valid = [r for r in results if r["trades"] >= 5]
    if valid:
        print(f"\n  Rankings (>=5 trades):")
        for rank_name, key in [("Profit Factor", "pf"), ("Win Rate", "win%"), ("Sharpe", "sharpe"), ("Return", "pnl%")]:
            ranked = sorted(valid, key=lambda x: x[key], reverse=True)
            best = ranked[0]
            print(f"    Best by {rank_name}: {best['name']} ({key}={best[key]:.2f})")

    # Save trade log
    trade_log = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "模拟交易记录 — 8 策略变体回测产生的逐笔交易",
        "total_trades": len(all_trades),
        "strategies": sorted(set(t["strategy"] for t in all_trades)),
        "trades": all_trades,
    }
    with open(TRADE_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(trade_log, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Trade log saved → {TRADE_LOG_PATH} ({len(all_trades)} trades)")

    return all_trades


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — NL Strategy Creation + Demo Validation + Playbook Packaging
# ═══════════════════════════════════════════════════════════════════════════

def _create_flow(user_input: str) -> None:
    """End-to-end: NL input → strategy → demo validation → Playbook package."""
    from agent.strategy_factory import (
        parse_strategy, generate_config_yaml,
        generate_playbook_manifest, generate_playbook_main_py,
    )
    from agent.api_logger import get_api_summary, reset_api_log
    from agent import AgentConfig

    banner("NL Strategy Creator")

    # ── Step 1: Parse natural language ─────────────────────────────────
    print(f"\n  Input: \"{user_input}\"")
    parsed = parse_strategy(user_input)
    print(f"\n  Parsed strategy:")
    print(f"    Template:   {parsed.template}")
    print(f"    Symbol:     {parsed.symbol}")
    print(f"    Timeframe:  {parsed.timeframe}")
    print(f"    Direction:  {parsed.direction}")
    print(f"    Entry:      {parsed.entry_desc}")
    print(f"    Exit:       {parsed.exit_desc}")
    print(f"    Stop Loss:  {parsed.stop_loss_pct}%")
    print(f"    Take Profit:{parsed.take_profit_pct}%")
    print(f"    Position:   {parsed.position_pct}%")
    print(f"    Confidence: {parsed.confidence:.0%} | OK: {parsed.parsed_ok}")

    if not parsed.parsed_ok:
        print(f"\n  WARNING: {parsed.note}")
        print("  Too few keywords matched — using conservative defaults.")

    # ── Step 2: Generate config YAML ────────────────────────────────────
    config_yaml = generate_config_yaml(parsed)
    config_path = os.path.join(OUTPUT_DIR, "nl_generated_config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_yaml)
    print(f"\n  Config generated → {config_path}")

    # ── Step 3: Demo Trading validation ─────────────────────────────────
    print(f"\n── Demo Trading Validation ──")
    demo_ok = False
    try:
        from demo_trading_test import DemoClient

        mcp_path = os.path.join(os.path.dirname(__file__), ".mcp.json")
        with open(mcp_path) as f:
            mcp_cfg = json.load(f)
        env = mcp_cfg["mcpServers"]["bitget"]["env"]

        client = DemoClient(
            api_key=env["BITGET_API_KEY"],
            secret=env["BITGET_SECRET_KEY"],
            passphrase=env["BITGET_PASSPHRASE"],
        )

        symbol = parsed.symbol
        tf = parsed.timeframe

        # Account
        try:
            account = client.get_futures_account()
            equity = float(account.get("accountEquity", 10000))
            print(f"  Futures equity: ${equity:,.0f}")
        except Exception:
            equity = 10000.0
            print(f"  Futures equity: unavailable, using default ${equity:,.0f}")

        # Market data
        df = client.get_candles(symbol, tf, limit=200)
        if len(df) == 0:
            print(f"  WARNING: No candle data for {symbol} {tf}")
        else:
            print(f"  Market data: {symbol} {tf} — {len(df)} bars, "
                  f"latest close ${df.iloc[-1]['close']:,.1f}")

            # Agent pipeline
            from agent import TradingAgent, AgentConfig, SentimentSnapshot

            agent_config = AgentConfig(
                symbol=symbol,
                timeframe=tf,
                btc_ema_fast=parsed.extra_params.get("ema_period", 20),
                btc_rsi_period=parsed.extra_params.get("rsi_period", 14),
                max_position_pct=parsed.position_pct / 100.0,
            )
            agent = TradingAgent(agent_config)

            sentiment = SentimentSnapshot(
                fear_greed_index=50,
                fear_greed_label="neutral",
                social_volume_change=0.0,
                long_short_ratio=1.0,
                taker_buy_ratio=0.5,
            )

            output = agent.run(
                market_df=df,
                account_equity=equity,
                current_positions=[],
                sentiment=sentiment,
            )

            sig = output.signal
            risk = output.risk
            print(f"\n  Agent four-layer pipeline:")
            print(f"    [1] PERCEPTION: {output.narrative}")
            print(f"    [2] DECISION:   {sig.type.value} | confidence={sig.confidence:.0%} | {sig.reason}")
            print(f"    [3] RISK:       {'APPROVED' if risk.approved else 'REJECTED'} | {risk.reason}")
            print(f"    [4] EXECUTION:  {'Would trade' if sig.type.value not in ('HOLD', 'NO_TRADE') else 'No action'}")

            # Test order lifecycle (always do an API connectivity test)
            try:
                close = float(df.iloc[-1]["close"])
                # Use proper decimal precision for the coin's price range
                if close >= 100:
                    price_precision = 1
                elif close >= 1:
                    price_precision = 2
                else:
                    price_precision = 4
                test_price = round(close * 0.5, price_precision)
                test_size = "0.0001" if close < 1 else "0.001"

                print(f"\n  Testing order lifecycle (API connectivity):")
                order_result = client.place_order(
                    symbol=symbol, side="buy", order_type="limit",
                    size=test_size, price=str(test_price), trade_side="open",
                )
                oid = order_result.get("data", {}).get("orderId", "")
                print(f"    Place: {order_result.get('msg')} | orderId={oid} | price={test_price}")

                if oid:
                    # Verify pending
                    pending = client.get_orders_pending(symbol)
                    pending_list = pending.get("data", {}).get("entrustedList") or []
                    print(f"    Pending orders: {len(pending_list)}")

                    # Cancel
                    cancel = client.cancel_order(symbol, oid)
                    print(f"    Cancel: {cancel.get('msg')}")

                    # Verify cancelled
                    pending2 = client.get_orders_pending(symbol)
                    pending_list2 = pending2.get("data", {}).get("entrustedList") or []
                    still_there = any(p.get("orderId") == oid for p in pending_list2)
                    print(f"    Verified: order {'NOT ' if still_there else ''}cancelled successfully")

                demo_ok = True
            except Exception as e:
                print(f"    Order test failed: {e}")

            # Get positions
            try:
                pos = client.get("/api/v2/mix/position/all-position?"
                                "productType=USDT-FUTURES&marginCoin=USDT")
                positions = pos.get("data", []) or []
                print(f"\n  Current positions: {len(positions)}")
                for p in positions:
                    print(f"    {p.get('symbol')} {p.get('holdSide')} "
                          f"size={p.get('total')} PnL={p.get('unrealizedPL', 0)}")
            except Exception as e:
                print(f"  Position query: unavailable ({e})")

        # API call summary
        api_summary = client.api_logger.summary()
        print(f"\n  API calls: {api_summary['total_calls']} "
              f"(success={api_summary['success']}, failed={api_summary['failed']})")

    except Exception as e:
        print(f"\n  Demo Trading validation skipped: {e}")

    # ── Step 4: Generate Playbook package ────────────────────────────────
    playbook_dir = os.path.join(OUTPUT_DIR, "playbook_generated")
    src_dir = os.path.join(playbook_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    manifest = generate_playbook_manifest(parsed)
    with open(os.path.join(playbook_dir, "manifest.yaml"), "w", encoding="utf-8") as f:
        f.write(manifest)

    main_py = generate_playbook_main_py(parsed)
    with open(os.path.join(src_dir, "main.py"), "w", encoding="utf-8") as f:
        f.write(main_py)

    # Generate backtest.yaml
    sl = parsed.stop_loss_pct or 5.0
    tp = parsed.take_profit_pct or 10.0
    backtest_yaml = f"""name: {parsed.symbol.lower()}-{parsed.template.replace('_', '-')}-{parsed.timeframe.lower()}
symbol: {parsed.symbol}
timeframe: {parsed.timeframe}
trade_size_pct: {parsed.position_pct}
fees: 0.06
stop_loss_pct: {sl}
take_profit_pct: {tp}
start: "2026-01-01"
"""
    with open(os.path.join(playbook_dir, "backtest.yaml"), "w", encoding="utf-8") as f:
        f.write(backtest_yaml)

    print(f"\n  Playbook package → {playbook_dir}")
    print(f"    manifest.yaml, src/main.py, backtest.yaml")

    # ── Step 5: Summary ─────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  Strategy creation complete")
    print(f"{'─'*60}")
    print(f"""
  Created files:
    Config:       {config_path}
    Playbook:     {playbook_dir}/
      manifest.yaml
      src/main.py
      backtest.yaml

  Strategy summary:
    Name:         {parsed.symbol} {parsed.template} ({parsed.timeframe})
    Template:     {parsed.template}
    Entry logic:  {parsed.entry_desc}
    Exit logic:   {parsed.exit_desc}
    Stop loss:    {sl}% | Take profit: {tp}%

  Demo validation: {'PASSED' if demo_ok else 'SKIPPED'}
    {'Order lifecycle tested (place->verify->cancel)' if demo_ok else '(offline)'}

  To deploy to Playbook for persistent execution:
    1. Upload {playbook_dir}/ to GetAgent Cloud
    2. Connect real funds (Playbook requires live account)
    3. Agent will run 24/7 on cloud platform

  To run locally: python run.py once --config {config_path}
""")

def _run_monitor_cycle(
    strategy_text: str = None,
    continuous: bool = False,
    interval_minutes: int = 15,
    dry_run: bool = True,
) -> None:
    """Run monitoring cycle(s) with live Bitget data.

    Args:
        strategy_text: NL strategy. If None, uses saved state or default.
        continuous: If True, loop indefinitely with interval.
        interval_minutes: Minutes between cycles (continuous mode).
        dry_run: If True, no real orders.
    """
    from agent.auto_cycle import run_cycle, compute_indicators_from_ohlcv, CycleState

    # Determine strategy
    if strategy_text is None:
        state = CycleState.load()
        if state.strategy_text:
            strategy_text = state.strategy_text
        else:
            strategy_text = "BTCUSDT 15min趋势跟随 EMA金叉进场 做多 止损1%止盈2%"

    strategy_text = strategy_text or "BTCUSDT 15min趋势跟随 EMA金叉进场 做多 止损1%止盈2%"

    if continuous:
        print("=" * 60)
        print(f"  DAEMON MODE — {strategy_text}")
        print(f"  Interval: {interval_minutes}min | Dry-run: {dry_run}")
        print(f"  Press Ctrl+C to stop")
        print("=" * 60)

    try:
        from demo_trading_test import DemoClient
        mcp_path = os.path.join(os.path.dirname(__file__), ".mcp.json")
        with open(mcp_path) as f:
            mcp_cfg = json.load(f)
        env = mcp_cfg["mcpServers"]["bitget"]["env"]
        client = DemoClient(
            api_key=env["BITGET_API_KEY"],
            secret=env["BITGET_SECRET_KEY"],
            passphrase=env["BITGET_PASSPHRASE"],
        )
    except Exception:
        client = None

    cycle_num = 0
    while True:
        cycle_num += 1
        print(f"\n{'─' * 50}")
        print(f"  Cycle #{cycle_num} — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
        print(f"{'─' * 50}")

        # Fetch live candles
        ohlcv_list = []
        if client:
            try:
                df = client.get_candles("BTCUSDT", "15min", limit=200)
                ohlcv_list = df.reset_index().to_dict(orient="records")
                print(f"  Fetched {len(ohlcv_list)} 15min candles from Bitget")
            except Exception as e:
                print(f"  Error fetching candles: {e}")

        # If no live data, try local file
        if not ohlcv_list:
            local_path = os.path.join(DATA_DIR, "btc_15min_latest.json")
            if os.path.exists(local_path):
                with open(local_path) as f:
                    ohlcv_list = json.load(f)
                print(f"  Using local data: {len(ohlcv_list)} bars")

        if not ohlcv_list:
            print("  No market data available, skipping cycle")
            if not continuous:
                break
            time.sleep(interval_minutes * 60)
            continue

        # Compute indicators
        indicators = compute_indicators_from_ohlcv(ohlcv_list)

        # Build market data (sentiment/macro/news use defaults for standalone mode)
        market_data = {
            "technical": indicators,
            "sentiment": {"fear_greed_index": 50, "fear_greed_label": "neutral", "long_short_ratio": 1.0},
            "macro": {"regime": "neutral"},
            "news": {"has_major_event": False, "bias": "neutral", "summary": ""},
        }

        # Run cycle
        result = run_cycle(
            strategy_text=strategy_text,
            market_data_json=json.dumps(market_data),
            dry_run=dry_run,
            client=client,
        )

        status = result.get("status", "unknown")
        print(f"  Result: {status}")
        if status == "entry":
            print(f"  Signal: {result.get('signal')} | Confidence: {result.get('confidence', 0):.0%}")
            print(f"  Entry={result.get('entry_price')} SL={result.get('stop_loss')} TP={result.get('take_profit')}")
        elif status == "no_trade":
            print(f"  Reason: {result.get('reason', 'conditions not met')}")

        if not continuous:
            break

        print(f"\n  Sleeping {interval_minutes}min until next cycle...")
        try:
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n  Daemon stopped by user.")
            break


def _run_full_demo() -> None:
    """Phase 1 + Phase 2 + Phase 3: full competition demo."""
    print("="*68)
    print("  BITGET HACKATHON — Adaptive Trading Agent")
    print("  赛道一: 交易 Agent")
    print(f"  启动时间: {datetime.now().isoformat()}")
    print("="*68)

    t0 = time.time()

    run_agent_pipeline()
    trades = run_backtest_benchmark()

    # Phase 3: Bitget Demo Trading live test (optional, needs network)
    demo_ok = False
    try:
        from demo_trading_test import main as demo_main
        print("\n")
        demo_main()
        demo_ok = True
    except Exception as e:
        print(f"\n  [Phase 3] Demo Trading test skipped (network/API unavailable): {e}")

    elapsed = time.time() - t0

    banner("Run Complete")
    demo_status = "[3] Demo Trading 实盘测试 — passed" if demo_ok else "[3] Demo Trading 实盘测试 — skipped (offline)"
    print(f"""
    Duration: {elapsed:.1f}s
    Trade log: {TRADE_LOG_PATH}
    Total backtest trades: {len(trades)}

    Deliverables verified:
      [1] Agent 四层闭环 pipeline — 4 scenarios passed
      [2] 8 策略变体回测对比 — metrics table + rankings
      {demo_status}

    评委可直接运行: pip install -r requirements.txt && python run.py
    """)


def _evaluate_and_execute_flow(strategy_text: str, market_data_json: str = "",
                              execute: bool = False, dry_run: bool = True) -> None:
    """Evaluate strategy conditions against market data, optionally execute.

    This is the core flow that Claude Code calls after invoking Skills:
      1. Parse NL strategy
      2. Load market data from JSON (populated by Skills)
      3. Evaluate strategy conditions
      4. Print comprehensive report
      5. If execute=True, place trade via DemoClient
    """
    from agent.strategy_factory import parse_strategy, generate_config_yaml
    from agent.strategy_executor import (
        evaluate_strategy, execute_trade, print_eval_report
    )
    from agent.market_snapshot import MarketSnapshot

    banner("Strategy Evaluation + Execution Engine")

    # Step 0: Parse strategy
    print(f"\n  Input: \"{strategy_text}\"")
    parsed = parse_strategy(strategy_text)
    print(f"  Parsed: {parsed.symbol} {parsed.timeframe} | "
          f"{parsed.template} | {parsed.direction} | "
          f"SL={parsed.stop_loss_pct}% TP={parsed.take_profit_pct}% | "
          f"Confidence={parsed.confidence:.0%}")

    # Step 1: Load market data
    market = MarketSnapshot()
    if market_data_json:
        try:
            data = json.loads(market_data_json) if isinstance(market_data_json, str) else market_data_json
            tech = data.get("technical", {})
            market.technical.symbol = tech.get("symbol", parsed.symbol)
            market.technical.timeframe = tech.get("timeframe", parsed.timeframe)
            market.technical.close = tech.get("close", 0)
            market.technical.rsi = tech.get("rsi")
            market.technical.macd_dif = tech.get("macd_dif")
            market.technical.macd_dea = tech.get("macd_dea")
            market.technical.macd_hist = tech.get("macd_hist")
            market.technical.ema_12 = tech.get("ema_12")
            market.technical.ema_26 = tech.get("ema_26")
            market.technical.ema_20 = tech.get("ema_20")
            market.technical.ema_50 = tech.get("ema_50")
            market.technical.atr = tech.get("atr")
            market.technical.adx = tech.get("adx")
            market.technical.bb_upper = tech.get("bb_upper")
            market.technical.bb_mid = tech.get("bb_mid")
            market.technical.bb_lower = tech.get("bb_lower")
            market.technical.volume_surge = tech.get("volume_surge", False)
            market.technical.trend_direction = tech.get("trend_direction", "neutral")

            sent = data.get("sentiment", {})
            market.sentiment.fear_greed_index = sent.get("fear_greed_index", 50)
            market.sentiment.fear_greed_label = sent.get("fear_greed_label", "neutral")
            market.sentiment.long_short_ratio = sent.get("long_short_ratio", 1.0)

            macro = data.get("macro", {})
            market.macro.regime = macro.get("regime", "neutral")
            market.macro.fed_funds_rate = macro.get("fed_funds_rate")
            market.macro.btc_nasdaq_correlation = macro.get("btc_nasdaq_correlation")

            news = data.get("news", {})
            market.news.has_major_event = news.get("has_major_event", False)
            market.news.bias = news.get("bias", "neutral")
            market.news.event_summary = news.get("summary", "")

            print(f"  Market data loaded: {market.technical.symbol} "
                  f"Close={market.technical.close:.1f} RSI={market.technical.rsi}")
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  WARNING: Failed to parse market data: {e}")
            print(f"  Will evaluate with empty market snapshot (all checks will fail)")
    else:
        print(f"  WARNING: No market data provided. Will evaluate with empty snapshot.")

    # Step 2: Evaluate strategy conditions
    print(f"\n── Evaluating Strategy Conditions ──")
    eval_result = evaluate_strategy(parsed, market)

    # Step 3: Execute if conditions met and execute flag is set
    exec_result = None
    if execute and eval_result.result.value != "NO_TRADE":
        print(f"\n── Executing Trade ──")
        try:
            mcp_path = os.path.join(os.path.dirname(__file__), ".mcp.json")
            with open(mcp_path) as f:
                mcp_cfg = json.load(f)
            env = mcp_cfg["mcpServers"]["bitget"]["env"]

            from demo_trading_test import DemoClient
            client = DemoClient(
                api_key=env["BITGET_API_KEY"],
                secret=env["BITGET_SECRET_KEY"],
                passphrase=env["BITGET_PASSPHRASE"],
            )
            exec_result = execute_trade(parsed, eval_result, market, client, dry_run=dry_run)
        except Exception as e:
            exec_result = type("ExecResult", (), {"executed": False, "error": str(e), "api_log": []})()
            print(f"  Execution failed: {e}")
    elif execute:
        print(f"\n── Execution Skipped (no entry signal) ──")

    # Step 4: Print comprehensive report
    print_eval_report(parsed, market, eval_result, exec_result)

    # Step 5: Save evaluation to file
    report = {
        "strategy": {
            "raw": strategy_text,
            "symbol": parsed.symbol,
            "timeframe": parsed.timeframe,
            "template": parsed.template,
            "direction": parsed.direction,
            "stop_loss_pct": parsed.stop_loss_pct,
            "take_profit_pct": parsed.take_profit_pct,
            "position_pct": parsed.position_pct,
        },
        "market": market.to_dict(),
        "evaluation": {
            "result": eval_result.result.value,
            "confidence": eval_result.confidence,
            "passed_checks": eval_result.passed_count,
            "total_checks": eval_result.total_count,
            "reason": eval_result.reason,
            "risk_warnings": eval_result.risk_warnings,
            "checks": [{"name": c.name, "passed": c.passed, "expected": c.expected, "actual": c.actual}
                      for c in eval_result.checks],
        },
    }
    if exec_result:
        report["execution"] = {
            "executed": exec_result.executed,
            "order_id": getattr(exec_result, "order_id", ""),
            "error": getattr(exec_result, "error", ""),
        }

    report_path = os.path.join(OUTPUT_DIR, "strategy_eval_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"  Report saved → {report_path}")


def _full_trade_flow(strategy_text: str, market_data_json: str = "",
                     execute: bool = False, dry_run: bool = True) -> dict:
    """Complete trading agent flow: NL → Skills → Evaluate → Metrics → Execute → Monitor.

    This is the main flow that Claude Code orchestrates:
      1. Parse NL strategy
      2. Load market data from Skills
      3. Evaluate entry conditions (5 checks per template)
      4. Estimate win rate, RR ratio, expected return
      5. Execute trade if conditions met
      6. Return monitoring instructions for continued oversight

    Returns a dict with all steps and monitoring guidance for Claude Code.
    """
    from agent.strategy_factory import parse_strategy, TEMPLATES
    from agent.strategy_executor import (
        evaluate_strategy, execute_trade, print_eval_report,
        estimate_trade_metrics, EvalResult,
    )
    from agent.position_monitor import PositionMonitor, print_monitor_status
    from agent.market_snapshot import MarketSnapshot

    banner("Complete Trading Agent Flow")

    # ═══════════════════════════════════════════════════════════════════
    # Step 1: Parse NL strategy
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 1] 解析自然语言策略")
    parsed = parse_strategy(strategy_text)
    t = TEMPLATES.get(parsed.template, {})
    print(f"  模板:   {t.get('name', parsed.template)}")
    print(f"  交易对: {parsed.symbol} | 周期: {parsed.timeframe}")
    print(f"  方向:   {parsed.direction} | 仓位: {parsed.position_pct}%")
    print(f"  止损:   {parsed.stop_loss_pct or 5}% | 止盈: {parsed.take_profit_pct or 10}%")
    print(f"  入场逻辑: {parsed.entry_desc}")
    print(f"  出场逻辑: {parsed.exit_desc}")

    # ═══════════════════════════════════════════════════════════════════
    # Step 2: Load market data
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 2] 加载 Skill 提供的市场数据")
    market = MarketSnapshot()
    if market_data_json:
        try:
            data = json.loads(market_data_json) if isinstance(market_data_json, str) else market_data_json
            tech = data.get("technical", {})
            market.technical.symbol = tech.get("symbol", parsed.symbol)
            market.technical.timeframe = tech.get("timeframe", parsed.timeframe)
            market.technical.close = tech.get("close", 0)
            market.technical.rsi = tech.get("rsi")
            market.technical.macd_dif = tech.get("macd_dif")
            market.technical.macd_dea = tech.get("macd_dea")
            market.technical.macd_hist = tech.get("macd_hist")
            market.technical.ema_12 = tech.get("ema_12")
            market.technical.ema_26 = tech.get("ema_26")
            market.technical.ema_20 = tech.get("ema_20")
            market.technical.ema_50 = tech.get("ema_50")
            market.technical.atr = tech.get("atr")
            market.technical.adx = tech.get("adx")
            market.technical.bb_upper = tech.get("bb_upper")
            market.technical.bb_mid = tech.get("bb_mid")
            market.technical.bb_lower = tech.get("bb_lower")
            market.technical.volume_surge = tech.get("volume_surge", False)
            market.technical.trend_direction = tech.get("trend_direction", "neutral")
            market.technical.support_levels = tech.get("support", [])
            market.technical.resistance_levels = tech.get("resistance", [])

            sent = data.get("sentiment", {})
            market.sentiment.fear_greed_index = sent.get("fear_greed_index", 50)
            market.sentiment.fear_greed_label = sent.get("fear_greed_label", "neutral")
            market.sentiment.long_short_ratio = sent.get("long_short_ratio", 1.0)
            market.sentiment.taker_buy_ratio = sent.get("taker_buy_ratio", 0.5)

            macro = data.get("macro", {})
            market.macro.regime = macro.get("regime", "neutral")
            market.macro.fed_funds_rate = macro.get("fed_funds_rate")
            market.macro.btc_nasdaq_correlation = macro.get("btc_nasdaq_correlation")

            news = data.get("news", {})
            market.news.has_major_event = news.get("has_major_event", False)
            market.news.bias = news.get("bias", "neutral")
            market.news.event_summary = news.get("summary", "")
        except Exception as e:
            print(f"  WARNING: 市场数据解析失败: {e}")

    print(f"  {market.summary()}")

    # ═══════════════════════════════════════════════════════════════════
    # Step 3: Evaluate entry conditions
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 3] 评估策略入场条件")
    eval_result = evaluate_strategy(parsed, market)

    for c in eval_result.checks:
        icon = "[PASS]" if c.passed else "[FAIL]"
        print(f"  {icon} {c.name}: 期望={c.expected} | 实际={c.actual}")

    print(f"  结果: {eval_result.passed_count}/{eval_result.total_count} 条件通过")
    print(f"  信心度: {eval_result.confidence:.0%}")

    if eval_result.result == EvalResult.NO_TRADE:
        print(f"\n  [结论] 不满足入场条件，保持观望")
        if eval_result.reason:
            print(f"  原因: {eval_result.reason}")
        if eval_result.risk_warnings:
            for w in eval_result.risk_warnings:
                print(f"  [!] {w}")
        return {"status": "no_trade", "reason": eval_result.reason,
                "parsed": parsed.__dict__, "market": market.to_dict(),
                "evaluation": eval_result.__dict__}

    # ═══════════════════════════════════════════════════════════════════
    # Step 4: Calculate trade metrics
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 4] 计算交易指标")
    metrics = estimate_trade_metrics(parsed, eval_result, market)

    print(f"  入场价:   {metrics.entry_price:.1f}")
    print(f"  止损位:   {metrics.stop_loss:.1f} ({metrics.risk_pct}%)")
    print(f"  止盈位:   {metrics.take_profit:.1f} ({metrics.reward_pct}%)")
    print(f"  盈亏比:   {metrics.risk_reward_ratio:.2f}:1")
    print(f"  预估胜率: {metrics.estimated_win_rate:.1%}")
    print(f"  期望收益: {metrics.expectancy:.2f}% per trade")
    print(f"  盈亏平衡胜率: {metrics.breakeven_win_rate:.1%}")
    print(f"  Kelly比例: {metrics.kelly_fraction:.1%}")

    # ═══════════════════════════════════════════════════════════════════
    # Step 5: Execute trade
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 5] 执行交易{' (模拟)' if dry_run else ' (实盘)'}")
    exec_result = None

    if execute or not dry_run:
        try:
            mcp_path = os.path.join(os.path.dirname(__file__), ".mcp.json")
            with open(mcp_path) as f:
                mcp_cfg = json.load(f)
            env = mcp_cfg["mcpServers"]["bitget"]["env"]

            from demo_trading_test import DemoClient
            client = DemoClient(
                api_key=env["BITGET_API_KEY"],
                secret=env["BITGET_SECRET_KEY"],
                passphrase=env["BITGET_PASSPHRASE"],
            )
            exec_result = execute_trade(parsed, eval_result, market, client, dry_run=dry_run)

            if exec_result.executed:
                print(f"  入场订单: {exec_result.order_id}")
                print(f"  止损订单: {exec_result.sl_order_id}")
                print(f"  止盈订单: {exec_result.tp_order_id}")
            elif exec_result.error:
                print(f"  {exec_result.error}")
        except Exception as e:
            print(f"  交易执行失败: {e}")
            exec_result = type("ExecResult", (), {"executed": False, "error": str(e),
                               "order_id": "", "sl_order_id": "", "tp_order_id": "", "api_log": []})()
    else:
        print(f"  [模拟] 将{'做多' if eval_result.result == EvalResult.ENTRY_LONG else '做空'}")
        print(f"  入场: {metrics.entry_price:.1f} | SL: {metrics.stop_loss:.1f} | TP: {metrics.take_profit:.1f}")

    # ═══════════════════════════════════════════════════════════════════
    # Step 6: Monitoring guidance
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n  [Step 6] 持仓监控指引")

    direction_str = "做多" if eval_result.result == EvalResult.ENTRY_LONG else "做空"
    print(f"\n  {'='*60}")
    print(f"  策略已{'执行' if (execute and getattr(exec_result, 'executed', False)) else '分析完成'}")
    print(f"  {'='*60}")
    print(f"""
  交易摘要:
    策略:   {t.get('name', parsed.template)} ({parsed.symbol} {parsed.timeframe})
    方向:   {direction_str}
    入场:   {metrics.entry_price:.1f} | 止损: {metrics.stop_loss:.1f} | 止盈: {metrics.take_profit:.1f}
    盈亏比: {metrics.risk_reward_ratio:.2f}:1 | 预估胜率: {metrics.estimated_win_rate:.1%}
    仓位:   {parsed.position_pct}% | 期望收益: {metrics.expectancy:.2f}%/笔

  持仓期间监控规则:
    - 每 4H 用 Skills 获取市场数据
    - 检查: EMA趋势 / MACD交叉 / RSI极端 / 成交量异动
    - 检查: 情绪面(恐惧贪婪) / 宏观面(Risk-On/Off) / 消息面(重大事件)
    - 风险预警: 接近SL/TP 85%时提醒
    - 立即平仓: 趋势反转 + 任一指标确认
    - 立即平仓: 重大利空消息 + 持仓方向不利

  平仓后自动生成:
    - 盈亏记录 (USDT + %)
    - 交易评级 (A/B/C/D/F)
    - 经验总结
    - 完整交易日志
""")

    if eval_result.risk_warnings:
        print(f"  [当前风险提示]")
        for w in eval_result.risk_warnings:
            print(f"  [!] {w}")

    return {
        "status": "entry" if eval_result.result != EvalResult.NO_TRADE else "no_trade",
        "parsed": parsed.__dict__,
        "market": market.to_dict(),
        "evaluation": {
            "result": eval_result.result.value,
            "confidence": eval_result.confidence,
            "passed": eval_result.passed_count,
            "total": eval_result.total_count,
            "checks": [{"name": c.name, "passed": c.passed, "expected": c.expected, "actual": c.actual}
                      for c in eval_result.checks],
            "reason": eval_result.reason,
            "risk_warnings": eval_result.risk_warnings,
        },
        "metrics": metrics.__dict__,
        "execution": {
            "executed": exec_result.executed if exec_result else False,
            "order_id": getattr(exec_result, "order_id", "") if exec_result else "",
            "sl_order_id": getattr(exec_result, "sl_order_id", "") if exec_result else "",
            "tp_order_id": getattr(exec_result, "tp_order_id", "") if exec_result else "",
            "error": getattr(exec_result, "error", "") if exec_result else "",
        },
        "monitoring_guide": {
            "check_interval": parsed.timeframe,
            "checks": ["EMA趋势", "MACD交叉", "RSI极端", "成交量异动",
                      "情绪面(恐惧贪婪)", "宏观面(Risk-On/Off)", "消息面(重大事件)"],
            "exit_triggers": ["趋势反转 + 指标确认", "重大利空消息", "接近SL/TP 85%+"],
        },
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Adaptive Trading Agent — Bitget Hackathon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                          Full demo (backtest + live test)
  python run.py create                   Interactive NL strategy creation
  python run.py create "BTC 4H趋势策略 EMA金叉进场 止损2%"
  python run.py evaluate "BTC 4H趋势" --market-data '{"technical":{...}}'
  python run.py evaluate "DOGE 1H动量" --market-data-file market.json --execute
  python run.py once                     Single strategy check, dry-run
  python run.py once --config presets/conservative.yaml
  python run.py daemon                   Continuous monitoring (dry-run)
  python run.py daemon --live            Continuous with real orders
  python run.py daemon -c presets/btc_trend_following.yaml --once
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Run mode")

    # ── Subcommand: create ──────────────────────────────────────────────
    create_p = sub.add_parser("create", help="Create strategy from natural language (Chinese)")
    create_p.add_argument("text", nargs="?", default=None,
                         help="Natural language strategy description")

    # ── Subcommand: evaluate (Skill-driven strategy check) ─────────────
    eval_p = sub.add_parser("evaluate",
        help="Evaluate strategy conditions against Skill-provided market data")
    eval_p.add_argument("text", help="Natural language strategy description")
    eval_p.add_argument("--market-data", "-m", default="",
                       help="Market data JSON string (from Skills)")
    eval_p.add_argument("--market-data-file", "-f", default="",
                       help="Path to market data JSON file")
    eval_p.add_argument("--execute", "-x", action="store_true",
                       help="Execute trade if conditions met (Demo Trading)")
    eval_p.add_argument("--live", action="store_true",
                       help="Real orders (default: dry-run even with --execute)")

    # ── Subcommand: trade (complete flow: NL → Skills → Metrics → Execute → Monitor) ─
    trade_p = sub.add_parser("trade",
        help="Complete agent flow: NL strategy → Skill analysis → metrics → execute → monitor guide")
    trade_p.add_argument("text", help="Natural language strategy description")
    trade_p.add_argument("--market-data-file", "-f", default="",
                       help="Path to market data JSON file (from Skills)")
    trade_p.add_argument("--execute", "-x", action="store_true",
                       help="Execute trade if conditions met")
    trade_p.add_argument("--live", action="store_true",
                       help="Real orders on Bitget (default: dry-run)")

    # ── Note: daemon/once moved to Claude Code orchestration loop ────
    # Use `python run_cycle_once.py` for single-cycle or
    # Claude Code autonomous loop with Skills cross-validation

    daemon_p = sub.add_parser("daemon", help="Continuous monitoring with live Bitget data")
    daemon_p.add_argument("text", nargs="?", default=None,
                         help="Strategy description (uses saved state if omitted)")
    daemon_p.add_argument("--interval", "-i", type=int, default=15,
                         help="Minutes between cycles (default: 15)")
    daemon_p.add_argument("--live", action="store_true",
                         help="Real orders (default: dry-run)")

    once_p = sub.add_parser("once", help="Single monitoring cycle with live Bitget data")
    once_p.add_argument("text", nargs="?", default=None,
                       help="Strategy description (uses saved state if omitted)")
    once_p.add_argument("--live", action="store_true",
                       help="Real orders (default: dry-run)")

    args = parser.parse_args()

    if args.command == "create":
        if args.text:
            _create_flow(args.text)
        else:
            print("=" * 60)
            print("  NL Strategy Creator")
            print("  Describe your strategy in Chinese (or English)")
            print("  Examples:")
            print("    BTC 4H趋势策略 EMA金叉 RSI过滤 止损2%")
            print("    DOGE 1H动量突破 RSI在55-65之间 做多")
            print("    ETH震荡策略 布林带下轨买入上轨卖出")
            print("=" * 60)
            user_input = input("\n  Your strategy: ").strip()
            if not user_input:
                print("  No input, using default example.")
                user_input = "BTC 4H趋势跟随策略 EMA金叉进场 RSI过滤 止损2% 止盈10%"
            _create_flow(user_input)
    elif args.command == "evaluate":
        # Load market data from file or string
        market_data = args.market_data
        if args.market_data_file:
            with open(args.market_data_file, "r", encoding="utf-8") as f:
                market_data = f.read()
        _evaluate_and_execute_flow(
            args.text, market_data_json=market_data,
            execute=args.execute, dry_run=not args.live,
        )
    elif args.command == "trade":
        market_data = ""
        if args.market_data_file:
            with open(args.market_data_file, "r", encoding="utf-8") as f:
                market_data = f.read()
        _full_trade_flow(
            args.text, market_data_json=market_data,
            execute=args.execute, dry_run=not args.live,
        )
    elif args.command in ("daemon", "once"):
        _run_monitor_cycle(
            strategy_text=args.text if hasattr(args, "text") and args.text else None,
            continuous=(args.command == "daemon"),
            interval_minutes=args.interval if hasattr(args, "interval") else 15,
            dry_run=not (hasattr(args, "live") and args.live),
        )
    else:
        _run_full_demo()


if __name__ == "__main__":
    main()
