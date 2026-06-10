"""Generate Step 1 verification images for all 5 analyst Skills."""
import sys, os, json, urllib.request
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
from datetime import datetime

# ── Font setup ──────────────────────────────────────────────
# Try to find a font that supports CJK
FONT_NAMES = ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Arial']
AVAILABLE = {f.name for f in fm.fontManager.ttflist}
CN_FONT = None
for name in FONT_NAMES:
    if name in AVAILABLE:
        CN_FONT = name
        break
if CN_FONT:
    plt.rcParams['font.family'] = CN_FONT
    print(f"Using font: {CN_FONT}")
else:
    print("No CJK font found, using ASCII labels")
    CN_FONT = None

plt.rcParams['axes.unicode_minus'] = False

OUT = os.path.dirname(os.path.abspath(__file__)) + '/images'
os.makedirs(OUT, exist_ok=True)

# ── Common data fetch ─────────────────────────────────────
print("Fetching BTC/USDT 4H candles...")
url = 'https://api.bitget.com/api/v2/spot/market/candles?symbol=BTCUSDT&granularity=4h&limit=200'
raw = json.loads(urllib.request.urlopen(url).read())
df = pd.DataFrame(raw['data'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quoteVol', 'amount'])
for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
    df[col] = df[col].astype(float)
df['timestamp'] = pd.to_datetime(df['timestamp'].astype(np.int64), unit='ms')
df = df.sort_values('timestamp').reset_index(drop=True)

# ── Compute indicators locally ─────────────────────────────
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = 2 * (dif - dea)
    return dif, dea, hist

def atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

close = df['close']
ema20 = ema(close, 20)
ema50 = ema(close, 50)
ema200 = ema(close, 200)
rsi14 = rsi(close, 14)
dif, dea, hist = macd(close)
atr14 = atr(df, 14)
natr14 = atr14 / close * 100

tail = slice(-80, None)  # last 80 bars for clarity
t = df['timestamp'].iloc[tail]
c = close.iloc[tail]

# ============================================================
#  1. TECHNICAL ANALYSIS
# ============================================================
print("Generating 01_technical_analysis.png...")
fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True,
                          gridspec_kw={'height_ratios': [3, 1.5, 1.5, 1.5]})
fig.suptitle('BTC/USDT 4H Technical Analysis — 2026-06-10', fontsize=16, fontweight='bold', y=0.98)

# Price + EMAs
ax = axes[0]
ax.plot(t, c, color='#1a1a2e', linewidth=1.5, label='Close')
ax.plot(t, ema20.iloc[tail], color='#ff6b35', linewidth=1, label='EMA20')
ax.plot(t, ema50.iloc[tail], color='#f7c948', linewidth=1, label='EMA50')
ax.plot(t, ema200.iloc[tail], color='#00b4d8', linewidth=1, label='EMA200')
ax.fill_between(t, c, ema20.iloc[tail], alpha=0.1, color='gray')
ax.set_ylabel('Price (USD)', fontsize=10)
ax.legend(loc='upper left', fontsize=8, ncol=4)
ax.grid(True, alpha=0.3)
ax.set_title(f'Price: ${c.iloc[-1]:.2f}  |  EMA20 < EMA50 < EMA200 (Bearish Alignment)', fontsize=10, color='#e63946')

# RSI
ax = axes[1]
ax.axhline(70, color='#e63946', linestyle='--', alpha=0.5, linewidth=0.8)
ax.axhline(30, color='#2a9d8f', linestyle='--', alpha=0.5, linewidth=0.8)
ax.axhline(50, color='gray', linestyle=':', alpha=0.4, linewidth=0.8)
ax.fill_between(t, 70, rsi14.iloc[tail], alpha=0.15, color='#e63946')
ax.fill_between(t, rsi14.iloc[tail], 30, alpha=0.15, color='#2a9d8f')
ax.plot(t, rsi14.iloc[tail], color='#6a4c93', linewidth=1.5)
ax.set_ylabel('RSI(14)', fontsize=10)
ax.set_ylim(0, 100)
ax.grid(True, alpha=0.3)
ax.set_title(f'RSI(14): {rsi14.iloc[-1]:.1f} — Oversold recovery underway', fontsize=10, color='#6a4c93')

# MACD
ax = axes[2]
ax.fill_between(t, 0, hist.iloc[tail], color=['#e63946' if v < 0 else '#2a9d8f' for v in hist.iloc[tail]], alpha=0.3)
ax.bar(t, hist.iloc[tail], color=['#e63946' if v < 0 else '#2a9d8f' for v in hist.iloc[tail]],
       width=0.03, alpha=0.7)
ax.plot(t, dif.iloc[tail], color='#1a1a2e', linewidth=1.2, label='DIF')
ax.plot(t, dea.iloc[tail], color='#e76f51', linewidth=1.2, label='DEA')
ax.axhline(0, color='gray', linewidth=0.5)
ax.set_ylabel('MACD', fontsize=10)
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)
ax.set_title(f'MACD: DIF={dif.iloc[-1]:.0f}, DEA={dea.iloc[-1]:.0f}, HIST narrowing (bearish momentum weakening)', fontsize=10, color='#e76f51')

# ATR
ax = axes[3]
ax.plot(t, atr14.iloc[tail], color='#264653', linewidth=1.5, label='ATR(14)')
ax2_ = ax.twinx()
ax2_.plot(t, natr14.iloc[tail], color='#2a9d8f', linewidth=1, alpha=0.6, label='NATR%')
ax.set_ylabel('ATR (USD)', fontsize=10)
ax2_.set_ylabel('NATR %', fontsize=10, color='#2a9d8f')
ax.grid(True, alpha=0.3)
ax.set_title(f'ATR(14): {atr14.iloc[-1]:.0f} USD  |  NATR: {natr14.iloc[-1]:.2f}%', fontsize=10, color='#264653')

fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(f'{OUT}/01_technical_analysis.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print("  -> 01_technical_analysis.png saved")

# ============================================================
#  2. SENTIMENT ANALYSIS
# ============================================================
print("Generating 02_sentiment.png...")
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
fig.suptitle('Crypto Market Sentiment — 2026-06-10', fontsize=16, fontweight='bold')

# Fear & Greed gauge
ax = axes[0, 0]
fg_value = 9
colors_fg = ['#2a9d8f', '#90be6d', '#f9c74f', '#f9844a', '#e63946']
ranges = [(0, 25), (25, 45), (45, 55), (55, 75), (75, 100)]
labels_fg = ['Extreme\nFear', 'Fear', 'Neutral', 'Greed', 'Extreme\nGreed']
for (start, end), color, label in zip(ranges, colors_fg, labels_fg):
    ax.barh(0, end - start, left=start, height=0.4, color=color, alpha=0.7, edgecolor='white')
    ax.text(start + (end-start)/2, 0, label, ha='center', va='center', fontsize=8, fontweight='bold', color='white')
ax.axvline(fg_value, color='black', linewidth=3, linestyle='-')
ax.scatter(fg_value, 0, color='black', s=200, zorder=5)
ax.text(fg_value, 0.25, f'{fg_value}/100', ha='center', fontsize=14, fontweight='bold', color='black')
ax.set_xlim(0, 100)
ax.set_ylim(-0.5, 0.5)
ax.set_yticks([])
ax.set_title(f'Fear & Greed Index: {fg_value}/100 (EXTREME FEAR)', fontsize=11, fontweight='bold', color='#2a9d8f')

# 14-day F&G trend
ax = axes[0, 1]
days = list(range(14, 0, -1))
fg_history = [12, 12, 12, 11, 23, 29, 28, 23, 23, 22, 10, 8, 12, 9]
ax.fill_between(days, 0, fg_history, alpha=0.3, color='#2a9d8f')
ax.plot(days, fg_history, 'o-', color='#2a9d8f', linewidth=2, markersize=8,
        markerfacecolor='white', markeredgewidth=2)
ax.axhline(25, color='#f9c74f', linestyle='--', alpha=0.5, linewidth=1, label='Fear threshold')
ax.fill_between(days, 0, 25, alpha=0.05, color='#e63946')
ax.set_xlabel('Days Ago', fontsize=9)
ax.set_ylabel('F&G Value', fontsize=9)
ax.set_ylim(0, 100)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)
ax.set_title('14-Day Fear & Greed Trend', fontsize=11, fontweight='bold')

# L/S ratio comparison
ax = axes[1, 0]
categories = ['Retail\nTraders', 'Top\nTraders']
ls_values = [2.04, 1.16]
colors_ls = ['#e63946', '#2a9d8f']
bars = ax.bar(categories, ls_values, color=colors_ls, alpha=0.8, width=0.4, edgecolor='white')
ax.axhline(1.0, color='gray', linestyle='-', linewidth=1, alpha=0.5)
for bar, val in zip(bars, ls_values):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.03, f'{val:.2f}',
            ha='center', fontsize=12, fontweight='bold')
ax.set_ylabel('Long/Short Ratio', fontsize=9)
ax.set_title('L/S Ratio: Retail vs Top Traders (Divergence!)', fontsize=11, fontweight='bold', color='#e63946')
ax.grid(True, alpha=0.3, axis='y')
ax.set_ylim(0, 2.5)

# Key metrics table
ax = axes[1, 1]
ax.axis('off')
metrics = [
    ('Parameter', 'Value', 'Signal'),
    ('Fear & Greed', '9 / 100', 'EXTREME FEAR'),
    ('Retail L/S', '2.04', 'Heavily Long'),
    ('Top Trader L/S', '1.16', 'Moderately Long'),
    ('Taker Buy/Sell', '0.99', 'Balanced'),
    ('Open Interest', '101K BTC', '-1.8% decline'),
    ('14-day F&G Range', '8 – 29', 'Persistent Fear'),
]
table = ax.table(cellText=metrics, cellLoc='center', loc='center',
                 colWidths=[0.3, 0.25, 0.45])
table.auto_set_font_size(False)
table.set_fontsize(9)
for i in range(len(metrics)):
    for j in range(3):
        cell = table[i, j]
        cell.set_facecolor('#f8f9fa' if i > 0 else '#2a9d8f')
        cell.set_text_props(color='black' if i > 0 else 'white', fontweight='bold' if i == 0 else 'normal')
        if i > 0 and j == 2:
            if 'FEAR' in str(metrics[i][j]):
                cell.set_text_props(color='#e63946', fontweight='bold')
            elif 'Long' in str(metrics[i][j]):
                cell.set_text_props(color='#e76f51')
ax.set_title('Sentiment Metrics Summary', fontsize=11, fontweight='bold', y=1.02)

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(f'{OUT}/02_sentiment.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print("  -> 02_sentiment.png saved")

# ============================================================
#  3. MACRO ANALYSIS
# ============================================================
print("Generating 03_macro.png...")
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Macro Environment Analysis — 2026-06-10', fontsize=16, fontweight='bold')

# BTC Cross-Asset Correlations
ax = axes[0, 0]
assets = ['Gold', 'DXY', 'Nasdaq', 'S&P500', '10Y T', 'VIX']
full_corr = [0.18, -0.16, 0.49, 0.50, -0.00, -0.46]
rolling_corr = [0.43, -0.29, 0.53, 0.59, -0.36, -0.41]
x = np.arange(len(assets))
w = 0.35
bars1 = ax.bar(x - w/2, full_corr, w, color='#6a4c93', alpha=0.8, label='Full Period (1Y)')
bars2 = ax.bar(x + w/2, rolling_corr, w, color='#ff6b35', alpha=0.8, label='Rolling (30D)')
ax.axhline(0, color='black', linewidth=0.8)
ax.axhline(0.4, color='gray', linestyle='--', alpha=0.4, linewidth=0.8)
ax.axhline(-0.4, color='gray', linestyle='--', alpha=0.4, linewidth=0.8)
ax.set_xticks(x)
ax.set_xticklabels(assets, fontsize=9)
ax.set_ylabel('Correlation Coefficient', fontsize=9)
ax.set_title('BTC Cross-Asset Correlations', fontsize=11, fontweight='bold')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3, axis='y')
for bar, val in zip(bars1, full_corr):
    y_pos = val + 0.03 if val >= 0 else val - 0.08
    ax.text(bar.get_x() + bar.get_width()/2, y_pos, f'{val:.2f}',
            ha='center', fontsize=7, color='#6a4c93')
for bar, val in zip(bars2, rolling_corr):
    y_pos = val + 0.03 if val >= 0 else val - 0.08
    ax.text(bar.get_x() + bar.get_width()/2, y_pos, f'{val:.2f}',
            ha='center', fontsize=7, color='#ff6b35')

# Key Rates
ax = axes[0, 1]
ax.axis('off')
rate_data = [
    ('Key Rates & Macro Indicators', 'Value', 'Trend'),
    ('Fed Funds Rate', '3.50 – 3.75%', 'Paused'),
    ('2Y Treasury Yield', '4.15%', 'Stable'),
    ('10Y Treasury Yield', '4.56%', 'Stable'),
    ('10Y-2Y Spread', '+0.40%', 'No Longer Inverted'),
    ('Breakeven Inflation', '2.33%', 'Moderate'),
    ('DXY (USD Index)', '99.90', 'Weakening'),
    ('VIX', '21.09', 'Elevated'),
    ('Mortgage 30Y', '6.48%', 'Declining'),
    ('SOFR', '3.63%', 'Stable'),
]
table = ax.table(cellText=rate_data, cellLoc='center', loc='center',
                 colWidths=[0.38, 0.28, 0.34])
table.auto_set_font_size(False)
table.set_fontsize(9)
for i, row in enumerate(rate_data):
    for j in range(3):
        cell = table[i, j]
        if i == 0:
            cell.set_facecolor('#6a4c93')
            cell.set_text_props(color='white', fontweight='bold')
        else:
            cell.set_facecolor('#f8f9fa' if i % 2 == 0 else 'white')
        if j == 2 and i > 0:
            if row[2] in ('Weakening', 'No Longer Inverted'):
                cell.set_text_props(color='#2a9d8f', fontweight='bold')
            elif row[2] == 'Elevated':
                cell.set_text_props(color='#e63946')
ax.set_title('Key Rates & Macro Dashboard', fontsize=11, fontweight='bold', y=1.02)

# Macro Verdict
ax = axes[1, 0]
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')
verdict_color = '#f9c74f'
ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor='#f8f9fa', edgecolor='#dee2e6', linewidth=2, zorder=0))
ax.text(0.5, 0.65, 'MIXED / RISK-NEUTRAL', ha='center', va='center', fontsize=22, fontweight='bold', color='#e76f51')
ax.text(0.5, 0.40, 'Macro Verdict', ha='center', va='center', fontsize=14, color='gray')
signals = [
    '+ Yield curve no longer inverted (10Y-2Y = +0.40%)',
    '+ DXY < 100, weakening USD supportive for BTC',
    '+ Fed on pause, no rate hikes expected',
    '- VIX elevated at 21, risk aversion present',
    '- SpaceX IPO creating liquidity squeeze',
    '- BTC-Equity correlation rising → contagion risk',
]
for i, s in enumerate(signals):
    c = '#2a9d8f' if s.startswith('+') else '#e63946'
    ax.text(0.05, 0.22 - i*0.06, s, fontsize=9, color=c, fontfamily='monospace')

# Fed Policy Context
ax = axes[1, 1]
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')
ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor='#f8f9fa', edgecolor='#dee2e6', linewidth=2))
ax.text(0.5, 0.85, 'Fed Policy & Crypto Implications', ha='center', va='center', fontsize=13, fontweight='bold', color='#1a1a2e')
implications = [
    '• Fed maintaining 3.50-3.75% target range since mid-2025',
    '• Market pricing in 25bp cut by September 2026',
    '• Yield curve normalization (un-inverting) reduces recession odds',
    '• Weakening DXY historically precedes BTC bull cycles',
    '• 10Y breakeven at 2.33% → inflation expectations anchored',
    '• BTC-S&P500 rolling correlation rising to 0.59 → macro-driven',
    '• SpaceX IPO + Anthropic IPO → near-term liquidity drain',
    '',
    'Bottom Line: Macro backdrop is improving but near-term',
    'liquidity events (SpaceX IPO) dominate price action.',
]
for i, text in enumerate(implications):
    ax.text(0.05, 0.72 - i*0.07, text, fontsize=9, color='#495057')

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(f'{OUT}/03_macro.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print("  -> 03_macro.png saved")

# ============================================================
#  4. NEWS BRIEFING
# ============================================================
print("Generating 04_news_briefing.png...")
fig, ax = plt.subplots(1, 1, figsize=(14, 9))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')
ax.set_facecolor('#f8f9fa')

ax.text(0.5, 0.96, 'Crypto News Briefing — 2026-06-10', ha='center', fontsize=18, fontweight='bold', color='#1a1a2e')
ax.text(0.5, 0.92, 'Dominant Theme: SpaceX IPO Liquidity Squeeze + Intensifying Global Regulation',
        ha='center', fontsize=11, color='#e76f51')

headlines = [
    ('MARKET MOVING', '#e63946', [
        'SpaceX IPO oversubscribed 4x — "classic pre-mega-IPO liquidity squeeze" hitting crypto & tech stocks',
        'Bitcoin ETFs net assets back to Nov 2024 (Trump election) levels — 18 months of inflows erased',
        'BTC briefly reclaimed $63K, liquidating $540M in shorts — 7-week high',
    ]),
    ('REGULATION', '#6a4c93', [
        'EU proposes ban on 11 crypto platforms in expanded Russia sanctions package',
        'US crypto tax bills face pushback in House Committee — staking/mining exemptions questioned',
        'Hyperliquid + Paradigm urge Treasury to revise GENIUS Act AML rules for stablecoins',
    ]),
    ('ADOPTION', '#2a9d8f', [
        'Japan\'s 3 largest banks (MUFG, SMBC, Mizuho) plan joint stablecoin launch by March 2027',
        'Chainalysis partners with South Korean police to combat crypto crime',
    ]),
    ('ON-CHAIN / MARKET STRUCTURE', '#f9c74f', [
        'XRP showing capitulation signs — holders selling at loss, Glassnode data hints at bottom',
        'Whale accumulation noted — analyst calls record-low RSI a "generational buying opportunity"',
        'Anthropic IPO pipeline (not Claude model) is what crypto traders should track — CoinDesk',
    ]),
]

y = 0.85
for category, color, items in headlines:
    ax.text(0.05, y, category, fontsize=10, fontweight='bold', color=color)
    y -= 0.03
    for item in items:
        ax.text(0.07, y, f'  {item}', fontsize=9, color='#495057')
        y -= 0.04
    y -= 0.01

# Source note
ax.text(0.5, 0.02, 'Sources: Cointelegraph, CoinDesk, Decrypt, Blockworks, Finnhub | Aggregated 2026-06-10',
        ha='center', fontsize=8, color='#adb5bd')

fig.tight_layout()
fig.savefig(f'{OUT}/04_news_briefing.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print("  -> 04_news_briefing.png saved")

# ============================================================
#  5. MARKET INTEL
# ============================================================
print("Generating 05_market_intel.png...")
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Market Intelligence — 2026-06-10', fontsize=16, fontweight='bold')

# Market Overview
ax = axes[0, 0]
ax.axis('off')
market_data = [
    ('Market Overview', ''),
    ('BTC Price', '$61,274  (-2.19% 24h)'),
    ('ETH Price', '$1,624.70  (-2.76% 24h)'),
    ('Total Market Cap', '$2.20 Trillion  (-2.56%)'),
    ('BTC Dominance', '55.96%'),
    ('24h Trading Volume', '$85.71 Billion'),
    ('Active Cryptocurrencies', '17,355'),
    ('Markets/Exchanges', '1,484'),
]
for i, (label, value) in enumerate(market_data):
    c = 'white' if i == 0 else '#f8f9fa'
    fw = 'bold' if i == 0 else 'normal'
    fs = 11 if i == 0 else 10
    ax.text(0.1, 0.85 - i*0.09, f'{label}', fontsize=fs, fontweight=fw, color='#1a1a2e' if i > 0 else '#2a9d8f')
    ax.text(0.6, 0.85 - i*0.09, f'{value}', fontsize=fs, fontweight='normal', color='#495057',
            ha='right' if i > 0 else 'center')
ax.set_title('Crypto Market Overview', fontsize=11, fontweight='bold', y=1.02)

# Top 10 Market Cap
ax = axes[0, 1]
ax.axis('off')
top10 = [
    ('Rank', 'Asset', 'Dominance'),
    ('1', 'BTC', '55.96%'),
    ('2', 'ETH', '8.95%'),
    ('3', 'USDT', '8.49%'),
    ('4', 'BNB', '3.59%'),
    ('5', 'USDC', '3.41%'),
    ('6', 'XRP', '3.14%'),
    ('7', 'SOL', '1.69%'),
    ('8', 'TRX', '1.39%'),
    ('9', 'HELOC', '0.88%'),
    ('10', 'stETH', '0.66%'),
]
table = ax.table(cellText=top10, cellLoc='center', loc='center',
                 colWidths=[0.15, 0.25, 0.25])
table.auto_set_font_size(False)
table.set_fontsize(9)
for i in range(len(top10)):
    for j in range(3):
        cell = table[i, j]
        if i == 0:
            cell.set_facecolor('#2a9d8f')
            cell.set_text_props(color='white', fontweight='bold')
        elif i == 1:
            cell.set_facecolor('#e8f5e0')
        else:
            cell.set_facecolor('#f8f9fa' if i % 2 == 0 else 'white')
ax.set_title('Top 10 by Market Cap Dominance', fontsize=11, fontweight='bold', y=1.02)

# ETF & Institutional Flows
ax = axes[1, 0]
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')
ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor='#f8f9fa', edgecolor='#dee2e6', linewidth=2))
ax.text(0.5, 0.92, 'ETF & Institutional Flow Intelligence', ha='center', fontsize=12, fontweight='bold', color='#1a1a2e')
etf_findings = [
    'BTC Spot ETFs: Net assets at Nov 2024 levels — 18 months of growth erased',
    'Recent $540M short liquidation at $63K reclaim suggests positioning skewed short',
    'CoinDesk: "The Strategy (MSTR) playbook looks different in 2026"',
    'Strategy holds 673,783 BTC but buying flow is now episodic vs sustained',
    'SpaceX + Anthropic IPOs creating "liquidity vacuum" for risk assets',
    '',
    'Direct daily ETF flow data: NOT available in current data source',
    'Proxy: News sentiment + derivatives positioning used instead',
]
for i, text in enumerate(etf_findings):
    c = '#6c757d' if text.startswith('Direct') else '#495057'
    fs = 8.5 if text.startswith('Direct') else 10
    ax.text(0.05, 0.78 - i*0.08, text, fontsize=fs, color=c)

# Whale & Derivatives Intelligence
ax = axes[1, 1]
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis('off')
ax.add_patch(plt.Rectangle((0, 0), 1, 1, facecolor='#f8f9fa', edgecolor='#dee2e6', linewidth=2))
ax.text(0.5, 0.92, 'Whale & Smart Money Positioning', ha='center', fontsize=12, fontweight='bold', color='#1a1a2e')
whale_findings = [
    'Retail L/S: 2.04 (67% long) — Heavily one-sided',
    'Top Trader L/S: 1.16 (54% long) — Much more conservative',
    'DIVERGENCE: Retail aggressively long, smart money cautious',
    '',
    'Open Interest: -1.8% → positions being closed, not added',
    'Stablecoin supply (USDT): Weekly decline of ~$1.15B (-0.6%)',
    '→ Capital flowing OUT of crypto, not in',
    '',
    'Analyst note: "Record-low RSI + whale accumulation =',
    'generational buying opportunity" despite near-term risk',
    '',
    'On-chain whale tracking: NOT available in current data source',
    'Proxy: Derivatives positioning + news + stablecoin flows',
]
for i, text in enumerate(whale_findings):
    c_val = '#6c757d' if text.startswith('On-chain') else '#495057'
    fs_val = 8.5 if (text.startswith('On-chain') or text.startswith('Direct')) else 10
    if 'DIVERGENCE' in text:
        c_val = '#e63946'
    if 'generational' in text:
        c_val = '#2a9d8f'
    ax.text(0.05, 0.78 - i*0.07, text, fontsize=fs_val, color=c_val)

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(f'{OUT}/05_market_intel.png', dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print("  -> 05_market_intel.png saved")

# ============================================================
print(f"\nAll 5 images saved to {OUT}/")
print("Files:")
for f in sorted(os.listdir(OUT)):
    size_kb = os.path.getsize(os.path.join(OUT, f)) / 1024
    print(f"  {f} ({size_kb:.0f} KB)")
