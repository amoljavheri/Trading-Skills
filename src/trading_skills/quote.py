# ABOUTME: Fetches stock quote from Tradier MCP (primary) or Yahoo Finance (fallback).
# ABOUTME: Returns price, volume, market cap, and key metrics.

import yfinance as yf


def parse_tradier_quote(data: dict) -> dict:
    """Parse Tradier get_market_quotes response into standard quote schema.

    Accepts either the full wrapper {"quotes": {"quote": {...}}}
    or a pre-unwrapped quote dict.
    """
    q = data.get("quotes", {}).get("quote", data)
    if isinstance(q, list):
        q = q[0] if q else {}
    if not q or q.get("type") == "error":
        return {"error": "Invalid or missing Tradier quote data"}
    return {
        "symbol": q.get("symbol", ""),
        "name": q.get("description", ""),
        "price": q.get("last"),
        "change": q.get("change"),
        "change_percent": q.get("change_percentage"),
        "volume": q.get("volume"),
        "avg_volume": q.get("average_volume"),
        "market_cap": None,      # not provided by Tradier quotes endpoint
        "high_52w": q.get("week_52_high"),
        "low_52w": q.get("week_52_low"),
        "pe_ratio": None,        # not provided by Tradier quotes endpoint
        "forward_pe": None,      # not provided by Tradier quotes endpoint
        "dividend_yield": None,  # not provided by Tradier quotes endpoint
        "beta": None,            # not provided by Tradier quotes endpoint
        "source": "tradier",
    }


def get_quote(symbol: str) -> dict:
    """Fetch current quote for a ticker symbol via Yahoo Finance."""
    ticker = yf.Ticker(symbol)
    info = ticker.info

    # Handle case where ticker doesn't exist
    if not info or info.get("regularMarketPrice") is None:
        return {"error": f"No data found for symbol: {symbol}"}

    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName", info.get("longName", "N/A")),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "change": info.get("regularMarketChange"),
        "change_percent": info.get("regularMarketChangePercent"),
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "high_52w": info.get("fiftyTwoWeekHigh"),
        "low_52w": info.get("fiftyTwoWeekLow"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "source": "yfinance",
    }
