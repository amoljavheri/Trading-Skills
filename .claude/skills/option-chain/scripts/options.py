#!/usr/bin/env python3
# ABOUTME: CLI wrapper for option chain data fetching.
# ABOUTME: Tradier MCP is primary (real Greeks); yfinance is fallback.

import argparse
import json
import sys

from trading_skills.options import get_expiries, get_option_chain, parse_tradier_chain


def main():
    parser = argparse.ArgumentParser(
        description="Fetch option chain data (Tradier MCP primary, yfinance fallback)"
    )
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--expiries", action="store_true", help="List expiration dates only")
    parser.add_argument("--expiry", help="Fetch chain for specific expiry (YYYY-MM-DD)")

    # Tradier-first flags
    parser.add_argument(
        "--tradier-json",
        metavar="FILE",
        help="Path to saved Tradier get_options_chain JSON (enables real Greeks)",
    )
    parser.add_argument(
        "--underlying-price",
        type=float,
        metavar="PRICE",
        help="Current underlying price (required with --tradier-json)",
    )

    args = parser.parse_args()
    symbol = args.symbol.upper()

    # --- Tradier path (primary) ---
    if args.tradier_json:
        if not args.expiry:
            print(
                json.dumps({"error": "--expiry YYYY-MM-DD is required with --tradier-json"}),
                file=sys.stderr,
            )
            sys.exit(1)
        if args.underlying_price is None:
            print(
                json.dumps({"error": "--underlying-price is required with --tradier-json"}),
                file=sys.stderr,
            )
            sys.exit(1)

        with open(args.tradier_json) as f:
            tradier_data = json.load(f)

        result = parse_tradier_chain(
            tradier_data,
            symbol=symbol,
            expiry=args.expiry,
            underlying_price=args.underlying_price,
        )
        print(json.dumps(result, indent=2))
        return

    # --- yfinance fallback ---
    if args.expiries:
        expiries = get_expiries(symbol)
        if not expiries:
            print(json.dumps({"error": f"No options found for {symbol}"}))
            sys.exit(1)
        print(json.dumps({"symbol": symbol, "expiries": expiries}, indent=2))
    elif args.expiry:
        result = get_option_chain(symbol, args.expiry)
        print(json.dumps(result, indent=2))
    else:
        # Default: show expiries
        expiries = get_expiries(symbol)
        if not expiries:
            print(json.dumps({"error": f"No options found for {symbol}"}))
            sys.exit(1)
        print(json.dumps({"symbol": symbol, "expiries": expiries}, indent=2))


if __name__ == "__main__":
    main()
