# ABOUTME: Fetches option chain data from Tradier MCP (primary) or Yahoo Finance (fallback).
# ABOUTME: Supports listing expiries, fetching chains by date, and parsing Tradier chain JSON.

import pandas as pd
import yfinance as yf

from trading_skills.utils import get_current_price


def get_expiries(symbol: str) -> list[str]:
    """Get available option expiration dates via yfinance (fallback)."""
    ticker = yf.Ticker(symbol)
    try:
        return list(ticker.options)
    except Exception:
        return []


def parse_tradier_chain(
    tradier_data: dict,
    symbol: str,
    expiry: str,
    underlying_price: float,
) -> dict:
    """Parse a Tradier MCP get_options_chain response into a standardised chain dict.

    Tradier provides real market Greeks (delta, gamma, theta, vega) which are
    more accurate than Black-Scholes estimates.  The output format is a superset
    of get_option_chain() — all existing fields are preserved and new Greek fields
    are added so downstream consumers can use either source transparently.

    Args:
        tradier_data: Raw JSON from get_options_chain(symbol, expiration, greeks=true).
                      Accepts both the raw MCP wrapper format
                      [{"type": "text", "text": "<json>"}] and a pre-parsed dict.
        symbol: Ticker symbol (used in output metadata).
        expiry: Expiration date string YYYY-MM-DD.
        underlying_price: Current stock price (used for inTheMoney detection).

    Returns:
        dict with keys: symbol, source, expiry, underlying_price, calls, puts.
        Each option entry contains: strike, bid, ask, mid, lastPrice, volume,
        openInterest, impliedVolatility, inTheMoney, delta, gamma, theta, vega,
        prob_profit_pct, spread_pct.
    """
    # Handle MCP wrapper format: [{"type": "text", "text": "<json string>"}]
    if isinstance(tradier_data, list) and tradier_data and "text" in tradier_data[0]:
        import json as _json
        tradier_data = _json.loads(tradier_data[0]["text"])

    options_list: list = []
    try:
        options_list = tradier_data["options"]["option"]
    except (KeyError, TypeError):
        pass

    calls: list[dict] = []
    puts: list[dict] = []

    for o in options_list:
        option_type = o.get("option_type", "").lower()
        if option_type not in ("call", "put"):
            continue

        strike = float(o.get("strike", 0))
        bid = float(o.get("bid") or 0)
        ask = float(o.get("ask") or 0)
        mid = round((bid + ask) / 2, 2)
        last = float(o.get("last") or o.get("lastPrice") or 0)
        volume = int(o.get("volume") or 0)
        oi = int(o.get("open_interest") or 0)

        greeks = o.get("greeks") or {}
        delta = greeks.get("delta")
        gamma = greeks.get("gamma")
        theta = greeks.get("theta")
        vega = greeks.get("vega")
        mid_iv = greeks.get("mid_iv")  # decimal (e.g. 0.38 = 38%)

        # Derived metrics
        iv_pct = round(mid_iv * 100, 1) if mid_iv is not None else None
        in_the_money = (
            (strike < underlying_price) if option_type == "call"
            else (strike > underlying_price)
        ) if underlying_price else False
        prob_profit = round((1 - abs(delta)) * 100, 1) if delta is not None else None
        spread_pct = round((ask - bid) / mid * 100, 1) if mid > 0 else None

        entry = {
            "strike": strike,
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "mid": mid,
            "lastPrice": round(last, 2),
            "volume": volume,
            "openInterest": oi,
            "impliedVolatility": iv_pct,
            "inTheMoney": in_the_money,
            # Real market Greeks from Tradier
            "delta": round(delta, 4) if delta is not None else None,
            "gamma": round(gamma, 4) if gamma is not None else None,
            "theta": round(theta, 4) if theta is not None else None,
            "vega": round(vega, 4) if vega is not None else None,
            # Derived
            "prob_profit_pct": prob_profit,
            "spread_pct": spread_pct,
        }

        if option_type == "call":
            calls.append(entry)
        else:
            puts.append(entry)

    # Sort by strike ascending
    calls.sort(key=lambda x: x["strike"])
    puts.sort(key=lambda x: x["strike"])

    return {
        "symbol": symbol.upper(),
        "source": "tradier",
        "expiry": expiry,
        "underlying_price": round(underlying_price, 2) if underlying_price else None,
        "calls": calls,
        "puts": puts,
    }


def get_option_chain(symbol: str, expiry: str) -> dict:
    """Fetch option chain for a specific expiration date via yfinance (fallback).

    For live data with real Greeks, use Tradier MCP get_options_chain() and
    pass the result to parse_tradier_chain() instead.
    """
    ticker = yf.Ticker(symbol)

    try:
        chain = ticker.option_chain(expiry)
    except Exception as e:
        return {"error": f"Failed to fetch option chain: {e}"}

    # Get underlying price
    info = ticker.info
    underlying_price = get_current_price(info)

    def safe_int(val):
        """Convert to int, handling NaN."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return int(val)

    def safe_float(val, decimals=2):
        """Convert to float, handling NaN."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return round(val, decimals)

    def process_options(df):
        """Convert options DataFrame to list of dicts."""
        records = []
        for _, row in df.iterrows():
            bid = safe_float(row.get("bid")) or 0
            ask = safe_float(row.get("ask")) or 0
            mid = round((bid + ask) / 2, 2) if (bid or ask) else None
            records.append(
                {
                    "strike": row["strike"],
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "lastPrice": safe_float(row.get("lastPrice")),
                    "volume": safe_int(row.get("volume")),
                    "openInterest": safe_int(row.get("openInterest")),
                    "impliedVolatility": safe_float(row.get("impliedVolatility", 0) * 100)
                    if row.get("impliedVolatility")
                    else None,
                    "inTheMoney": bool(row.get("inTheMoney", False)),
                    # Greeks not available from yfinance — must use Tradier or Black-Scholes
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                    "prob_profit_pct": None,
                    "spread_pct": None,
                }
            )
        return records

    return {
        "symbol": symbol.upper(),
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/options?p={symbol}",
        "expiry": expiry,
        "underlying_price": underlying_price,
        "calls": process_options(chain.calls),
        "puts": process_options(chain.puts),
    }
