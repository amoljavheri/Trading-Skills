# ABOUTME: Gathers comprehensive stock analysis data from multiple modules.
# ABOUTME: Returns detailed JSON with conviction score, CSP analysis, LEAP scenarios,
# ABOUTME: market context, and spread strategies for report generation by Claude.

import math
import sys
from datetime import datetime, timedelta

import yfinance as yf
from scipy.stats import norm

from trading_skills.fundamentals import get_fundamentals
from trading_skills.piotroski import calculate_piotroski_score
from trading_skills.scanner_bullish import SCORE_MAX, compute_bullish_score
from trading_skills.scanner_pmcc import analyze_pmcc
from trading_skills.spreads import (
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
    get_option_price,
)
from trading_skills.technicals import (
    _find_swing_levels,
    compute_raw_indicators,
)
from trading_skills.utils import get_current_price

# Sector ETF mapping for market context
SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}


# ---------------------------------------------------------------------------
# Phase 5: Market Context
# ---------------------------------------------------------------------------


def get_market_context(sector: str | None = None) -> dict:
    """Compute market regime context from SPY trend + VIX proxy + sector ETF.

    Returns dict with SPY trend, VIX regime, and optional sector trend.
    Adds one yfinance call (SPY); sector ETF call is optional.
    """
    result = {
        "spy_trend": None,
        "spy_price": None,
        "spy_sma50": None,
        "spy_above_sma50": None,
        "spy_above_sma200": None,
        "vix_proxy": None,
        "vix_regime": None,
        "sector_etf": None,
        "sector_trend": None,
    }

    try:
        spy = yf.Ticker("SPY")
        spy_df = spy.history(period="12mo")
        if spy_df.empty or len(spy_df) < 50:
            return result

        spy_raw = compute_raw_indicators(spy_df)
        spy_price = float(spy_df["Close"].iloc[-1])
        spy_sma50 = spy_raw.get("sma50")
        spy_sma200 = spy_raw.get("sma200")

        result["spy_price"] = round(spy_price, 2)
        result["spy_sma50"] = round(spy_sma50, 2) if spy_sma50 else None
        result["spy_above_sma50"] = spy_price > spy_sma50 if spy_sma50 else None
        result["spy_above_sma200"] = spy_price > spy_sma200 if spy_sma200 else None

        # Determine SPY trend: bullish / bearish / sideways
        if spy_sma50:
            pct_from_sma50 = (spy_price - spy_sma50) / spy_sma50 * 100
            # Sideways: within ±2% of SMA50
            if abs(pct_from_sma50) <= 2.0:
                result["spy_trend"] = "sideways"
            elif spy_price > spy_sma50:
                result["spy_trend"] = "bullish"
            else:
                result["spy_trend"] = "bearish"

        # VIX proxy: ATM call IV from SPY near-term options
        try:
            spy_expiries = spy.options
            if spy_expiries:
                today = datetime.now().date()
                target = today + timedelta(days=35)
                sel_expiry = None
                for exp in spy_expiries:
                    exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                    if exp_date >= target:
                        sel_expiry = exp
                        break
                if sel_expiry:
                    chain = spy.option_chain(sel_expiry)
                    if not chain.calls.empty:
                        calls = chain.calls
                        strikes = sorted(calls["strike"].unique())
                        atm = min(strikes, key=lambda x: abs(x - spy_price))
                        atm_row = calls[calls["strike"] == atm]
                        if not atm_row.empty:
                            iv_val = atm_row.iloc[0].get("impliedVolatility")
                            if iv_val and not math.isnan(iv_val):
                                vix_proxy = float(iv_val) * 100
                                result["vix_proxy"] = round(vix_proxy, 1)
                                if vix_proxy < 15:
                                    result["vix_regime"] = "low"
                                elif vix_proxy < 20:
                                    result["vix_regime"] = "normal"
                                elif vix_proxy < 30:
                                    result["vix_regime"] = "elevated"
                                else:
                                    result["vix_regime"] = "high"
        except Exception:
            pass  # VIX proxy is best-effort

        # Sector ETF trend
        if sector and sector in SECTOR_ETFS:
            try:
                etf_symbol = SECTOR_ETFS[sector]
                result["sector_etf"] = etf_symbol
                etf = yf.Ticker(etf_symbol)
                etf_df = etf.history(period="6mo")
                if not etf_df.empty and len(etf_df) >= 50:
                    etf_raw = compute_raw_indicators(etf_df)
                    etf_price = float(etf_df["Close"].iloc[-1])
                    etf_sma50 = etf_raw.get("sma50")
                    if etf_sma50:
                        pct = (etf_price - etf_sma50) / etf_sma50 * 100
                        if abs(pct) <= 2.0:
                            result["sector_trend"] = "sideways"
                        elif etf_price > etf_sma50:
                            result["sector_trend"] = "bullish"
                        else:
                            result["sector_trend"] = "bearish"
            except Exception:
                pass

    except Exception as e:
        print(f"Market context error: {e}", file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# Phase 1: Unified Conviction Score
# ---------------------------------------------------------------------------


def compute_conviction_score(
    bullish: dict,
    pmcc: dict,
    fundamentals_info: dict,
    piotroski: dict,
    market_context: dict | None = None,
) -> dict:
    """Compute unified 0-10 conviction score with dimensional breakdown.

    Components:
    - Technical (5.5 max): trend(3) + ADX(0.5) + RSI(1) + volume_momentum(1)
    - Fundamental (2 max): piotroski(1) + valuation(1)
    - Strategy (1.5 max): PMCC viability(1.5)
    - Market (1 max): market_regime(1)
    """
    components = {}
    strengths = []
    risks = []

    # --- Trend (3 pts) from normalized_score ---
    norm_score = bullish.get("normalized_score", 0) or 0
    if norm_score >= 0.52:
        trend_pts = 3.0
    elif norm_score >= 0.35:
        trend_pts = 2.0
    elif norm_score >= 0.17:
        trend_pts = 1.0
    else:
        trend_pts = 0.0
    raw_score = bullish.get("score", 0) or 0
    components["trend"] = {
        "score": trend_pts,
        "max": 3,
        "detail": f"Bullish score {raw_score:.1f}/{SCORE_MAX} (normalized {norm_score:.3f})",
    }
    if trend_pts >= 2:
        strengths.append(
            f"Strong trend (score {raw_score:.1f}/{SCORE_MAX}, "
            f"stage: {bullish.get('trend_stage', 'N/A')})"
        )
    elif trend_pts == 0:
        risks.append(f"Weak/no trend (score {raw_score:.1f}/{SCORE_MAX})")

    # --- ADX (0.5 pts) — reduced, already counted in trend ---
    adx_val = bullish.get("adx") or 0
    dmp = bullish.get("dmp") or 0
    dmn = bullish.get("dmn") or 0
    if adx_val >= 25 and dmp > dmn:
        adx_pts = 0.5
        detail = f"Strong bullish trend (ADX={adx_val:.0f})"
    else:
        adx_pts = 0.0
        detail = f"ADX={adx_val:.0f}" if adx_val else "ADX N/A"
    components["adx"] = {"score": adx_pts, "max": 0.5, "detail": detail}
    if adx_val >= 25 and dmp > dmn:
        strengths.append(f"Confirmed trend direction (ADX {adx_val:.1f})")

    # --- RSI (1 pt) ---
    rsi_val = bullish.get("rsi") or 50
    if 50 <= rsi_val <= 70:
        rsi_pts = 1.0
        detail = f"Bullish zone ({rsi_val:.1f})"
    elif 30 <= rsi_val < 50:
        rsi_pts = 0.5
        detail = f"Neutral ({rsi_val:.1f})"
    else:
        rsi_pts = 0.0
        detail = f"{'Overbought' if rsi_val > 70 else 'Oversold'} ({rsi_val:.1f})"
    components["rsi"] = {"score": rsi_pts, "max": 1, "detail": detail}
    if rsi_val > 70:
        risks.append(f"RSI overbought ({rsi_val:.1f})")
    elif rsi_val < 30:
        risks.append(f"RSI oversold ({rsi_val:.1f})")

    # --- Volume/momentum (1 pt) ---
    breakout = bullish.get("breakout_signal", False)
    vol_confirmed = bullish.get("volume_confirmed", False)
    obv_trend = bullish.get("obv_trend")
    if breakout and vol_confirmed:
        vol_pts = 1.0
        detail = "Breakout + volume confirmed"
    elif obv_trend == "rising":
        vol_pts = 0.5
        detail = "OBV accumulation"
    else:
        vol_pts = 0.0
        detail = "No volume confirmation"
    components["volume_momentum"] = {"score": vol_pts, "max": 1, "detail": detail}
    if breakout:
        strengths.append("20-day high breakout")
    if vol_confirmed:
        strengths.append("Volume-confirmed move")

    # --- Piotroski (1 pt) ---
    pio_score = piotroski.get("score") or 0
    if pio_score >= 7:
        pio_pts = 1.0
    elif pio_score >= 4:
        pio_pts = 0.5
    else:
        pio_pts = 0.0
    components["piotroski"] = {
        "score": pio_pts,
        "max": 1,
        "detail": f"F-Score {pio_score}/9",
    }
    if pio_score >= 7:
        strengths.append(f"Strong Piotroski ({pio_score}/9)")
    elif pio_score <= 3:
        risks.append(f"Weak Piotroski ({pio_score}/9)")

    # --- Valuation (1 pt) ---
    forward_pe = fundamentals_info.get("forwardPE")
    if forward_pe and forward_pe > 0:
        if forward_pe < 15:
            val_pts = 1.0
            detail = f"Attractive (Fwd P/E {forward_pe:.1f}x)"
        elif forward_pe <= 25:
            val_pts = 0.5
            detail = f"Reasonable (Fwd P/E {forward_pe:.1f}x)"
        else:
            val_pts = 0.0
            detail = f"Premium (Fwd P/E {forward_pe:.1f}x)"
    else:
        val_pts = 0.0
        detail = "Fwd P/E N/A"
    components["valuation"] = {"score": val_pts, "max": 1, "detail": detail}
    if forward_pe and forward_pe > 30:
        risks.append(f"Expensive valuation (Fwd P/E {forward_pe:.1f}x)")
    elif forward_pe and forward_pe < 15:
        strengths.append(f"Attractive valuation (Fwd P/E {forward_pe:.1f}x)")

    # --- PMCC/Strategy (1.5 pts) ---
    pmcc_score = pmcc.get("pmcc_score") or 0
    if pmcc_score >= 9:
        pmcc_pts = 1.5
    elif pmcc_score >= 7:
        pmcc_pts = 1.0
    elif pmcc_score >= 5:
        pmcc_pts = 0.5
    else:
        pmcc_pts = 0.0
    components["pmcc_strategy"] = {
        "score": pmcc_pts,
        "max": 1.5,
        "detail": f"PMCC score {pmcc_score}/11",
    }
    if pmcc_score >= 9:
        strengths.append(f"Excellent PMCC candidate ({pmcc_score}/11)")
    elif pmcc_score >= 7:
        strengths.append(f"Good PMCC candidate ({pmcc_score}/11)")
    elif pmcc_score > 0 and pmcc_score < 5:
        risks.append(f"Poor PMCC viability ({pmcc_score}/11)")

    # --- Market regime (1 pt) ---
    mc = market_context or {}
    spy_trend = mc.get("spy_trend")
    vix_regime = mc.get("vix_regime")

    if spy_trend == "bullish" and vix_regime in ("low", "normal"):
        mkt_pts = 1.0
        detail = f"Bullish market, VIX {vix_regime}"
    elif spy_trend == "bullish" and vix_regime == "elevated":
        mkt_pts = 0.75
        detail = "Bullish market, elevated VIX"
    elif spy_trend == "sideways" or (spy_trend is None and market_context is None):
        mkt_pts = 0.5
        detail = "Sideways/unknown market"
    elif spy_trend == "bearish" and vix_regime in ("low", "normal"):
        mkt_pts = 0.25
        detail = f"Bearish market, VIX {vix_regime}"
    else:
        mkt_pts = 0.0
        detail = "Bearish market, high VIX"
        risks.append("Bearish market regime with elevated volatility")
    components["market_regime"] = {"score": mkt_pts, "max": 1, "detail": detail}
    if spy_trend == "bearish":
        risks.append(f"SPY in downtrend ({mc.get('spy_price', 'N/A')})")

    # Additional strengths/risks from fundamentals
    iv_pct = pmcc.get("iv_pct") or 0
    if 25 <= iv_pct <= 50:
        strengths.append(f"Ideal IV range ({iv_pct:.0f}%)")
    roe = fundamentals_info.get("returnOnEquity") or 0
    if roe > 0.15:
        strengths.append(f"Strong ROE ({roe * 100:.1f}%)")
    debt_eq = fundamentals_info.get("debtToEquity") or 0
    if debt_eq > 100:
        risks.append(f"High debt/equity ({debt_eq:.0f}%)")
    rev_growth = fundamentals_info.get("revenueGrowth") or 0
    if rev_growth < 0:
        risks.append(f"Revenue declining ({rev_growth * 100:+.1f}%)")
    payout = fundamentals_info.get("payoutRatio") or 0
    if payout > 0.8:
        risks.append(f"High payout ratio ({payout * 100:.0f}%)")

    # --- Compute total ---
    total = sum(c["score"] for c in components.values())
    total = max(0.0, min(total, 10.0))

    # --- Dimensional groupings ---
    tech_score = (
        components["trend"]["score"]
        + components["adx"]["score"]
        + components["rsi"]["score"]
        + components["volume_momentum"]["score"]
    )
    fund_score = components["piotroski"]["score"] + components["valuation"]["score"]
    strat_score = components["pmcc_strategy"]["score"]
    mkt_score = components["market_regime"]["score"]

    dimensions = {
        "technical": {"score": round(tech_score, 2), "max": 5.5},
        "fundamental": {"score": round(fund_score, 2), "max": 2},
        "strategy": {"score": round(strat_score, 2), "max": 1.5},
        "market": {"score": round(mkt_score, 2), "max": 1},
    }

    # --- Signal alignment ---
    tech_pct = tech_score / 5.5 if tech_score > 0 else 0
    fund_pct = fund_score / 2.0 if fund_score > 0 else 0
    conflicts = []

    if tech_pct > 0.6 and fund_pct < 0.3:
        alignment = "conflicting"
        conflicts.append(
            f"Strong technicals ({tech_score:.1f}/5.5) but weak fundamentals ({fund_score:.1f}/2)"
        )
    elif fund_pct > 0.6 and tech_pct < 0.3:
        alignment = "conflicting"
        conflicts.append(
            f"Strong fundamentals ({fund_score:.1f}/2) but weak technicals ({tech_score:.1f}/5.5)"
        )
    elif tech_pct > 0.6 and fund_pct > 0.6:
        alignment = "aligned"
    else:
        alignment = "mixed"

    # Check market vs stock conflicts
    if trend_pts >= 2 and spy_trend == "bearish":
        conflicts.append("Stock bullish but market in downtrend — monitor closely")
    if trend_pts == 0 and spy_trend == "bullish":
        conflicts.append("Stock weak despite bullish market — stock-specific issue")

    # --- Verdict ---
    if total >= 8:
        verdict = "Strong Bull"
        recommendation = "BUY / PMCC CANDIDATE"
        recommendation_level = "positive"
    elif total >= 6:
        verdict = "Moderately Bullish"
        recommendation = "BUY / PMCC CANDIDATE"
        recommendation_level = "positive"
    elif total >= 4:
        verdict = "Neutral"
        recommendation = "HOLD / MONITOR"
        recommendation_level = "neutral"
    elif total >= 2:
        verdict = "Bearish"
        recommendation = "AVOID / WAIT"
        recommendation_level = "negative"
    else:
        verdict = "Strong Bear"
        recommendation = "AVOID / WAIT"
        recommendation_level = "negative"

    return {
        "total": round(total, 2),
        "max": 10,
        "components": {k: {**v, "score": round(v["score"], 2)} for k, v in components.items()},
        "dimensions": dimensions,
        "signal_alignment": alignment,
        "conflicts": conflicts,
        "verdict": verdict,
        "recommendation": recommendation,
        "recommendation_level": recommendation_level,
        "strengths": strengths,
        "risks": risks,
    }


def compute_recommendation(data: dict) -> dict:
    """Backward-compatible wrapper around compute_conviction_score.

    Returns the same shape as the original function for existing tests.
    """
    bullish = data.get("bullish", {})
    pmcc = data.get("pmcc", {})
    fundamentals = data.get("fundamentals", {})
    piotroski = data.get("piotroski", {})
    market_context = data.get("market_context")

    conviction = compute_conviction_score(
        bullish=bullish,
        pmcc=pmcc,
        fundamentals_info=fundamentals.get("info", {}),
        piotroski=piotroski,
        market_context=market_context,
    )

    return {
        "recommendation": conviction["recommendation"],
        "recommendation_level": conviction["recommendation_level"],
        "points": conviction["total"],
        "strengths": conviction["strengths"],
        "risks": conviction["risks"],
        "conviction_score": conviction,
    }


# ---------------------------------------------------------------------------
# Phase 2: CSP Analysis (Delta-Based)
# ---------------------------------------------------------------------------


def analyze_csp(
    current_price: float,
    puts_data: list[dict],
    dte: int,
    bullish_score: float = 0,
    next_earnings: str | None = None,
    market_context: dict | None = None,
    support_levels: dict | None = None,
) -> dict:
    """Analyze Cash Secured Put opportunities using delta-based strike selection.

    Args:
        current_price: Current stock price.
        puts_data: List of put option dicts, each with at minimum:
            strike, bid, ask. Optionally: delta, iv (as decimal).
        dte: Days to expiry.
        bullish_score: Raw bullish score from scanner.
        next_earnings: Next earnings date string (YYYY-MM-DD).
        market_context: Market regime context dict.
        support_levels: Dict with sma50, sma200, swing_lows for support context.
    """
    if not puts_data or dte <= 0:
        return {"error": "No puts data or invalid DTE"}

    # Determine if we have real delta values
    has_delta = any(p.get("delta") is not None for p in puts_data)

    # Delta targets for 3 tiers
    delta_targets = {
        "conservative": 0.15,
        "balanced": 0.25,
        "aggressive": 0.35,
    }

    # Fallback: price-based approximation when no delta
    pct_targets = {
        "conservative": 0.90,
        "balanced": 0.95,
        "aggressive": 0.98,
    }

    tiers = {}
    for tier_name, target_delta in delta_targets.items():
        if has_delta:
            # Find put with delta closest to target (delta is negative for puts)
            best = None
            best_diff = float("inf")
            for p in puts_data:
                d = p.get("delta")
                if d is None:
                    continue
                d_abs = abs(d)
                diff = abs(d_abs - target_delta)
                if diff < best_diff:
                    best_diff = diff
                    best = p
        else:
            # Fallback: find strike closest to price * pct_target
            target_strike = current_price * pct_targets[tier_name]
            best = None
            best_diff = float("inf")
            for p in puts_data:
                diff = abs(p["strike"] - target_strike)
                if diff < best_diff:
                    best_diff = diff
                    best = p

        if best is None:
            continue

        strike = best["strike"]
        bid = best.get("bid") or 0
        ask = best.get("ask") or 0
        mid = (bid + ask) / 2
        delta_abs = abs(best.get("delta") or 0)
        iv_val = best.get("iv") or best.get("mid_iv") or 0
        iv_pct = iv_val * 100 if iv_val < 1 else iv_val  # handle both decimal and %

        # Calculations
        ann_yield = (mid / strike) * (365 / dte) * 100 if strike > 0 else 0
        prob_profit = (1 - delta_abs) * 100 if delta_abs > 0 else None
        capital_required = strike * 100
        cost_basis = strike - mid

        tier_data = {
            "strike": strike,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": round(mid, 2),
            "delta": round(-delta_abs, 4) if delta_abs else None,
            "iv_pct": round(iv_pct, 1) if iv_pct else None,
            "ann_yield_pct": round(ann_yield, 1),
            "prob_profit_pct": round(prob_profit, 1) if prob_profit else None,
            "capital_required": round(capital_required, 2),
            "cost_basis_if_assigned": round(cost_basis, 2),
            "selection_method": "delta" if has_delta else "estimated",
        }

        # Support context
        if support_levels:
            sma50 = support_levels.get("sma50")
            sma200 = support_levels.get("sma200")
            swing_lows = support_levels.get("swing_lows", [])

            below_strike = [sl for sl in swing_lows if sl < strike]
            nearest_support = max(below_strike) if below_strike else None

            support_ctx = {
                "nearest_support": nearest_support,
                "strike_vs_sma50": (("above" if strike > sma50 else "below") if sma50 else None),
                "strike_vs_sma200": (("above" if strike > sma200 else "below") if sma200 else None),
                "distance_to_support_pct": (
                    round((strike - nearest_support) / nearest_support * 100, 1)
                    if nearest_support and nearest_support > 0
                    else None
                ),
            }

            # Warning: strike below SMA200 in downtrend
            if sma200 and strike < sma200 and bullish_score < 4:
                support_ctx["warning"] = (
                    "Strike below SMA200 in weak trend — elevated assignment risk"
                )
            tier_data["support_context"] = support_ctx

        tiers[tier_name] = tier_data

    if not tiers:
        return {"error": "Could not find suitable put strikes"}

    # --- Suitability rating ---
    mc = market_context or {}
    spy_above_sma200 = mc.get("spy_above_sma200", True)
    vix_proxy = mc.get("vix_proxy")

    # Find ATM IV (use balanced tier if available)
    atm_iv = 0
    for tier_name in ["balanced", "aggressive", "conservative"]:
        if tier_name in tiers and tiers[tier_name].get("iv_pct"):
            atm_iv = tiers[tier_name]["iv_pct"]
            break

    # Earnings proximity
    days_to_earnings = None
    if next_earnings:
        try:
            ear_date = datetime.strptime(next_earnings, "%Y-%m-%d").date()
            days_to_earnings = (ear_date - datetime.now().date()).days
        except (ValueError, TypeError):
            pass

    # Base suitability
    if (
        atm_iv >= 25
        and bullish_score >= 5
        and (days_to_earnings is None or days_to_earnings > 30)
        and mc.get("spy_trend") != "bearish"
    ):
        suitability = "good"
        reason = (
            f"IV at {atm_iv:.0f}% provides good premium; bullish trend (score {bullish_score:.1f})"
        )
    elif (
        atm_iv < 15
        or bullish_score < 2
        or (days_to_earnings is not None and days_to_earnings <= 14)
        or (bullish_score < 3 and mc.get("spy_trend") == "bearish")
    ):
        suitability = "avoid"
        reasons = []
        if atm_iv < 15:
            reasons.append(f"IV too low ({atm_iv:.0f}%)")
        if bullish_score < 2:
            reasons.append(f"weak trend ({bullish_score:.1f})")
        if days_to_earnings is not None and days_to_earnings <= 14:
            reasons.append(f"earnings in {days_to_earnings} days")
        if bullish_score < 3 and mc.get("spy_trend") == "bearish":
            reasons.append("weak stock in bearish market")
        reason = "; ".join(reasons)
    else:
        suitability = "caution"
        reasons = []
        if atm_iv < 25:
            reasons.append(f"moderate IV ({atm_iv:.0f}%)")
        if bullish_score < 5:
            reasons.append(f"moderate trend ({bullish_score:.1f})")
        if days_to_earnings is not None and days_to_earnings <= 30:
            reasons.append(f"earnings in {days_to_earnings} days")
        reason = "; ".join(reasons) if reasons else "mixed signals"

    # Market regime modifier: downgrade by one level if SPY < SMA200
    if spy_above_sma200 is False:
        if suitability == "good":
            suitability = "caution"
            reason += " [downgraded: SPY below SMA200]"
        elif suitability == "caution":
            suitability = "avoid"
            reason += " [downgraded: SPY below SMA200]"

    flags = []
    if vix_proxy and vix_proxy > 30:
        flags.append("Elevated assignment risk — high market fear (VIX-proxy > 30%)")

    return {
        "dte": dte,
        "suitability": {"rating": suitability, "reason": reason, "flags": flags},
        "tiers": tiers,
        "recommended_tier": "balanced" if "balanced" in tiers else list(tiers.keys())[0],
        "source": "tradier" if has_delta else "yfinance",
    }


# ---------------------------------------------------------------------------
# Phase 3: LEAP Scenario Analysis
# ---------------------------------------------------------------------------


def analyze_leap_scenarios(
    current_price: float,
    leap_call: dict,
    iv: float,
    scenarios: list[float] | None = None,
) -> dict:
    """Compute LEAP call scenario analysis with delta+gamma+theta approximation.

    Args:
        current_price: Current stock price.
        leap_call: Dict with strike, bid, ask, mid, delta, gamma (optional), theta.
        iv: Implied volatility as decimal (e.g., 0.35).
        scenarios: List of move percentages. Default: [-0.10, 0, 0.05, 0.10, 0.20, 0.30].
    """
    if scenarios is None:
        scenarios = [-0.10, 0.0, 0.05, 0.10, 0.20, 0.30]

    cost = leap_call.get("mid") or 0
    delta = leap_call.get("delta") or 0
    gamma = leap_call.get("gamma")
    theta = leap_call.get("theta") or 0
    monthly_theta = abs(theta) * 30

    if cost <= 0 or delta <= 0:
        return {"error": "Invalid LEAP data (cost or delta is zero)"}

    scenario_results = []
    for move_pct in scenarios:
        price_change = current_price * move_pct
        est_value = cost + (delta * price_change)
        if gamma and gamma > 0:
            est_value += 0.5 * gamma * price_change**2
        est_value -= monthly_theta
        est_value = max(0, est_value)  # Can't go below 0

        pnl = est_value - cost
        return_pct = (pnl / cost) * 100

        # Confidence label
        abs_move = abs(move_pct)
        if abs_move <= 0.05:
            confidence = "high"
        elif abs_move <= 0.10:
            confidence = "moderate"
        else:
            confidence = "low"

        scenario_results.append(
            {
                "move_pct": round(move_pct * 100, 1),
                "target_price": round(current_price * (1 + move_pct), 2),
                "est_value": round(est_value, 2),
                "pnl": round(pnl, 2),
                "return_pct": round(return_pct, 1),
                "confidence": confidence,
            }
        )

    # Break-even move (% stock must rise to cover theta drag)
    breakeven_pct = (monthly_theta / delta / current_price * 100) if delta > 0 else None

    # Probability of +30% LEAP gain in 1 month
    prob_30_gain = None
    if iv > 0 and delta > 0:
        target_gain = cost * 0.30
        required_stock_move = (target_gain + monthly_theta) / delta
        monthly_vol = current_price * iv * math.sqrt(30 / 365)
        if monthly_vol > 0:
            z = required_stock_move / monthly_vol
            prob_30_gain = (1 - norm.cdf(z)) * 100

    return {
        "leap_details": {
            "strike": leap_call.get("strike"),
            "expiry": leap_call.get("expiry"),
            "bid": leap_call.get("bid"),
            "ask": leap_call.get("ask"),
            "mid": round(cost, 2),
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "monthly_theta": round(monthly_theta, 2),
            "cost_per_contract": round(cost * 100, 2),
        },
        "scenarios": scenario_results,
        "breakeven_move_pct": round(breakeven_pct, 2) if breakeven_pct else None,
        "prob_30pct_gain_1mo": round(prob_30_gain, 1) if prob_30_gain else None,
        "model_note": (
            "First-order approximation. LEAPS are highly sensitive to "
            "IV changes. Accuracy degrades for moves >15%."
        ),
        "source": "tradier" if gamma is not None else "estimated",
    }


# ---------------------------------------------------------------------------
# Phase 4: Spread Strategies (delegates to spreads.py)
# ---------------------------------------------------------------------------


def compute_spread_strategies(
    symbol: str,
    ticker=None,
    tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Compute 5 spread strategies, delegating to spreads.py.

    Uses Tradier data when available, falls back to yfinance.
    """
    try:
        ticker = ticker or yf.Ticker(symbol)
        info = ticker.info
        price = underlying_price or get_current_price(info)

        if not price:
            return {"error": "Could not get current price"}

        expiries = ticker.options
        if not expiries:
            return {"error": "No options available"}

        today = datetime.now().date()
        target_date = today + timedelta(days=35)
        selected_expiry = None

        for exp in expiries:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            if exp_date >= target_date:
                selected_expiry = exp
                break

        if not selected_expiry:
            selected_expiry = expiries[-1] if expiries else None
        if not selected_expiry:
            return {"error": "No suitable expiry found"}

        exp_date = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
        dte = (exp_date - today).days

        # Get chain for strike discovery
        chain = ticker.option_chain(selected_expiry)
        calls = chain.calls
        puts = chain.puts
        if calls.empty or puts.empty:
            return {"error": "Empty option chain"}

        strikes = sorted(calls["strike"].unique())
        atm_strike = min(strikes, key=lambda x: abs(x - price))
        strike_diff = strikes[1] - strikes[0] if len(strikes) > 1 else 5

        results = {
            "expiry": selected_expiry,
            "dte": dte,
            "underlying_price": round(price, 2),
            "atm_strike": atm_strike,
            "strategies": {},
            "source": "tradier" if tradier_options else "yfinance",
        }

        # Use spreads.py analyze functions with Tradier if available
        try:
            vert_bull = analyze_vertical(
                symbol,
                selected_expiry,
                atm_strike,
                atm_strike + strike_diff,
                "call",
                tradier_options=tradier_options,
                underlying_price=underlying_price,
            )
            if "error" not in vert_bull:
                results["strategies"]["bull_call_spread"] = {
                    "name": "Bull Call Spread",
                    "direction": "bullish",
                    "long_strike": atm_strike,
                    "short_strike": atm_strike + strike_diff,
                    "net_debit": vert_bull.get("net_debit"),
                    "net_debit_total": vert_bull.get("net_debit_total"),
                    "max_profit": vert_bull.get("max_profit"),
                    "max_loss": vert_bull.get("max_loss"),
                    "breakeven": vert_bull.get("breakeven"),
                    "risk_reward": vert_bull.get("risk_reward"),
                }
        except Exception:
            pass

        try:
            vert_bear = analyze_vertical(
                symbol,
                selected_expiry,
                atm_strike,
                atm_strike - strike_diff,
                "put",
                tradier_options=tradier_options,
                underlying_price=underlying_price,
            )
            if "error" not in vert_bear:
                results["strategies"]["bear_put_spread"] = {
                    "name": "Bear Put Spread",
                    "direction": "bearish",
                    "long_strike": atm_strike,
                    "short_strike": atm_strike - strike_diff,
                    "net_debit": vert_bear.get("net_debit"),
                    "net_debit_total": vert_bear.get("net_debit_total"),
                    "max_profit": vert_bear.get("max_profit"),
                    "max_loss": vert_bear.get("max_loss"),
                    "breakeven": vert_bear.get("breakeven"),
                    "risk_reward": vert_bear.get("risk_reward"),
                }
        except Exception:
            pass

        try:
            straddle = analyze_straddle(
                symbol,
                selected_expiry,
                atm_strike,
                tradier_options=tradier_options,
                underlying_price=underlying_price,
            )
            if "error" not in straddle:
                results["strategies"]["long_straddle"] = {
                    "name": "Long Straddle",
                    "direction": "neutral (expects big move)",
                    "strike": atm_strike,
                    "total_cost": straddle.get("total_cost"),
                    "max_profit": "unlimited",
                    "max_loss": straddle.get("max_loss"),
                    "breakeven_up": straddle.get("breakeven_up"),
                    "breakeven_down": straddle.get("breakeven_down"),
                    "move_needed_pct": straddle.get("move_needed_pct"),
                }
        except Exception:
            pass

        try:
            strangle = analyze_strangle(
                symbol,
                selected_expiry,
                atm_strike + strike_diff,
                atm_strike - strike_diff,
                tradier_options=tradier_options,
                underlying_price=underlying_price,
            )
            if "error" not in strangle:
                results["strategies"]["long_strangle"] = {
                    "name": "Long Strangle",
                    "direction": "neutral (expects big move)",
                    "call_strike": atm_strike + strike_diff,
                    "put_strike": atm_strike - strike_diff,
                    "total_cost": strangle.get("total_cost"),
                    "max_profit": "unlimited",
                    "max_loss": strangle.get("max_loss"),
                    "breakeven_up": strangle.get("breakeven_up"),
                    "breakeven_down": strangle.get("breakeven_down"),
                }
        except Exception:
            pass

        try:
            ic = analyze_iron_condor(
                symbol,
                selected_expiry,
                atm_strike - 2 * strike_diff,
                atm_strike - strike_diff,
                atm_strike + strike_diff,
                atm_strike + 2 * strike_diff,
                tradier_options=tradier_options,
                underlying_price=underlying_price,
            )
            if "error" not in ic:
                results["strategies"]["iron_condor"] = {
                    "name": "Iron Condor",
                    "direction": "neutral (expects low volatility)",
                    "put_long": atm_strike - 2 * strike_diff,
                    "put_short": atm_strike - strike_diff,
                    "call_short": atm_strike + strike_diff,
                    "call_long": atm_strike + 2 * strike_diff,
                    "net_credit": ic.get("net_credit"),
                    "net_credit_total": ic.get("net_credit_total"),
                    "max_profit": ic.get("max_profit"),
                    "max_loss": ic.get("max_loss"),
                    "breakeven_down": ic.get("breakeven_down"),
                    "breakeven_up": ic.get("breakeven_up"),
                    "risk_reward": ic.get("risk_reward"),
                }
        except Exception:
            pass

        # Fallback: if spreads.py failed, use local yfinance logic
        if not results["strategies"]:
            return _analyze_spreads_fallback(price, calls, puts, selected_expiry, dte)

        return results

    except Exception as e:
        return {"error": str(e)}


def _analyze_spreads_fallback(price, calls, puts, expiry, dte):
    """Fallback spread analysis using yfinance option chain directly."""
    strikes = sorted(calls["strike"].unique())
    atm_strike = min(strikes, key=lambda x: abs(x - price))
    strike_diff = strikes[1] - strikes[0] if len(strikes) > 1 else 5

    results = {
        "expiry": expiry,
        "dte": dte,
        "underlying_price": round(price, 2),
        "atm_strike": atm_strike,
        "strategies": {},
        "source": "yfinance_fallback",
    }

    def get_opt(option_type, strike):
        opt = get_option_price(calls, puts, strike, option_type)
        if opt:
            opt["iv"] = round(opt["iv"] * 100, 1)
        return opt

    # Bull Call Spread
    long_c = get_opt("call", atm_strike)
    short_c = get_opt("call", atm_strike + strike_diff)
    if long_c and short_c:
        nd = long_c["mid"] - short_c["mid"]
        w = strike_diff
        mp = w - nd
        results["strategies"]["bull_call_spread"] = {
            "name": "Bull Call Spread",
            "direction": "bullish",
            "long_strike": atm_strike,
            "short_strike": atm_strike + strike_diff,
            "net_debit": round(nd, 2),
            "net_debit_total": round(nd * 100, 2),
            "max_profit": round(mp * 100, 2),
            "max_loss": round(nd * 100, 2),
            "breakeven": round(atm_strike + nd, 2),
            "risk_reward": round(mp / nd, 2) if nd > 0 else None,
        }

    return results


# ---------------------------------------------------------------------------
# Data fetching & report generation
# ---------------------------------------------------------------------------


def fetch_data(symbol: str, include_market_context: bool = True) -> dict:
    """Fetch all analysis data for a symbol using library functions directly."""
    ticker = yf.Ticker(symbol)

    # Bullish scanner
    bullish_data = compute_bullish_score(symbol, ticker=ticker) or {}

    # PMCC scanner
    pmcc_data = analyze_pmcc(symbol, ticker=ticker) or {}

    # Fundamentals
    fundamentals = get_fundamentals(symbol, "all", ticker=ticker)

    # Piotroski
    piotroski = calculate_piotroski_score(symbol, ticker=ticker)

    # Spread analysis (delegating to spreads.py)
    spreads = compute_spread_strategies(symbol, ticker=ticker)

    # Market context
    market_ctx = None
    if include_market_context:
        sector = fundamentals.get("info", {}).get("sector")
        market_ctx = get_market_context(sector=sector)

    return {
        "symbol": symbol,
        "bullish": bullish_data,
        "pmcc": pmcc_data,
        "fundamentals": fundamentals,
        "piotroski": piotroski,
        "spreads": spreads,
        "market_context": market_ctx,
    }


def generate_report_data(symbol: str, tradier_data: dict | None = None) -> dict:
    """Generate complete stock analysis report data.

    Args:
        symbol: Ticker symbol.
        tradier_data: Optional dict with Tradier MCP data:
            {"quote": {...}, "near_term_chain": {...}, "leaps_chain": {...}}
    """
    symbol = symbol.upper()

    # Fetch data
    data = fetch_data(symbol)

    # Check if we got any data
    if not data.get("bullish") and not data.get("fundamentals"):
        return {"error": f"Failed to fetch data for {symbol}"}

    bullish = data.get("bullish", {})
    market_ctx = data.get("market_context")

    # Determine definitive price
    yf_price = bullish.get("price")
    tradier_price = None
    if tradier_data and tradier_data.get("quote"):
        tradier_price = tradier_data["quote"].get("last")

    definitive_price = tradier_price or yf_price
    price_discrepancy = None
    if tradier_price and yf_price and yf_price > 0:
        price_discrepancy = abs(tradier_price - yf_price) / yf_price * 100
        if price_discrepancy > 1.0:
            print(
                f"WARNING: Price discrepancy {price_discrepancy:.1f}% "
                f"(Tradier={tradier_price}, yfinance={yf_price})",
                file=sys.stderr,
            )

    # Compute conviction score
    conviction = compute_conviction_score(
        bullish=bullish,
        pmcc=data.get("pmcc", {}),
        fundamentals_info=data.get("fundamentals", {}).get("info", {}),
        piotroski=data.get("piotroski", {}),
        market_context=market_ctx,
    )

    # Compute recommendation (backward compat)
    recommendation = {
        "recommendation": conviction["recommendation"],
        "recommendation_level": conviction["recommendation_level"],
        "points": conviction["total"],
        "strengths": conviction["strengths"],
        "risks": conviction["risks"],
    }

    # Support levels for CSP
    support_levels = None
    if bullish:
        # Get swing lows from price history
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
            swing = _find_swing_levels(df) if not df.empty else {}
        except Exception:
            swing = {}

        support_levels = {
            "sma50": bullish.get("pct_from_sma50"),  # will need actual SMA50 value
            "sma200": bullish.get("sma200"),
            "swing_lows": swing.get("swing_lows", []),
        }

    return {
        "symbol": symbol,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "recommendation": recommendation,
        "conviction_score": conviction,
        "company": {
            "name": data.get("fundamentals", {}).get("info", {}).get("name", symbol),
            "sector": data.get("fundamentals", {}).get("info", {}).get("sector"),
            "industry": data.get("fundamentals", {}).get("info", {}).get("industry"),
            "market_cap": data.get("fundamentals", {}).get("info", {}).get("marketCap"),
            "enterprise_value": (
                data.get("fundamentals", {}).get("info", {}).get("enterpriseValue")
            ),
            "beta": data.get("fundamentals", {}).get("info", {}).get("beta"),
        },
        "market_context": market_ctx,
        "trend_analysis": {
            "bullish_score": bullish.get("score"),
            "score_max": SCORE_MAX,
            "normalized_score": bullish.get("normalized_score"),
            "price": bullish.get("price"),
            "period_return_pct": bullish.get("period_return_pct"),
            "pct_from_sma20": bullish.get("pct_from_sma20"),
            "pct_from_sma50": bullish.get("pct_from_sma50"),
            "pct_from_sma200": bullish.get("pct_from_sma200"),
            "above_sma200": bullish.get("above_sma200"),
            "rsi": bullish.get("rsi"),
            "macd": bullish.get("macd"),
            "macd_signal": bullish.get("macd_signal"),
            "adx": bullish.get("adx"),
            "signals": bullish.get("signals", []),
            "next_earnings": bullish.get("next_earnings"),
            "earnings_timing": bullish.get("earnings_timing"),
            # v2 fields
            "trend_stage": bullish.get("trend_stage"),
            "breakout_signal": bullish.get("breakout_signal"),
            "volume_confirmed": bullish.get("volume_confirmed"),
            "trend_consistency": bullish.get("trend_consistency"),
            "obv_trend": bullish.get("obv_trend"),
            "relative_volume": bullish.get("relative_volume"),
        },
        "pmcc_analysis": {
            "pmcc_score": data.get("pmcc", {}).get("pmcc_score"),
            "iv_pct": data.get("pmcc", {}).get("iv_pct"),
            "leaps": data.get("pmcc", {}).get("leaps", {}),
            "short": data.get("pmcc", {}).get("short", {}),
            "metrics": data.get("pmcc", {}).get("metrics", {}),
        },
        "fundamentals": {
            "valuation": {
                "trailing_pe": (data.get("fundamentals", {}).get("info", {}).get("trailingPE")),
                "forward_pe": (data.get("fundamentals", {}).get("info", {}).get("forwardPE")),
                "price_to_book": (data.get("fundamentals", {}).get("info", {}).get("priceToBook")),
                "eps_ttm": data.get("fundamentals", {}).get("info", {}).get("eps"),
                "forward_eps": (data.get("fundamentals", {}).get("info", {}).get("forwardEps")),
            },
            "profitability": {
                "profit_margin": (data.get("fundamentals", {}).get("info", {}).get("profitMargin")),
                "operating_margin": (
                    data.get("fundamentals", {}).get("info", {}).get("operatingMargin")
                ),
                "roe": (data.get("fundamentals", {}).get("info", {}).get("returnOnEquity")),
                "roa": (data.get("fundamentals", {}).get("info", {}).get("returnOnAssets")),
                "revenue_growth": (
                    data.get("fundamentals", {}).get("info", {}).get("revenueGrowth")
                ),
                "earnings_growth": (
                    data.get("fundamentals", {}).get("info", {}).get("earningsGrowth")
                ),
            },
            "dividend": {
                "yield": (data.get("fundamentals", {}).get("info", {}).get("dividendYield")),
                "rate": (data.get("fundamentals", {}).get("info", {}).get("dividendRate")),
                "payout_ratio": (data.get("fundamentals", {}).get("info", {}).get("payoutRatio")),
            },
            "balance_sheet": {
                "debt_to_equity": (
                    data.get("fundamentals", {}).get("info", {}).get("debtToEquity")
                ),
                "current_ratio": (data.get("fundamentals", {}).get("info", {}).get("currentRatio")),
            },
            "earnings_history": data.get("fundamentals", {}).get("earnings", [])[:8],
        },
        "piotroski": {
            "score": data.get("piotroski", {}).get("score"),
            "max_score": 9,
            "interpretation": data.get("piotroski", {}).get("interpretation"),
            "criteria": data.get("piotroski", {}).get("criteria", {}),
        },
        "support_levels": support_levels,
        "spread_strategies": data.get("spreads", {}),
        "data_sources": {
            "technicals": "yfinance",
            "fundamentals": "yfinance",
            "options": "tradier" if tradier_data else "yfinance",
            "quote": "tradier" if tradier_price else "yfinance",
            "definitive_price": definitive_price,
            "price_discrepancy_pct": (round(price_discrepancy, 1) if price_discrepancy else None),
        },
    }
