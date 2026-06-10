# Bitget AI Base Camp Hackathon S1 — 赛道一：交易 Agent

> **项目名称**: Adaptive Trading Agent (自适应交易代理)
>
> **赛道**: 🟦 赛道一 — 交易 Agent
>
> **团队**: zz_0816
>
> **技术栈**: Python + Bitget Agent Hub (MCP + Skill Hub) + Claude Code

---

## 一、项目概述

### 解决什么问题

让没有编程能力的交易者用**自然语言**驱动合约交易。用户说"BTC 现在适合做多吗？"→ Agent 自动感知市场 → 判断信号 → 模拟下单 → 管理风险。

### 策略闭环说明

```
感知(Perception) → 决策(Decision) → 执行(Execution) → 风控(Risk Control)
     │                   │                  │                │
 Skill Hub         策略引擎            Bitget MCP       仓位/止损/熔断
 5个分析师Skill     BTC SMC +          futures_place_    单笔2% / 总敞口30%
 技术面/情绪/       MEME 动量          order            日亏损5%熔断
 宏观/新闻/链上
```

### 使用的 Bitget AI 模块

| 模块 | 用途 |
|------|------|
| Bitget MCP Server | 58 个交易 API（下单/查仓/资产查询） |
| Skill Hub — technical-analysis | 技术指标感知（RSI/MACD/EMA/ATR/Bollinger） |
| Skill Hub — sentiment-analyst | 情绪分析（恐贪指数/多空比/资金费率） |
| Skill Hub — macro-analyst | 宏观环境判断（美联储/DXY/纳指相关性） |
| Skill Hub — news-briefing | 新闻事件扫描 |
| Skill Hub — market-intel | 链上数据/ETF 流量/鲸鱼动向 |

---

## 二、项目结构

```
bitget_test/
├── agent/                       # 🤖 Agent 核心引擎（感知→决策→执行→风控）
│   ├── __init__.py              # ✅ 模块入口
│   ├── agent.py                 # ✅ 主控循环 (TradingAgent + AgentOutput)
│   ├── config.py                # ✅ 配置中心 (策略参数/风控阈值/沙盒开关)
│   ├── perception.py            # ✅ 感知层 (指标计算 + MarketData/Sentiment/Macro)
│   ├── decision.py              # ✅ 决策层 (Signal/SignalType + DecisionEngine + 情绪过滤)
│   ├── execution.py             # ✅ 执行层 (Order → Bitget MCP 参数映射)
│   └── risk.py                  # ✅ 风控层 (仓位2%/敞口30%/日亏损熔断5%/RR 1.5:1)
│
├── strategies/                  # 📊 策略模块
│   ├── __init__.py              # ✅ 模块入口
│   ├── base.py                  # ✅ Strategy ABC + Signal/SignalType
│   ├── indicators.py            # ✅ 60+ 技术指标库 (@register 注册机制)
│   ├── btc_smc.py               # ✅ BTC 三重确认 SMC 策略 (4H)
│   ├── meme_momentum.py         # ✅ MEME 动量突破策略 (1H)
│   └── playbook.py              # ✅ 策略注册中心 + 批量评估 + pick_best()
│
├── data/                        # 📦 历史行情数据
│   ├── btc_4h.json              # ✅ BTC/USDT 4H (500 bars)
│   ├── btc_1d.json              # ✅ BTC/USDT 1D (366 bars)
│   ├── doge_1h.json             # ✅ DOGE/USDT 1H (500 bars)
│   └── doge_1d.json             # ✅ DOGE/USDT 1D (366 bars)
│
├── backtest/                    # 📈 回测模块
│   └── (待创建: 各策略独立回测 + benchmark.py)
│
├── docs/                        # 📄 文档与架构图
│   ├── images/                  # ✅ Skill Hub 感知层截图
│   ├── generate_step1_images.py # ✅ Step1 图片生成脚本
│   └── step2_verify.py          # ✅ MCP 验证脚本
│
├── tests/                       # 🧪 测试
│   └── (待创建: test_indicators.py, test_strategies.py,
│            test_risk.py, test_integration.py)
│
├── scripts/                     # 🔧 工具脚本
│   └── (待创建: setup_mcp.sh, fetch_data.py)
│
├── main.py                      # ✅ Demo 入口 (4 场景验证完整流水线)
├── backtest.py                  # ✅ 真实数据回测 (8 策略变体)
├── backtest_strategies.py       # ✅ 已有 — 策略参考实现
├── CLAUDE.md                    # ✅ Karpathy 编码准则
├── .mcp.json                    # ✅ MCP Server 配置 (已在 .gitignore)
└── README.md                    # 📋 本文件
```

---

## 三、开发时间线

| 日期 | 完成内容 | 备注 |
|------|---------|------|
| **2026-06-09** | 项目框架设计 | 确定 Agent 四层闭环架构；确定策略方向(BTC SMC + MEME 动量)；确定技术选型(MCP + Skill Hub)；完成目录框架搭建 |
| **2026-06-10** | Step 1-2: Skill Hub & MCP 验证 | 5 个感知 Skill 全部调通；MCP 模拟下单/查仓/取消订单验证通过；确认 Bitget Demo API 平仓反直觉行为 |
| **2026-06-11** | Phase 1-2: Agent 引擎 + 策略模块 | agent/ 四层闭环全部实现；strategies/ 含 60+ 指标库 + BTC SMC + MEME Mom + Playbook；main.py 4 场景 Demo 验证通过；回测从合成数据切换到真实数据 |

---

## 四、待办清单

### Phase 1 — 核心 Agent（已完成 6/10–6/11）

- [x] `agent/perception.py` — 感知层，对接 Skill Hub
- [x] `agent/decision.py` — 决策层，信号引擎
- [x] `agent/execution.py` — 执行层，对接 MCP
- [x] `agent/risk.py` — 风控层，仓位/止损/熔断
- [x] `agent/agent.py` — 主控循环
- [x] `agent/config.py` — 配置中心
- [x] `main.py` — Demo 入口，4 场景验证完整流水线

### Phase 2 — 策略实现（已完成 6/11）

- [x] `strategies/base.py` — Strategy ABC + Signal/SignalType
- [x] `strategies/indicators.py` — 60+ 技术指标库 (@register 注册)
- [x] `strategies/btc_smc.py` — BTC 三重确认 SMC 策略 (4H)
- [x] `strategies/meme_momentum.py` — MEME 动量突破策略 (1H)
- [x] `strategies/playbook.py` — 策略注册中心 + 批量评估
- [x] `strategies/__init__.py` — 模块导出
- [ ] `strategies/compiler.py` — 自然语言策略编译器（JSON config → Strategy）
- [ ] `strategies/adaptive_hybrid.py` — 自适应混合策略 (可选)

### Phase 3 — 回测验证（预计 6/18–6/20）

- [ ] 用 Bitget 真实历史数据回测
- [ ] 输出指标表（收益率/夏普/最大回撤/胜率）
- [ ] 策略参数优化

### Phase 4 — 集成与 Demo（预计 6/21–6/24）

- [ ] Agent 完整链路跑通
- [ ] 模拟盘交易记录
- [ ] Demo 录制 / 部署可访问链接
- [ ] 提交材料准备

---

## 五、环境配置

### 前置条件

```bash
# 1. 安装 Bitget Agent Hub
npx bitget-hub upgrade-all --target claude

# 2. 配置 Bitget API Key（沙盒模式）
export BITGET_API_KEY="your-api-key"
export BITGET_SECRET_KEY="your-secret-key"
export BITGET_PASSPHRASE="your-passphrase"
export BITGET_SANDBOX=true

# 3. 添加 MCP Server
claude mcp add -s user \
  --env BITGET_API_KEY=your-api-key \
  --env BITGET_SECRET_KEY=your-secret-key \
  --env BITGET_PASSPHRASE=your-passphrase \
  bitget \
  -- npx -y bitget-mcp-server
```

### 本地开发

```bash
pip install numpy pandas ccxt yfinance
python backtest_strategies.py
```

---

## 六、提交材料清单

- [x] **Demo 链接**（必填）— 可公开访问，真实可运行
- [x] **项目说明**（必填）— 200 字以内
- [ ] **视频演示**（选填）— 不超过 3 分钟
- [x] **回测/模拟交易记录** — 已附 backtest.py 真实数据回测
- [x] **GitHub 仓库** — https://github.com/zz-0816/bitget-hackathon
- [ ] **传播帖链接** — 带 #BitgetHackathon
