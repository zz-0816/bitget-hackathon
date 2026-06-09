# strategies/ — 交易策略模块

> 每个策略封装为独立类，暴露 `evaluate(df) → Signal` 接口。

---

## 待创建文件

| 文件 | 职责 | 策略逻辑 |
|------|------|---------|
| `__init__.py` | 模块入口 | 导出 BTCSMCStrategy、MEMEMomentumStrategy |
| `btc_smc.py` | **BTC 三重确认 SMC 策略** | 4H 周期, EMA20/50/200 三重排列 + RSI 趋势 + MACD 方向, SL 基于摆动高低点, RR 2:1 |
| `meme_momentum.py` | **MEME 动量突破策略** | 1H 周期, RSI 55-65 动量区间 + MACD 柱加速 + 量能放大, SL 基于 2x ATR, 分批止盈 |
| `adaptive_hybrid.py` | **自适应混合策略 (可选)** | 根据市场状态(趋势/震荡/高波动)自动切换策略模式；趋势时跟踪、震荡时均值回归、不明确时空仓 |

## 策略接口规范

```python
class Strategy:
    name: str          # 策略名称
    timeframe: str     # 周期 (4h / 1h)
    symbol: str        # 交易对

    def evaluate(self, df: pd.DataFrame) -> Signal:
        """输入带指标的 OHLCV DataFrame，返回交易信号"""
        ...
```

## 备注

- 策略**不应**包含 API 调用，保持纯函数/纯计算
- 入场/离场逻辑分离，方便回测和实盘复用
- 每个策略对应 `backtest/` 下独立的回测脚本
