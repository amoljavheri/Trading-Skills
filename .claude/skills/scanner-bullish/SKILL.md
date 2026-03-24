---
name: scanner-bullish
description: Scan stocks for bullish trends using technical indicators (SMA, RSI, MACD, ADX), volume confirmation, breakout detection, and trend consistency. Use when user asks to scan for bullish stocks, find trending stocks, or rank symbols by momentum.
dependencies: ["trading-skills"]
---

# Bullish Scanner v2

Scans symbols for bullish trends and ranks them by composite score. Detects trend stage (early/mid/extended), volume confirmation, and 20-day breakouts.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/scan.py SYMBOLS [--top N] [--period PERIOD] [--min-score FLOAT]
```

## Arguments

- `SYMBOLS` - Comma-separated ticker symbols (e.g., `AAPL,MSFT,GOOGL,NVDA`)
- `--top` - Number of top results to return (default: 30)
- `--period` - Historical period: 3mo, 6mo, 12mo (default: 12mo for SMA200 calculation)
- `--min-score` - Filter: only return results with score >= threshold

## Scoring System v2 (max ~11.5 points)

### Core Trend (max 4.5)

| Indicator | Condition | Points |
|-----------|-----------|--------|
| SMA20 | Price > SMA20 | +1.0 |
| SMA50 | Price > SMA50 | +1.0 |
| SMA200 | Price > SMA200 (bull market) | +1.5 |
| SMA200 | Price < SMA200 | **HARD-CAP score at 3.0** |

### Momentum Indicators (max 2.5)

| Indicator | Condition | Points |
|-----------|-----------|--------|
| RSI | 55-70 (sweet spot) | +1.0 |
| | 45-55 (neutral) | +0.5 |
| | 70-80 (strong, caution) | +0.25 |
| | >80 with ADX < 20 | **-0.5** (overbought penalty) |
| | >80 with ADX ≥ 20 | +0.25 (strong trend) |
| | 30-45 (weak) | +0.25 |
| | <30 (oversold) | +0.25 |
| MACD | MACD > Signal | +1.0 |
| | Histogram rising | +0.5 |

### Trend Strength (max 1.5 / min -0.5)

| Indicator | Condition | Points |
|-----------|-----------|--------|
| ADX | >25 with +DI > -DI (strong trend) | +1.5 |
| | +DI > -DI only | +0.5 |
| | <15 with -DI > +DI (directionless) | **-0.5** |

### Trend Consistency (max 2.0, replaces v1 momentum)

| Condition | Points |
|-----------|--------|
| 20/20 days above SMA20 | +2.0 |
| 15/20 days | +1.5 |
| 10/20 days | +1.0 |
| 5/20 days | +0.5 |

### Volume & Breakout (max 2.0)

| Indicator | Condition | Points |
|-----------|-----------|--------|
| OBV | OBV > OBV_SMA20 (accumulation) | +0.5 |
| RVOL | > 1.3x on up-close day | +0.5 |
| Breakout | Current high ≥ 20-day high | +1.0 |

### Penalties

| Condition | Points |
|-----------|--------|
| Price > 2× ATR above SMA20 (overextended) | **-0.5** |

## Trend Stage Classification

Each result includes a `trend_stage` field based on ATR-normalized distance from SMA20:

| Stage | Condition | Meaning |
|-------|-----------|---------|
| `early` | Just crossed SMA20 or < 0.5× ATR above | Fresh breakout, highest reward potential |
| `mid` | 0.5–2.0× ATR above SMA20, SMA20 > SMA50 | Healthy trend, ideal entry zone |
| `extended` | > 2.0× ATR above SMA20 | Stretched, higher pullback risk |
| `below` | Price below SMA20 | Not in uptrend |

## Output

Returns JSON with:
- `scan_date` - Timestamp of scan
- `scoring_version` - "2.0"
- `score_max` - Maximum possible score (11.5)
- `symbols_scanned` - Total symbols analyzed
- `results` - Array sorted by score (highest first):
  - `symbol`, `score`, `normalized_score` (0-1), `price`
  - `trend_stage` (early/mid/extended/below)
  - `breakout_signal` (true/false)
  - `volume_confirmed` (true/false)
  - `obv_trend` (rising/falling)
  - `relative_volume`, `trend_consistency` (0.0-1.0)
  - `next_earnings`, `earnings_timing` (BMO/AMC)
  - `period_return_pct`, `pct_from_sma20`, `pct_from_sma50`, `pct_from_sma200`
  - `rsi`, `macd`, `adx`, `dmp`, `dmn`
  - `signals` - List of triggered conditions

## Examples

```bash
# Scan with defaults (12mo period for SMA200)
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA,TSLA

# Top 10 with minimum score filter
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA,TSLA,AMD,AMZN,META --top 10 --min-score 5

# Shorter period (note: SMA200 won't be available with 3mo)
uv run python scripts/scan.py AAPL,MSFT,GOOGL --period 6mo
```

## Interpretation (Normalized Score)

| Normalized | Raw Score | Meaning |
|------------|-----------|---------|
| > 0.70 | > 8.0 | Strong bullish — all indicators aligned + volume |
| 0.50–0.70 | 5.5–8.0 | Moderate bullish — most indicators positive |
| 0.30–0.50 | 3.0–5.5 | Neutral/weak — mixed signals |
| < 0.30 | < 3.0 | Bearish — below SMA200 or very weak |

## Dependencies

- `pandas`
- `pandas-ta`
- `yfinance`
