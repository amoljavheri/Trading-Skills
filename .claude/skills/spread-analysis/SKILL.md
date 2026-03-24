---
name: spread-analysis
description: Analyze option spread strategies like vertical spreads, iron condors, straddles, strangles. Use when user asks about spreads, multi-leg strategies, vertical spread, iron condor, straddle, strangle, or strategy analysis.
dependencies: ["trading-skills"]
---

# Spread Analysis

Analyze multi-leg option strategies with real market Greeks via Tradier MCP (primary), or Yahoo Finance (fallback).

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

### Tradier MCP Workflow (Primary — Real Greeks)

**Step 1 — Fetch the options chain from Tradier:**
```
Call: get_options_chain(symbol="AAPL", expiration="2026-04-17", greeks=true)
Save JSON response to: sandbox/AAPL_chain_2026-04-17.json
```

**Step 2 — Get the underlying price:**
```
Call: get_market_quotes(symbols="AAPL")
```

**Step 3 — Run spread analysis with real Greeks:**
```bash
uv run python scripts/spreads.py AAPL --strategy vertical \
  --expiry 2026-04-17 --type call \
  --long-strike 180 --short-strike 185 \
  --tradier-json sandbox/AAPL_chain_2026-04-17.json \
  --underlying-price 248.50
```

### yfinance Fallback (No Real Greeks)

```bash
uv run python scripts/spreads.py AAPL --strategy vertical \
  --expiry 2026-04-17 --type call --long-strike 180 --short-strike 185
```

## Strategies

**Vertical Spread** (bull/bear call/put spread):
```bash
uv run python scripts/spreads.py AAPL --strategy vertical \
  --expiry 2026-04-17 --type call --long-strike 180 --short-strike 185 \
  [--tradier-json FILE --underlying-price PRICE]
```

**Diagonal Spread** (different expiries — PMCC, calendar):
```bash
uv run python scripts/spreads.py AAPL --strategy diagonal \
  --type call \
  --long-expiry 2027-01-16 --long-strike 180 \
  --short-expiry 2026-04-17 --short-strike 190 \
  [--tradier-json-long sandbox/AAPL_chain_2027-01-16.json \
   --tradier-json-short sandbox/AAPL_chain_2026-04-17.json \
   --underlying-price PRICE]
```

**Straddle** (long call + long put at same strike):
```bash
uv run python scripts/spreads.py AAPL --strategy straddle \
  --expiry 2026-04-17 --strike 185 \
  [--tradier-json FILE --underlying-price PRICE]
```

**Strangle** (long OTM call + OTM put):
```bash
uv run python scripts/spreads.py AAPL --strategy strangle \
  --expiry 2026-04-17 --put-strike 175 --call-strike 195 \
  [--tradier-json FILE --underlying-price PRICE]
```

**Iron Condor** (sell strangle + buy wider strangle):
```bash
uv run python scripts/spreads.py AAPL --strategy iron-condor \
  --expiry 2026-04-17 \
  --put-long 165 --put-short 175 --call-short 195 --call-long 205 \
  [--tradier-json FILE --underlying-price PRICE]
```

## Arguments

| Flag | Description |
|------|-------------|
| `SYMBOL` | Ticker symbol |
| `--strategy` | `vertical`, `diagonal`, `straddle`, `strangle`, `iron-condor` |
| `--expiry` | Expiry date YYYY-MM-DD (single expiry strategies) |
| `--long-expiry` / `--short-expiry` | Expiry dates for diagonal |
| `--type` | `call` or `put` |
| `--strike` | Strike for straddle |
| `--long-strike` / `--short-strike` | Strikes for vertical/diagonal |
| `--put-strike` / `--call-strike` | Strikes for strangle |
| `--put-long` / `--put-short` / `--call-short` / `--call-long` | Strikes for iron condor |
| `--tradier-json FILE` | Tradier chain JSON (primary expiry) |
| `--tradier-json-long FILE` | Tradier chain JSON for long/back-month expiry (diagonal) |
| `--tradier-json-short FILE` | Tradier chain JSON for short/front-month expiry (diagonal) |
| `--underlying-price PRICE` | Current stock price (required with Tradier) |

## Output

Returns JSON with strategy-specific fields:

**All strategies include:**
- `symbol`, `source` (`tradier` or `yfinance`), `strategy`, `direction`, `expiry`
- `underlying_price`
- `legs` — each leg has: `action` (buy/sell), `strike`, `type`, `bid`, `ask`, `mid`, `iv`
  - **Tradier only:** `delta`, `gamma`, `theta`, `vega`

**Strategy-specific metrics:**

| Strategy | Key Metrics |
|----------|-------------|
| Vertical | `net_debit`, `max_profit`, `max_loss`, `breakeven`, `risk_reward` |
| Diagonal | `net_debit`, `max_loss`, `short_premium_collected` |
| Straddle | `total_cost`, `max_loss`, `breakeven_up`, `breakeven_down`, `move_needed_pct` |
| Strangle | `total_cost`, `max_loss`, `breakeven_up`, `breakeven_down` |
| Iron Condor | `net_credit`, `max_profit`, `max_loss`, `breakeven_up`, `breakeven_down`, `profit_range` |

Explain the risk/reward, directional bias, and when this strategy is appropriate given current market conditions.

## Data Source

| Source | Greeks per leg | Data Quality |
|--------|----------------|--------------|
| Tradier MCP | Real market delta/gamma/theta/vega | Live bid/ask |
| yfinance | None (null) | Delayed, unofficial |

## Dependencies

- `pandas`
- `yfinance`
