#!/usr/bin/env python3
# ABOUTME: Extracts targeted option strikes from a saved Tradier option chain file.
# ABOUTME: Uses delta-based selection, premium/liquidity filters, and cost basis awareness.

import argparse
import json
import os

# ── Delta ranges by trend class ──────────────────────────────────────────────
# Format: {trend: {call: (min_delta, max_delta), put: (min_delta, max_delta)}}
# Puts use absolute delta values for comparison (actual delta is negative).
DELTA_RANGES = {
    "strong_bull": {"call": (0.15, 0.25), "put": (0.20, 0.30)},
    "bull":        {"call": (0.20, 0.35), "put": (0.20, 0.30)},
    "neutral":     {"call": (0.25, 0.40), "put": (0.20, 0.30)},
    "bear":        {"call": (0.30, 0.45), "put": (0.10, 0.20)},
    "strong_bear": {"call": (0.35, 0.50), "put": (0.10, 0.15)},
}

# ── Legacy % OTM fallback (used when greeks are missing) ─────────────────────
LEGACY_PCT = {
    "call": {
        "bullish":  [1.03, 1.05, 1.07, 1.10],
        "bearish":  [1.01, 1.02, 1.03, 1.05],
        "neutral":  [1.02, 1.05, 1.08],
    },
    "put": {
        "bullish":  [0.97, 0.95, 0.92],
        "bearish":  [0.95, 0.92, 0.90],
        "neutral":  [0.97, 0.95, 0.92, 0.90],
    },
}


def _enrich_option(
    o: dict, current_price: float, dte: int, cost_basis: float | None,
    use_mid: bool = False,
) -> dict:
    """Build an enriched strike dict from a raw Tradier option record."""
    g = o.get("greeks") or {}
    bid = o.get("bid", 0) or 0
    ask = o.get("ask", 0) or 0
    mid = round((bid + ask) / 2, 2)
    iv = round(g.get("mid_iv", 0) * 100, 1) if g.get("mid_iv") else 0.0
    delta = round(g.get("delta", 0), 3)
    theta = round(g.get("theta", 0), 4)
    prob_profit = round((1 - abs(delta)) * 100, 1)
    otm_pct = round((o["strike"] / current_price - 1) * 100, 1)

    # Yield price: use mid for tight spreads when --use-mid, else bid (conservative)
    spread_pct_raw = round((ask - bid) / mid * 100, 1) if mid > 0 else 999.0
    if use_mid and spread_pct_raw < 5.0 and mid > 0:
        yield_price = mid
    else:
        yield_price = bid
    if yield_price > 0:
        ann_yield = round((yield_price / o["strike"]) * (365 / max(dte, 1)) * 100, 1)
    else:
        ann_yield = 0.0

    # ── Liquidity assessment ─────────────────────────────────────────────
    oi = o.get("open_interest", 0) or 0
    vol = o.get("volume", 0) or 0
    spread_pct = round((ask - bid) / mid * 100, 1) if mid > 0 else 999.0

    liquidity_issues: list[str] = []
    if bid <= 0:
        liquidity_issues.append("no bid")
    if oi < 100:
        liquidity_issues.append(f"low OI ({oi})")
    if spread_pct > 15:
        liquidity_issues.append(f"wide spread ({spread_pct}%)")
    liquidity_pass = len(liquidity_issues) == 0

    result = {
        "strike": o["strike"],
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "delta": delta,
        "theta": theta,
        "iv_pct": iv,
        "prob_profit_pct": prob_profit,
        "ann_yield_pct": ann_yield,
        "otm_pct": otm_pct,
        "open_interest": oi,
        "volume": vol,
        "spread_pct": spread_pct,
        "liquidity_pass": liquidity_pass,
        "liquidity_issues": liquidity_issues,
    }

    # ── Cost basis flag (calls only) ─────────────────────────────────────
    if cost_basis is not None and o.get("option_type") == "call":
        result["below_cost_basis"] = o["strike"] < cost_basis

    return result


def extract_strikes(
    filepath: str,
    current_price: float,
    option_type: str,
    market: str = "neutral",
    dte: int = 30,
    custom_strikes: list[float] | None = None,
    trend: str | None = None,
    delta_min: float | None = None,
    delta_max: float | None = None,
    cost_basis: float | None = None,
    min_premium: float = 0.0,
    min_ann_yield: float = 0.0,
    use_mid: bool = False,
) -> dict:
    """
    Extract relevant strikes from a saved Tradier option chain JSON file.

    Args:
        filepath:       Path to the saved tool-results chain file
        current_price:  Current stock price
        option_type:    "call" or "put"
        market:         Legacy market bias ("bullish"/"bearish"/"neutral") — fallback only
        dte:            Days to expiration (for annualized yield calc)
        custom_strikes: If provided, use these exact strikes
        trend:          Per-stock trend class (strong_bull/bull/neutral/bear/strong_bear)
        delta_min:      Override minimum abs(delta) for strike selection
        delta_max:      Override maximum abs(delta) for strike selection
        cost_basis:     Cost basis per share (for flagging calls below cost)
        min_premium:    Minimum mid premium to include (default 0 = no filter)
                        Dynamic floor: max(min_premium, price * 0.002) to avoid
                        negligible premiums on expensive stocks.
        min_ann_yield:  Minimum annualized yield % to include (default 0)
        use_mid:        When True and spread < 5%, use mid price for yield calc
                        instead of bid. Better fill expectation on liquid options.

    Returns:
        Dict with "strikes" list and optional "action": "SKIP" if all filtered out.
    """
    with open(filepath) as f:
        data = json.load(f)
    chain = json.loads(data[0]["text"])
    options = chain["options"]["option"]

    # ── Step 1: Select candidate options ─────────────────────────────────
    skip_filters = False
    if custom_strikes:
        # Exact strike mode — bypass delta selection AND premium/liquidity filters
        matches = [
            o for o in options
            if o["option_type"] == option_type and o["strike"] in custom_strikes
        ]
        skip_filters = True  # User explicitly chose these strikes
    elif trend and trend in DELTA_RANGES and not (delta_min is not None or delta_max is not None):
        # Delta-based selection using trend class
        d_min, d_max = DELTA_RANGES[trend][option_type if option_type == "call" else "put"]
        matches = _select_by_delta(options, option_type, current_price, d_min, d_max)
    elif delta_min is not None or delta_max is not None:
        # Explicit delta range override
        d_min = delta_min if delta_min is not None else 0.0
        d_max = delta_max if delta_max is not None else 1.0
        matches = _select_by_delta(options, option_type, current_price, d_min, d_max)
    else:
        # Legacy % OTM fallback (when no trend/delta specified)
        matches = _select_by_pct_otm(options, option_type, current_price, market)

    # ── Step 2: Enrich with metrics ──────────────────────────────────────
    results = []
    for o in sorted(matches, key=lambda x: x["strike"]):
        results.append(_enrich_option(o, current_price, dte, cost_basis, use_mid=use_mid))

    # ── Step 3: Apply filters (skipped for custom_strikes) ─────────────
    # Dynamic premium floor: scales with stock price to avoid negligible premiums
    effective_min_premium = max(min_premium, current_price * 0.002)

    passed = []
    filtered = []

    if skip_filters:
        passed = results
    else:
        for r in results:
            reasons = []
            if effective_min_premium > 0 and r["mid"] < effective_min_premium:
                reasons.append(f"premium ${r['mid']:.2f} < ${effective_min_premium:.2f}")
            if min_ann_yield > 0 and r["ann_yield_pct"] < min_ann_yield:
                reasons.append(f"ann yield {r['ann_yield_pct']:.1f}% < {min_ann_yield:.1f}%")
            if not r["liquidity_pass"]:
                reasons.append(f"liquidity: {', '.join(r['liquidity_issues'])}")

            if reasons:
                r["filtered_reason"] = "; ".join(reasons)
                filtered.append(r)
            else:
                passed.append(r)

    # ── Step 4: Return results or SKIP ───────────────────────────────────
    if not passed and not filtered:
        return {
            "action": "SKIP",
            "reasons": ["no matching strikes found in chain"],
        }
    elif not passed:
        # All strikes failed filters
        reason_summary = set()
        for f_item in filtered:
            reason_summary.add(f_item.get("filtered_reason", "unknown"))
        return {
            "action": "SKIP",
            "reasons": sorted(reason_summary),
            "filtered_strikes": filtered,
        }
    else:
        return {
            "action": "TRADE",
            "strikes": passed,
            "filtered_strikes": filtered if filtered else None,
        }


def _select_by_delta(
    options: list[dict], option_type: str, current_price: float,
    delta_min: float, delta_max: float,
) -> list[dict]:
    """Select options by delta range. For puts, compares abs(delta)."""
    matches = []
    for o in options:
        if o["option_type"] != option_type:
            continue
        g = o.get("greeks") or {}
        d = g.get("delta")
        if d is None:
            continue
        abs_d = abs(d)
        # For calls: want OTM so delta < 0.50, filter by range
        # For puts: delta is negative, use absolute value
        if delta_min <= abs_d <= delta_max:
            # Also ensure the option is OTM (or near ATM)
            if option_type == "call" and o["strike"] >= current_price * 0.98:
                matches.append(o)
            elif option_type == "put" and o["strike"] <= current_price * 1.02:
                matches.append(o)
    return matches


def _select_by_pct_otm(
    options: list[dict], option_type: str, current_price: float, market: str,
) -> list[dict]:
    """Legacy fallback: select by % OTM multipliers."""
    ot_key = "call" if option_type == "call" else "put"
    pcts = LEGACY_PCT[ot_key].get(market, LEGACY_PCT[ot_key]["neutral"])
    step = 0.50 if current_price < 20 else (1.0 if current_price < 50 else 2.5)
    raw_targets = [current_price * p for p in pcts]
    target_strikes = sorted(set(round(t / step) * step for t in raw_targets))

    return [
        o for o in options
        if o["option_type"] == option_type and o["strike"] in target_strikes
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Extract targeted option strikes from chain file"
    )
    parser.add_argument("--file", required=True, help="Path to saved Tradier option chain file")
    parser.add_argument("--symbol", required=True, help="Stock symbol")
    parser.add_argument("--price", required=True, type=float, help="Current stock price")
    parser.add_argument("--type", required=True, choices=["call", "put"], help="Option type")
    # Legacy market bias (fallback)
    parser.add_argument("--market", default="neutral",
                        choices=["bullish", "bearish", "neutral"])
    parser.add_argument("--dte", type=int, default=30, help="Days to expiration")
    parser.add_argument("--strikes", help="Comma-separated custom strikes (e.g. 185,190,195)")
    # New: delta-based selection
    parser.add_argument("--trend",
                        choices=["strong_bull", "bull", "neutral", "bear", "strong_bear"],
                        help="Per-stock trend class (determines delta range)")
    parser.add_argument("--delta-min", type=float, help="Override: minimum abs(delta)")
    parser.add_argument("--delta-max", type=float, help="Override: maximum abs(delta)")
    # New: filters
    parser.add_argument("--cost-basis", type=float,
                        help="Cost basis per share (flags CC below cost)")
    parser.add_argument("--min-premium", type=float, default=0.0,
                        help="Minimum mid premium to include (default: 0 = no filter)")
    parser.add_argument("--min-ann-yield", type=float, default=0.0,
                        help="Minimum annualized yield %% to include (default: 0)")
    parser.add_argument("--use-mid", action="store_true",
                        help="Use mid price for yield calc when spread < 5%% (default: bid)")

    args = parser.parse_args()

    # Input validation
    if args.price <= 0:
        parser.error("--price must be positive")
    if args.dte <= 0:
        parser.error("--dte must be positive")
    if args.delta_min is not None and args.delta_max is not None:
        if args.delta_min >= args.delta_max:
            parser.error("--delta-min must be less than --delta-max")
    if args.min_premium < 0:
        parser.error("--min-premium must be non-negative")
    if args.min_ann_yield < 0:
        parser.error("--min-ann-yield must be non-negative")
    if not os.path.exists(args.file):
        parser.error(f"File not found: {args.file}")

    custom = [float(s) for s in args.strikes.split(",")] if args.strikes else None

    result = extract_strikes(
        filepath=args.file,
        current_price=args.price,
        option_type=args.type,
        market=args.market,
        dte=args.dte,
        custom_strikes=custom,
        trend=args.trend,
        delta_min=args.delta_min,
        delta_max=args.delta_max,
        cost_basis=args.cost_basis,
        min_premium=args.min_premium,
        min_ann_yield=args.min_ann_yield,
        use_mid=args.use_mid,
    )

    output = {
        "symbol": args.symbol.upper(),
        "current_price": args.price,
        "option_type": args.type,
        "dte": args.dte,
    }
    if args.trend:
        output["trend"] = args.trend
    elif args.delta_min or args.delta_max:
        output["delta_range"] = f"{args.delta_min or 0.0}-{args.delta_max or 1.0}"
    else:
        output["market"] = args.market

    output.update(result)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
