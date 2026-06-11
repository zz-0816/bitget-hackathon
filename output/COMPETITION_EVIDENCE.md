# 赛道一 · 全自动策略机器人 — 完整证据包

> **比赛**: Bitget Agent Hub Hackathon Track 1
> **项目**: bitget_test
> **提交时间**: 2026-06-11
> **Git 分支**: master
> **最新提交**: `6d101e3` feat: 权限预配置 + 策略工厂 + API审计 + 一键启动 + 项目清理 + 文档重写

---

## 一、架构总览

```
用户 NL 策略描述
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  Claude Code (编排器 / 运行时)                            │
│                                                         │
│  [每轮循环]                                              │
│    ├─ 并行调用 4 个 Skills (MCP tools):                   │
│    │   ├─ crypto_derivatives  → OHLCV K线数据             │
│    │   ├─ sentiment_index     → 恐惧贪婪指数               │
│    │   ├─ derivatives_sentiment → 多空比 / OI             │
│    │   ├─ rates_yields        → 宏观利率 / 利差            │
│    │   └─ news_feed           → 加密新闻                   │
│    │                                                     │
│    ├─ Python 指标计算 (numpy):                            │
│    │   EMA12/26/20/50 + MACD(DIF/DEA/HIST)               │
│    │   + RSI14 + ATR14 + BB(20,2) + ADX14                │
│    │                                                     │
│    ├─ agent/auto_cycle.py::run_cycle()                   │
│    │   ├─ parse_strategy()     → NL解析                   │
│    │   ├─ evaluate_strategy()  → 5条件加权检查              │
│    │   ├─ estimate_trade_metrics() → 入场/SL/TP/仓位       │
│    │   ├─ DemoClient           → 下单/查询/取消 (沙盒)      │
│    │   ├─ evaluate_exit_conditions() → 7维退出检查          │
│    │   └─ generate_trade_summary() → P&L + 评级 A-F       │
│    │                                                     │
│    └─ 状态持久化 → output/auto_trade_state.json            │
└─────────────────────────────────────────────────────────┘
```

### 四大核心设计原则

| 原则 | 实现 |
|------|------|
| **Skills 驱动** | 4 个 Skills 并行调用，数据来源多元交叉验证 |
| **Claude Code 编排** | 只有 Claude Code 可调用 MCP 工具 → Claude Code 是运行时 |
| **双层评估** | 入场前 5 条件加权 + 情绪/宏观/新闻三重过滤 |
| **全生命周期** | NL→解析→评估→入场→SL/TP→监控→退出→P&L→评级 |

---

## 二、Skills 四维交叉验证 (本次会话)

### 技术面 (crypto_derivatives + Python 指标计算)

| 指标 | 最新值 | 信号 |
|------|--------|------|
| BTC价格 | $63,040 | — |
| EMA12/26 | 62963.7 / 62899.7 | **金叉** (EMA12 > EMA26) |
| EMA20/50 | 62937.1 / 62724.9 | 多头排列 |
| MACD (DIF/DEA/HIST) | 64.02 / 92.75 / -57.46 | **空头** (DIF < DEA), 柱状图收窄 |
| RSI(14) | 55.16 | 中性偏强 |
| ADX(14) | 38.57 | 趋势市 (>25) |
| ATR(14) | 240.86 | 波动率 ~0.38% |
| BB(20,2) | 上轨 63247 / 中轨 62974 / 下轨 62702 | 价格在中轨上方 |
| 成交量 | 放量 (1.5x 均量) | 异常活跃 |

### 情绪面 (sentiment_index + derivatives_sentiment)

| 指标 | 值 | 解读 |
|------|-----|------|
| 恐惧贪婪指数 | **12/100** | 极度恐惧 |
| 多空比 | **1.71** | 偏多, 但从 2.18 持续下降 |
| 多空比趋势 | 下降中 | 空头在增加 |

### 宏观面 (rates_yields)

| 指标 | 值 |
|------|-----|
| 联邦基金利率上限 | 3.75% |
| 10Y 国债收益率 | 4.53% |
| 10Y-2Y 利差 | +0.42% (正利差, 未倒挂) |
| 高收益债信用利差 | 2.80% |
| 宏观评级 | **谨慎** (Risk-Cautious) |

### 消息面 (news_feed: CoinDesk + Decrypt + CoinTelegraph)

| 事件 | 影响 |
|------|------|
| BTC ETF 6月净流出 $21亿 | 利空 |
| 伊朗关闭霍尔木兹海峡 | 地缘风险 |
| 日本加密 ETF 法案推进 | 利好 |
| Tether 领投 $14亿机器人公司 | 中性/利好 |
| 匈牙利撤销加密交易限制 | 利好 |

**消息面综合**: 偏空 (ETF 流出 + 地缘风险主导)

---

## 三、策略评估引擎

### NL 解析

```
输入: "BTCUSDT 15min趋势跟随 EMA金叉进场 MACD上涨确认 做多 止损1%止盈2%"
解析:
  symbol: BTCUSDT
  timeframe: 15min
  direction: long
  template: trend_following
  sl_pct: 1.0%
  tp_pct: 2.0%
  position_pct: 2.0%
```

### 5 条件加权检查 (trend_following 模板)

| # | 检查项 | 权重 | 期望 | 实际 | 本轮结果 |
|---|--------|------|------|------|---------|
| 1 | EMA Golden Cross (12/26) | 25% | EMA12 > EMA26 | EMA12=62963.7 EMA26=62899.7 | PASS |
| 2 | MACD Direction | 25% | DIF > DEA | DIF=64.0 DEA=92.8 | **FAIL** |
| 3 | ADX Trending | 20% | ADX > 25 | ADX=38.6 | PASS |
| 4 | RSI Zone | 15% | 30 < RSI < 70 | RSI=55.2 | PASS |
| 5 | Price vs EMA20 | 15% | Close > EMA20 | Close=63040 EMA20=62937 | PASS |

**本轮**: 4/5 通过, 置信度 56% (<60% 不交易)

### 情绪/宏观/新闻过滤

| 过滤器 | 状态 | 影响 |
|--------|------|------|
| 极度恐惧 (12/100) | 触发警告 | 做多信号打折, 置信度 -10% |
| 宏观 Risk-Cautious | 无警告 | — |
| ETF 流出 + 地缘风险 | 触发警告 | 做多信号打折 |

---

## 四、自主循环运行记录

### 状态文件 (`output/auto_trade_state.json`)

```json
{
  "strategy_text": "BTCUSDT 15min趋势跟随 EMA金叉进场 MACD上涨确认 做多 止损1%止盈2%",
  "parsed_symbol": "BTCUSDT",
  "parsed_timeframe": "15min",
  "parsed_direction": "long",
  "parsed_template": "trend_following",
  "parsed_sl_pct": 1.0,
  "parsed_tp_pct": 2.0,
  "parsed_position_pct": 2.0,
  "in_position": false,
  "cycle_count": 7,
  "trades_completed": 0,
  "total_pnl": 0.0,
  "trade_history": []
}
```

### 每轮循环记录

| 周期 | 时间 | 价格 | EMA | MACD | RSI | 通过 | 置信度 | 信号 |
|------|------|------|-----|------|-----|------|--------|------|
| #1-5 | 09:34-14:30 | ~62,800-63,000 | GOLDEN | BEAR | ~53 | 4/5 | 56% | NO_TRADE |
| #6 | 14:31 | 63,040 | GOLDEN | BEAR | 55 | 4/5 | 56% | NO_TRADE |
| #7 | 14:31 | 63,040 | GOLDEN | BEAR | 55 | 4/5 | 56% | NO_TRADE |

**全程风控合规**: 7 轮循环, MACD 未翻多 → 0 次误入场, 风控逻辑正确过滤了不成熟的信号。

---

## 五、Bitget Demo Trading API 调用审计

### API 调用摘要 (`output/api_calls.jsonl`)

| 统计项 | 数值 |
|--------|------|
| 总 API 调用 | **29 次** |
| 成功 | 29 (100%) |
| 失败 | 0 |
| 环境 | Bitget Demo Trading (paptrading: 1) |
| 端点 | `api.bitget.com` |

### API 调用明细

| 类型 | 次数 | 说明 |
|------|------|------|
| GET /account/accounts | 7 | 账户余额查询 |
| POST /order/place-order | 5 | 限价单下单测试 |
| GET /orders-pending | 9 | 挂单查询 |
| POST /cancel-order | 4 | 订单取消测试 |
| GET /all-position | 4 | 持仓查询 |

### 订单生命周期验证

每次测试完整链路: **下单 → 查询确认 → 取消 → 确认取消**

```
Place Order (id=1448892798144249857, price=31407.7)  →  [OK]
Query Pending (status=live, side=buy)                 →  [OK]
Cancel Order (orderId=1448892798144249857)             →  [OK]
Query Pending (entrustedList=None)                     →  [OK, fully cancelled]
```

### 账户状态

```
Futures Equity: 9,998.92 USDT
Total Equity:   29,998.92 USDT (含现货)
Open Positions: 0
Margin Mode:    cross
Position Mode:  hedge_mode
```

---

## 六、策略回测记录

### 回测范围 (`output/trade_log.json`)

| 统计项 | 数值 |
|--------|------|
| 交易总数 | **39 笔** |
| 策略变体 | **8 个** |
| 交易品种 | BTCUSDT + DOGEUSDT |
| 覆盖周期 | 1D + 4H + 1H |

### 策略变体 (8个)

| 策略 | 品种 | 方向 | 周期 |
|------|------|------|------|
| BTC SMC Long | BTCUSDT | 做多 | 1D |
| BTC SMC Long | BTCUSDT | 做多 | 4H |
| BTC SMC Short | BTCUSDT | 做空 | 1D |
| BTC SMC Short | BTCUSDT | 做空 | 4H |
| DOGE Momentum Long | DOGEUSDT | 做多 | 1D |
| DOGE Momentum Long | DOGEUSDT | 做多 | 1H |
| DOGE Momentum Short | DOGEUSDT | 做空 | 1D |
| DOGE Momentum Short | DOGEUSDT | 做空 | 1H |

### 回测性能摘要

| 品种 | 方向 | 周期 | 交易笔数 | 胜率 | 平均盈亏% |
|------|------|------|---------|------|---------|
| BTC | Long | 1D | 10 | 30% | -0.33% |
| BTC | Long | 4H | 3 | 33% | -0.56% |
| BTC | Short | 1D | 13 | 46% | +1.39% |
| BTC | Short | 4H | 4 | 75% | +4.43% |
| DOGE | Long | 1D | 4 | 0% | -2.94% |
| DOGE | Long | 1H | 2 | 0% | -0.56% |
| DOGE | Short | 1D | 2 | 50% | +3.54% |
| DOGE | Short | 1H | 1 | 0% | -1.58% |

### 退出原因分布

| 原因 | 次数 | 占比 |
|------|------|------|
| EMA20_Break | 16 | 41% |
| RSI_BearDiv/BullDiv | 7 | 18% |
| TrendDeath | 7 | 18% |
| TakeProfit | 4 | 10% |
| StopLoss | 3 | 8% |
| VolClimax+Wick | 2 | 5% |

---

## 七、Demo Trading 完整验证 (`output/demo_trading_log.json`)

### 验证摘要

```
数据管道: Bitget Futures API → 本地指标计算 → 信号生成 → 风控过滤 → 订单执行
所有层级已测试: true
订单已布下并取消: true
交易记录不可篡改: true
```

### 策略信号 (4H + 1D 双周期)

| 周期 | 方向 | 置信度 | 三重确认 |
|------|------|--------|---------|
| 4H | watch (观望) | 0% | EMA未对齐 |
| 1D | **short (做空)** | 75% | EMA+RSI+MACD+ADX 全部确认 |

### 风控验证

| 检查层 | 结果 |
|--------|------|
| 仓位限制 (2.0%) | PASS |
| 风险敞口 (30.0%) | PASS |
| 熔断 (日亏5%) | PASS |
| 盈亏比 (≥1.5:1) | **REJECTED** (RR=1.50:1) |

---

## 八、代码模块清单

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `agent/auto_cycle.py` | 550 | 自主循环核心引擎: run_cycle(), compute_indicators_from_ohlcv(), build_market_snapshot_from_json(), CycleState |
| `run_cycle_once.py` | 50 | 单次循环启动器 (供 Claude Code 调用) |
| `output/COMPETITION_EVIDENCE.md` | — | 本证据文件 |

### 修改文件 (本轮)

| 文件 | 修改内容 |
|------|---------|
| `agent/market_snapshot.py` | +ema_12, ema_26 字段 (支持金叉检测) |
| `agent/strategy_executor.py` | EMA20>EMA50 → EMA12>EMA26 金叉逻辑 |
| `agent/__init__.py` | +auto_cycle 模块导出 |
| `run.py` | +ema_12, ema_26 数据加载 |

### 完整 Agent 模块 (13 文件)

```
agent/
  __init__.py          — 模块导出
  config.py            — Agent 配置
  agent.py             — 四层闭环 Agent (Perception→Decision→Risk→Execution)
  perception.py        — 市场感知 (MarketData/Sentiment/Macro/News)
  decision.py          — 决策引擎 (Signal/SignalType)
  execution.py         — 执行引擎 (Order)
  risk.py              — 风控管理 (RiskManager)
  strategy_factory.py  — 自然语言策略解析 (parse_strategy)
  strategy_executor.py — 策略评估 + 退出条件 + P&L (evaluate_strategy/exit)
  market_snapshot.py   — 市场快照 (TechnicalSnapshot/SentimentSnapshot/...)
  position_monitor.py  — 持仓监控 (PositionMonitor/MonitorState)
  auto_cycle.py        — 自主循环引擎 (NEW)
  api_logger.py        — API 调用审计
```

---

## 九、数据文件

| 文件 | 内容 |
|------|------|
| `data/btc_15min_latest.json` | 100根15min OHLCV (实时更新) |
| `data/btc_4h_bitget.json` | BTC 4H Bitget 历史数据 |
| `data/btc_1d_bitget.json` | BTC 1D Bitget 历史数据 |
| `data/doge_1h_bitget.json` | DOGE 1H Bitget 历史数据 |
| `data/doge_1d_bitget.json` | DOGE 1D Bitget 历史数据 |
| `data/market_snapshot_latest.json` | 最新四维市场快照 |
| `output/auto_trade_state.json` | 持久化循环状态 |
| `output/api_calls.jsonl` | API 调用完整审计日志 |
| `output/trade_log.json` | 39笔回测交易记录 |
| `output/demo_trading_log.json` | Demo Trading 完整验证报告 |
| `output/strategy_eval_report.json` | 策略评估结果 |

---

## 十、赛道一评分标准对照

| 评分维度 | 本项目实现 | 证据 |
|---------|-----------|------|
| **自主性** | 全自动 NL→执行→监控→退出 闭环, 0人工干预 | auto_cycle.py + 7轮循环 |
| **多维数据** | 4 Skills 交叉验证 (技术+情绪+宏观+消息) | Section 二 |
| **策略评估** | 5条件加权检查 + 3重过滤器 | Section 三 |
| **DEMO可运行** | Bitget Demo Trading 沙盒, 29次API调用100%成功 | Section 五 + api_calls.jsonl |
| **风控** | 四层过滤 + 熔断 + 盈亏比 + SL/TP 自动部署 | Section 七 |
| **回测** | 39笔历史交易, 8策略变体 | Section 六 + trade_log.json |
| **可审计** | 全链路 API 日志 (jsonl) + 状态持久化 | api_calls.jsonl + auto_trade_state.json |
| **架构** | Claude Code 编排 + Skills 数据 + Python 引擎 + DemoClient 执行 | Section 一 |

---

## 十一、循环运行日志示例

```
[14:31:57] CYCLE #6 | $63,040.0 | EMA=GOLDEN | MACD=BEAR | RSI=55
[PASS] EMA Golden Cross (12/26): EMA12=62963.7 EMA26=62899.7
[FAIL] MACD Direction: DIF=64.0200 DEA=92.7500
[PASS] ADX Trending: ADX=38.6
[PASS] RSI Zone: RSI=55.2
[PASS] Price vs EMA20: Close=63040.0 EMA20=62937.1
[!] 恐惧贪婪指数=12/100 (极度恐惧)，做多信号打折
[NO TRADE] 4/5 passed (confidence=56%, need >=60%)
[REASON] 通过: EMA Golden Cross (12/26), ADX Trending, RSI Zone, Price vs EMA20
         未通过: MACD Direction
```

---

> **结论**: 本项目实现了完整的 NL策略 → 四维交叉验证 → 自主循环 → 自动执行 → 持续监控 → 自动退出 → P&L评级的全自动交易Agent闭环。所有模块可在 Bitget Demo Trading 沙盒环境直接运行，API调用100%成功，风控逻辑正确过滤了不成熟信号。
