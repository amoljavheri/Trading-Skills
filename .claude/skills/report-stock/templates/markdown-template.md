# Stock Analysis Report - Markdown Template

Format the JSON data into a markdown report saved to `sandbox/`.

**Filename**: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md`

## Report Structure

### 1. Header

```markdown
# {SYMBOL} Stock Analysis Report
**{company.name}** - Comprehensive Analysis
Generated: {generated}
```

### 2. Recommendation Box

```markdown
## Recommendation: {recommendation.recommendation}

**Conviction Score: {conviction_score.total} / 10** — {conviction_score.verdict}
Signal Alignment: {conviction_score.signal_alignment}

**Strengths:**
- {strength 1}
- {strength 2}
...

**Risks:**
- {risk 1}
- {risk 2}
...
```

Use `recommendation.recommendation_level` to label: "positive" = BUY, "neutral" = HOLD, "negative" = AVOID.

### 3. Company Overview

| Metric | Value |
|--------|-------|
| Company | `company.name` |
| Sector | `company.sector` |
| Industry | `company.industry` |
| Market Cap | Format as `$X.XB` or `$X.XM` |
| Enterprise Value | Format as `$X.XB` or `$X.XM` |
| Beta | 2 decimals |

### 4. Market Context

```markdown
## 🌍 Market Context

| Indicator | Value | Signal |
|-----------|-------|--------|
| SPY Trend | bullish/bearish/sideways | {emoji} |
| SPY Price | $X.XX | Above/Below SMA50 |
| VIX Regime | low/normal/elevated/high | Risk level |
| Sector ({sector_etf}) | bullish/bearish/sideways | Sector trend |
```

If `market_context` is null, display "Market context unavailable".

### 5. Trend Analysis

| Indicator | Value | Signal |
|-----------|-------|--------|
| Bullish Score | `X.XX / 11.5` (normalized: `X.XXX`) | Strong(≥0.52)/Moderate(≥0.35)/Weak |
| Trend Stage | early/mid/extended/below | Stage classification |
| Price | `$X.XX` | - |
| Period Return | `±X.X%` | Bullish/Bearish |
| vs SMA20 | `±X.X%` | Above/Below |
| vs SMA50 | `±X.X%` | Above/Below |
| vs SMA200 | `±X.X%` | Above/Below — bull/bear market |
| RSI | `X.X` | Overbought(>70)/Oversold(<30)/Bullish(50-70)/Neutral |
| MACD | `X.XX vs Signal X.XX` | Bullish/Bearish |
| ADX | `X.X` | Strong(≥40)/Moderate(25-40)/Weak(<25) Trend |
| Volume Confirmed | Yes/No | RVOL confirmation |
| Breakout Signal | Yes/No | 20-day high breakout |
| OBV Trend | rising/falling | Accumulation/Distribution |
| Trend Consistency | `X/20 days` | Days above SMA20 |
| Next Earnings | `YYYY-MM-DD` | `BMO`/`AMC` |

**Signals:** List `trend_analysis.signals` as bullet points.

### 6. Fundamental Analysis

#### Valuation

| Metric | Value | Assessment |
|--------|-------|------------|
| Trailing P/E | `X.Xx` | Attractive(<15)/Reasonable(15-25)/Premium(>25) |
| Forward P/E | `X.Xx` | Same |
| Price/Book | `X.Xx` | - |
| EPS (TTM) | `$X.XX` | - |
| Forward EPS | `$X.XX` | - |

#### Profitability

| Metric | Value | Assessment |
|--------|-------|------------|
| Profit Margin | `X.X%` | Excellent(>20%)/Good(10-20%)/Low(<10%) |
| Operating Margin | `X.X%` | Same |
| ROE | `X.X%` | Same |
| ROA | `X.X%` | - |
| Revenue Growth | `±X.X%` | Growing/Declining |
| Earnings Growth | `±X.X%` | Growing/Declining |

#### Dividend & Balance Sheet

| Metric | Value | Assessment |
|--------|-------|------------|
| Dividend Yield | `X.XX%` or "None" | High(>5%)/Attractive(2-5%)/Low(<2%)/None |
| Dividend Rate | `$X.XX/share` | - |
| Payout Ratio | `X%` | At limit(>80%)/Moderate(50-80%)/Conservative(<50%) |
| Debt/Equity | `X.X%` | High(>100%)/Moderate(50-100%)/Low(<50%) |
| Current Ratio | `X.XXx` | Good(>1.5)/Adequate(1-1.5)/Low(<1) |

#### Earnings History

| Date | Estimate | Actual | Surprise |
|------|----------|--------|----------|
| YYYY-MM-DD | $X.XX | $X.XX | ±X.X% |

Up to 8 quarters.

### 7. Piotroski F-Score

**Score: X/9** ({piotroski.interpretation})

| Criteria | Result | Details |
|----------|--------|---------|
| 1. Positive Net Income | PASS/FAIL | Value |
| 2. Positive ROA | PASS/FAIL | Value |
| 3. Positive Operating CF | PASS/FAIL | Value |
| 4. CF > Net Income | PASS/FAIL | CF: X, NI: Y |
| 5. Lower Long-Term Debt | PASS/FAIL | Recent: X, Prev: Y |
| 6. Higher Current Ratio | PASS/FAIL | Recent: X, Prev: Y |
| 7. No Share Dilution | PASS/FAIL | Recent: X, Prev: Y |
| 8. Higher Gross Margin | PASS/FAIL | Recent: X, Prev: Y |
| 9. Higher Asset Turnover | PASS/FAIL | Recent: X, Prev: Y |

### 8. Overall Conviction Score

```markdown
## 🎯 Overall Conviction Score: X.X / 10  —  [Verdict]

Signal Alignment: aligned / mixed / conflicting
```

If conflicting, list `conviction_score.conflicts` as bullet points.

#### Component Breakdown

| Component | Score | Max | Signal |
|-----------|-------|-----|--------|
| Trend (bullish score) | X.X | 3.0 | detail |
| ADX strength | X.X | 0.5 | detail |
| RSI zone | X.X | 1.0 | detail |
| Volume/momentum | X.X | 1.0 | detail |
| Piotroski F-Score | X.X | 1.0 | detail |
| Valuation (Fwd P/E) | X.X | 1.0 | detail |
| PMCC viability | X.X | 1.5 | detail |
| Market regime | X.X | 1.0 | detail |
| **TOTAL** | **X.X** | **10** | |

#### Dimensional Summary

| Dimension | Score | Max | Pct |
|-----------|-------|-----|-----|
| 📈 Technical | X.X | 5.5 | XX% |
| 📊 Fundamental | X.X | 2.0 | XX% |
| 🎯 Strategy | X.X | 1.5 | XX% |
| 🌍 Market | X.X | 1.0 | XX% |

Verdict labels:
- 0–1.99: ⚠️ Strong Bear — Avoid
- 2–3.99: 🔴 Bearish — Avoid/Wait
- 4–5.99: 🟡 Neutral — Watch
- 6–7.99: 🟢 Moderately Bullish — Favorable
- 8–9.99: 🚀 Strong Bull — High Conviction
- 10: ⚡ Exceptional — Rare Setup

### 9. LEAP Call Scenarios

```markdown
## 📈 LEAP Call Scenarios

📊 *Source: {data_sources.options} option chain — {real/estimated} prices*

**LEAP Details:**
- Strike: $X | Expiry: YYYY-MM-DD | **Bid: $XX.XX / Ask: $XX.XX / Mid: $XX.XX** (~$X,XXX per contract)
- Delta: 0.XX | IV: XX% | Monthly Theta Drag: $X.XX/month

**Scenario Analysis (1 Month)**

| Stock Move | Target Price | LEAP Est. Value | P&L | Return % | Confidence |
|-----------|-------------|----------------|-----|---------|------------|
| -10% | $XXX | ~$XX | -$XX | -XX% 🔴 | low |
| Flat (0%) | $XXX | ~$XX | -$X | -X% 🟡 | high |
| +5% | $XXX | ~$XX | +$X | +X% 🟡 | high |
| +10% | $XXX | ~$XX | +$XX | +XX% 🟢 | moderate |
| +20% | $XXX | ~$XX | +$XX | +XX% 🚀 | low |
| +30% | $XXX | ~$XX | +$XX | +XX% 🚀 | low |

*{model_note}*

**Break-even**: Stock needs to rise ~X.X% in 30 days to cover theta drag
**Prob. of +30% LEAP gain in 1 month**: ~XX%
```

### 10. Cash Secured Put (CSP) Analysis

```markdown
## 💰 Cash Secured Put Analysis

📊 *Source: {data_sources.options} option chain — {real/estimated} bid/ask*

**CSP Suitability**: ✅ Good / ⚠️ Caution / ❌ Avoid
*Reason: {suitability.reason}*
{flags as bullet points if any}

**Expiry**: YYYY-MM-DD (~XX DTE)

| Tier | Strike | Bid | Ask | Mid Premium | Delta | IV | Ann. Yield | Prob. Profit | Capital |
|------|--------|-----|-----|-------------|-------|----|-----------|-------------|---------|
| 🛡️ Conservative (δ~0.15) | $XXX | $X.XX | $X.XX | $X.XX | 0.XX | XX% | XX% | XX% | $XX,XXX |
| ⚖️ Balanced (δ~0.25) | $XXX | $X.XX | $X.XX | $X.XX | 0.XX | XX% | XX% | XX% | $XX,XXX |
| 🎯 Aggressive (δ~0.35) | $XXX | $X.XX | $X.XX | $X.XX | 0.XX | XX% | XX% | XX% | $XX,XXX |
```

If `support_context` is present on a tier, add:
```markdown
**Support Context**: Strike vs SMA50: above/below | Strike vs SMA200: above/below
Nearest support: $XX.XX (X.X% below strike)
```

**Recommended strike**: $XXX (Balanced) — [reason]
**Assignment scenario**: If assigned, cost basis = $XXX − $X.XX premium = **$XXX.XX**
**Next step if assigned**: Sell covered calls (wheel strategy) at $XXX strike

### 11. PMCC Viability

| Metric | Value | Assessment |
|--------|-------|------------|
| PMCC Score | `X / 11` | Excellent(≥9)/Good(7-8)/Acceptable(5-6)/Poor(<5) |
| Implied Volatility | `X.X%` | Ideal(25-50%)/Acceptable(20-60%)/High(>60%)/Low(<20%) |
| LEAPS Expiry | `YYYY-MM-DD (X days)` | - |
| LEAPS Strike | `$X` | - |
| LEAPS Delta | `0.XXX` | On Target(0.75-0.85)/Off Target |
| LEAPS Bid/Ask | `$X.XX / $X.XX` | - |
| LEAPS Spread | `X.X%` | Good(<10%)/Acceptable(10-20%)/Wide(>20%) |
| Short Expiry | `YYYY-MM-DD (X days)` | - |
| Short Strike | `$X` | - |
| Short Delta | `0.XXX` | On Target(0.15-0.25)/Off Target |
| Short Bid/Ask | `$X.XX / $X.XX` | - |
| Short Spread | `X.X%` | Good(<10%)/Acceptable(10-20%)/Wide(>20%) |

#### Trade Metrics

| Metric | Value |
|--------|-------|
| Net Debit | `$X,XXX.XX` |
| Short Yield (per cycle) | `X.XX%` |
| Estimated Annual Yield | `X.X%` |
| Max Profit (if assigned) | `$X,XXX.XX` |
| ROI at Max Profit | `X.X%` |
| Capital Required | `$X,XXX.XX` |

### 12. Option Spread Strategies

**Expiry:** {spread_strategies.expiry} ({spread_strategies.dte} days)
**Source:** {spread_strategies.source}

#### Strategy Summary

| Strategy | Direction | Max Profit | Max Loss | Risk/Reward | Breakeven |
|----------|-----------|------------|----------|-------------|-----------|
| Bull Call Spread | Bullish | $XXX | $XXX | X.XX | $XXX |
| Bear Put Spread | Bearish | $XXX | $XXX | X.XX | $XXX |
| Long Straddle | Neutral | Unlimited | $XXX | - | $XXX / $XXX |
| Long Strangle | Neutral | Unlimited | $XXX | - | $XXX / $XXX |
| Iron Condor | Neutral | $XXX | $XXX | X.XX | $XXX - $XXX |

#### Strategy Details

For each strategy, show legs, cost, breakeven, max profit/loss.

### 13. Investment Summary

**Strengths:**
- (from conviction_score.strengths)

**Risk Factors:**
- (from conviction_score.risks)

**Data Sources:**
- Technicals: {data_sources.technicals}
- Fundamentals: {data_sources.fundamentals}
- Options: {data_sources.options}
- Quote: {data_sources.quote}
- Definitive Price: ${data_sources.definitive_price}
{if price_discrepancy_pct: "⚠️ Price discrepancy: X.X% between sources"}

### Footer

```markdown
---
*This analysis is for informational purposes only and does not constitute financial advice.
Options trading involves significant risk of loss. Past performance is not indicative of future results.*
```

## Formatting Rules

- Percentages: Always show sign for changes (`+5.2%`, `-3.1%`)
- Currency: `$123.45`, `$1.2B`, `$45.6M`
- Ratios: 1 decimal for P/E, 2 decimals for delta/beta
- Scores: `X / max` format
- Missing data: "N/A" or "-"
- Conviction score components: use the `detail` field from each component dict
