---
name: roll-manager
description: >
  Analyze and optimize rolling decisions for existing short option positions
  (Covered Calls and Cash Secured Puts). Classifies each position by moneyness
  and risk, applies decision engine rules (profit capture, DTE, ITM logic, delta
  risk, theta preservation, earnings guards), and finds specific roll targets
  with exact strikes, prices, and net credit/debit calculations from live
  Tradier option chain data.
  Use when the user asks: "should I roll my options", "check my options for
  rolling", "roll manager", "roll analysis", "manage my expiring options",
  "what should I do with my ITM calls", "assignment risk check",
  "roll my covered calls", "optimize my options positions", or any request
  about managing existing short options.
dependencies: ["trading-skills"]
---

# Roll Manager

Analyzes existing short option positions and recommends optimal rolling, closing, or expiration actions. Unlike the basic `rolling_checks.py` (which only flags positions), this skill finds **specific roll targets** with exact strikes, prices, and net credit/debit calculations.

## Step 1: Parse Portfolio

Reuse `parse_etrade.py` from portfolio-income-plan:

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/parse_etrade.py \
  --csv "C:/Users/amolj/Downloads/Portfolio_*.csv"
```

Save output to `sandbox/portfolio.json`.

## Step 2: Fetch Live Quotes

For each underlying symbol in the portfolio's short option positions:

```
get_market_quotes(symbols="NVDA,AMD,AAPL")
```

Save as `sandbox/current_prices.json`:
```json
{"NVDA": 255.50, "AMD": 165.20, "AAPL": 248.75}
```

## Step 3: Fetch Earnings Calendar

For each underlying, check earnings dates using Finnhub MCP or preflight data.

Save as `sandbox/earnings_dates.json`:
```json
{
  "NVDA": {"date": "2026-04-23", "days_away": 33},
  "AMD": {"date": "2026-05-05", "days_away": 45}
}
```

## Step 4: Fetch Option Chains

For each underlying symbol with short options:

1. Call `get_option_expirations(symbol)` to find available expiry dates
2. Select current position's expiry + next 2-3 monthly expiries
3. Call `get_options_chain(symbol, expiration, greeks=true)` for each
4. Save each to `sandbox/chains/SYMBOL_EXPIRY.json`

Example:
```
get_options_chain(symbol="NVDA", expiration="2026-04-17", greeks=true)
→ save to sandbox/chains/NVDA_2026-04-17.json

get_options_chain(symbol="NVDA", expiration="2026-05-16", greeks=true)
→ save to sandbox/chains/NVDA_2026-05-16.json
```

## Step 5: Run Roll Analyzer

```bash
uv run python .claude/skills/roll-manager/scripts/roll_analyzer.py \
  --portfolio sandbox/portfolio.json \
  --prices sandbox/current_prices.json \
  --chains-dir sandbox/chains/ \
  --assignment-mode neutral \
  --earnings sandbox/earnings_dates.json
```

### Parameters

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--portfolio` | Yes | — | Path to parse_etrade.py JSON output |
| `--prices` | Yes | — | Path to {symbol: price} JSON |
| `--chains-dir` | Yes | — | Directory with SYMBOL_EXPIRY.json chain files |
| `--profit-target` | No | 50.0 | Profit capture % threshold |
| `--max-debit` | No | 0.50 | Max acceptable net debit per contract |
| `--assignment-mode` | No | neutral | `avoid` / `neutral` / `wheel` |
| `--trend-overrides` | No | — | {symbol: trend_class} JSON from preflight |
| `--earnings` | No | — | {symbol: {date, days_away}} JSON |

## Step 6: Present Results

Display results ordered by urgency (highest first). For each position:

1. **Position summary**: symbol, type, strike, expiry, strategy (CC/CSP), moneyness
2. **Action**: CLOSE_EARLY, ROLL_OUT, ROLL_OUT_AND_UP, ROLL_OUT_AND_DOWN, LET_EXPIRE, HOLD
3. **Why now**: Human-readable temporal trigger explanation
4. **Roll targets** (if applicable): ranked by quality score with net credit/debit
5. **Warnings**: earnings, premium erosion, hold-for-upside flags

## Decision Rules

| # | Condition | Action | Urgency |
|---|-----------|--------|---------|
| 1 | Profit >= target% (theta guard: if <10% of premium remains and DTE<=10, let expire) | CLOSE_EARLY or LET_EXPIRE | 1 or 0 |
| 2 | DTE <= 5, OTM by >3% | LET_EXPIRE | 0 |
| 3 | DTE <= 5, within 3% of strike | ROLL_OUT | 2 |
| 4 | ITM CC, low extrinsic (<$0.25) or delta >0.70 | ROLL_OUT_AND_UP | 2 |
| 5 | ITM CC, good extrinsic | HOLD | 0 |
| 6 | ITM CSP, wheel mode + bullish | LET_EXPIRE (accept assignment) | 1 |
| 6b | ITM CSP, avoid mode | ROLL_OUT_AND_DOWN | 2 |
| 7 | ITM CSP, bearish/neutral | ROLL_OUT_AND_DOWN | 2 |
| 8 | Delta >0.60, DTE <= 14 | HOLD (warning) | 1 |
| 9 | Default | HOLD | 0 |

## Assignment Mode Guide

| Mode | Behavior | Best For |
|------|----------|----------|
| `avoid` | Always roll ITM positions to avoid assignment | Traders who want to keep their shares/cash |
| `neutral` | Roll bearish/neutral ITM; accept bullish ITM CSPs | Default balanced approach |
| `wheel` | Accept ITM CSP assignment on bullish stocks | Wheel strategy practitioners |

## Roll Quality Score (0-10)

| Component | Points | Logic |
|-----------|--------|-------|
| Net credit | 0-4 | -$0.50 debit=0, $0=2, >=$1.00=4 |
| Delta improvement | 0-2 | Closer to target delta range center |
| Theta pickup | 0-1.5 | More negative theta = more daily income |
| Liquidity | 0-1.5 | Spread <5% (+0.5), OI >500 (+0.5), volume >0 (+0.5) |
| DTE sweet spot | 0-1 | 21-45 DTE=1.0, 14-21 or 45-60=0.5 |

## Execution Notes

When a roll has poor execution characteristics (wide spread > 10% or net credit < $0.10):

**CLOSE_AND_REOPEN** — The system recommends executing as two separate trades:
1. Close current position with a limit order at mid price
2. Wait for fill, then sell new contract separately

This typically saves $0.10-0.30/contract vs. a single roll order.

## Config Constants

All tunable thresholds are at the top of `roll_analyzer.py`:

| Constant | Default | Purpose |
|----------|---------|---------|
| `PROFIT_TARGET_PCT` | 50.0 | Profit capture threshold |
| `THETA_EXIT_PCT` | 0.10 | Let expire below 10% of original premium |
| `THETA_EXIT_MAX_DTE` | 10 | Theta exit only when DTE <= 10 |
| `EARNINGS_BLOCK_DAYS` | 14 | Hard-block rolls within 14d of earnings |
| `PREMIUM_EROSION_PCT` | 0.005 | Flag exit when premium < 0.5% of capital |
| `CLOSE_REOPEN_SPREAD_PCT` | 10.0 | Suggest 2-trade execution above 10% |

## Key Rules

1. **Never roll into earnings** — targets within 14 days of earnings are disqualified (unless wheel mode)
2. **Net credit preferred** — rolls with net debit > $0.50/contract are marked disqualified
3. **Theta preservation** — don't close options worth <10% of original premium with <=10 DTE; let theta finish
4. **Premium erosion warning** — flag positions where premium received < 0.5% of capital at risk (likely over-rolled)
5. **Deep ITM fallback** — when no credit roll exists, suggest accept-assignment or roll-for-debit alternatives
6. **Strong bull hold** — ITM CC in strong uptrend gets hold_for_upside flag instead of auto-roll

## Dependencies

**Python packages**: json, argparse, os, sys, datetime, statistics (all stdlib)

**Shared imports**: `shared_utils.py` (classify_earnings_risk), `extract_strikes.py` (DELTA_RANGES) from portfolio-income-plan

**MCP tools**: Tradier MCP (get_market_quotes, get_option_expirations, get_options_chain), Finnhub MCP (GetEarningsCalendar)
