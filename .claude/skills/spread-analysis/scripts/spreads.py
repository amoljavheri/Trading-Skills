#!/usr/bin/env python3
# ABOUTME: CLI wrapper for option spread strategy analysis.
# ABOUTME: Tradier MCP is primary (real Greeks); yfinance is fallback.

import argparse
import json
import sys

from trading_skills.spreads import (
    _load_tradier_options_list,
    analyze_diagonal,
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)


def _load_tradier(path: str) -> list:
    """Load and extract Tradier options list from a saved JSON file."""
    with open(path) as f:
        raw = json.load(f)
    return _load_tradier_options_list(raw)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze option spreads (Tradier MCP primary, yfinance fallback)"
    )
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["vertical", "diagonal", "straddle", "strangle", "iron-condor"],
    )
    parser.add_argument("--expiry", help="Expiry date (YYYY-MM-DD)")
    parser.add_argument("--long-expiry", help="Long leg expiry for diagonal")
    parser.add_argument("--short-expiry", help="Short leg expiry for diagonal")
    parser.add_argument("--type", choices=["call", "put"], help="Option type for vertical/diagonal")
    parser.add_argument("--strike", type=float, help="Strike for straddle")
    parser.add_argument("--long-strike", type=float, help="Long strike")
    parser.add_argument("--short-strike", type=float, help="Short strike")
    parser.add_argument("--put-strike", type=float, help="Put strike for strangle")
    parser.add_argument("--call-strike", type=float, help="Call strike for strangle")
    parser.add_argument("--put-long", type=float, help="Long put for iron condor")
    parser.add_argument("--put-short", type=float, help="Short put for iron condor")
    parser.add_argument("--call-short", type=float, help="Short call for iron condor")
    parser.add_argument("--call-long", type=float, help="Long call for iron condor")

    # Tradier-first flags
    parser.add_argument(
        "--tradier-json",
        metavar="FILE",
        help="Path to saved Tradier get_options_chain JSON for the primary expiry",
    )
    parser.add_argument(
        "--tradier-json-long",
        metavar="FILE",
        help="Tradier JSON for the long (back-month) expiry (diagonal only)",
    )
    parser.add_argument(
        "--tradier-json-short",
        metavar="FILE",
        help="Tradier JSON for the short (front-month) expiry (diagonal only)",
    )
    parser.add_argument(
        "--underlying-price",
        type=float,
        metavar="PRICE",
        help="Current underlying price (required with --tradier-json)",
    )

    args = parser.parse_args()

    # Resolve Tradier options lists if provided
    tradier_options = None
    if args.tradier_json:
        if args.underlying_price is None:
            print(
                json.dumps({"error": "--underlying-price is required with --tradier-json"}),
                file=sys.stderr,
            )
            sys.exit(1)
        tradier_options = _load_tradier(args.tradier_json)

    long_tradier = _load_tradier(args.tradier_json_long) if args.tradier_json_long else None
    short_tradier = _load_tradier(args.tradier_json_short) if args.tradier_json_short else None

    underlying = args.underlying_price

    if args.strategy == "vertical":
        result = analyze_vertical(
            args.symbol,
            args.expiry,
            args.type,
            args.long_strike,
            args.short_strike,
            tradier_options=tradier_options,
            underlying_price=underlying,
        )
    elif args.strategy == "diagonal":
        result = analyze_diagonal(
            args.symbol,
            args.type,
            args.long_expiry,
            args.long_strike,
            args.short_expiry,
            args.short_strike,
            long_tradier_options=long_tradier,
            short_tradier_options=short_tradier,
            underlying_price=underlying,
        )
    elif args.strategy == "straddle":
        result = analyze_straddle(
            args.symbol,
            args.expiry,
            args.strike,
            tradier_options=tradier_options,
            underlying_price=underlying,
        )
    elif args.strategy == "strangle":
        result = analyze_strangle(
            args.symbol,
            args.expiry,
            args.put_strike,
            args.call_strike,
            tradier_options=tradier_options,
            underlying_price=underlying,
        )
    elif args.strategy == "iron-condor":
        result = analyze_iron_condor(
            args.symbol,
            args.expiry,
            args.put_long,
            args.put_short,
            args.call_short,
            args.call_long,
            tradier_options=tradier_options,
            underlying_price=underlying,
        )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
