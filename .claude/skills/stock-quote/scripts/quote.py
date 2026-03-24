#!/usr/bin/env python3
# ABOUTME: CLI wrapper for stock quote fetching.
# ABOUTME: Tries Tradier MCP data first (via --tradier arg), falls back to Yahoo Finance.

import argparse
import json
import sys

from trading_skills.quote import get_quote, parse_tradier_quote


def main():
    parser = argparse.ArgumentParser(description="Fetch stock quote")
    parser.add_argument("symbol", help="Ticker symbol (e.g. AAPL)")
    parser.add_argument(
        "--tradier",
        help="Raw JSON string from Tradier get_market_quotes tool",
        default=None,
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()

    if args.tradier:
        try:
            data = json.loads(args.tradier)
            result = parse_tradier_quote(data)
            if "error" not in result:
                print(json.dumps(result, indent=2))
                sys.exit(0)
        except Exception:
            pass  # fall through to yfinance

    result = get_quote(symbol)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
