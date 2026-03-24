---
name: portfolio-income-plan
description: >
  Generate a 4-week options income plan from an E*Trade portfolio CSV.
  Reads the latest CSV from the Etrade Files folder, identifies all stock positions
  and existing option positions, fetches LIVE option chain prices via Tradier MCP,
  and produces a week-by-week covered call (CC) and cash secured put (CSP) income
  plan with real bid/ask premiums, annualized yields, earnings conflict warnings,
  and new large-cap candidate recommendations (CSP-first wheel opportunities).
  Use this skill whenever the user asks for: "income plan", "weekly options plan",
  "what covered calls should I sell", "portfolio income strategy", "4-week plan",
  "what options can I sell on my portfolio", "generate income from my stocks",
  "covered call plan", "CSP plan", or "options income from my E*Trade account".
  Always trigger when user mentions portfolio + income + options in the same request.
user_invocable: true
dependencies: ["trading-skills"]
---

# Portfolio Income Plan Generator

Reads your E*Trade portfolio CSV → runs pre-flight checks (earnings, trends, budget) →
fetches live Tradier option prices → generates a 4-week covered call + cash secured put
income plan with **real market prices** and **delta-based strike selection**.

---

## Folder & File Convention

**CSV Location**: `C:\Claude Projects\Copied Skills Project\trading_skills\Etrade Files\`

Always use the **most recently modified** CSV file in that folder.
If multiple CSVs exist, pick the one with the latest modified date.

---

## Step 1: Parse the E*Trade Portfolio CSV

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/parse_etrade.py
```

This script automatically:
- Finds the latest CSV in `Etrade Files/`
- Parses stock positions (symbol, quantity, cost_basis_per_share, current_value)
- Parses existing option positions (underlying, type, strike, expiry, quantity)
- Separates cash/buying power from equity
- Returns structured JSON

**Save the output** to `sandbox/portfolio.json` for use in later steps.

---

## Step 2: Get Live Quotes for All Positions

Use Tradier MCP to get current prices for all stocks:

```
get_market_quotes(symbols="NVDA,SOFI,MSTR,GAP,SOXQ,INTC,AMD,...")
```

Use the returned `last` price as the definitive current price.
Compare with CSV cost basis to determine P&L status.

---

## Step 2.5: Run Pre-Flight Checks

**This is a critical step — run BEFORE fetching any option chains.**

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/preflight_checks.py \
  --file sandbox/portfolio.json
```

This returns:
- **Market regime** (`market_regime`): QQQ vs SMA200 + VXN level — top-down filter applied to all CSP decisions
- **Earnings risks** per stock (BLOCK / SHORT_DTE_ONLY / SAFE + safe expiry dates)
- **Per-stock trend** class (strong_bull / bull / neutral / bear / strong_bear) — now uses SMA200 hard cap
- **Position sizing budget** (usable cash, max per CSP, max total CSPs)
- **Existing options map** (to avoid duplicate strikes)
- **CC-eligible stocks** (100+ shares only)

### 🌍 Market Regime Rules (Backtest-Validated)

The preflight now checks `market_regime.warning` first. Apply these rules BEFORE any strike selection:

| QQQ vs SMA200 | VXN Level | Delta Adjustment | Action |
|---|---|---|---|
| Above SMA200 | < 25 (normal) | None — use standard | Proceed normally |
| Above SMA200 | 25–35 (high) | Reduce one tier | e.g. 0.20 → 0.15 |
| Below SMA200 | Any | Reduce one tier | e.g. 0.20 → 0.15 |
| Below SMA200 | 25–35 (high) | Reduce two tiers | e.g. 0.20 → 0.10 |
| Any | ≥ 35 (extreme) | **SKIP all new CSPs** | Hold cash, wait for VXN < 30 |

> **Why this matters**: Backtest over 3 years showed CSP assignment rate jumps from **13% (bull)** to **30% (bear)** when QQQ is below its 200-day MA. A single bear-market assignment cluster can wipe out 10+ weeks of premium.

Use these results to drive ALL subsequent decisions:
- Check `market_regime.warning` first — if VXN ≥ 35, stop and hold cash
- Apply delta tier adjustment from `market_regime.recommended_delta_tier`
- Skip stocks with earnings risk = BLOCK
- Use trend class as `--trend` parameter in extract_strikes.py (SMA200 hard cap already applied)
- Respect budget limits when selecting CSPs
- Don't suggest strikes that duplicate existing options
- Check `stress_test.stress_pass` — if False, reduce CSP exposure before adding new ones
- Check sector concentration — no single sector should exceed 30% of total CSP capital

### 🔴 Assignment Stress Test

Preflight now includes a `stress_test` section that models simultaneous assignment of all open short puts:

```json
{
  "stress_test": {
    "total_assignment_capital": 85000,
    "cash_available": 100000,
    "shortfall": 0,
    "coverage_pct": 117.6,
    "stress_pass": true,
    "recommendation": "OK — cash covers all simultaneous assignments"
  }
}
```

If `stress_pass` is **false**, the plan MUST flag this prominently and recommend reducing CSP exposure
before adding new positions. A shortfall means a simultaneous assignment event could trigger margin calls.

### 🏢 Sector Concentration Limits

CSP candidates are now filtered so no single sector exceeds **30%** of total CSP capital:

- Candidates sorted by wheel_score (strongest first)
- First candidate per sector always passes
- Subsequent candidates in the same sector are dropped if they'd breach the 30% cap
- Dropped candidates appear in `dropped_for_concentration` in scan output

This prevents correlated assignment clusters (e.g., NVDA + AMD + MRVL all assigned in a semiconductor selloff).

### 🔄 Rolling Checks (Before New Trades)

Run rolling checks before generating new recommendations:

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/rolling_checks.py \
  --portfolio sandbox/portfolio.json \
  --prices sandbox/current_prices.json
```

Returns per-position recommendations:
- **ROLL_EARLY**: 60%+ of premium captured → buy to close, re-sell new cycle
- **ROLL_URGENT**: ITM with ≤7 DTE → roll out/up to avoid assignment
- **ROLL_DECISION**: <5 DTE and within 2% of strike → decide: expire, roll, or close
- **HOLD**: No action needed

Display urgent/early positions at the top of the income plan report.

---

## Step 2.6: Scan for New Portfolio Candidates (REQUIRED)

Run **after** preflight checks to find large-cap stocks (>$200B market cap) worth adding
to the portfolio via the wheel strategy (CSP-first entry). This step is **required** and
must be included in every income plan report.

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/scan_candidates.py \
  --portfolio sandbox/portfolio.json \
  --budget 12119 \
  --market-cap-min 200 \
  --top-n 10
```

Save output to `sandbox/candidates.json`.

Key parameters:
| Parameter | Purpose | Default |
|-----------|---------|---------|
| `--portfolio` | Path to portfolio.json from parse_etrade.py | Required |
| `--budget` | Max CSP capital (use `max_per_csp` from preflight) | Required |
| `--market-cap-min` | Minimum market cap in billions | 200 |
| `--top-n` | Number of candidates to return | 10 |
| `--piotroski` | Add Piotroski F-score (slower, ~2 min extra) | Off |

**Candidate types returned:**
- `NEW_CANDIDATE` — not in portfolio; enter via CSP
- `OWNED_TOPUP` — own 1–99 shares; buy more to reach 100 for CC eligibility
- `OWNED_ELIGIBLE` — already own 100+ shares (excluded, managed by main plan)

**Wheel suitability score (0–10):** trend (0–3) + IV quality (0–3) + earnings safety (0–2) + CSP affordability (0–1) + fundamentals (0–1)
- **≥ 7 → ADD** | **5–6 → WATCH** | **< 5 → SKIP**

Include the candidate analysis in the report under "💡 New Position Opportunities".

---

## Step 3: Check Market Conditions

Use `mcp__finnhub-mcp__GetQuote` for QQQ to assess overall market:
- QQQ above 50-day MA → **Bullish** → general market bias
- QQQ below 50-day MA → **Bearish** → more conservative approach

> **Note**: Per-stock trends from preflight_checks.py override the global market bias.
> A stock trending bullish in a bearish market still gets bullish strike selection.

---

## Step 4: Get Option Expirations for Each Stock

For each CC-eligible stock and CSP candidate:
```
get_option_expirations(symbol="SYMBOL")
```

Select target expiry dates:
- **Week 1 target**: closest date 7–14 DTE from today
- **Week 2 target**: next date after Week 1
- **Monthly target**: closest date 28–45 DTE (for bigger premium)
- **Respect earnings**: if preflight says SHORT_DTE_ONLY, use safe_expiry_before as max

---

## Step 5: Fetch Live Option Chains & Extract Strikes

For each stock, fetch the option chain for the target expiry:
```
get_options_chain(symbol="SYMBOL", expiration="TARGET-DATE", greeks=true)
```

**Save chain files** to `sandbox/chains/SYMBOL_EXPIRY.json`, then extract:

```bash
uv run python .claude/skills/portfolio-income-plan/scripts/extract_strikes.py \
  --file sandbox/chains/NVDA_2026-04-17.json \
  --symbol NVDA \
  --price 180.40 \
  --type call \
  --trend neutral \
  --dte 30 \
  --cost-basis 187.99 \
  --min-premium 0.50 \
  --min-ann-yield 15
```

### Key Parameters:
| Parameter | Purpose | Default |
|-----------|---------|---------|
| `--trend` | Per-stock trend from preflight (determines delta range) | Required |
| `--cost-basis` | Flags CC strikes below cost basis | Optional |
| `--min-premium` | Skips options with mid < threshold (dynamic floor: `max(min_premium, price×0.002)`) | 0.50 |
| `--min-ann-yield` | Skips options with annualized yield < threshold | 15 |
| `--delta-min/max` | Override delta range directly | Auto from trend |
| `--use-mid` | Use mid price for yield calc when spread < 5% (otherwise uses conservative bid) | Off |

### Delta-Based Strike Selection (replaces % OTM)

Strikes are selected by **delta range**, which automatically adjusts for each stock's volatility:

**Covered Calls (CC):**
| Trend | Delta Range | Effect |
|-------|------------|--------|
| strong_bull | 0.15 – 0.25 | Very far OTM — preserve upside |
| bull | 0.20 – 0.35 | Moderate OTM — balanced |
| neutral | 0.25 – 0.40 | Standard range |
| bear | 0.30 – 0.45 | Closer to money — more premium |
| strong_bear | 0.35 – 0.50 | Near ATM — maximum premium |

**Cash Secured Puts (CSP) — Standard Regime (QQQ > SMA200, VXN < 25):**
| Trend | Delta Range | Effect |
|-------|------------|--------|
| strong_bull / bull | 0.20 – 0.30 | Standard OTM buffer |
| neutral | 0.20 – 0.30 | Standard OTM buffer |
| bear / strong_bear | 0.10 – 0.20 | Wider buffer — more protection |

**CSP Delta Adjustments by Market Regime (apply on top of per-stock trend):**
| Market Condition | Adjustment | Example |
|---|---|---|
| QQQ > SMA200, VXN < 25 | None (standard) | bull → 0.20–0.30 |
| QQQ > SMA200, VXN 25–35 | Reduce one tier | bull → 0.15–0.20 |
| QQQ < SMA200, VXN < 25 | Reduce one tier | bull → 0.15–0.20 |
| QQQ < SMA200, VXN 25–35 | Reduce two tiers | bull → 0.10–0.15 |
| VXN ≥ 35 | **SKIP — no new CSPs** | Wait for VXN < 30 |

> SMA200 note: Per-stock trend scores now have a **hard cap of 3.0** (= "neutral") when the stock is below its own 200-day MA. This prevents a short-term bounce in a downtrending stock from generating an over-optimistic CSP recommendation.

### Understanding the Output

The script returns one of two results:

**`"action": "TRADE"`** — viable strikes found:
```json
{
  "action": "TRADE",
  "strikes": [
    {
      "strike": 185.0, "bid": 2.10, "mid": 2.12, "delta": 0.336,
      "ann_yield_pct": 46.5, "prob_profit_pct": 66.4,
      "spread_pct": 1.9, "liquidity_pass": true,
      "below_cost_basis": true
    }
  ],
  "filtered_strikes": [...]
}
```

**`"action": "SKIP"`** — no viable trades (all filtered out):
```json
{
  "action": "SKIP",
  "reasons": ["premium $0.26 < $0.50", "liquidity: wide spread (106%)"],
  "filtered_strikes": [...]
}
```

When action = SKIP, list the stock under **"Skipped — No Trade"** with reasons.
Do NOT force a suboptimal trade.

---

## Step 6: Build the 4-Week Income Plan

### Rolling Check (Before New Trades)

Before generating new recommendations, check existing positions:
- If any short option has gained > 60% of premium → suggest "buy to close early and re-sell"
- If any short option is ITM with < $0.25 extrinsic value → flag for urgent roll
- If any short option has < 5 DTE and is near the money → flag for roll decision

### Week Structure

Generate a plan for exactly **4 weeks** from next Monday:
- **Week 1**: Monday after today — "Setup Day" (deploy most positions)
- **Week 2**: Following Monday — "Roll Day" (roll short-term expirations)
- **Week 3**: 3 weeks out — "Mid-cycle" (monitor + roll)
- **Week 4**: 4 weeks out — "Expiry week" (collect or reassign)

### For Each Stock Position, Determine Action:

```
IF preflight earnings risk = BLOCK:
  → SKIP this stock entirely
  → Show warning: "⚠️ Earnings [DATE] — no trades"

IF preflight earnings risk = SHORT_DTE_ONLY:
  → Only sell CC expiring BEFORE safe_expiry_before date
  → Show warning: "⚠️ Earnings [DATE] — short expiry only"

IF stock has existing CC expiring this week:
  → Let it expire, then sell new CC next week
  → Show expected premium for new CC

IF stock has no CC (uncovered) AND is CC-eligible (100+ shares):
  → Sell CC immediately on Week 1
  → Use extract_strikes.py with --trend from preflight

IF stock is deeply underwater (>20% loss):
  → Only sell CC at or above cost basis
  → Note: "Recovery mode — building cost basis reduction"
  → Use --cost-basis flag to get the warning

IF extract_strikes returns action=SKIP:
  → List under "Skipped — No Trade" with reasons
  → Do NOT force a trade
```

### For Cash Positions, Suggest CSPs:

```
Use budget from preflight_checks.py:
  → max_per_csp: maximum capital per individual CSP (20% of usable cash)
  → max_total_csp: maximum total CSP exposure (50% of usable cash)

IF usable_cash > 0:
  → Suggest CSP candidates where strike × 100 <= max_per_csp
  → Track running total — stop when cumulative reaches max_total_csp
  → Default candidates: AMD, NVDA, ORCL, DELL, MRVL
  → Show: strike, real premium, ann yield, prob profit, capital needed
```

---

## Step 7: Calculate Income Projections

For each trade, compute:
```
weekly_income = bid_premium × 100 × contracts
annual_run_rate = weekly_income × 52
yield_on_cost = (bid_premium / strike) × (365 / DTE) × 100
```

Aggregate totals:
```
total_week1_income = sum of all premiums collected Monday
total_4week_income = sum of all cycles over 4 weeks
monthly_income_rate = total_4week_income
annualized_rate = monthly_income_rate × 12
yield_on_portfolio = (annualized_rate / total_portfolio_value) × 100
```

---

## Step 8: Generate the Report

Output a structured markdown report saved to:
`sandbox/Income_Plan_{YYYY-MM-DD}_{HHmm}.md`

### Report Sections:

```markdown
# 4-Week Portfolio Income Plan
**Generated**: {date} | **Portfolio Value**: ${total} | **Market**: Bullish/Bearish

## ⚠️ Market Context
- QQQ trend: [above/below 50MA]
- Key dates: Fed meetings, earnings, expiry dates
- Strategy adjustment: [what changed due to market]

## 📊 Portfolio Snapshot
| Symbol | Shares | Cost Basis | Current | P&L | Trend | CC Status |
|--------|--------|-----------|---------|-----|-------|-----------|

## 💰 Cash Available: $XX,XXX
| Budget | Amount |
|--------|--------|
| Usable Cash | $XX,XXX |
| Max Per CSP (20%) | $XX,XXX |
| Max Total CSPs (50%) | $XX,XXX |
| Buffer Kept | $5,000 |

## 📅 Week 1 — [Date]: Setup Day
| Stock | Action | Strike | Expiry | Bid | Delta | Ann Yield | Prob Win | Liq | Income |
|-------|--------|--------|--------|-----|-------|-----------|----------|-----|--------|
| NVDA  | Sell CC| $185   | Apr17  | $5.40| 0.34 | 36.4%     | 66%      | ✅  | $540   |
...
**Week 1 Total Income: $X,XXX**

### Skipped — No Trade
| Stock | Reason |
|-------|--------|
| GAP   | Premium $0.26 below $0.50 minimum |

## 📅 Week 2 — [Date]: Roll Day
...

## 📅 Week 3 — [Date]: Mid-Cycle
...

## 📅 Week 4 — [Date]: Expiry Week
...

## 💵 4-Week Income Summary
| Category | Amount |
|----------|--------|
| Total Premium Collected | $X,XXX |
| Monthly Run Rate | $X,XXX |
| Annualized Run Rate | $XX,XXX |
| Yield on Portfolio | X.X% |
| Yield on Deployed Capital | XX% |

## ⚠️ Earnings Warnings
- MSTR: Apr 30 — close all options by Apr 24!
- TEM: May 1 — short expiry only

## 💡 New Position Opportunities (Large-Cap >$200B) — REQUIRED SECTION

Results from `scan_candidates.py` (Step 2.6) — stocks worth adding via CSP-first wheel strategy.
This section is **required in every report**.

### New Candidates
| Symbol | Sector | Price | Trend | IV | Earnings | Score | Rec | CSP Strike | Capital |
|--------|--------|-------|-------|----|----------|-------|-----|-----------|---------|
| XXX | Tech | $XXX | bull | 38% | 44d SAFE | 8.0 | ADD | $XXX (10% OTM) | $XX,XXX |

### Top-Up Opportunities (buy more to reach 100 shares)
| Symbol | Owned | Need | Buy Cost | Trend | Score | Rec |
|--------|-------|------|----------|-------|-------|-----|
| AMD | 25 | 75 more | ~$14,960 | strong_bear | 4.0 | SKIP |

## 📋 Execution Checklist
Monday morning order sequence with limit prices (use BID).

## ⚠️ Risk Disclaimer
Options trading involves risk of loss. This is not financial advice.
```

---

## Key Rules Always Apply

1. **Never sell options expiring AFTER earnings** without explicit warning
2. **Always keep $5,000 cash buffer** — never deploy 100% into CSPs
3. **Position sizing**: max 20% of usable cash per CSP, max 50% total CSP exposure
4. **For underwater stocks**: only sell CC above cost basis OR document the loss acceptance
5. **Use BID price as limit order**, not mid — more conservative fill
6. **Label all prices**: ✅ Real Tradier data OR 📊 Estimated
7. **SOXQ/ETFs**: may only have monthly expirations — check before planning weeklies
8. **Option level 1** accounts: can only do covered calls and cash secured puts (no spreads)
9. **Skip bad trades**: if extract_strikes returns SKIP, respect it — do not force a trade
10. **Delta over % OTM**: always use `--trend` parameter for strike selection, not fixed percentages
11. **Existing positions**: check preflight existing_options map — don't duplicate open strikes
12. **Market regime first**: always check `market_regime` from preflight before selecting any CSP delta — backtest proves bear market doubles assignment risk
13. **SMA200 hard cap**: per-stock trend is automatically capped at "neutral" (score ≤ 3.0) when stock is below its 200-day MA — prevents over-optimistic CSP entry on bear bounces
14. **VXN ≥ 35**: skip ALL new CSPs regardless of individual stock trends — extreme volatility clusters create multi-week assignment streaks
15. **Sector concentration**: no single sector may exceed 30% of total CSP capital — prevents correlated assignment clusters
16. **Stress test**: before adding new CSPs, verify `stress_test.stress_pass` is true — if false, reduce exposure first
17. **Dynamic premium floor**: min premium scales with stock price (`max(min_premium, price×0.002)`) — prevents negligible premiums on expensive stocks
18. **Rolling checks**: check existing positions for roll opportunities (60% profit, ITM near expiry) BEFORE generating new trades. NOTE: `cost_basis` from parse_etrade.py is stored as **per-share price** (e.g. 1.22 = $1.22/share) while `current_value` is the **total dollar value** of the position (e.g. −32.5 = $32.50 total for one contract). Do NOT divide `cost_basis` by 100 — it is already per-share.
19. **Scan for candidates**: REQUIRED — always run `scan_candidates.py` after preflight and include "💡 New Position Opportunities" section in report (no exceptions for "optional")
20. **Short-term momentum override**: `check_recent_momentum()` runs on every candidate and every portfolio stock. If 5-day return ≤ −3% AND ≥ 3 consecutive red days → downgrade trend one tier and subtract 1.0 from wheel score. If 5-day return ≤ −5% AND ≥ 5 consecutive red days → force trend to 'bear', cap wheel score at 3.9 (auto-SKIP). This catches sharp recent drops that 20/50/200-day SMA scoring smooths over (e.g. KO −4.1% over 5 days was scored 'neutral' without this rule).

---

## Example Usage

```
User: "generate income plan for my portfolio"
User: "what covered calls should I sell this week"
User: "create 4-week options income plan"
User: "how can I make weekly income from my stocks"
```

---

## Dependencies

- `pandas` — CSV reading and data manipulation
- `yfinance` — earnings dates, technical indicators
- `glob`, `os`, `pathlib` — file discovery
- **Tradier MCP** — live option chains, quotes, expirations
- **Finnhub MCP** — market setup quality, supplemental earnings data
