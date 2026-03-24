---
name: stock-quote
description: Get real-time stock quote with price, volume, change, market cap, and 52-week range for any ticker symbol. Use when user asks about current stock price, quote, or basic stock info.
dependencies: ["trading-skills"]
---

# Stock Quote

Fetch current stock data — Tradier MCP is the primary source; Yahoo Finance is the fallback.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

### Step 1 — Fetch live quote from Tradier MCP

Call the Tradier MCP tool with the requested symbol:

```
get_market_quotes(symbols="SYMBOL")
```

Save the full JSON result returned by the tool.

### Step 2 — Run script with Tradier data

Pass the Tradier JSON to the script:

```bash
uv run python scripts/quote.py SYMBOL --tradier '<tradier_json>'
```

Replace `SYMBOL` with the ticker (e.g., AAPL, MSFT, TSLA) and `<tradier_json>` with the raw JSON string from Step 1.

### Fallback — Yahoo Finance (if Tradier unavailable)

If Tradier MCP is unavailable or returns an error, run without the `--tradier` flag:

```bash
uv run python scripts/quote.py SYMBOL
```

## Output

The script outputs JSON with:
- `symbol`, `name`, `price`, `change`, `change_percent`
- `volume`, `avg_volume`
- `high_52w`, `low_52w`
- `market_cap`, `pe_ratio`, `dividend_yield`, `beta` *(null when source is `tradier` — not provided by Tradier quotes endpoint)*
- `source` — `"tradier"` or `"yfinance"`

Present the data in a readable format. Highlight significant moves (>2% change).

## Dependencies

- Tradier MCP (`get_market_quotes`) — primary
- `yfinance` — fallback
