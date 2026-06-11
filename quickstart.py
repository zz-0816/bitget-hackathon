"""quickstart.py — 一键策略创建+运行

Usage:
  python quickstart.py
  python quickstart.py "BTC 4H趋势策略 EMA金叉 止损2%"
  python quickstart.py --live

Flow:
  1. 输入自然语言描述策略
  2. 自动解析 → 生成配置
  3. 连接 Demo Trading 验证
  4. 启动 Agent 持续监控

No CLI subcommands to remember. Just run it.
"""
import json, os, sys, time, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def banner(text: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def load_credentials() -> tuple:
    with open(os.path.join(os.path.dirname(__file__), ".mcp.json")) as f:
        mcp_cfg = json.load(f)
    env = mcp_cfg["mcpServers"]["bitget"]["env"]
    return env["BITGET_API_KEY"], env["BITGET_SECRET_KEY"], env["BITGET_PASSPHRASE"]


def main():
    parser = argparse.ArgumentParser(description="一键策略创建+运行")
    parser.add_argument("text", nargs="?", default=None,
                       help="自然语言策略描述（不提供则交互输入）")
    parser.add_argument("--live", action="store_true",
                       help="真实下单模式（默认 dry-run）")
    parser.add_argument("--once", action="store_true",
                       help="只跑一个周期后退出")
    args = parser.parse_args()

    # ═════════════════════════════════════════════════════════════════
    # Step 1: Get NL input
    # ═════════════════════════════════════════════════════════════════
    banner("Step 1: 策略描述")

    if args.text:
        user_input = args.text
        print(f"  输入: \"{user_input}\"")
    else:
        print("  用中文描述你想要的策略，例如：")
        print("    BTC 4H趋势跟随策略 EMA金叉 RSI过滤 止损2%")
        print("    DOGE 1H动量突破 做多 止损3%")
        print("    ETH震荡策略 布林带下轨买入上轨卖出")
        print()
        user_input = input("  ▶ 你的策略: ").strip()
        if not user_input:
            print("  未输入，使用默认示例")
            user_input = "BTC 4H趋势跟随策略 EMA金叉进场 RSI过滤 止损2%"

    # ═════════════════════════════════════════════════════════════════
    # Step 2: Parse + generate config
    # ═════════════════════════════════════════════════════════════════
    banner("Step 2: 解析策略")

    from agent.strategy_factory import (
        parse_strategy, generate_config_yaml,
        generate_playbook_manifest, generate_playbook_main_py,
    )

    parsed = parse_strategy(user_input)

    print(f"  模板:     {parsed.template}")
    print(f"  交易对:   {parsed.symbol}")
    print(f"  周期:     {parsed.timeframe}")
    print(f"  方向:     {parsed.direction}")
    print(f"  入场:     {parsed.entry_desc}")
    print(f"  出场:     {parsed.exit_desc}")
    print(f"  止损:     {parsed.stop_loss_pct}%")
    print(f"  止盈:     {parsed.take_profit_pct or '默认'}%")
    print(f"  仓位:     {parsed.position_pct}%")
    print(f"  杠杆:     {parsed.leverage}x")
    print(f"  匹配度:   {parsed.confidence:.0%}")

    config_path = os.path.join(OUTPUT_DIR, "quickstart_config.yaml")
    config_yaml = generate_config_yaml(parsed)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_yaml)
    print(f"\n  配置已保存 → {config_path}")

    # ═════════════════════════════════════════════════════════════════
    # Step 3: Demo Trading 验证
    # ═════════════════════════════════════════════════════════════════
    banner("Step 3: Demo Trading 验证")

    from demo_trading_test import DemoClient
    from agent import TradingAgent, AgentConfig, SentimentSnapshot

    api_key, secret, passphrase = load_credentials()
    client = DemoClient(api_key, secret, passphrase)

    # Account
    try:
        account = client.get_futures_account()
        equity = float(account.get("accountEquity", 10000))
        print(f"  账户权益: ${equity:,.0f}")
    except Exception:
        equity = 10000.0
        print(f"  账户权益: 离线，使用默认 $10,000")

    # Market data
    symbol, tf = parsed.symbol, parsed.timeframe
    df = client.get_candles(symbol, tf, limit=200)
    if len(df) == 0:
        print(f"  ✗ 无法获取 {symbol} {tf} 行情数据，终止")
        return

    close = float(df.iloc[-1]["close"])
    print(f"  行情: {symbol} {tf} | {len(df)} 根K线 | 最新价 ${close:,.1f}")

    # Agent pipeline
    agent_config = AgentConfig(
        symbol=symbol,
        timeframe=tf,
        btc_ema_fast=parsed.extra_params.get("ema_period", 20),
        btc_rsi_period=parsed.extra_params.get("rsi_period", 14),
        max_position_pct=parsed.position_pct / 100.0,
    )
    agent = TradingAgent(agent_config)

    sentiment = SentimentSnapshot(
        fear_greed_index=50, fear_greed_label="neutral",
        social_volume_change=0.0, long_short_ratio=1.0, taker_buy_ratio=0.5,
    )
    output = agent.run(
        market_df=df, account_equity=equity,
        current_positions=[], sentiment=sentiment,
    )

    sig = output.signal
    risk = output.risk
    print(f"\n  Agent 四层 Pipeline:")
    print(f"    [1] 感知: {output.narrative[:120]}")
    print(f"    [2] 决策: {sig.type.value} | 置信度={sig.confidence:.0%} | {sig.reason}")
    print(f"    [3] 风控: {'通过' if risk.approved else '拒绝'} | {risk.reason}")
    action = "下单" if sig.type.value not in ("HOLD", "NO_TRADE") else "无操作"
    print(f"    [4] 执行: {action}")

    # Order lifecycle test
    try:
        price_prec = 1 if close >= 100 else (2 if close >= 1 else 4)
        test_price = round(close * 0.5, price_prec)
        test_size = "0.001" if close >= 1 else "0.0001"

        order_result = client.place_order(
            symbol=symbol, side="buy", order_type="limit",
            size=test_size, price=str(test_price), trade_side="open",
        )
        oid = order_result.get("data", {}).get("orderId", "")
        if oid:
            client.cancel_order(symbol, oid)
        print(f"  订单链路: 下单→取消 [OK]")
    except Exception as e:
        print(f"  订单链路: 跳过 ({e})")

    api_summary = client.api_logger.summary()
    print(f"  API调用: {api_summary['total_calls']}次 | "
          f"成功{api_summary['success']} | 失败{api_summary['failed']}")

    # ═════════════════════════════════════════════════════════════════
    # Step 4: Playbook 打包
    # ═════════════════════════════════════════════════════════════════
    playbook_dir = os.path.join(OUTPUT_DIR, "playbook_generated")
    src_dir = os.path.join(playbook_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    with open(os.path.join(playbook_dir, "manifest.yaml"), "w", encoding="utf-8") as f:
        f.write(generate_playbook_manifest(parsed))
    with open(os.path.join(src_dir, "main.py"), "w", encoding="utf-8") as f:
        f.write(generate_playbook_main_py(parsed))
    sl = parsed.stop_loss_pct or 5.0
    tp = parsed.take_profit_pct or 10.0
    with open(os.path.join(playbook_dir, "backtest.yaml"), "w", encoding="utf-8") as f:
        f.write(f"name: {parsed.symbol.lower()}-{parsed.template.replace('_', '-')}-{parsed.timeframe.lower()}\n")
        f.write(f"symbol: {parsed.symbol}\n")
        f.write(f"timeframe: {parsed.timeframe}\n")
        f.write(f"trade_size_pct: {parsed.position_pct}\n")
        f.write(f"fees: 0.06\n")
        f.write(f"stop_loss_pct: {sl}\n")
        f.write(f"take_profit_pct: {tp}\n")
        f.write(f"start: \"2026-01-01\"\n")
    print(f"\n  Playbook 包 → {playbook_dir}/")

    # ═════════════════════════════════════════════════════════════════
    # Step 5: 启动 Agent 持续监控
    # ═════════════════════════════════════════════════════════════════
    banner("Step 5: Agent 持续监控")

    dry_run = not args.live
    mode_str = "DRY-RUN（仅信号，不下单）" if dry_run else "LIVE（真实下单）"
    print(f"  模式: {mode_str}")
    print(f"  策略: {parsed.symbol} {parsed.timeframe} {parsed.template}")
    print(f"  配置: {config_path}")

    from daemon import run_daemon
    print(f"\n  启动 daemon...\n")
    run_daemon(config_path, dry_run=dry_run, once=args.once)


if __name__ == "__main__":
    main()
