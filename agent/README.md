# agent/ — Trading Agent 核心引擎

> **感知 → 决策 → 执行 → 风控** 四层闭环的主控模块。

---

## 待创建文件

| 文件 | 职责 | 存放内容 |
|------|------|---------|
| `__init__.py` | 模块入口 | 导出 TradingAgent 和 AgentConfig |
| `agent.py` | **主控循环** | 串联四个环节的 run_loop()，每步输出结构化结果给 Claude Code |
| `config.py` | **配置中心** | 策略参数、风控阈值、沙盒开关；从环境变量读取 |
| `perception.py` | **感知层** | 行情数据获取 + 技术指标计算(RSI/MACD/EMA/ATR/Bollinger)；`MarketData`、`SentimentSnapshot`、`MacroSnapshot` 数据结构 |
| `decision.py` | **决策层** | 加载策略 → 跑信号检测 → 输出 `Signal`(ENTRY_LONG/ENTRY_SHORT/EXIT/HOLD/NO_TRADE)；宏观/情绪过滤器 |
| `execution.py` | **执行层** | 信号 → 订单转换；`Order` 数据结构映射到 Bitget MCP `futures_place_order` 参数 |
| `risk.py` | **风控层** | 仓位计算(单笔最大2%)、总敞口限制(30%)、日亏损熔断(5%)、最低RR过滤(1.5:1) |

## 数据流

```
PerceptionReport ──→ DecisionEngine ──→ Signal
                         │                  │
                    策略模块(BTC/MEME)    RiskManager
                                           │
                                      通过/拒绝
                                           │
                                      ExecutionEngine
                                           │
                                      Order → Bitget MCP
```

## 备注

- 所有 Bitget API 调用在 Claude Code 环境通过 MCP 完成，Python 层只做**逻辑编排和数据结构定义**
- Skill Hub 的 5 个感知 Skill (technical-analysis/sentiment-analyst/macro-analyst/news-briefing/market-intel) 由 Claude Code 调用后传入 perception 层
- 沙盒模式通过环境变量 `BITGET_SANDBOX=true` 控制
