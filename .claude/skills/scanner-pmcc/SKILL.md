---
name: scanner-pmcc
description: Scan stocks for Poor Man's Covered Call (PMCC) suitability. Analyzes LEAPS and short call options for delta, liquidity, spread, IV, and yield. Use when user asks about PMCC candidates, diagonal spreads, or LEAPS strategies.
---

# PMCC Scanner

Finds optimal Poor Man's Covered Call setups by scoring symbols on option chain quality.

## What is PMCC?

Buy deep ITM LEAPS call (delta ~0.80) + Sell short-term OTM call (delta ~0.20) against it. Cheaper alternative to covered calls.

## Workflow (Tradier-first)

**Always use Tradier MCP for option chains.** yfinance is not used — Tradier provides real market Greeks (delta, IV) with no stale/NaN data issues.

For each symbol, the sequence is:

1. **Get stock price** — call `stock_quote(symbol)` or use Tradier `get_quote`
2. **Get option expiries** — call Tradier `get_option_expirations(symbol, includeAllRoots=true, strikes=false)`
3. **Select LEAPS expiry** — pick the expiry closest to 452 DTE within 365–540 day range; fallback: nearest ≥ 270 days
4. **Select short expiry** — pick the nearest expiry with 21–45 DTE; fallback: 7–21 DTE
5. **Fetch LEAPS chain** — call Tradier `get_options_chain(symbol, leaps_expiry, greeks=true)`
6. **Fetch short chain** — call Tradier `get_options_chain(symbol, short_expiry, greeks=true)`
7. **Call scan_pmcc MCP tool** — pass all Tradier data as JSON strings:

```
scan_pmcc(
  symbol = "AAPL",
  tradier_leaps_chain_json = "<json string of LEAPS chain>",
  tradier_leaps_expiry = "2027-01-15",
  tradier_short_chain_json = "<json string of short chain>",
  tradier_short_expiry = "2026-04-25",
  tradier_price = 195.50
)
```

## Arguments

- `symbol` — comma-separated tickers for batch (Tradier data params apply to all when provided; use single-symbol calls for best results with Tradier)
- `tradier_leaps_chain_json` — raw JSON string from Tradier get_options_chain (LEAPS expiry)
- `tradier_short_chain_json` — raw JSON string from Tradier get_options_chain (short expiry)
- `tradier_leaps_expiry` — LEAPS expiration date (YYYY-MM-DD)
- `tradier_short_expiry` — short expiration date (YYYY-MM-DD)
- `tradier_price` — current stock price

## Scoring System (raw max = 13, normalized to 0–10)

| Category | Condition | Points |
|----------|-----------|--------|
| **LEAPS Delta** | Within ±0.05 of 0.80 | +2 |
| | Within ±0.10 | +1 |
| **Short Delta** | Within ±0.05 of 0.20 | +1 |
| | Within ±0.10 | +0.5 |
| **Delta Spread** | ≥ 0.55 | +1 |
| | ≥ 0.45 | +0.5 |
| **LEAPS OI** | ≥ 500 | +1 |
| | ≥ 100 | +0.5 |
| **Short OI** | ≥ 1000 | +1 |
| | ≥ 200 | +0.5 |
| **LEAPS Spread** | < 10% | +1 |
| | < 15% | +0.5 |
| **Short Spread** | < 10% | +1 |
| | < 20% | +0.5 |
| **IV (LEAPS)** | 25–40% sweet spot | +2 |
| | 20–25% or 40–50% | +1 |
| **Realistic Yield** | ≥ 35% annualized | +2 |
| | ≥ 20% | +1 |
| | ≥ 10% | +0.5 |
| **Downside Protection** | ≥ 15% to breakeven | +1 |
| | ≥ 8% | +0.5 |
| **Penalties** | Earnings within short window | −2 |
| | Short strike < 3% OTM | −0.5 |

## Hard Rejects

- LEAPS OI < 20 (illiquid)
- LEAPS spread > 25% (untradeable)
- Short call bid = 0 (no executable price)
- IV < 5% (implausible data)
- No expiry ≥ 270 days (LEAPS unavailable)
- No expiry with 7–45 DTE (no short leg)

## Output

Returns JSON with:
- `symbol`, `price`, `leaps_iv_pct`, `short_iv_pct`, `pmcc_score` (0–10)
- `earnings_date`, `earnings_risk`
- `leaps` — expiry, days, strike, delta, bid/ask/mid, spread_pct, volume, OI, intrinsic, extrinsic
- `short` — expiry, days, strike, delta, bid/ask/mid, spread_pct, volume, OI
- `metrics` — net_debit, max_loss, breakeven_price, pct_to_breakeven, annual_yield_theoretical_pct, annual_yield_realistic_pct, capital_required, delta_spread
- `risk_flags` — list of warnings

## Interpretation

- Score ≥ 8: Excellent candidate
- Score 6–7.9: Good candidate
- Score 4–5.9: Acceptable with caveats
- Score < 4: Poor liquidity or structure

## Key Constraints

- Short strike **must be above** LEAPS strike
- LEAPS target DTE: 452 days (midpoint of 12–18 month range)
- Short target DTE: 21–45 days (TastyTrade standard)
- Realistic yield uses 65% bid capture rate (accounts for slippage)
- Breakeven = LEAPS strike + (LEAPS mid − short bid)
