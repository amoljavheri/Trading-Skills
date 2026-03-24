---
name: option-chain
description: Get option chain data including calls and puts with strikes, bids, asks, volume, open interest, and implied volatility. Use when user asks about options, option prices, calls, puts, or option chain for a specific expiration date.
dependencies: ["trading-skills"]
---

# Option Chain

Fetch option chain data with real market Greeks via Tradier MCP (primary), or Yahoo Finance (fallback).

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

### Tradier MCP Workflow (Primary — Real Greeks)

**Step 1 — Get available expiry dates:**
```
Call: get_option_expirations(symbol="AAPL")
```

**Step 2 — Get the underlying price:**
```
Call: get_market_quotes(symbols="AAPL")
```
Extract `last` or `bid`/`ask` mid from the response.

**Step 3 — Fetch the options chain with Greeks:**
```
Call: get_options_chain(symbol="AAPL", expiration="2026-04-17", greeks=true)
Save JSON response to: sandbox/AAPL_chain_2026-04-17.json
```

**Step 4 — Parse and format:**
```bash
uv run python scripts/options.py AAPL \
  --tradier-json sandbox/AAPL_chain_2026-04-17.json \
  --expiry 2026-04-17 \
  --underlying-price 248.50
```

### yfinance Fallback (No Real Greeks)

**List available expiry dates:**
```bash
uv run python scripts/options.py AAPL --expiries
```

**Fetch chain for a specific expiry:**
```bash
uv run python scripts/options.py AAPL --expiry 2026-04-17
```

## Arguments

| Flag | Description |
|------|-------------|
| `SYMBOL` | Ticker symbol (e.g., AAPL, SPY, TSLA) |
| `--expiries` | List available expiration dates (yfinance fallback only) |
| `--expiry YYYY-MM-DD` | Expiry date to fetch |
| `--tradier-json FILE` | Path to saved Tradier chain JSON (enables real Greeks) |
| `--underlying-price PRICE` | Current stock price (required with `--tradier-json`) |

## Output

Returns JSON with:
- `symbol`, `source` (`tradier` or `yfinance`), `expiry`, `underlying_price`
- `calls` / `puts` — arrays of option rows:

| Field | Description |
|-------|-------------|
| `strike` | Strike price |
| `bid` / `ask` / `mid` | Market prices |
| `lastPrice` | Last traded price |
| `volume` / `openInterest` | Activity |
| `impliedVolatility` | IV as percentage (e.g., 38.0 = 38%) |
| `inTheMoney` | Boolean |
| `delta` | Real market delta (Tradier only; `null` from yfinance) |
| `gamma` | Real market gamma (Tradier only) |
| `theta` | Real market theta (Tradier only) |
| `vega` | Real market vega (Tradier only) |
| `prob_profit_pct` | `(1 - abs(delta)) × 100` — probability of expiring OTM |
| `spread_pct` | `(ask - bid) / mid × 100` — bid/ask spread quality |

Present data as a table. Highlight:
- High volume/OI strikes (liquidity anchors)
- Notable IV levels (premium opportunities)
- `prob_profit_pct` for quick probability assessment
- `spread_pct` > 10% warns of poor liquidity

## Data Source

| Source | Greeks | Data Quality |
|--------|--------|--------------|
| Tradier MCP | Real market Greeks | Live bid/ask |
| yfinance | None (null) | Delayed, unofficial |

## Dependencies

- `pandas`
- `yfinance`
