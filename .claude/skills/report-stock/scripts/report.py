#!/usr/bin/env python3
# ABOUTME: CLI wrapper for comprehensive stock analysis data gathering.
# ABOUTME: Returns detailed JSON for PDF/markdown generation by Claude.
# ABOUTME: Accepts optional Tradier MCP JSON data for real option pricing.

import argparse
import json
import sys

from trading_skills.report import generate_report_data


def main():
    parser = argparse.ArgumentParser(description="Gather stock analysis data")
    parser.add_argument("symbol", help="Stock ticker symbol")
    parser.add_argument(
        "--tradier-quote-json",
        help="Tradier quote JSON string (from get_market_quotes)",
    )
    parser.add_argument(
        "--tradier-chain-json",
        help="Tradier near-term option chain JSON string (for CSP/spreads)",
    )
    parser.add_argument(
        "--tradier-leaps-json",
        help="Tradier LEAPS option chain JSON string (for LEAP scenarios/PMCC)",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Build tradier_data dict if any Tradier flags provided
    tradier_data = None
    if args.tradier_quote_json or args.tradier_chain_json or args.tradier_leaps_json:
        tradier_data = {}
        if args.tradier_quote_json:
            try:
                tradier_data["quote"] = json.loads(args.tradier_quote_json)
            except json.JSONDecodeError:
                print("Warning: Invalid --tradier-quote-json, ignoring", file=sys.stderr)
        if args.tradier_chain_json:
            try:
                tradier_data["near_term_chain"] = json.loads(args.tradier_chain_json)
            except json.JSONDecodeError:
                print("Warning: Invalid --tradier-chain-json, ignoring", file=sys.stderr)
        if args.tradier_leaps_json:
            try:
                tradier_data["leaps_chain"] = json.loads(args.tradier_leaps_json)
            except json.JSONDecodeError:
                print("Warning: Invalid --tradier-leaps-json, ignoring", file=sys.stderr)

    result = generate_report_data(symbol, tradier_data=tradier_data)

    if "error" in result:
        print(json.dumps(result))
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
