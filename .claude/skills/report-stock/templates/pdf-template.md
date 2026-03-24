# Stock Analysis Report PDF Template

Use this template to generate professional PDF reports from the JSON data returned by the report script.

## Document Structure

### Page Layout
- **Page Size**: Letter (8.5" x 11")
- **Margins**: 0.75" all sides
- **Font**: Helvetica family

### Color Palette
```
Header Background:   #2C3E50 (dark blue-gray)
Positive/Good:       #27AE60 (green)
Warning/Caution:     #F39C12 (yellow/orange)
Negative/Bad:        #E74C3C (red)
Light Background:    #ECF0F1 (light gray)
Border/Divider:      #BDC3C7 (mid gray)
Accent:              #3498DB (blue)
```

## Report Sections

### 1. Title Section
```
[SYMBOL] Stock Analysis Report          (24pt, bold, #2C3E50)
[Company Name] - Comprehensive Analysis  (12pt, #BDC3C7)
Generated: [Date at Time]               (10pt, #BDC3C7)
─────────────────────────────────────── (2pt line, #2C3E50)
```

### 2. Executive Summary Box
Color-coded box based on `recommendation.recommendation_level`:
- `positive` → Green (#27AE60)
- `neutral` → Yellow (#F39C12)
- `negative` → Red (#E74C3C)

```
┌─────────────────────────────────────────────────┐
│ RECOMMENDATION: [recommendation.recommendation] │  (white text on colored bg)
│ CONVICTION SCORE: X.X / 10 — [verdict]         │  (large, white text)
│ Signal Alignment: aligned/mixed/conflicting     │
├─────────────────────────────────────────────────┤
│ • [strength 1]                                  │  (lighter tinted bg)
│ • [strength 2]                                  │
│ • [strength 3]                                  │
│                                                 │
│ Cautions:                                       │
│ • [risk 1]                                      │
│ • [risk 2]                                      │
└─────────────────────────────────────────────────┘
```

### 3. Company Overview Table

| Metric | Value |
|--------|-------|
| Company | `company.name` |
| Sector | `company.sector` |
| Industry | `company.industry` |
| Market Cap | Format as `$X.XB` |
| Enterprise Value | Format as `$X.XB` |
| Beta | `company.beta` (2 decimals) |

### 4. Market Context Table

| Indicator | Value | Signal |
|-----------|-------|--------|
| SPY Trend | bullish/bearish/sideways | Emoji indicator |
| SPY Price | $X.XX | Above/Below SMA50 |
| VIX Regime | low/normal/elevated/high | Risk level |
| Sector ETF | XLK/XLV/etc | Sector trend |

### 5. Trend Analysis Table

| Indicator | Value | Signal |
|-----------|-------|--------|
| Bullish Score | `X.XX / 11.5` (normalized: `X.XXX`) | Strong(≥0.52)/Moderate(≥0.35)/Weak |
| Trend Stage | early/mid/extended/below | Classification |
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

**Signal interpretations:**
- Normalized Score: ≥0.52 = "Strong Bullish", ≥0.35 = "Moderate", ≥0.17 = "Neutral", <0.17 = "Bearish"
- RSI: >70 = "Overbought (caution)", <30 = "Oversold", ≥50 = "Bullish", <50 = "Neutral"
- ADX: ≥40 = "Strong Trend", ≥25 = "Moderate Trend", <25 = "Weak/No Trend"

### 6. Fundamental Analysis (Page 2)

#### Valuation Metrics Table

| Metric | Value | Assessment |
|--------|-------|------------|
| Trailing P/E | `X.Xx` | Attractive(<15)/Reasonable(15-25)/Premium(>25) |
| Forward P/E | `X.Xx` | Same as above |
| Price/Book | `X.Xx` | - |
| EPS (TTM) | `$X.XX` | - |
| Forward EPS | `$X.XX` | - |

#### Profitability Table

| Metric | Value | Assessment |
|--------|-------|------------|
| Profit Margin | `X.X%` | Excellent(>20%)/Good(10-20%)/Low(<10%) |
| Operating Margin | `X.X%` | Same as above |
| ROE | `X.X%` | Excellent(>20%)/Good(10-20%)/Low(<10%) |
| ROA | `X.X%` | - |
| Revenue Growth | `±X.X%` | Growing/Declining |
| Earnings Growth | `±X.X%` | Growing/Declining |

#### Dividend & Balance Sheet Table

| Metric | Value | Assessment |
|--------|-------|------------|
| Dividend Yield | `X.XX%` or "None" | High(>5%)/Attractive(2-5%)/Low(<2%)/No Dividend |
| Dividend Rate | `$X.XX/share` | - |
| Payout Ratio | `X%` | At limit(>80%)/Moderate(50-80%)/Conservative(<50%) |
| Debt/Equity | `X.X%` | High(>100%)/Moderate(50-100%)/Low(<50%) |
| Current Ratio | `X.XXx` | Good(>1.5)/Adequate(1-1.5)/Low(<1) |

#### Earnings History Table

| Date | Estimate | Actual | Surprise |
|------|----------|--------|----------|
| YYYY-MM-DD | $X.XX | $X.XX | ±X.X% |
| ... (up to 8 quarters) |

### 7. Piotroski F-Score Section

Header: `Piotroski F-Score: X/9 (interpretation)`

| Criteria | Result | Details |
|----------|--------|---------|
| 1. Positive Net Income | PASS/FAIL | Value |
| 2. Positive ROA | PASS/FAIL | Value |
| 3. Positive Operating CF | PASS/FAIL | Value |
| 4. CF > Net Income | PASS/FAIL | Value |
| 5. Lower Long-Term Debt | PASS/FAIL | Recent: X, Prev: Y |
| 6. Higher Current Ratio | PASS/FAIL | Recent: X, Prev: Y |
| 7. No Share Dilution | PASS/FAIL | Recent: X, Prev: Y |
| 8. Higher Gross Margin | PASS/FAIL | Recent: X, Prev: Y |
| 9. Higher Asset Turnover | PASS/FAIL | Recent: X, Prev: Y |

### 8. Overall Conviction Score (Blue accent box)

```
┌─ CONVICTION SCORE: X.X / 10 — [Verdict] ─────────────┐
│ Signal Alignment: aligned/mixed/conflicting            │
│                                                        │
│ Component          | Score | Max  | Detail             │
│ ─────────────────  | ───── | ──── | ──────             │
│ Trend              | X.X   | 3.0  | from components    │
│ ADX strength       | X.X   | 0.5  | from components    │
│ RSI zone           | X.X   | 1.0  | from components    │
│ Volume/momentum    | X.X   | 1.0  | from components    │
│ Piotroski F-Score  | X.X   | 1.0  | from components    │
│ Valuation          | X.X   | 1.0  | from components    │
│ PMCC viability     | X.X   | 1.5  | from components    │
│ Market regime      | X.X   | 1.0  | from components    │
│ ─────────────────  | ───── | ──── |                    │
│ TOTAL              | X.X   | 10   |                    │
│                                                        │
│ Dimensions:                                            │
│ Technical: X.X/5.5 | Fundamental: X.X/2.0             │
│ Strategy: X.X/1.5  | Market: X.X/1.0                  │
│                                                        │
│ Conflicts: (list if any)                               │
└────────────────────────────────────────────────────────┘
```

Verdict colors: 0-3.99 Red, 4-5.99 Yellow, 6-7.99 Green, 8+ Dark Green

### 9. LEAP Call Scenarios

```
┌─ LEAP CALL SCENARIOS ─────────────────────────────────┐
│ Source: {data_sources.options} — {real/estimated}      │
│                                                        │
│ Strike: $X | Expiry: YYYY-MM-DD                       │
│ Bid: $XX.XX | Ask: $XX.XX | Mid: $XX.XX              │
│ Delta: 0.XX | Monthly Theta: $X.XX                    │
│                                                        │
│ Move    | Target  | Est Value | P&L    | Return | Conf│
│ ─────── | ─────── | ───────── | ────── | ────── | ────│
│ -10%    | $XXX    | ~$XX      | -$XX   | -XX%   | low │
│ Flat    | $XXX    | ~$XX      | -$X    | -X%    | high│
│ +5%     | $XXX    | ~$XX      | +$X    | +X%    | high│
│ +10%    | $XXX    | ~$XX      | +$XX   | +XX%   | mod │
│ +20%    | $XXX    | ~$XX      | +$XX   | +XX%   | low │
│ +30%    | $XXX    | ~$XX      | +$XX   | +XX%   | low │
│                                                        │
│ Break-even: ~X.X% move in 30 days                     │
│ Prob +30% gain in 1mo: ~XX%                           │
└────────────────────────────────────────────────────────┘
```

### 10. Cash Secured Put (CSP) Analysis

```
┌─ CSP ANALYSIS ─ Suitability: Good/Caution/Avoid ─────┐
│ Source: {data_sources.options} — {real/estimated}      │
│ Reason: {suitability.reason}                          │
│ Expiry: YYYY-MM-DD (~XX DTE)                          │
│                                                        │
│ Tier          | Strike | Mid  | Delta | Ann.Yld | P.P.│
│ ───────────── | ────── | ──── | ───── | ─────── | ────│
│ Conservative  | $XXX   | $X.X | 0.15  | XX%     | XX% │
│ Balanced      | $XXX   | $X.X | 0.25  | XX%     | XX% │
│ Aggressive    | $XXX   | $X.X | 0.35  | XX%     | XX% │
│                                                        │
│ Recommended: $XXX (Balanced)                          │
│ If assigned: cost basis = $XXX.XX                     │
└────────────────────────────────────────────────────────┘
```

### 11. PMCC Viability Table

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

### 12. PMCC Trade Metrics Table (Blue accent header)

| Metric | Value |
|--------|-------|
| Net Debit | `$X.XX` |
| Short Yield (per cycle) | `X.XX%` |
| Estimated Annual Yield | `X.X%` |
| Max Profit (if assigned) | `$X.XX` |
| ROI at Max Profit | `X.X%` |
| Capital Required | `$X,XXX.XX` |

### 13. Option Spread Strategies Section (Blue accent header)

Header: `Option Spread Strategies - Expiry: YYYY-MM-DD (X days)`

Data from `spread_strategies`:

#### Strategy Summary Table

| Strategy | Direction | Max Profit | Max Loss | Risk/Reward | Breakeven |
|----------|-----------|------------|----------|-------------|-----------|
| Bull Call Spread | Bullish | $XXX | $XXX | X.XX | $XXX |
| Bear Put Spread | Bearish | $XXX | $XXX | X.XX | $XXX |
| Long Straddle | Neutral (expects move) | Unlimited | $XXX | - | $XXX / $XXX |
| Long Strangle | Neutral (expects move) | Unlimited | $XXX | - | $XXX / $XXX |
| Iron Condor | Neutral (low vol) | $XXX | $XXX | X.XX | $XXX - $XXX |

#### Detailed Strategy Boxes

**Bull Call Spread** (Green border if direction is bullish)
```
┌─ BULL CALL SPREAD ─────────────────────────────────────┐
│ Buy $[long_strike] Call / Sell $[short_strike] Call    │
│ Net Debit: $X.XX ($XXX total)                          │
│ Breakeven: $XXX.XX                                     │
│ Max Profit: $XXX | Max Loss: $XXX                      │
│ Risk/Reward: X.XX                                      │
└────────────────────────────────────────────────────────┘
```

**Bear Put Spread** (Red border if direction is bearish)
```
┌─ BEAR PUT SPREAD ──────────────────────────────────────┐
│ Buy $[long_strike] Put / Sell $[short_strike] Put      │
│ Net Debit: $X.XX ($XXX total)                          │
│ Breakeven: $XXX.XX                                     │
│ Max Profit: $XXX | Max Loss: $XXX                      │
│ Risk/Reward: X.XX                                      │
└────────────────────────────────────────────────────────┘
```

**Long Straddle** (Blue border - neutral)
```
┌─ LONG STRADDLE ────────────────────────────────────────┐
│ Buy $[strike] Call + Buy $[strike] Put                 │
│ Total Cost: $XXX                                       │
│ Move Needed: X.X% for profit                           │
│ Breakeven Up: $XXX | Breakeven Down: $XXX              │
│ Max Profit: Unlimited | Max Loss: $XXX                 │
└────────────────────────────────────────────────────────┘
```

**Long Strangle** (Blue border - neutral)
```
┌─ LONG STRANGLE ────────────────────────────────────────┐
│ Buy $[call_strike] Call + Buy $[put_strike] Put        │
│ Total Cost: $XXX                                       │
│ Breakeven Up: $XXX | Breakeven Down: $XXX              │
│ Max Profit: Unlimited | Max Loss: $XXX                 │
└────────────────────────────────────────────────────────┘
```

**Iron Condor** (Gray border - neutral/income)
```
┌─ IRON CONDOR ──────────────────────────────────────────┐
│ Sell $[put_short]/$[call_short] Strangle               │
│ Buy $[put_long]/$[call_long] Wings                     │
│ Net Credit: $X.XX ($XXX total)                         │
│ Profit Range: $XXX - $XXX                              │
│ Max Profit: $XXX | Max Loss: $XXX                      │
│ Risk/Reward: X.XX                                      │
└────────────────────────────────────────────────────────┘
```

**Strategy Guidance Note** (Light gray box, italic):
- Bull Call: Moderately bullish, defined risk
- Bear Put: Moderately bearish, defined risk
- Straddle/Strangle: Expect large move, direction uncertain
- Iron Condor: Range-bound, collect premium

### 14. Investment Summary (Final Page)

#### Strengths Box (Green)
```
┌─ STRENGTHS ─────────────────────────────────────┐
│ • [strength from recommendation.strengths]      │
│ • ...                                           │
└─────────────────────────────────────────────────┘
```

#### Risk Factors Box (Yellow)
```
┌─ RISK FACTORS ──────────────────────────────────┐
│ • [risk from recommendation.risks]              │
│ • ...                                           │
└─────────────────────────────────────────────────┘
```

### 15. Data Sources Box (Light gray)
```
┌─ DATA SOURCES ─────────────────────────────────┐
│ Technicals: {data_sources.technicals}          │
│ Fundamentals: {data_sources.fundamentals}      │
│ Options: {data_sources.options}                │
│ Quote: {data_sources.quote}                    │
│ Definitive Price: ${definitive_price}          │
│ {if price_discrepancy: "⚠️ X.X% discrepancy"} │
└─────────────────────────────────────────────────┘
```

### 16. Footer (All Pages)
```
─────────────────────────────────────── (1pt line, #BDC3C7)
This analysis is for informational purposes only and does not
constitute financial advice. Options trading involves significant
risk of loss. Past performance is not indicative of future results.
                                         (8pt, italic, centered, #BDC3C7)
```

## Formatting Rules

### Numbers
- Percentages: Always show sign for changes (`+5.2%`, `-3.1%`)
- Currency: Use `$` with appropriate precision (`$123.45`, `$1.2B`, `$45.6M`)
- Ratios: One decimal for P/E, two decimals for delta/beta
- Scores: Show as `X / max` format

### Table Styling
- Header row: Dark background (#2C3E50), white text, bold
- Alternating row colors: white / light gray (#ECF0F1)
- Grid lines: 0.5pt, mid gray (#BDC3C7)
- Padding: 5-8pt vertical

### Null/Missing Data
- Display as "N/A" or "-"
- Skip rows entirely if key data is missing
