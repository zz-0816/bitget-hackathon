# Adaptive Trading Agent（自适应交易代理）

> **Bitget AI Base Camp Hackathon S1 — 赛道一：交易 Agent**
>
> 团队: zz_0816 | 技术栈: Python + Bitget Agent Hub

---

## 一、解决了谁的问题

**目标用户：加密货币散户交易者。**

散户交易者面临的核心痛点：

1. **追涨杀跌**：看到涨了就追进去，看到跌了就恐慌割肉，缺乏客观判断标准
2. **毫无交易逻辑**：凭感觉、看群消息、跟 KOL 喊单做决策，没有可复现的交易体系
3. **无系统风控**：不知道设多少仓位、什么位置止损、一天亏多少该停手

本项目用一个**四层闭环自动交易 Agent** 替代散户的主观判断：

```
你的角色: 设定策略参数 + 风险预算（1 分钟）

Agent 的角色:
  感知层 → 自动计算 RSI/MACD/EMA/ATR/Bollinger 等 60+ 技术指标
  决策层 → BTC SMC 三重确认 + MEME 动量突破双策略并行评估
  风控层 → 仓位上限 / 敞口上限 / 日亏损熔断 / 盈亏比过滤
  执行层 → 输出标准化订单参数（可直接对接 Bitget API）
```

**效果：散户从"凭感觉操作"变成"有纪律执行"，每一笔交易都有据可查。**

---

## 二、评委一键运行

### 首次设置（仅需 1 步，1 分钟）

```bash
# 1. 复制 MCP 配置模板，填入你的 Bitget Demo Trading API Key
cp .mcp.json.example .mcp.json
# 编辑 .mcp.json，将 your-api-key-here 等三个字段替换为你的 API Key
```

然后打开 Claude Code 加载本项目即可。

**无需手动配置权限** — 项目已内置 `.claude/settings.json`，对所有安全操作（Bash/MCP/Skill/文件写入/WebFetch）进行了预授权。评委不会被反复询问权限弹窗。

### 运行

```bash
# 2. 安装依赖（仅需 Python 3.10+）
pip install -r requirements.txt

# 3. 最简启动 — 自然语言创建策略 + Agent 持续监控
python quickstart.py
python quickstart.py "BTC 4H趋势策略 EMA金叉进场 止损2%"
python quickstart.py --once                   # 单周期检查
python quickstart.py --live                   # 真实下单模式

# 3. 完整演示（回测 + Demo Trading + Agent 闭环）
python run.py

# 分场景运行：
python run.py create                          # ★ 自然语言创建策略（交互式）
python run.py create "BTC 4H趋势策略 EMA金叉进场 止损2%"
python run.py once                            # 单次策略检查（dry-run）
python run.py once --config presets/conservative.yaml
python run.py daemon                          # 持续自动交易（dry-run）
python run.py daemon --live                   # 持续自动交易（真实下单）
```

`quickstart.py` 一键完成 5 步（无需任何子命令）：

| 步骤 | 内容 | 输出 |
|------|------|------|
| Step 1 | 自然语言输入策略描述 | 中文直接描述即可 |
| Step 2 | 自动解析 → 生成配置 | `output/quickstart_config.yaml` |
| Step 3 | Demo Trading 实时验证 | 行情→Agent四层→信号→订单链路 |
| Step 4 | Playbook 自动打包 | `output/playbook_generated/` |
| Step 5 | 启动 Agent 持续监控 | daemon 持续运行 |

### 策略配置化（用户无需写代码）

编辑 `config.yaml` 即可自定义策略参数和风控规则：

```yaml
# config.yaml — 用户只需改这个文件
strategy:
  name: "BTC SMC Triple Confluence"
  symbols: ["BTCUSDT"]
  timeframes: ["4H"]

risk:
  position_pct: 2.0       # 单笔仓位上限
  exposure_pct: 30.0      # 总敞口上限
  daily_loss_pct: 5.0     # 日亏损熔断

execution:
  mode: "demo"            # demo / live
  trade_size_usdt: 100    # 每笔金额
  dry_run: true           # true=只看信号不下单
```

提供 3 套预设模板（`presets/`）：趋势跟随 / 保守型 / MEME 动量突破。

---

## 三、核心架构

```
感知(Perception) → 决策(Decision) → 风控(Risk) → 执行(Execution)
     │                   │                │              │
 60+ 技术指标        双策略引擎        3 层风控      标准化订单
 RSI/MACD/EMA/    BTC SMC 三重确认   单笔仓位≤2%    Bitget MCP
 ATR/Bollinger/   MEME 动量突破      总敞口≤30%     参数映射
 ADX/BB%                                   日亏损熔断 5%
```

### 策略详解

**BTC SMC 三重确认（4H）**：
- EMA 趋势对齐 + RSI 动量确认 + MACD 方向确认 + ADX 趋势强度过滤
- 三重同时满足才进场，任一条件破坏即出场

**MEME 动量突破（1H）**：
- RSI 动量区间(55-65) + MACD 加速 + 成交量激增
- 分批止盈（50%仓位在 1.5R，剩余跟踪止盈）

### 风控三层防护

| 层级 | 规则 | 说明 |
|------|------|------|
| 仓位控制 | 单笔 ≤ 账户 2% | 防止单笔重仓 |
| 敞口控制 | 总敞口 ≤ 账户 30% | 防止过度交易 |
| 熔断机制 | 日亏损 ≥ 5% 停手 | 防止情绪化连续亏损 |
| 盈亏比过滤 | 最低 1.5:1 | 过滤低质量信号 |

---

## 四、可核查使用记录

每次运行自动输出以下审计日志到 `output/` 目录：

| 日志文件 | 内容 |
|----------|------|
| `output/trade_log.json` | 所有策略的全部逐笔交易（回测） |
| `output/demo_trading_log.json` | Demo Trading 实盘操作日志 |
| `output/daemon_log.json` | 持续 Agent 循环运行日志 |
| `output/api_calls.jsonl` | 全链路 API 调用审计（请求/响应/耗时/成败） |

每笔交易包含：策略名称、进场时间、出场时间、方向、进场价、出场价、盈亏百分比、持仓周期、出场原因。评委可直接打开 JSON 文件逐笔核查。

---

## 五、项目结构

```
bitget_test/
├── agent/                    # Agent 核心引擎（四层闭环）
│   ├── agent.py              # 主控循环 + AgentOutput
│   ├── config.py             # 配置中心
│   ├── perception.py         # 感知层（指标计算 + 市场数据结构）
│   ├── decision.py           # 决策层（Signal 引擎 + 情绪过滤）
│   ├── execution.py          # 执行层（Order → Bitget MCP 参数）
│   ├── risk.py               # 风控层（仓位/敞口/熔断/RR 过滤）
│   ├── strategy_factory.py   # NL 策略解析器 + 配置生成 + Playbook 打包
│   └── api_logger.py         # 全链路 API 调用审计日志（JSONL）
├── strategies/               # 策略模块
│   ├── indicators.py         # 60+ 技术指标库
│   ├── btc_smc.py            # BTC SMC 三重确认策略
│   ├── meme_momentum.py      # MEME 动量突破策略
│   └── playbook.py           # 策略注册中心 + 批量评估
├── backtest/                 # 回测模块
│   ├── btc_smc_backtest.py   # BTC SMC 独立回测
│   ├── meme_momentum_backtest.py  # MEME 独立回测
│   └── benchmark.py          # 多策略横向对比
├── data/                     # 历史行情数据（JSON）
├── output/                   # ★ 交易记录 + Agent 日志输出
│   ├── trade_log.json        # 回测交易记录
│   ├── demo_trading_log.json # Demo Trading 实盘日志
│   ├── daemon_log.json       # 持续交易循环日志
│   └── api_calls.jsonl       # 全链路 API 审计
├── presets/                  # 策略预设模板（用户可直接使用）
│   ├── btc_trend_following.yaml
│   ├── conservative.yaml
│   └── meme_breakout.yaml
├── output/playbook_generated/ # ★ 自动生成的 Playbook 包
├── .claude/
│   └── settings.json         # ★ 权限预配置（评委无需手动授权）
├── .mcp.json.example         # ★ MCP 配置模板 → 评委复制为 .mcp.json
├── CLAUDE.md                 # ★ Agent 角色定义（策略创建运行审核机器人）
├── config.yaml               # ★ 用户配置文件（改参数不写代码）
├── quickstart.py             # ★ 一键策略创建 + Agent 监控（推荐入口）
├── run.py                    # 完整演示入口
├── daemon.py                 # 持续交易循环引擎
├── demo_trading_test.py      # Bitget Demo Trading 完整测试
├── requirements.txt          # Python 依赖
└── README.md                 # 本文件
```

---

## 六、环境配置（评委无需此步骤，已预配置）

项目已通过 `.claude/settings.json` 预配置了所有权限。评委只需完成 `.mcp.json.example → .mcp.json` 的 API Key 配置（见第二节）。

```bash
# 如需安装 Bitget Agent Hub（MCP + Skill Hub）
npx bitget-hub upgrade-all --target claude

# 评委只需要一个 Bitget Demo Trading API Key（沙盒模式，Read + Trade 权限）
# 填入 .mcp.json 即可，无需配置环境变量
```

---

## 七、提交材料清单

- [x] **Demo 可运行** — `pip install -r requirements.txt && python quickstart.py`
- [x] **项目说明** — 散户追涨杀跌 → Agent 系统化交易
- [x] **可核查使用记录** — `output/trade_log.json` + `output/demo_trading_log.json` + `output/daemon_log.json` + `output/api_calls.jsonl`
- [x] **回测指标** — 8 策略变体完整对比（胜率/夏普/最大回撤/盈亏比/期望值）
- [x] **Bitget Demo Trading 实盘测试** — 7 阶段完整链路（账户→行情→信号→风控→下单→验证→日志）
- [x] **策略配置化** — `config.yaml` 用户改参数不写代码 + 3 套预设模板
- [x] **自然语言创建策略** — `python quickstart.py "中文描述"` 一键生成配置+验证+Playbook
- [x] **持续交易循环** — `python quickstart.py` 自动进入 daemon 监控
- [x] **全链路 API 审计** — `output/api_calls.jsonl` JSONL 格式记录每次 API 调用
- [x] **权限预配置** — `.claude/settings.json` 预授权所有安全操作，评委开箱即用
- [x] **CLAUDE.md 角色定义** — 策略创建运行审核机器人，支持自然语言对话式操作
- [x] **Playbook 加分项** — 自动生成 Playbook 包到 `output/playbook_generated/`
- [x] **GitHub 仓库** — https://github.com/zz-0816/bitget-hackathon
- [ ] **传播帖链接** — 待发布
