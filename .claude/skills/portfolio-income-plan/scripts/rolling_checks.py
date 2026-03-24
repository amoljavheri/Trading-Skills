#!/usr/bin/env python3
# ABOUTME: Checks existing short option positions for rolling/closing opportunities.
# ABOUTME: Returns ROLL_EARLY (60%+ profit), ROLL_URGENT (ITM, low extrinsic),
# ABOUTME: ROLL_DECISION (<5 DTE near money), or HOLD for each position.

import argparse
import json
import os
from datetime import datetime


def check_rolling(
    option_positions: list[dict],
    current_prices: dict[str, float],
    option_quotes: dict[str, float] | None = None,
) -> list[dict]:
    """Check each short option position for roll/close recommendations.

    Args:
        option_positions: List of option dicts from parse_etrade.py
        current_prices: Map of symbol → current stock price
        option_quotes: Optional map of "SYMBOL_STRIKE_EXPIRY" → current option ask price

    Returns list of recommendation dicts.
    """
    today = datetime.now().date()
    results = []

    for opt in option_positions:
        qty = opt.get("quantity", 0)
        if qty >= 0:
            continue  # Only check short positions

        symbol = opt.get("underlying", "")
        strike = opt.get("strike", 0)
        expiry_str = opt.get("expiry", "")
        option_type = opt.get("option_type", "")

        if not expiry_str or not strike:
            continue

        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        dte = (expiry - today).days
        contracts = abs(qty)
        current_price = current_prices.get(symbol, 0)

        action = "HOLD"
        reason = ""
        urgency = 0  # 0=low, 1=medium, 2=high

        # Check 1: Profit target (60% of premium captured)
        # cost_basis from parse_etrade.py = per-share price received (e.g. 1.22 = $1.22/share)
        # current_value from parse_etrade.py = TOTAL dollar value of position (e.g. -32.5 = $32.50 total)
        # Units DIFFER — must not divide cost_basis by 100 again.
        cost_basis_per_share = abs(opt.get("cost_basis", 0))   # already per-share
        current_value = abs(opt.get("current_value", 0))        # total dollars
        if cost_basis_per_share > 0 and current_value > 0:
            # Profit = what we sold for - what it costs to close
            per_contract_sold = cost_basis_per_share             # per-share price received
            per_contract_now = current_value / contracts / 100   # total -> per-share
            if per_contract_sold > 0 and per_contract_now < per_contract_sold:
                profit_pct = ((per_contract_sold - per_contract_now) / per_contract_sold) * 100
                if profit_pct >= 60:
                    action = "ROLL_EARLY"
                    reason = (
                        f"Profit {profit_pct:.0f}% >= 60% target. "
                        f"Buy to close ~${per_contract_now:.2f}, re-sell new cycle."
                    )
                    urgency = 1

        # Check 2: Near money with <5 DTE
        if dte < 5 and current_price > 0 and strike > 0:
            moneyness_pct = abs(current_price - strike) / strike * 100
            if moneyness_pct < 2.0:
                action = "ROLL_DECISION"
                reason = (
                    f"<5 DTE ({dte}d), only {moneyness_pct:.1f}% from strike. "
                    "Decide: let expire, roll out, or close."
                )
                urgency = 2

        # Check 3: ITM check
        if current_price > 0:
            is_itm = (
                (option_type == "call" and current_price > strike) or
                (option_type == "put" and current_price < strike)
            )
            if is_itm and dte <= 7:
                action = "ROLL_URGENT"
                itm_amount = abs(current_price - strike)
                reason = (
                    f"ITM by ${itm_amount:.2f} with {dte} DTE. "
                    "Roll out/up to avoid assignment."
                )
                urgency = 2

        results.append({
            "symbol": symbol,
            "option_type": option_type,
            "strike": strike,
            "expiry": expiry_str,
            "dte": dte,
            "contracts": contracts,
            "current_stock_price": current_price,
            "action": action,
            "reason": reason,
            "urgency": urgency,
        })

    # Sort by urgency descending (most urgent first)
    results.sort(key=lambda x: -x["urgency"])
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Check existing short options for rolling opportunities"
    )
    parser.add_argument("--portfolio", required=True,
                        help="Path to parse_etrade.py JSON output")
    parser.add_argument("--prices", required=True,
                        help="Path to JSON file with {symbol: current_price} map")
    args = parser.parse_args()

    if not os.path.exists(args.portfolio):
        parser.error(f"File not found: {args.portfolio}")
    if not os.path.exists(args.prices):
        parser.error(f"File not found: {args.prices}")

    with open(args.portfolio) as f:
        portfolio = json.load(f)
    with open(args.prices) as f:
        prices = json.load(f)

    results = check_rolling(
        option_positions=portfolio.get("option_positions", []),
        current_prices=prices,
    )

    # Summary
    urgent = [r for r in results if r["action"] in ("ROLL_URGENT", "ROLL_DECISION")]
    early = [r for r in results if r["action"] == "ROLL_EARLY"]
    holds = [r for r in results if r["action"] == "HOLD"]

    output = {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_short_positions": len(results),
        "urgent_count": len(urgent),
        "roll_early_count": len(early),
        "hold_count": len(holds),
        "positions": results,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
