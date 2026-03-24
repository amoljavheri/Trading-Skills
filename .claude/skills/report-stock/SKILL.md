---
name: report-stock
description: >
  Generate a comprehensive stock analysis report (PDF or markdown) with full technical analysis,
  fundamentals, REAL live option chain data (via Tradier MCP), LEAP call scenarios with actual
  bid/ask prices, cash secured put (CSP) analysis with real premiums and greeks, PMCC viability,
  option spread strategies, and an overall 1-10 bullish conviction score.
  Use this skill whenever the user asks for a full stock report, deep-dive analysis, or wants to
  know if a stock is a good candidate for options strategies like LEAPs, CSP, or PMCC.
  Trigger on phrases like: "run report-stock on X", "give me a full stock report for X",
  "analyze X completely", "stock analysis report for X", "is X a good LEAP candidate",
  "deep dive on X", "full analysis of X", "comprehensive report on X", "should I buy LEAPs on X",
  "is X good for cash secured puts", "CSP analysis for X", "PMCC analysis for X",
  "find CSP candidates", "find PMCC candidates", "options analysis for X",
  or any request for thorough/complete analysis of a stock.
user_invocable: true
arguments:
  - name: symbols
    description: Stock ticker symbol(s) — single or space-separated list (e.g., AAPL or "AAPL MSFT GOOGL")
    required: true
dependencies: ["trading-skills"]
---

# Stock Analysis Report Generator

Generates professional, comprehensive reports covering trend analysis, fundamentals, PMCC viability,
LEAP call scenarios with **real Tradier option prices**, Cash Secured Put (CSP) analysis with
**actual bid/ask premiums and live greeks**, option spread strategies, market context, and an
overall 1-10 bullish conviction score. Supports PDF and markdown output formats.

**All scoring, CSP analysis, LEAP scenarios, and market context are computed in Python.**
Claude's role is to: (1) fetch Tradier data, (2) pass it to the script, (3) format the output.

---

## Step 1: Fetch Tradier Live Data (MCP)

Use Tradier MCP tools to get **live option prices, greeks, and IV**.

### A. Live Stock Quote
```
get_market_quotes(symbols="SYMBOL")
```
Use the returned `last` price as the definitive current price.

### B. Find Target Expiry Dates
```
get_option_expirations(symbol="SYMBOL")
```
From the list, select:
- **CSP/Spread expiry**: closest to **30–45 DTE** from today
- **LEAPS expiry**: closest to **250–400 DTE** (prefer Jan LEAPS if available)

### C. Fetch Near-Term Option Chain (CSP, Spreads, Stock IV)
```
get_options_chain(symbol="SYMBOL", expiration="CSP-EXPIRY-DATE", greeks=true)
```

### D. Fetch LEAPS Option Chain (LEAP Scenarios, PMCC)
```
get_options_chain(symbol="SYMBOL", expiration="LEAPS-EXPIRY-DATE", greeks=true)
```

**Fallback**: If Tradier returns no data, skip Tradier flags — the script uses yfinance estimates,
clearly labeled as "Estimated".

---

## Step 2: Run Report Script

```bash
uv run python scripts/report.py SYMBOL \
  --tradier-quote-json 'QUOTE_JSON' \
  --tradier-chain-json 'CHAIN_JSON' \
  --tradier-leaps-json 'LEAPS_JSON'
```

All flags are optional. Without Tradier data, the script uses yfinance.

**Returns JSON with all computed sections:**

| Section | Key | Description |
|---------|-----|-------------|
| Recommendation | `recommendation` | Strengths, risks, recommendation level |
| Conviction Score | `conviction_score` | 0-10 score with 8 components, dimensional breakdown, signal alignment |
| Company | `company` | Name, sector, industry, market cap, beta |
| Market Context | `market_context` | SPY trend, VIX proxy, sector ETF trend |
| Trend Analysis | `trend_analysis` | Bullish score, RSI, MACD, ADX, SMA levels, v2 signals |
| PMCC Analysis | `pmcc_analysis` | PMCC score, IV%, LEAPS/short details, trade metrics |
| Fundamentals | `fundamentals` | Valuation, profitability, dividend, balance sheet, earnings history |
| Piotroski | `piotroski` | F-Score with all 9 criteria pass/fail |
| Support Levels | `support_levels` | SMA50, SMA200, swing lows for CSP context |
| Spread Strategies | `spread_strategies` | Bull call, bear put, straddle, strangle, iron condor |
| Data Sources | `data_sources` | Tradier vs yfinance, definitive price, discrepancy % |

---

## Step 3: Compute CSP & LEAP Analysis (if Tradier data available)

When Tradier chain data is available, Claude should also call the Python functions directly
or use the JSON data to populate these sections. The script provides the framework —
supplement with Tradier-specific data in the report template.

**CSP tiers** are delta-based (0.15/0.25/0.35) and computed by `analyze_csp()`.
**LEAP scenarios** use Taylor expansion and are computed by `analyze_leap_scenarios()`.

---

## Step 4: Generate Report

Choose output format based on user preference:

**Markdown** (default): Read `templates/markdown-template.md` for full formatting instructions.
Save to `sandbox/` with filename: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md`

**PDF**: Use the `pdf` skill and read `templates/pdf-template.md`.
Save to `sandbox/` with filename: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.pdf`

---

## Step 5: Report Results to User

After generating, tell the user:
1. **Overall Conviction Score** (X/10) with one-line verdict and dimensional breakdown
2. **Signal alignment** — aligned / mixed / conflicting (with conflict explanations)
3. **Top trade setup** — best options strategy given conditions (CSP / LEAP / PMCC / Spread)
4. **Key risk to watch**
5. **File path** of the saved report

---

## Full Report Sections

| # | Section | Key Data |
|---|---------|----------|
| 1 | Executive Summary | Conviction score, recommendation, company overview |
| 2 | Market Context | SPY trend, VIX regime, sector trend |
| 3 | Technical Analysis | RSI, MACD, ADX, SMA20/50/200, trend stage, v2 signals |
| 4 | Fundamental Analysis | Valuation, profitability, balance sheet, earnings history |
| 5 | Piotroski F-Score | All 9 criteria pass/fail |
| 6 | Overall Conviction Score | 8-component scoring table with dimensional breakdown |
| 7 | LEAP Call Scenarios | Real/estimated prices, scenario table, break-even, probability |
| 8 | Cash Secured Put (CSP) | Delta-based 3-tier strikes, yields, suitability with market regime |
| 9 | PMCC Viability | Score, LEAPS/short details, trade metrics |
| 10 | Option Spread Strategies | Bull call, bear put, straddle, strangle, iron condor |
| 11 | Investment Summary | Strengths, risks, disclaimer |

---

## Dependencies

This skill aggregates data from:
- `scanner-bullish` → RSI, MACD, ADX, SMA trend analysis (v2 with volume, breakout, consistency)
- `scanner-pmcc` → PMCC viability score, spread strategies
- `fundamentals` → financial ratios, Piotroski, earnings history
- **Tradier MCP** → real-time option chain, live greeks, IV, bid/ask prices
