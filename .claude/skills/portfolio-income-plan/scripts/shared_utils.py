#!/usr/bin/env python3
# ABOUTME: Shared utility functions for portfolio income plan scripts.
# ABOUTME: Contains classify_trend, classify_earnings_risk, market regime logic,
# ABOUTME: and short-term momentum override used by preflight_checks.py and scan_candidates.py.

import yfinance as yf

from trading_skills.technicals import compute_raw_indicators

# Tier order used by momentum downgrade
_TREND_TIERS = ["strong_bull", "bull", "neutral", "bear", "strong_bear"]


def classify_trend(score: float) -> str:
    """Map bullish score (0-8+) to trend class."""
    if score >= 6.0:
        return "strong_bull"
    elif score >= 4.0:
        return "bull"
    elif score >= 2.0:
        return "neutral"
    elif score >= 1.0:
        return "bear"
    else:
        return "strong_bear"


def classify_earnings_risk(days_away: int | None) -> str:
    """Classify earnings risk based on days until next earnings.

    Returns: UNKNOWN | PAST | BLOCK | SHORT_DTE_ONLY | SAFE
    """
    if days_away is None:
        return "UNKNOWN"
    if days_away <= 0:
        return "PAST"
    if days_away <= 14:
        return "BLOCK"
    if days_away <= 21:
        return "SHORT_DTE_ONLY"
    return "SAFE"


def check_recent_momentum(symbol: str) -> dict:
    """Detect short-term bearish momentum missed by long-term trend scoring.

    Uses last 10 trading days to compute 5-day return and consecutive red-day count.
    This catches sharp recent drops (like KO -4.1% over 5 days) that a 20/50/200-day
    SMA-based score smooths over.

    Thresholds (Rule 20):
      - strong_bearish : 5d_ret <= -5%  AND consec_reds >= 5  → block CSP, force 'bear'
      - bearish        : 5d_ret <= -3%  AND consec_reds >= 3  → downgrade one tier
      - mild_bearish   : consec_reds >= 3  (any magnitude)    → warning only, no downgrade
      - neutral        : no override

    Returns dict with momentum_class, 5d_return_pct, consecutive_reds, warning.
    """
    result = {
        "momentum_class": "neutral",
        "five_day_return_pct": None,
        "consecutive_reds": 0,
        "warning": None,
        "should_block": False,
    }
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="15d")
        if hist.empty or len(hist) < 6:
            return result

        closes = list(hist["Close"])
        five_day_ret = (closes[-1] - closes[-6]) / closes[-6] * 100
        result["five_day_return_pct"] = round(five_day_ret, 2)

        # Count consecutive red days from the most recent close backwards
        reds = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] < closes[i - 1]:
                reds += 1
            else:
                break
        result["consecutive_reds"] = reds

        if five_day_ret <= -5.0 and reds >= 5:
            result["momentum_class"] = "strong_bearish"
            result["should_block"] = True
            result["warning"] = (
                f"MOMENTUM BLOCK: {five_day_ret:.1f}% in 5d, {reds} consecutive red days — "
                "forced to 'bear', skip CSP until stabilisation"
            )
        elif five_day_ret <= -3.0 and reds >= 3:
            result["momentum_class"] = "bearish"
            result["warning"] = (
                f"Momentum bearish: {five_day_ret:.1f}% in 5d, {reds} consecutive red days — "
                "trend downgraded one tier"
            )
        elif reds >= 3:
            result["momentum_class"] = "mild_bearish"
            result["warning"] = (
                f"Mild bearish momentum: {reds} consecutive red days — monitor closely"
            )
    except Exception:
        pass

    return result


def apply_momentum_downgrade(trend_class: str, momentum: dict) -> str:
    """Downgrade long-term trend class based on recent 5-day momentum (Rule 20).

    strong_bearish → force at least 'bear' (or keep 'strong_bear' if already there)
    bearish        → drop one tier (e.g. neutral → bear, bull → neutral)
    mild_bearish   → no change (warning only)
    neutral        → no change
    """
    mc = momentum.get("momentum_class", "neutral")
    if mc not in ("strong_bearish", "bearish"):
        return trend_class

    try:
        idx = _TREND_TIERS.index(trend_class)
    except ValueError:
        return trend_class

    if mc == "strong_bearish":
        # Force at minimum 'bear' (index 3)
        return _TREND_TIERS[max(idx, 3)]
    else:
        # Drop one tier, cap at strong_bear
        return _TREND_TIERS[min(idx + 1, len(_TREND_TIERS) - 1)]


def enforce_sma200_cap(trend_class: str, above_sma200: bool | None) -> str:
    """Cap trend at 'neutral' when stock is below its own SMA200.

    This prevents over-optimistic CSP entry on bear bounces.
    SKILL.md Rule 13: SMA200 hard cap.
    """
    if above_sma200 is False and trend_class in ("strong_bull", "bull"):
        return "neutral"
    return trend_class


# ── Sector concentration limits ─────────────────────────────────────────────

MAX_SECTOR_PCT = 0.30  # No single sector exceeds 30% of total CSP exposure


def enforce_sector_limits(
    candidates: list[dict],
    max_sector_pct: float = MAX_SECTOR_PCT,
) -> tuple[list[dict], list[dict]]:
    """Drop weakest candidates if any sector exceeds max_sector_pct of total CSP exposure.

    Candidates must already be sorted by wheel_score descending (strongest first).
    Returns (kept, dropped) lists.
    """
    if not candidates:
        return candidates, []

    total_capital = sum(c.get("csp_capital_needed", 0) or 0 for c in candidates)
    if total_capital == 0:
        return candidates, []

    kept = []
    dropped = []
    sector_capital: dict[str, float] = {}

    for cand in candidates:
        sector = cand.get("sector", "Unknown")
        cap_needed = cand.get("csp_capital_needed", 0) or 0
        current_sector = sector_capital.get(sector, 0)

        # Allow the first candidate in any sector through; only enforce limits on
        # subsequent additions that would push the sector over the threshold.
        if (
            current_sector > 0
            and total_capital > 0
            and (current_sector + cap_needed) / total_capital > max_sector_pct
        ):
            cand["dropped_reason"] = (
                f"Sector '{sector}' would exceed {max_sector_pct*100:.0f}% concentration "
                f"(${current_sector + cap_needed:,.0f} / ${total_capital:,.0f})"
            )
            dropped.append(cand)
            continue

        sector_capital[sector] = current_sector + cap_needed
        kept.append(cand)

    return kept, dropped


# ── Stress test ──────────────────────────────────────────────────────────────


def compute_stress_test(portfolio_data: dict, budget: dict | None = None) -> dict:
    """Compute worst-case scenario if all open short puts (CSPs) are assigned simultaneously.

    Args:
        portfolio_data: Parsed portfolio JSON from parse_etrade.py
        budget: Budget dict from preflight (optional, for context)

    Returns dict with total assignment capital, shortfall, and per-position details.
    """
    cash = portfolio_data.get("cash_available", 0)
    option_positions = portfolio_data.get("option_positions", [])

    # Find all short puts (CSPs)
    short_puts = [
        o for o in option_positions
        if o.get("option_type") == "put" and (o.get("quantity", 0) < 0)
    ]

    total_assignment_capital = 0
    assignments = []
    for put in short_puts:
        contracts = abs(put.get("quantity", 0))
        capital = put["strike"] * 100 * contracts
        total_assignment_capital += capital
        assignments.append({
            "symbol": put.get("underlying", "?"),
            "strike": put["strike"],
            "contracts": contracts,
            "capital_required": capital,
        })

    coverage_pct = (
        round(cash / total_assignment_capital * 100, 1)
        if total_assignment_capital > 0
        else 100.0
    )

    result = {
        "total_assignment_capital": round(total_assignment_capital, 2),
        "cash_available": round(cash, 2),
        "shortfall": round(max(0, total_assignment_capital - cash), 2),
        "coverage_pct": coverage_pct,
        "assignments": assignments,
        "stress_pass": total_assignment_capital <= cash,
    }

    if not result["stress_pass"]:
        result["recommendation"] = (
            f"REDUCE CSP exposure — shortfall ${result['shortfall']:,.0f} "
            f"if all {len(assignments)} CSPs assigned simultaneously"
        )
    else:
        result["recommendation"] = "OK — cash covers all simultaneous assignments"

    return result


# ── Market regime ────────────────────────────────────────────────────────────


def compute_market_regime() -> dict:
    """Fetch QQQ SMA200 and VXN to determine top-down market regime.

    Backtest evidence (3-year QQQ CSP study):
      - QQQ > SMA200 (bull): assignment rate 13.2%
      - QQQ < SMA200 (bear): assignment rate 30.0% — 2.3x worse
      - VXN > 25: assignment clusters triple in frequency

    Returns dict with all fields needed by both preflight_checks.py and scan_candidates.py.
    """
    result = {
        # Common fields
        "qqq_price": None,
        "qqq_sma200": None,
        "qqq_above_sma200": None,
        "vxn": None,
        # preflight_checks format
        "market_regime": "unknown",
        "csp_delta_adjustment": "none",
        "csp_recommendation": "",
        "warning": None,
        "vxn_regime": "unknown",
        "vxn_warning": None,
        # scan_candidates format
        "regime": "unknown",
        "recommended_delta_tier": "standard",
        "regime_note": "",
    }
    try:
        qqq = yf.Ticker("QQQ")
        df = qqq.history(period="12mo")
        if not df.empty and len(df) >= 200:
            raw = compute_raw_indicators(df)
            qqq_price = float(df["Close"].iloc[-1])
            sma200 = raw.get("sma200")
            result["qqq_price"] = round(qqq_price, 2)
            if sma200 is not None:
                result["qqq_sma200"] = round(sma200, 2)
                above = qqq_price > sma200
                result["qqq_above_sma200"] = above
                pct = ((qqq_price - sma200) / sma200) * 100

                if above:
                    result["market_regime"] = "bull"
                    result["regime"] = "bull"
                    result["csp_recommendation"] = (
                        f"QQQ {pct:+.1f}% above SMA200 — bull market. "
                        "Use standard delta targets per stock trend."
                    )
                    result["regime_note"] = (
                        f"QQQ ${qqq_price:.2f} above SMA200 ${sma200:.2f} ({pct:+.1f}%)"
                    )
                else:
                    result["market_regime"] = "bear"
                    result["regime"] = "bear"
                    result["csp_delta_adjustment"] = "reduce_one_tier"
                    warning = (
                        f"⚠️ QQQ {pct:+.1f}% BELOW SMA200 — BEAR MARKET. "
                        "CSP assignment risk is 2.3× higher than normal. "
                        "Reduce delta by one tier (e.g. 0.20→0.15, 0.15→0.10). "
                        "Consider skipping new CSPs on weak/bear-trend stocks entirely."
                    )
                    result["warning"] = warning
                    result["csp_recommendation"] = warning
                    result["regime_note"] = (
                        f"QQQ ${qqq_price:.2f} BELOW SMA200 ${sma200:.2f} ({pct:+.1f}%)"
                    )
    except Exception as e:
        result["error"] = str(e)

    try:
        vxn = yf.Ticker("^VXN")
        vxn_df = vxn.history(period="5d")
        if not vxn_df.empty:
            vxn_val = float(vxn_df["Close"].iloc[-1])
            result["vxn"] = round(vxn_val, 1)
            if vxn_val >= 35:
                result["vxn_regime"] = "extreme"
                vxn_warning = (
                    f"⚠️⚠️ VXN={vxn_val:.0f} — EXTREME VOLATILITY (≥35). "
                    "Skip ALL new CSPs. Wait for VXN to fall below 30."
                )
                result["vxn_warning"] = vxn_warning
                if result["warning"]:
                    result["warning"] += " | " + vxn_warning
                else:
                    result["warning"] = vxn_warning
            elif vxn_val >= 25:
                result["vxn_regime"] = "high"
                vxn_warning = (
                    f"⚠️ VXN={vxn_val:.0f} — HIGH VOLATILITY (25–35). "
                    "Reduce delta one tier further. Use half-size positions."
                )
                result["vxn_warning"] = vxn_warning
                if result["warning"]:
                    result["warning"] += " | " + vxn_warning
                else:
                    result["warning"] = vxn_warning
            else:
                result["vxn_regime"] = "normal"
                result["vxn_warning"] = None
    except Exception:
        pass

    # Combine regime + VXN into delta tier recommendation
    regime = result["regime"]
    vxn_regime = result["vxn_regime"]
    if vxn_regime == "extreme":
        result["recommended_delta_tier"] = "skip"
        result["regime_note"] += " | VXN≥35 → SKIP new CSPs"
    elif regime == "bear" or vxn_regime == "high":
        result["recommended_delta_tier"] = "reduce"
        result["regime_note"] += " | Bear/high-VXN → reduce delta one tier"
    else:
        result["recommended_delta_tier"] = "standard"

    return result
