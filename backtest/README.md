# backtest/ — 回测模块

> 每个策略对应一个独立回测脚本，用真实或合成数据验证策略表现。

---

## 待创建 / 已有文件

| 文件 | 说明 |
|------|------|
| `../backtest.py` | **已有** — BTC SMC + MEME 动量 合成数据回测 |
| `../backtest_strategies.py` | **已有** — 同上策略，尝试 yfinance/Bitget API 拉真实数据 |
| `btc_smc_backtest.py` | **待创建** — BTC SMC 独立回测，输出完整指标表 |
| `meme_momentum_backtest.py` | **待创建** — MEME 动量独立回测 |
| `benchmark.py` | **待创建** — 多策略横向对比，生成汇总表 |

## 回测输出指标

每轮回测应输出以下指标表格：

| 指标 | 说明 |
|------|------|
| Total Trades | 总交易次数 |
| Win Rate | 胜率 (%) |
| Total PnL | 累计收益率 (%) |
| Profit Factor | 总盈利/总亏损 |
| Max Drawdown | 最大回撤 (%) |
| Sharpe Ratio | 夏普比率 |
| Avg Win / Avg Loss | 平均盈利/亏损 (%) |
| Expectancy | 每笔交易期望收益 (%) |
