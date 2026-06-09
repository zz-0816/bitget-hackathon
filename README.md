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
│   └── (待创建: agent.py, config.py, perception.py,
│            decision.py, execution.py, risk.py)
│
├── strategies/                  # 📊 策略模块
│   └── (待创建: btc_smc.py, meme_momentum.py,
│            adaptive_hybrid.py)
│
├── backtest/                    # 📈 回测模块
│   └── (待创建: 各策略独立回测 + benchmark.py)
│
├── docs/                        # 📄 文档
│   └── (待创建: architecture.md, submission.md,
│            demo_script.md)
│
├── tests/                       # 🧪 测试
│   └── (待创建: test_indicators.py, test_strategies.py,
│            test_risk.py, test_integration.py)
│
├── scripts/                     # 🔧 工具脚本
│   └── (待创建: setup_mcp.sh, fetch_data.py)
│
├── backtest.py                  # ✅ 已有 — 合成数据回测
├── backtest_strategies.py       # ✅ 已有 — 真实数据回测
├── .mcp.json                    # ✅ 已有 — MCP Server 配置
└── README.md                    # 📋 本文件
```

---

## 三、开发时间线

| 日期 | 完成内容 | 备注 |
|------|---------|------|
| **2026-06-09** | 项目框架设计 | 确定 Agent 四层闭环架构；确定策略方向(BTC SMC + MEME 动量)；确定技术选型(MCP + Skill Hub + Playbook)；完成目录框架搭建 |

---

## 四、待办清单

### Phase 1 — 核心 Agent（预计 6/10–6/13）

- [ ] `agent/perception.py` — 感知层，对接 Skill Hub
- [ ] `agent/decision.py` — 决策层，信号引擎
- [ ] `agent/execution.py` — 执行层，对接 MCP
- [ ] `agent/risk.py` — 风控层，仓位/止损/熔断
- [ ] `agent/agent.py` — 主控循环

### Phase 2 — 策略实现（预计 6/14–6/17）

- [ ] `strategies/btc_smc.py` — BTC 三重确认 SMC 策略
- [ ] `strategies/meme_momentum.py` — MEME 动量突破策略

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

- [ ] **Demo 链接**（必填）— 可公开访问，真实可运行
- [ ] **项目说明**（必填）— 200 字以内
- [ ] **视频演示**（选填）— 不超过 3 分钟
- [ ] **回测/模拟交易记录** — 附在 Demo 中
- [ ] **传播帖链接** — 带 #BitgetHackathon
