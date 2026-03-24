---
name: technical-analysis
description: Compute technical indicators like RSI, MACD, Bollinger Bands, SMA, EMA for a stock. Use when user asks about technical analysis, indicators, RSI, MACD, moving averages, overbought/oversold, or chart analysis.
dependencies: ["trading-skills"]
---

# Technical Analysis

Compute technical indicators using pandas-ta. Supports multi-symbol analysis, trend classification, signal confluence, support/resistance levels, and volume analysis.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/technicals.py SYMBOL [--period PERIOD] [--indicators INDICATORS] [--earnings] [--beta]
```

## Arguments

- `SYMBOL` - Ticker symbol or comma-separated list (e.g., `AAPL` or `AAPL,MSFT,GOOGL`)
- `--period` - Historical period: 1mo, 3mo, 6mo, 1y (default: 3mo)
- `--indicators` - Comma-separated list: rsi,macd,bb,sma,ema,atr,adx,vwap,sr (default: all)
- `--earnings` - Include earnings data (upcoming date + history)
- `--beta` - Include beta vs SPY (requires extra data fetch)

## Output

Single symbol returns:
- `price` - Current price, change, change_pct
- `indicators` - Computed values for each indicator (see below)
- `signals` - Buy/sell signals with `strength` (0.0-1.0) and `volume_confirmed` flags
- `trend` - Trend classification: `label` (strong_bull/bull/neutral/bear/strong_bear), `score`, `factors`
- `confluence` - Signal alignment: `bullish_count`, `bearish_count`, `bias`, `strength`
- `risk_metrics` - Volatility, Sharpe, Sortino, max drawdown, optional beta
- `earnings` - Upcoming date and EPS history (if `--earnings`)

Multiple symbols returns:
- `results` - Array of individual symbol results

## Indicators

| Name | Key | Description |
|------|-----|-------------|
| RSI | `rsi` | RSI(14) + Stochastic RSI (K/D) |
| MACD | `macd` | MACD line, signal, histogram |
| Bollinger Bands | `bb` | Upper, lower, middle, bandwidth |
| SMA | `sma` | SMA20, SMA50, SMA200 |
| EMA | `ema` | EMA12, EMA26 |
| ATR | `atr` | ATR(14) value and percent of price |
| ADX | `adx` | ADX, +DI, -DI |
| VWAP | `vwap` | Volume-weighted average price |
| Support/Resistance | `sr` | Pivot points (S1/S2/R1/R2), swing highs/lows, nearest levels |
| Volume | *(always)* | Relative volume, OBV trend, ROC(12) |

## Interpretation

### Trend & Momentum
- RSI > 70 = overbought, RSI < 30 = oversold
- Stochastic RSI > 80 = overbought, < 20 = oversold (more sensitive than RSI)
- MACD crossover = momentum shift (stronger when above zero line)
- Golden cross (SMA20 > SMA50) = bullish, Death cross = bearish
- ADX > 25 = strong trend, +DI > -DI = bullish direction
- ROC > 0 = positive momentum

### Volume
- Relative volume > 1.5 = unusual activity (confirms moves)
- Relative volume < 0.5 = low conviction
- OBV rising = volume supports uptrend

### Support/Resistance
- Pivot points: classic floor trader levels from prior day OHLC
- Swing highs/lows: recent price extremes from bar structure
- Nearest support/resistance: closest levels to current price

### Risk
- Sharpe ratio > 1 = good risk-adjusted returns, > 2 = excellent
- Sortino ratio > 1 = good (only penalizes downside volatility)
- Max drawdown: worst peak-to-trough decline in period
- Beta > 1 = more volatile than market, < 1 = less volatile

### Signal Quality
- `strength` (0.0-1.0): Conviction level (RSI 72 = 0.07 weak, RSI 95 = 0.83 strong)
- `volume_confirmed`: Signal occurred on above-average volume (>1.5x)
- `confluence.strength`: strong (3+ aligned signals), moderate (2), weak (0-1)

## Examples

```bash
# Single symbol with all indicators
uv run python scripts/technicals.py AAPL

# Multiple symbols
uv run python scripts/technicals.py AAPL,MSFT,GOOGL

# With earnings data and beta
uv run python scripts/technicals.py NVDA --earnings --beta

# Specific indicators only
uv run python scripts/technicals.py TSLA --indicators rsi,macd,sr
```

---

# Correlation Analysis

Compute price correlation matrix between multiple symbols for diversification analysis.

## Instructions

```bash
uv run python scripts/correlation.py SYMBOLS [--period PERIOD]
```

## Arguments

- `SYMBOLS` - Comma-separated ticker symbols (minimum 2)
- `--period` - Historical period: 1mo, 3mo, 6mo, 1y (default: 3mo)

## Output

- `symbols` - List of symbols analyzed
- `period` - Time period used
- `correlation_matrix` - Nested dict with correlation values between all pairs

## Interpretation

- Correlation near 1.0 = highly correlated (move together)
- Correlation near -1.0 = negatively correlated (move opposite)
- Correlation near 0 = uncorrelated (independent movement)
- For diversification, prefer low/negative correlations

## Examples

```bash
# Portfolio correlation
uv run python scripts/correlation.py AAPL,MSFT,GOOGL,AMZN

# Sector comparison
uv run python scripts/correlation.py XLF,XLK,XLE,XLV --period 6mo

# Check hedge effectiveness
uv run python scripts/correlation.py SPY,GLD,TLT
```

## Dependencies

- `numpy`
- `pandas`
- `pandas-ta`
- `yfinance`
