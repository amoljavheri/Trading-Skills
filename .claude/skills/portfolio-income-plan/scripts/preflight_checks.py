#!/usr/bin/env python3
# ABOUTME: Pre-flight checks before fetching option chains for income plan.
# ABOUTME: Returns earnings risks, per-stock trends, position sizing budget, and existing options.
# ABOUTME: Includes market regime (QQQ vs SMA200) and VXN volatility regime.

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# Shared utilities (classify_trend, market regime, etc.)
sys.path.insert(0, os.path.dirname(__file__))
from shared_utils import (  # noqa: E402
    apply_momentum_downgrade,
    check_recent_momentum,
    classify_trend,
    compute_market_regime,
    compute_stress_test,
    enforce_sma200_cap,
)

from trading_skills.earnings import get_earnings_info
from trading_skills.scanner_bullish import compute_bullish_score


def check_earnings(symbols: list[str]) -> dict:
    """Check earnings dates for each symbol and classify risk."""
    today = datetime.now().date()
    results = {}

    for sym in symbols:
        try:
            info = get_earnings_info(sym)
            date_str = info.get("earnings_date")
            if not date_str:
                results[sym] = {"date": None, "risk": "UNKNOWN", "days_away": None}
                continue

            earn_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            days_away = (earn_date - today).days

            if days_away <= 0:
                risk = "PAST"
            elif days_away <= 7:
                risk = "BLOCK"  # Do NOT sell any options
            elif days_away <= 14:
                risk = "BLOCK"  # Do NOT sell options spanning this date
            elif days_away <= 21:
                risk = "SHORT_DTE_ONLY"  # Only sell options expiring BEFORE earnings
            else:
                risk = "SAFE"

            # Calculate the last safe expiry date
            safe_expiry = None
            if risk in ("BLOCK", "SHORT_DTE_ONLY"):
                # Last safe expiry is 3-5 business days before earnings
                buffer_days = 5 if days_away <= 14 else 3
                safe_expiry = (earn_date - timedelta(days=buffer_days)).isoformat()

            results[sym] = {
                "date": date_str,
                "timing": info.get("timing"),
                "days_away": days_away,
                "risk": risk,
                "safe_expiry_before": safe_expiry,
            }
        except Exception as e:
            results[sym] = {"date": None, "risk": "ERROR", "error": str(e)}

    return results


def check_trends(symbols: list[str]) -> dict:
    """Compute per-stock trend classification using 12-month data for SMA200."""
    results = {}
    for sym in symbols:
        try:
            data = compute_bullish_score(sym, period="12mo")
            if data:
                score = data.get("score", 0)
                above_sma200 = data.get("above_sma200")
                trend_class = classify_trend(score)
                # SMA200 hard cap (Rule 13): prevent bullish trend on stocks below SMA200
                trend_class = enforce_sma200_cap(trend_class, above_sma200)
                # Short-term momentum override (Rule 20)
                momentum = check_recent_momentum(sym)
                trend_class = apply_momentum_downgrade(trend_class, momentum)
                signals = data.get("signals", [])
                if momentum.get("warning"):
                    signals = signals + [f"⚡ {momentum['warning']}"]
                results[sym] = {
                    "score": round(score, 1),
                    "class": trend_class,
                    "above_sma200": above_sma200,
                    "momentum_class": momentum.get("momentum_class", "neutral"),
                    "momentum_5d_return_pct": momentum.get("five_day_return_pct"),
                    "momentum_consecutive_reds": momentum.get("consecutive_reds", 0),
                    "signals": signals,
                }
            else:
                results[sym] = {"score": 0.0, "class": "neutral", "signals": []}
        except Exception as e:
            results[sym] = {"score": 0.0, "class": "neutral", "error": str(e)}
    return results


def compute_budget(cash_available: float, buffer: float = 5000.0) -> dict:
    """Compute CSP position sizing budget."""
    usable = max(0, cash_available - buffer)
    return {
        "cash_available": round(cash_available, 2),
        "buffer": round(buffer, 2),
        "usable_cash": round(usable, 2),
        "max_per_csp": round(usable * 0.20, 2),    # 20% max per position
        "max_total_csp": round(usable * 0.50, 2),   # 50% max total exposure
    }


def extract_existing_options(option_positions: list[dict]) -> dict:
    """Build a map of existing options by underlying symbol."""
    result: dict[str, list[dict]] = {}
    for opt in option_positions:
        underlying = opt.get("underlying", "")
        if not underlying:
            continue
        if underlying not in result:
            result[underlying] = []
        result[underlying].append({
            "type": opt.get("option_type"),
            "strike": opt.get("strike"),
            "expiry": opt.get("expiry"),
            "quantity": opt.get("quantity"),
        })
    return result


def run_preflight(portfolio_data: dict) -> dict:
    """Run all pre-flight checks on parsed portfolio data."""
    # Collect all unique symbols
    stock_symbols = [s["symbol"] for s in portfolio_data.get("stock_positions", [])]
    option_underlyings = list({
        o["underlying"] for o in portfolio_data.get("option_positions", [])
    })
    all_symbols = sorted(set(stock_symbols + option_underlyings))

    print(f"Running preflight for {len(all_symbols)} symbols...", file=sys.stderr)

    # 0. Market regime check (top-down filter — must run first)
    print("  Checking market regime (QQQ SMA200 + VXN)...", file=sys.stderr)
    market_regime = compute_market_regime()

    # 1. Earnings check
    print("  Checking earnings dates...", file=sys.stderr)
    earnings = check_earnings(all_symbols)

    # 2. Per-stock trend analysis (uses 12mo data for SMA200)
    print("  Computing per-stock trends (12mo / SMA200)...", file=sys.stderr)
    trends = check_trends(stock_symbols)  # Only stocks, not option-only positions

    # 3. Position sizing budget
    cash = portfolio_data.get("cash_available", 0)
    budget = compute_budget(cash)

    # 4. Existing options map
    existing = extract_existing_options(portfolio_data.get("option_positions", []))

    # 5. CC-eligible stocks (100+ shares)
    cc_eligible = [
        s["symbol"] for s in portfolio_data.get("stock_positions", [])
        if s.get("quantity", 0) >= 100
    ]

    # 6. Stress test — worst-case simultaneous assignment scenario
    print("  Running assignment stress test...", file=sys.stderr)
    stress_test = compute_stress_test(portfolio_data, budget)

    return {
        "market_regime": market_regime,
        "earnings": earnings,
        "trends": trends,
        "budget": budget,
        "existing_options": existing,
        "cc_eligible": sorted(cc_eligible),
        "stress_test": stress_test,
        "total_stocks": len(stock_symbols),
        "total_symbols_checked": len(all_symbols),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight checks for portfolio income plan"
    )
    parser.add_argument("--file", help="Path to parse_etrade.py JSON output file")
    parser.add_argument("--buffer", type=float, default=5000.0,
                        help="Cash buffer to keep (default: $5,000)")
    args = parser.parse_args()

    if args.buffer < 0:
        parser.error("--buffer must be non-negative")

    # Read portfolio JSON from file or stdin
    if args.file:
        if not os.path.exists(args.file):
            parser.error(f"File not found: {args.file}")
        with open(args.file) as f:
            portfolio_data = json.load(f)
    else:
        portfolio_data = json.load(sys.stdin)

    if "stock_positions" not in portfolio_data:
        parser.error("Portfolio JSON missing 'stock_positions' key")

    result = run_preflight(portfolio_data)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
