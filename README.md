# 全自动策略交易 Agent

> **Bitget AI Base Camp Hackathon S1 — 赛道一：交易 Agent**
>
> 团队: zz_0816 | 技术栈: Python + Claude Code + Bitget Agent Hub Skills

---

## 一、解决了谁的问题

**目标用户：加密货币散户交易者。**

核心痛点：追涨杀跌、凭感觉操作、无系统风控。

本项目用一个**全自动策略 Agent** 替代散户的主观判断：

```
你的角色: 用自然语言描述策略（1 分钟）

Agent 的角色（全自动）:
  NL 策略解析   → 识别 symbol/timeframe/template/参数
  4 Skill 验证   → 技术面 + 情绪面 + 宏观面 + 消息面 交叉验证
  5 条件评估     → EMA金叉 + MACD方向 + ADX趋势 + RSI区间 + 价格vs均线
  风控过滤       → 情绪极端/宏观风险/重大事件 三重过滤
  自动执行       → Demo Trading 入场 + SL/TP 计划委托
  持续监控       → 7 维退出条件检查, 触发自动平仓
  P&L 总结       → 自动生成交易总结 + A-F 评级
```

---

## 二、评委快速上手

### 1. 配置 API Key（1 分钟）

```bash
cp .mcp.json.example .mcp.json
# 编辑 .mcp.json，填入 Bitget Demo Trading API Key（沙盒模式，Read + Trade 权限）
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 开始使用（在 Claude Code 中直接用中文对话）

**无需 CLI，直接对话即可操作：**

| 你说什么 | Agent 做什么 |
|---------|------------|
| "帮我做一个 BTC 4H 趋势跟随策略" | 完整流程：解析→验证→审核报告→Playbook |
| "检查一下当前 BTC" | 四维交叉审核（不创建策略，只输出报告） |
| "启动持续监控 BTC 15min 趋势做多" | 后台启动自主循环，每 15 分钟检查一次 |
| "当前持仓怎么样" | 查询 Bitget Demo Trading 持仓状态 |
| "回测一下这个策略" | 运行 backtest benchmark 输出对比结果 |

支持的策略描述示例：
- `"BTCUSDT 15min趋势跟随 EMA金叉进场 MACD上涨确认 做多 止损1%止盈2%"`
- `"DOGE 1H动量突破 RSI在55-65之间 做多"`
- `"ETH震荡策略 布林带下轨买入上轨卖出"`

---

## 三、核心技术架构

```
Claude Code (编排器/运行时)
  │
  ├─ [每轮循环] 并行调用 4 个 Skills (MCP tools):
  │   ├─ crypto_derivatives     → OHLCV K线数据
  │   ├─ sentiment_index        → 恐惧贪婪指数
  │   ├─ derivatives_sentiment  → 多空比 / OI
  │   ├─ rates_yields           → 宏观利率 / 利差
  │   └─ news_feed              → 加密新闻
  │
  ├─ [指标计算] agent/auto_cycle.py::compute_indicators_from_ohlcv()
  │   EMA12/26/20/50 + MACD(DIF/DEA/HIST) + RSI14 + ATR14 + BB(20,2) + ADX14
  │
  ├─ [策略评估] agent/strategy_executor.py::evaluate_strategy()
  │   5 条件加权检查 + 情绪/宏观/新闻三重过滤
  │
  ├─ [交易执行] DemoClient → Bitget Demo Trading Sandbox
  │   入场限价单 + SL/TP 计划委托 (自动部署)
  │
  ├─ [持仓监控] agent/strategy_executor.py::evaluate_exit_conditions()
  │   7 维退出检查 → 触发自动平仓 → P&L + A-F 评级
  │
  └─ [状态持久化] output/auto_trade_state.json
      position / cycles / PnL / trade_history
```

### 为什么用 Claude Code 作为编排器？

Skills（MCP 市场数据工具）**只能由 Claude Code 调用**，独立 Python 进程无法访问。因此 Claude Code 是运行时，Python 模块（`agent/auto_cycle.py`）是计算引擎——Claude Code 取数据，Python 算指标 + 评估 + 执行。

---

## 四、策略评估引擎

### 5 条件加权检查（trend_following 模板）

| # | 检查项 | 权重 | 说明 |
|---|--------|------|------|
| 1 | EMA Golden Cross (12/26) | 25% | EMA12 > EMA26 金叉确认 |
| 2 | MACD Direction | 25% | DIF > DEA 多头排列 |
| 3 | ADX Trending | 20% | ADX > 25 趋势市确认 |
| 4 | RSI Zone | 15% | 30 < RSI < 70 非极端区间 |
| 5 | Price vs EMA20 | 15% | 价格 > EMA20 短期趋势确认 |

### 三重过滤器

| 过滤器 | 数据来源 | 规则 |
|--------|---------|------|
| 情绪过滤 | 恐惧贪婪指数 + 多空比 | FG < 25 做多信号打折; LS ratio 趋势反转警告 |
| 宏观过滤 | 利率 + 利差 + 信用利差 | Risk-Off 时做多信号打折; 收益率曲线倒挂警告 |
| 新闻过滤 | CoinDesk/Decrypt/CoinTelegraph | 重大地缘/监管事件 → 降低置信度 |

### 7 维退出条件

| 退出条件 | 触发规则 |
|---------|---------|
| SL 触及 | 价格触及止损位 |
| TP 触及 | 价格触及止盈位 |
| EMA 破坏 | EMA12 < EMA26（金叉转为死叉） |
| MACD 翻转 | DIF < DEA（多头转空头） |
| RSI 极端 | RSI > 85（超买退出） |
| 时间止损 | 持仓超过 N 根 K 线未盈利 |
| 拖尾止损 | 盈利后 ATR 动态止损 |

---

## 五、可核查证据

### 交易与审计记录（`output/`）

| 文件 | 内容 |
|------|------|
| `api_calls.jsonl` | 全链路 API 调用审计（29 次, 100% 成功） |
| `trade_log.json` | 39 笔回测交易（8 策略变体） |
| `demo_trading_log.json` | Demo Trading 实盘验证（7 阶段完整链路） |
| `auto_trade_state.json` | 自主循环状态持久化 |
| `strategy_eval_report.json` | 策略评估结果 + 风控过滤详情 |
| `COMPETITION_EVIDENCE.md` | 赛道一完整证据包 |

### 回测指标摘要（39 笔交易, 8 策略变体）

| 策略 | 品种 | 方向 | 周期 | 胜率 | 平均盈亏% |
|------|------|------|------|------|---------|
| BTC SMC | BTCUSDT | Long | 1D | 30% | -0.33% |
| BTC SMC | BTCUSDT | Short | 1D | 46% | +1.39% |
| BTC SMC | BTCUSDT | Short | 4H | 75% | +4.43% |
| DOGE Mom | DOGEUSDT | Short | 1D | 50% | +3.54% |

---

## 六、项目结构

```
bitget_test/
├── agent/                          # Agent 核心引擎 (15 文件)
│   ├── auto_cycle.py               # ★ 自主循环引擎 (run_cycle + 指标计算)
│   ├── strategy_executor.py        # ★ 策略评估 + 退出条件 + P&L 评级
│   ├── strategy_factory.py         # NL 策略解析 → 结构化配置
│   ├── claude_cycle.py             # Claude Code 编排单次循环入口 + 证据链
│   ├── bitget_mcp_server.py        # Python MCP Server (Bitget API)
│   ├── market_snapshot.py          # 市场快照（技术/情绪/宏观/新闻）
│   ├── position_monitor.py         # 持仓监控 + 状态管理
│   ├── agent.py                    # 四层闭环 TradingAgent
│   ├── perception.py               # 感知层 (MarketData/Sentiment/Macro)
│   ├── decision.py                 # 决策引擎 (Signal/SignalType)
│   ├── execution.py                # 执行引擎 (Order)
│   ├── risk.py                     # 风控引擎 (RiskManager)
│   ├── config.py                   # Agent 配置
│   └── api_logger.py               # API 调用审计日志
├── strategies/                     # 策略模块
│   ├── btc_smc.py                  # BTC SMC 三重确认策略
│   ├── meme_momentum.py            # MEME 动量突破策略
│   ├── indicators.py               # 60+ 技术指标库
│   └── playbook.py                 # 策略注册中心
├── backtest/                       # 回测模块
│   ├── btc_smc_backtest.py         # BTC SMC 独立回测
│   ├── meme_momentum_backtest.py   # MEME 独立回测
│   └── benchmark.py                # 多策略横向对比
├── data/                           # 行情数据
│   ├── btc_15min_latest.json       # BTC 15min 实时 OHLCV
│   ├── btc_1d_bitget.json          # BTC 1D Bitget 数据
│   ├── btc_4h_bitget.json          # BTC 4H Bitget 数据
│   ├── doge_1h_bitget.json         # DOGE 1H Bitget 数据
│   ├── doge_1d_bitget.json         # DOGE 1D Bitget 数据
│   └── market_snapshot_latest.json # 最新四维市场快照
├── output/                         # ★ 交易记录 + 证据
│   ├── api_calls.jsonl             # API 审计日志 (91 calls)
│   ├── cycle_evidence.jsonl        # 循环证据链 (17 records)
│   ├── trade_log.json              # 回测交易记录 (39 trades)
│   ├── demo_trading_log.json       # Demo Trading 日志
│   ├── auto_trade_state.json       # 循环状态持久化 (36 cycles)
│   ├── strategy_eval_report.json   # 策略评估报告
│   ├── COMPETITION_EVIDENCE.md     # ★ 完整证据包
│   └── playbook_generated/         # 自动生成 Playbook
├── presets/                        # 策略预设模板
│   ├── btc_trend_following.yaml
│   ├── conservative.yaml
│   └── meme_breakout.yaml
├── run_cycle_once.py               # 单轮循环启动器
├── run.py                          # CLI 功能入口
├── demo_trading_test.py            # DemoClient (Bitget 沙盒)
├── config.yaml                     # 用户配置（改参数不写代码）
├── CLAUDE.md                       # Agent 角色定义 + 行为准则
└── requirements.txt                # Python 依赖
```

---

## 七、提交材料清单（赛道一要求对照）

### 必填材料

| # | 要求 | 状态 | 链接/文件 |
|---|------|------|----------|
| 1 | **GitHub 仓库** (Public + README) | ✅ | [github.com/zz-0816/bitget-hackathon](https://github.com/zz-0816/bitget-hackathon) |
| 2 | **Paper Trading 日志** | ✅ | [`output/PAPER_TRADING_LOG.md`](output/PAPER_TRADING_LOG.md) — 含时间戳、交易对、方向、价格、数量、账户余额变化 |
| 3 | **实盘/模拟交易记录** | ✅ | [`output/api_calls.jsonl`](output/api_calls.jsonl) (119 次 API 审计) + [`output/cycle_evidence.jsonl`](output/cycle_evidence.jsonl) (17 条循环证据) |

### 补充材料

| # | 要求 | 状态 | 链接/文件 |
|---|------|------|----------|
| 4 | **回测报告** (附生成代码) | ✅ | [`output/trade_log.json`](output/trade_log.json) (39 笔) + [`backtest/`](backtest/) (生成代码) |
| 5 | **演示视频** (≤3min) | ⬜ | 暂未录制 (项目可直接对话操作，无需登录) |

### 证据索引

```
output/
├── PAPER_TRADING_LOG.md          ★ 提交用 Paper Trading 日志 (含完整交易明细+账户变动)
├── COMPETITION_EVIDENCE.md       ★ 完整证据包 (架构/策略/循环/风控/评分对照)
├── api_calls.jsonl               ★ 119 次 Bitget API 调用审计 (JSONL 格式)
├── cycle_evidence.jsonl          ★ 17 条自主循环证据 (含市场快照+指标+决策)
├── auto_trade_state.json            持久化循环状态 (36 轮, 1 笔交易)
├── trade_log.json                   39 笔回测交易记录 (8 策略变体)
├── demo_trading_log.json            Demo Trading 验证 (7 阶段完整链路)
├── strategy_eval_report.json        策略评估报告
├── daemon_log.json                  Daemon 模式运行日志
└── playbook_generated/             自动生成策略 Playbook
```

### 评分方向自查

| 方向 | 本项目 |
|------|--------|
| **思路深度** | 散户追涨杀跌痛点 → 全自动策略 Agent; NL→4 Skills 交叉验证→5条件加权→3重过滤器→7维退出, 核心假设成立 |
| **可运行性** | `pip install -r requirements.txt` 后在 Claude Code 中直接对话操作; Demo Trading 沙盒 119 次 API 调用验证 |
| **完成度** | MVP 完整跑通: NL 策略 → 36 轮自主循环 → 1 笔完整交易 (入场→监控→风控退出→P&L 评级); 诚实描述完成度 |
| **新颖性** | Claude Code 作为 AI Agent 编排器 (非传统脚本调度); 只有 AI Agent 才能自然语言→自动执行的闭环 |
