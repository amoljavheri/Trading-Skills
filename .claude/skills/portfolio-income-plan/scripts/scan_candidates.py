#!/usr/bin/env python3
# ABOUTME: Scans the S&P 100 large-cap universe for new wheel strategy candidates.
# ABOUTME: Filters by market cap >$200B, scores on trend/IV/earnings/affordability.
# ABOUTME: Applies top-down market regime filter (QQQ SMA200 + VXN) to adjust CSP delta targets.

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Shared utilities
sys.path.insert(0, os.path.dirname(__file__))
from shared_utils import (  # noqa: E402
    apply_momentum_downgrade,
    check_recent_momentum,
    classify_earnings_risk,
    classify_trend,
    compute_market_regime,
    enforce_sector_limits,
    enforce_sma200_cap,
)

from trading_skills.earnings import get_earnings_info
from trading_skills.fundamentals import get_fundamentals
from trading_skills.scanner_bullish import compute_bullish_score
from trading_skills.scanner_pmcc import analyze_pmcc

# ── S&P 100 universe ─────────────────────────────────────────────────────────
SP100_UNIVERSE = [
    # Technology
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "QCOM", "TXN", "MU", "INTC",
    "CRM", "ORCL", "IBM", "AMAT", "KLAC", "LRCX", "MRVL",
    # Large-cap internet / software
    "GOOGL", "META", "AMZN", "NFLX", "ADBE", "NOW", "INTU",
    # AI / cloud
    "PLTR", "SNOW", "PANW",
    # Consumer / retail
    "TSLA", "HD", "MCD", "SBUX", "NKE", "LOW", "TGT", "COST", "WMT",
    # Financial
    "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP",
    "BLK", "SCHW", "MMC",
    # Healthcare
    "UNH", "JNJ", "ABT", "LLY", "PFE", "MRK", "AMGN", "GILD",
    "TMO", "DHR", "MDT", "HUM", "CVS",
    # Energy
    "XOM", "CVX", "COP",
    # Industrial / diversified
    "GE", "HON", "RTX", "CAT", "DE", "UPS", "FDX",
    # Telecom / media
    "T", "VZ", "DIS",
    # Consumer staples
    "PG", "KO", "PEP", "PM", "MO",
    # Other
    "TSM", "BABA",
]

# ── Wheel suitability score (0–10) ───────────────────────────────────────────
def compute_wheel_score(
    trend_class: str,
    iv_pct: float | None,
    earnings_days: int | None,
    csp_affordable: bool,
    profit_margin: float | None,
    momentum: dict | None = None,
) -> float:
    score = 0.0

    # Trend component (0–3)
    trend_points = {
        "strong_bull": 3.0,
        "bull": 3.0,
        "neutral": 2.0,
        "bear": 1.0,
        "strong_bear": 0.0,
    }
    score += trend_points.get(trend_class, 0.0)

    # Momentum penalty (Rule 20): short-term bearish momentum reduces score
    if momentum:
        mc = momentum.get("momentum_class", "neutral")
        if mc == "strong_bearish":
            score -= 2.0   # hard block: kills almost any ADD recommendation
        elif mc == "bearish":
            score -= 1.0   # drops WATCH→SKIP or ADD→WATCH
        elif mc == "mild_bearish":
            score -= 0.5   # minor caution flag

    # IV quality component (0–3)
    if iv_pct is not None:
        if 30 <= iv_pct <= 60:
            score += 3.0  # sweet spot
        elif 20 <= iv_pct < 30:
            score += 2.0  # decent
        elif iv_pct > 60:
            score += 1.0  # too volatile
        # < 20% → 0 points

    # Earnings safety component (0–2)
    if earnings_days is None:
        score += 1.0  # unknown — partial credit
    elif earnings_days > 21:
        score += 2.0
    elif earnings_days >= 14:
        score += 1.0
    # < 14 days → 0 points

    # CSP affordability component (0–1)
    if csp_affordable:
        score += 1.0

    # Fundamental quality component (0–1)
    if profit_margin is not None and profit_margin > 0.15:
        score += 1.0

    return round(score, 1)


def recommendation(score: float) -> str:
    if score >= 7.0:
        return "ADD"
    elif score >= 5.0:
        return "WATCH"
    return "SKIP"


# ── Per-symbol analysis ───────────────────────────────────────────────────────
def analyze_symbol(
    symbol: str,
    budget: float,
    owned_positions: dict[str, int],  # symbol → shares owned
) -> dict | None:
    """Fetch all data and build a candidate entry for one symbol."""
    try:
        # Fundamentals first — needed for market cap filter
        fund = get_fundamentals(symbol, data_type="info")
        info = fund.get("info", {})
        market_cap = info.get("marketCap") or 0
        if market_cap < 200_000_000_000:
            return None  # Below threshold

        name = info.get("name") or symbol
        sector = info.get("sector") or "Unknown"
        profit_margin = info.get("profitMargin")  # may be None
        beta = info.get("beta")
        pe = info.get("trailingPE")

        # Trend analysis — uses 12mo period to enable SMA200 scoring
        bull_data = compute_bullish_score(symbol, period="12mo")
        bullish_score = bull_data["score"] if bull_data else 0.0
        price = bull_data["price"] if bull_data else 0.0
        trend_class = classify_trend(bullish_score)
        signals = bull_data.get("signals", []) if bull_data else []
        above_sma200 = bull_data.get("above_sma200") if bull_data else None
        # SMA200 hard cap (Rule 13): prevent bullish trend on stocks below SMA200
        trend_class = enforce_sma200_cap(trend_class, above_sma200)

        # Short-term momentum override (Rule 20): detect sharp recent drops missed by
        # long-term SMA scoring. E.g. 5 consecutive red days / -4% week → downgrade trend.
        momentum = check_recent_momentum(symbol)
        trend_class = apply_momentum_downgrade(trend_class, momentum)
        if momentum.get("warning"):
            signals.append(f"⚡ {momentum['warning']}")

        # IV via PMCC scanner (yfinance, no Tradier needed)
        pmcc_data = analyze_pmcc(symbol)
        iv_pct = pmcc_data.get("iv_pct") if pmcc_data else None

        # Earnings
        earn = get_earnings_info(symbol)
        earnings_date = earn.get("earnings_date")
        earnings_timing = earn.get("timing")
        earnings_days: int | None = None
        if earnings_date:
            today = datetime.now().date()
            earn_dt = datetime.strptime(earnings_date, "%Y-%m-%d").date()
            earnings_days = (earn_dt - today).days
        earnings_risk = classify_earnings_risk(earnings_days)

        # Affordability: CSP strike ≈ 90% OTM × 100
        csp_capital = round(price * 100, 0) if price else None
        csp_affordable = bool(csp_capital and csp_capital <= budget)

        # Wheel score — include momentum penalty
        wheel_score = compute_wheel_score(
            trend_class, iv_pct, earnings_days, csp_affordable, profit_margin, momentum
        )
        # Hard block: momentum override forces SKIP regardless of other scores
        if momentum.get("should_block"):
            wheel_score = min(wheel_score, 3.9)  # cap below WATCH threshold

        # Candidate type
        shares_owned = owned_positions.get(symbol, 0)
        if shares_owned >= 100:
            candidate_type = "OWNED_ELIGIBLE"
        elif shares_owned > 0:
            candidate_type = "OWNED_TOPUP"
        else:
            candidate_type = "NEW_CANDIDATE"

        # CSP entry suggestion (10% OTM from current price)
        suggested_strike = round(price * 0.90, 2) if price else None
        suggested_capital = round(suggested_strike * 100, 0) if suggested_strike else None

        # Strengths and risks narrative
        strengths = []
        risks = []

        if trend_class in ("strong_bull", "bull"):
            strengths.append(f"Bullish trend ({trend_class.replace('_', ' ')})")
        elif trend_class == "neutral":
            strengths.append("Neutral trend — stable entry")
        else:
            risks.append(f"Downtrend ({trend_class.replace('_', ' ')}) — risky CSP entry")

        if iv_pct and 30 <= iv_pct <= 60:
            strengths.append(f"IV {iv_pct:.0f}% — good premium")
        elif iv_pct and iv_pct > 60:
            risks.append(f"High IV {iv_pct:.0f}% — elevated assignment risk")
        elif iv_pct and iv_pct < 20:
            risks.append(f"Low IV {iv_pct:.0f}% — little premium available")

        if earnings_risk == "SAFE":
            strengths.append(f"Earnings {earnings_days}d away — safe for 30d options")
        elif earnings_risk == "BLOCK":
            risks.append(f"Earnings in {earnings_days}d — DO NOT sell options")
        elif earnings_risk == "SHORT_DTE_ONLY":
            risks.append(f"Earnings in {earnings_days}d — short DTE only")

        if not csp_affordable:
            risks.append(
                f"CSP capital ~${suggested_capital:,.0f} exceeds budget ${budget:,.0f}"
            )

        if profit_margin is not None and profit_margin < 0:
            risks.append("Unprofitable — negative profit margin")

        if candidate_type == "OWNED_TOPUP":
            needed = 100 - shares_owned
            topup_cost = round(price * needed, 0)
            strengths.append(
                f"Top-up: buy {needed} more shares (~${topup_cost:,.0f}) for CC eligibility"
            )
        elif candidate_type == "OWNED_ELIGIBLE":
            risks.append("Already CC-eligible — managed in main plan")

        entry = {
            "symbol": symbol,
            "name": name,
            "type": candidate_type,
            "price": round(price, 2),
            "market_cap_b": round(market_cap / 1e9, 1),
            "sector": sector,
            "beta": round(beta, 2) if beta else None,
            "trailing_pe": round(pe, 1) if pe else None,
            "profit_margin_pct": round(profit_margin * 100, 1) if profit_margin else None,
            "trend_class": trend_class,
            "bullish_score": round(bullish_score, 1),
            "above_sma200": above_sma200,
            "momentum_class": momentum.get("momentum_class", "neutral"),
            "momentum_5d_return_pct": momentum.get("five_day_return_pct"),
            "momentum_consecutive_reds": momentum.get("consecutive_reds", 0),
            "momentum_warning": momentum.get("warning"),
            "signals": signals,
            "iv_pct": iv_pct,
            "earnings_date": earnings_date,
            "earnings_timing": earnings_timing,
            "earnings_days_away": earnings_days,
            "earnings_risk": earnings_risk,
            "csp_affordable": csp_affordable,
            "csp_capital_needed": int(csp_capital) if csp_capital else None,
            "wheel_score": wheel_score,
            "recommendation": recommendation(wheel_score),
            "csp_entry": {
                "suggested_strike": suggested_strike,
                "suggested_strike_pct": "~10% OTM",
                "capital_needed": int(suggested_capital) if suggested_capital else None,
                "affordable": csp_affordable,
            },
            "strengths": strengths,
            "risks": risks,
        }

        # Top-up specific fields
        if candidate_type == "OWNED_TOPUP":
            entry["shares_owned"] = shares_owned
            entry["shares_needed"] = 100 - shares_owned
            entry["topup_cost_estimate"] = round(price * (100 - shares_owned), 0)

        return entry

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


# ── Main ─────────────────────────────────────────────────────────────────────
def scan_candidates(
    portfolio_data: dict,
    budget: float,
    market_cap_min_b: float = 200.0,
    top_n: int = 10,
    include_piotroski: bool = False,
) -> dict:
    """Screen the S&P 100 universe for wheel strategy candidates."""
    # Build owned positions map
    owned_positions: dict[str, int] = {}
    for pos in portfolio_data.get("stock_positions", []):
        owned_positions[pos["symbol"]] = pos.get("quantity", 0)

    owned_eligible = [s for s, q in owned_positions.items() if q >= 100]
    owned_partial = [s for s, q in owned_positions.items() if 0 < q < 100]

    # ── Top-down market regime check (run before symbol scan) ────────────────
    print("  Checking market regime (QQQ SMA200 + VXN)...", file=sys.stderr)
    market_regime = compute_market_regime()
    regime_tier = market_regime.get("recommended_delta_tier", "standard")
    if regime_tier == "skip":
        print(
            "  ⚠️  VXN EXTREME — recommending SKIP on all new CSPs",
            file=sys.stderr,
        )
    elif regime_tier == "reduce":
        print(
            f"  ⚠️  {market_regime.get('regime_note', '')} — reducing delta tier",
            file=sys.stderr,
        )

    print(
        f"Screening {len(SP100_UNIVERSE)} S&P 100 symbols for "
        f"market cap ≥ ${market_cap_min_b:.0f}B...",
        file=sys.stderr,
    )
    print(f"  Already CC-eligible: {owned_eligible}", file=sys.stderr)
    print(f"  Partial positions (top-up candidates): {owned_partial}", file=sys.stderr)

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(analyze_symbol, sym, budget, owned_positions): sym
            for sym in SP100_UNIVERSE
        }
        done = 0
        total = len(SP100_UNIVERSE)
        for future in as_completed(futures):
            sym = futures[future]
            done += 1
            print(f"  [{done}/{total}] {sym}", file=sys.stderr)
            try:
                result = future.result()
                if result is None:
                    pass  # below market cap threshold
                elif "error" in result:
                    errors.append(result)
                else:
                    results.append(result)
            except Exception as e:
                errors.append({"symbol": sym, "error": str(e)})

    # Separate eligible (already owned 100+) from real candidates
    eligible_symbols = [r for r in results if r["type"] == "OWNED_ELIGIBLE"]
    candidates = [r for r in results if r["type"] != "OWNED_ELIGIBLE"]

    # Annotate each candidate with regime-adjusted delta recommendation
    DELTA_TIERS = {
        # (trend_class, regime_tier) → recommended CSP delta
        "standard": {
            "strong_bull": 0.20, "bull": 0.20, "neutral": 0.20,
            "bear": 0.15, "strong_bear": 0.10,
        },
        "reduce": {
            "strong_bull": 0.15, "bull": 0.15, "neutral": 0.12,
            "bear": 0.10, "strong_bear": 0.08,
        },
        "skip": {
            "strong_bull": None, "bull": None, "neutral": None,
            "bear": None, "strong_bear": None,
        },
    }
    tier_map = DELTA_TIERS.get(regime_tier, DELTA_TIERS["standard"])
    for cand in candidates:
        tc = cand.get("trend_class", "neutral")
        suggested_delta = tier_map.get(tc)
        cand["regime_adjusted_delta"] = suggested_delta
        cand["regime_tier"] = regime_tier
        # Downgrade recommendation to WATCH if skip regime
        if regime_tier == "skip" and cand.get("recommendation") == "ADD":
            cand["recommendation"] = "WATCH"
            cand["risks"] = cand.get("risks", []) + [
                "VXN≥35 extreme volatility — defer CSP entry until VXN < 30"
            ]
        # Flag bear-market stocks below their own SMA200
        if cand.get("above_sma200") is False:
            if not any("SMA200" in r for r in cand.get("risks", [])):
                cand["risks"] = cand.get("risks", []) + [
                    "Stock below own SMA200 — in individual bear market"
                ]

    # Sort by wheel score descending, then alphabetically
    candidates.sort(key=lambda x: (-x["wheel_score"], x["symbol"]))

    # Enforce sector concentration limits (30% max per sector)
    candidates, dropped_for_concentration = enforce_sector_limits(candidates)

    # Optional Piotroski enrichment on top candidates
    if include_piotroski and candidates:
        from trading_skills.piotroski import calculate_piotroski_score

        print(
            f"  Running Piotroski F-score on top {min(top_n, len(candidates))} candidates...",
            file=sys.stderr,
        )
        for cand in candidates[:top_n]:
            try:
                p = calculate_piotroski_score(cand["symbol"])
                cand["piotroski_score"] = p.get("score")
                cand["piotroski_interpretation"] = p.get("interpretation")
            except Exception as e:
                cand["piotroski_error"] = str(e)

    qualifying_count = len(results)
    top_candidates = candidates[:top_n]

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "market_regime": market_regime,
        "market_cap_threshold_b": market_cap_min_b,
        "budget": {"max_per_csp": budget},
        "screened_count": len(SP100_UNIVERSE),
        "qualifying_large_cap": qualifying_count,
        "owned_eligible_count": len(eligible_symbols),
        "candidate_count": len(candidates),
        "candidates": top_candidates,
        "dropped_for_concentration": (
            [{"symbol": d["symbol"], "sector": d.get("sector"), "reason": d.get("dropped_reason")}
             for d in dropped_for_concentration]
            if dropped_for_concentration else None
        ),
        "owned_eligible": sorted(s["symbol"] for s in eligible_symbols),
        "errors": errors if errors else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan S&P 100 large-cap universe for wheel strategy candidates"
    )
    parser.add_argument(
        "--portfolio",
        required=True,
        help="Path to parse_etrade.py JSON output (portfolio.json)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        required=True,
        help="Max capital per CSP (from preflight_checks.py max_per_csp)",
    )
    parser.add_argument(
        "--market-cap-min",
        type=float,
        default=200.0,
        help="Minimum market cap in billions (default: 200)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Number of top candidates to return (default: 10)",
    )
    parser.add_argument(
        "--piotroski",
        action="store_true",
        help="Include Piotroski F-score for top candidates (slower)",
    )
    args = parser.parse_args()

    if args.budget <= 0:
        parser.error("--budget must be positive")
    if args.market_cap_min <= 0:
        parser.error("--market-cap-min must be positive")
    if args.top_n <= 0:
        parser.error("--top-n must be positive")
    if not os.path.exists(args.portfolio):
        parser.error(f"File not found: {args.portfolio}")

    with open(args.portfolio) as f:
        portfolio_data = json.load(f)

    result = scan_candidates(
        portfolio_data=portfolio_data,
        budget=args.budget,
        market_cap_min_b=args.market_cap_min,
        top_n=args.top_n,
        include_piotroski=args.piotroski,
    )
    import numpy as np

    class _Encoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.bool_,)):
                return bool(o)
            if isinstance(o, (np.integer,)):
                return int(o)
            if isinstance(o, (np.floating,)):
                return float(o)
            return super().default(o)

    print(json.dumps(result, indent=2, cls=_Encoder))


if __name__ == "__main__":
    main()
