"""daemon.py — Continuous trading loop powered by the Agent four-layer engine.

The daemon is a thin scheduling wrapper. All trading logic lives in agent/:
  Perception → Decision → Risk → Execution (four-layer closed loop)

Usage:
  python run.py daemon                     # continuous monitoring (dry-run)
  python run.py daemon --live              # continuous with real orders
  python run.py daemon --once              # single cycle
  python run.py once                       # alias for single cycle
  python run.py once --config presets/conservative.yaml
"""
import argparse, json, os, sys, signal, time
from datetime import datetime, timezone

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from agent import TradingAgent, AgentConfig, SentimentSnapshot
from demo_trading_test import DemoClient

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
DAEMON_LOG_PATH = os.path.join(OUTPUT_DIR, "daemon_log.json")


# ═══════════════════════════════════════════════════════════════════════════
# Config → AgentConfig mapper
# ═══════════════════════════════════════════════════════════════════════════

def _build_agent_config(user_cfg: dict) -> AgentConfig:
    """Map user config.yaml to AgentConfig dataclass."""
    s = user_cfg.get("strategy", {})
    r = user_cfg.get("risk", {})
    ind = s.get("indicators", {})
    sig = s.get("signal", {})
    tfs = s.get("timeframes", ["4H"])
    primary_tf = tfs[0]
    secondary_tf = tfs[1] if len(tfs) > 1 else "1D"

    return AgentConfig(
        symbol=s.get("symbols", ["BTCUSDT"])[0],
        timeframe=primary_tf,
        secondary_tf=secondary_tf,
        btc_ema_fast=ind.get("ema_fast", 20),
        btc_ema_mid=ind.get("ema_slow", 50),
        btc_rsi_period=ind.get("rsi_period", 14),
        btc_rsi_long_min=ind.get("rsi_oversold", 30),
        btc_rsi_short_max=ind.get("rsi_overbought", 70),
        btc_macd_fast=ind.get("macd_fast", 12),
        btc_macd_slow=ind.get("macd_slow", 26),
        btc_macd_signal=ind.get("macd_signal", 9),
        btc_atr_period=ind.get("atr_period", 14),
        btc_atr_sl_mult=r.get("atr_stop_mult", 2.0),
        btc_atr_tp_mult=r.get("atr_tp_mult", 3.0),
        btc_vol_surge_mult=1.5,
        max_position_pct=r.get("position_pct", 2.0) / 100.0,
        max_total_exposure_pct=r.get("exposure_pct", 30.0) / 100.0,
        daily_loss_circuit_breaker=r.get("daily_loss_pct", 5.0) / 100.0,
        min_risk_reward_ratio=r.get("min_rr", 1.5),
        sentiment_filter_enabled=sig.get("sentiment_filter", True),
        fear_greed_oversold=25,
        fear_greed_overbought=75,
    )


def load_credentials() -> tuple[str, str, str]:
    mcp_path = os.path.join(PROJECT_DIR, ".mcp.json")
    with open(mcp_path) as f:
        mcp_cfg = json.load(f)
    env = mcp_cfg["mcpServers"]["bitget"]["env"]
    return env["BITGET_API_KEY"], env["BITGET_SECRET_KEY"], env["BITGET_PASSPHRASE"]


# ═══════════════════════════════════════════════════════════════════════════
# Daemon State
# ═══════════════════════════════════════════════════════════════════════════

class DaemonState:
    def __init__(self):
        self.running = True
        self.cycle_count = 0
        self.signals_generated = 0
        self.trades_placed = 0
        self.start_time = datetime.now(timezone.utc)
        self.pipeline_history: list[dict] = []

    def record_pipeline(self, agent_output: dict) -> None:
        self.pipeline_history.append({
            "cycle": self.cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **agent_output,
        })
        if len(self.pipeline_history) > 200:
            self.pipeline_history = self.pipeline_history[-200:]
        self._save()

    def _save(self) -> None:
        log = {
            "daemon_started": self.start_time.isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "cycles": self.cycle_count,
            "signals_generated": self.signals_generated,
            "trades_placed": self.trades_placed,
            "runtime": str(datetime.now(timezone.utc) - self.start_time),
            "recent_pipelines": self.pipeline_history[-50:],
        }
        with open(DAEMON_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Daemon Core — Agent-powered continuous loop
# ═══════════════════════════════════════════════════════════════════════════

def run_daemon(config_path: str, dry_run: bool = True, once: bool = False) -> None:
    # ── Load config ────────────────────────────────────────────────────
    with open(config_path, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f)

    agent_config = _build_agent_config(user_cfg)
    exec_cfg = user_cfg.get("execution", {})
    strat_cfg = user_cfg.get("strategy", {})

    symbol = agent_config.symbol
    timeframe = agent_config.timeframe
    secondary_tf = agent_config.secondary_tf
    interval_sec = {"1h": 3600, "4h": 14400, "1d": 86400}.get(exec_cfg.get("interval", timeframe), 3600)

    api_key, secret, passphrase = load_credentials()
    client = DemoClient(api_key, secret, passphrase)

    # ── Initialize Agent ───────────────────────────────────────────────
    agent = TradingAgent(agent_config)
    state = DaemonState()

    print("=" * 68)
    print("  ADAPTIVE TRADING AGENT — CONTINUOUS MONITORING")
    print("=" * 68)
    print(f"  Config:      {config_path}")
    print(f"  Strategy:    {strat_cfg.get('name', 'BTC SMC')}")
    print(f"  Symbol:      {symbol} @ {timeframe}" + (f" + {secondary_tf} confirmation" if secondary_tf else ""))
    print(f"  Check every: {exec_cfg.get('interval', timeframe)} ({interval_sec}s)")
    print(f"  Trade size:  {exec_cfg.get('trade_size_usdt', 100)} USDT")
    print(f"  Mode:        {'DRY-RUN (signals only)' if dry_run else 'LIVE (real orders)'}")
    print(f"  Risk limits: pos<={agent_config.max_position_pct*100:.0f}% | "
          f"exp<={agent_config.max_total_exposure_pct*100:.0f}% | "
          f"loss<={agent_config.daily_loss_circuit_breaker*100:.0f}%")
    print(f"  Agent log:   {DAEMON_LOG_PATH}")
    print("-" * 68)

    if dry_run:
        print("  DRY-RUN: Agent will run full Perception->Decision->Risk pipeline")
        print("  but skip Execution layer (no orders placed).")
        print("-" * 68)

    def shutdown(signum=None, frame=None):
        state.running = False
        print("\n  [Agent] Shutdown signal received, finishing current cycle...")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while state.running:
            state.cycle_count += 1
            now = datetime.now(timezone.utc)
            cycle_start = time.time()

            # ── Fetch market data ──────────────────────────────────────
            df_primary = client.get_candles(symbol, timeframe, limit=200)
            if len(df_primary) == 0:
                print(f"  [{now:%H:%M:%S}] Cycle #{state.cycle_count}: No market data, retry in 60s")
                if once:
                    break
                time.sleep(60)
                continue

            df_secondary = None
            if secondary_tf and secondary_tf != timeframe:
                df_secondary = client.get_candles(symbol, secondary_tf, limit=200)

            ticker = client.get_ticker(symbol)
            last_price = float(ticker.get("lastPr", df_primary.iloc[-1]["close"]))

            # ── Get account equity ─────────────────────────────────────
            try:
                account = client.get_futures_account()
                equity = float(account.get("accountEquity", 10000))
            except Exception:
                equity = 10000.0

            # ── Get current positions ──────────────────────────────────
            try:
                pos_result = client.get("/api/v2/mix/position/all-position?"
                                        "productType=USDT-FUTURES&marginCoin=USDT")
                positions = pos_result.get("data", []) or []
            except Exception:
                positions = []

            # ── Fetch sentiment (optional) ─────────────────────────────
            sentiment = None
            try:
                import urllib.request
                url = "https://api.bitget.com/api/v2/mix/market/funding-rate?" \
                      f"productType=USDT-FUTURES&symbol={symbol}"
                fr_data = json.loads(urllib.request.urlopen(url, timeout=5).read())
                funding_rate = float(fr_data.get("data", [{}])[0].get("fundingRate", 0)) \
                    if fr_data.get("data") else 0.0
                # Use funding rate and price action as proxy sentiment
                sentiment = SentimentSnapshot(
                    fear_greed_index=50,
                    fear_greed_label="neutral",
                    social_volume_change=0.0,
                    long_short_ratio=1.0 if funding_rate > 0 else 0.8,
                    taker_buy_ratio=0.5,
                )
            except Exception:
                pass

            # ── Run Agent Four-Layer Pipeline ─────────────────────────
            # This is the core: Perception → Decision → Risk → Execution
            output = agent.run(
                market_df=df_primary,
                account_equity=equity,
                current_positions=positions,
                sentiment=sentiment,
                secondary_df=df_secondary,
            )

            # ── Display Agent Output ──────────────────────────────────
            sig = output.signal
            risk = output.risk
            order = output.order
            p = output.perception.primary if output.perception else None

            cycle_header = f"[{now:%H:%M:%S}] Cycle #{state.cycle_count}"
            if p:
                cycle_header += f" | {symbol} ${last_price:,.1f}"

            if sig and sig.type.value not in ("HOLD", "NO_TRADE"):
                state.signals_generated += 1
                direction = "LONG" if "LONG" in sig.type.value else "SHORT" if "SHORT" in sig.type.value else sig.type.value
                print(f"\n  {cycle_header}")
                print(f"    [1] PERCEPTION: RSI={p.rsi:.0f} | MACD={p.macd:.2f} | "
                      f"Trend={'BULL' if output.perception.trend_bullish else 'BEAR' if output.perception.trend_bearish else 'NEUTRAL'} | "
                      f"ATR={p.atr:.1f} | Vol={'HIGH' if p.volume_surge else 'normal'}")
                print(f"    [2] DECISION:   {sig.type.value} | strategy={sig.strategy} | "
                      f"confidence={sig.confidence:.0%}")
                print(f"    [3] RISK:       {'APPROVED' if risk.approved else 'REJECTED'} | {risk.reason}")
                if risk.approved and order:
                    if dry_run:
                        print(f"    [4] EXECUTION:  [DRY-RUN] Would place {order.side.upper()} "
                              f"{order.order_type} size={order.size} trade_side={order.trade_side}")
                    else:
                        # Real order placement via DemoClient
                        order_params = order.to_api_params()
                        try:
                            api_result = client.post("/api/v2/mix/order/place-order", order_params)
                            print(f"    [4] EXECUTION:  Order placed — {api_result.get('msg')} "
                                  f"id={api_result.get('data', {}).get('orderId', 'N/A')}")
                            state.trades_placed += 1
                            # Cancel demo order immediately
                            oid = api_result.get("data", {}).get("orderId", "")
                            if oid:
                                client.cancel_order(symbol, oid)
                        except Exception as e:
                            print(f"    [4] EXECUTION:  Order FAILED — {e}")
                else:
                    print(f"    [4] EXECUTION:  Skipped (risk rejected or no order)")
            else:
                # Idle cycle — compact one-line status
                rsi_str = f"RSI={p.rsi:.0f}" if p and p.rsi else ""
                macd_str = f"MACD={p.macd:.2f}" if p and p.macd else ""
                print(f"  {cycle_header} | {sig.type.value if sig else 'IDLE'} | {rsi_str} {macd_str} | {output.narrative}")

            # ── Record pipeline output ─────────────────────────────────
            state.record_pipeline(output.to_dict() if hasattr(output, 'to_dict') else {})

            # ── Single run? ────────────────────────────────────────────
            if once:
                elapsed = time.time() - cycle_start
                print(f"\n  Single cycle complete ({elapsed:.1f}s). "
                      f"Signals: {state.signals_generated}, Trades: {state.trades_placed}")
                state._save()
                break

            # ── Wait for next cycle ────────────────────────────────────
            elapsed = time.time() - cycle_start
            sleep_time = max(1, interval_sec - elapsed)
            if sleep_time > 5:
                mins = sleep_time / 60
                print(f"    Next check in {mins:.0f}m{sleep_time%60:.0f}s | "
                      f"Running: {datetime.now(timezone.utc) - state.start_time} | "
                      f"Cycles: {state.cycle_count} | Signals: {state.signals_generated}")
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        state._save()
        # API call summary
        api_summary = client.api_logger.summary()
        runtime = datetime.now(timezone.utc) - state.start_time
        print(f"\n{'=' * 68}")
        print(f"  Agent daemon stopped.")
        print(f"  Runtime: {runtime} | Cycles: {state.cycle_count} | "
              f"Signals: {state.signals_generated} | Trades: {state.trades_placed}")
        print(f"  API calls: {api_summary['total_calls']} "
              f"(success={api_summary['success']}, failed={api_summary['failed']})")
        print(f"  Agent log: {DAEMON_LOG_PATH}")
        print(f"  API log:   output/api_calls.jsonl")
        print(f"{'=' * 68}")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive Trading Agent Daemon")
    parser.add_argument("--config", "-c", default=os.path.join(PROJECT_DIR, "config.yaml"),
                        help="Path to config YAML")
    parser.add_argument("--live", action="store_true",
                        help="Execute real orders on Bitget Demo Trading")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit")
    args = parser.parse_args()

    dry_run = not args.live

    if not dry_run:
        print("=" * 60)
        print("  WARNING: LIVE MODE — orders WILL be placed")
        print("=" * 60)
        resp = input("  Continue? (yes/no): ").strip().lower()
        if resp != "yes":
            print("  Aborted.")
            return

    run_daemon(args.config, dry_run=dry_run, once=args.once)


if __name__ == "__main__":
    main()
