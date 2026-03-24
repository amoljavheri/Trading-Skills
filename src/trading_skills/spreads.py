# ABOUTME: Analyzes multi-leg option spread strategies.
# ABOUTME: Supports verticals, diagonals, straddles, strangles, iron condors.
# ABOUTME: Uses Tradier MCP chain data (primary) or yfinance (fallback).

import yfinance as yf

from trading_skills.utils import get_current_price

# ---------------------------------------------------------------------------
# Low-level option price helpers
# ---------------------------------------------------------------------------

def get_option_price(chain_calls, chain_puts, strike: float, option_type: str) -> dict | None:
    """Get option price from yfinance chain DataFrames (fallback path).

    Returns dict with bid, ask, mid, iv, and null Greeks (not available from yfinance).
    """
    options = chain_calls if option_type == "call" else chain_puts
    match = options[options["strike"] == strike]
    if match.empty:
        return None
    row = match.iloc[0]
    bid = float(row.get("bid") or 0)
    ask = float(row.get("ask") or 0)
    mid = (bid + ask) / 2
    # Fall back to lastPrice when bid/ask are zero (e.g. outside market hours)
    if mid == 0:
        mid = float(row.get("lastPrice") or 0)
    return {
        "strike": strike,
        "type": option_type,
        "bid": bid,
        "ask": ask,
        "mid": round(mid, 2),
        "iv": row.get("impliedVolatility"),
        # Greeks not available from yfinance
        "delta": None,
        "gamma": None,
        "theta": None,
        "vega": None,
    }


def get_option_price_from_tradier(
    options_list: list, strike: float, option_type: str
) -> dict | None:
    """Get option price from a flat Tradier chain options list (primary path).

    Includes real market Greeks (delta, gamma, theta, vega) from Tradier.

    Args:
        options_list: List of Tradier option dicts (from chain["options"]["option"]).
        strike: Target strike price.
        option_type: "call" or "put".

    Returns:
        Dict with bid, ask, mid, iv, delta, gamma, theta, vega — or None if not found.
    """
    match = next(
        (
            o for o in options_list
            if o.get("option_type", "").lower() == option_type
            and float(o.get("strike", 0)) == strike
        ),
        None,
    )
    if match is None:
        return None

    bid = float(match.get("bid") or 0)
    ask = float(match.get("ask") or 0)
    mid = (bid + ask) / 2
    if mid == 0:
        mid = float(match.get("last") or match.get("lastPrice") or 0)

    greeks = match.get("greeks") or {}
    delta = greeks.get("delta")
    gamma = greeks.get("gamma")
    theta = greeks.get("theta")
    vega = greeks.get("vega")
    mid_iv = greeks.get("mid_iv")

    return {
        "strike": strike,
        "type": option_type,
        "bid": round(bid, 2),
        "ask": round(ask, 2),
        "mid": round(mid, 2),
        "iv": round(mid_iv * 100, 1) if mid_iv is not None else None,
        "delta": round(delta, 4) if delta is not None else None,
        "gamma": round(gamma, 4) if gamma is not None else None,
        "theta": round(theta, 4) if theta is not None else None,
        "vega": round(vega, 4) if vega is not None else None,
    }


def _load_tradier_options_list(tradier_json: dict | list) -> list:
    """Extract flat options list from a Tradier chain response.

    Handles both raw MCP wrapper [{"type":"text","text":"<json>"}] and pre-parsed dicts.
    """
    import json as _json

    if isinstance(tradier_json, list) and tradier_json and "text" in tradier_json[0]:
        tradier_json = _json.loads(tradier_json[0]["text"])
    try:
        return tradier_json["options"]["option"]
    except (KeyError, TypeError):
        return []


def _resolve_option_price(
    tradier_options: list | None,
    yf_chain_calls,
    yf_chain_puts,
    strike: float,
    option_type: str,
) -> dict | None:
    """Resolve option price using Tradier (preferred) or yfinance DataFrames."""
    if tradier_options is not None:
        return get_option_price_from_tradier(tradier_options, strike, option_type)
    return get_option_price(yf_chain_calls, yf_chain_puts, strike, option_type)


# ---------------------------------------------------------------------------
# Spread analysis functions (all accept optional tradier_options + underlying_price)
# ---------------------------------------------------------------------------

def analyze_vertical(
    symbol: str,
    expiry: str,
    option_type: str,
    long_strike: float,
    short_strike: float,
    tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Analyze vertical spread (bull/bear call/put spread).

    Args:
        tradier_options: Pre-loaded Tradier options list for real Greeks.
                         If None, fetches from yfinance.
        underlying_price: Current stock price (required when using Tradier).
    """
    if tradier_options is not None:
        long_opt = get_option_price_from_tradier(tradier_options, long_strike, option_type)
        short_opt = get_option_price_from_tradier(tradier_options, short_strike, option_type)
        underlying = underlying_price
        source = "tradier"
    else:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(expiry)
        info = ticker.info
        underlying = get_current_price(info)
        long_opt = get_option_price(chain.calls, chain.puts, long_strike, option_type)
        short_opt = get_option_price(chain.calls, chain.puts, short_strike, option_type)
        source = "yfinance"

    if not long_opt or not short_opt:
        return {"error": "Could not find options at specified strikes"}

    # Calculate spread metrics
    net_debit = long_opt["mid"] - short_opt["mid"]
    width = abs(long_strike - short_strike)

    if option_type == "call":
        if long_strike < short_strike:  # Bull call spread
            max_profit = width - net_debit
            max_loss = net_debit
            breakeven = long_strike + net_debit
            direction = "bullish"
        else:  # Bear call spread (credit spread)
            max_profit = -net_debit
            max_loss = width + net_debit
            breakeven = short_strike - net_debit
            direction = "bearish"
    else:  # put
        if long_strike > short_strike:  # Bear put spread
            max_profit = width - net_debit
            max_loss = net_debit
            breakeven = long_strike - net_debit
            direction = "bearish"
        else:  # Bull put spread (credit spread)
            max_profit = -net_debit
            max_loss = width + net_debit
            breakeven = short_strike + net_debit
            direction = "bullish"

    return {
        "symbol": symbol.upper(),
        "source": source,
        "strategy": f"Vertical {option_type.title()} Spread",
        "direction": direction,
        "expiry": expiry,
        "underlying_price": round(underlying, 2) if underlying else None,
        "legs": [
            {"action": "buy", **long_opt},
            {"action": "sell", **short_opt},
        ],
        "net_debit": round(net_debit, 2),
        "max_profit": round(max_profit * 100, 2),
        "max_loss": round(max_loss * 100, 2),
        "breakeven": round(breakeven, 2),
        "risk_reward": round(max_profit / max_loss, 2) if max_loss > 0 else None,
    }


def analyze_diagonal(
    symbol: str,
    option_type: str,
    long_expiry: str,
    long_strike: float,
    short_expiry: str,
    short_strike: float,
    long_tradier_options: list | None = None,
    short_tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Analyze diagonal spread (different expiries and strikes).

    Args:
        long_tradier_options: Tradier options list for the long (back-month) expiry.
        short_tradier_options: Tradier options list for the short (front-month) expiry.
        underlying_price: Current stock price (required when using Tradier).
    """
    if long_tradier_options is not None and short_tradier_options is not None:
        long_opt = get_option_price_from_tradier(
            long_tradier_options, long_strike, option_type
        )
        short_opt = get_option_price_from_tradier(
            short_tradier_options, short_strike, option_type
        )
        underlying = underlying_price
        source = "tradier"
    else:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        underlying = get_current_price(info)
        long_chain = ticker.option_chain(long_expiry)
        short_chain = ticker.option_chain(short_expiry)
        long_opt = get_option_price(long_chain.calls, long_chain.puts, long_strike, option_type)
        short_opt = get_option_price(
            short_chain.calls, short_chain.puts, short_strike, option_type
        )
        source = "yfinance"

    if not long_opt or not short_opt:
        return {"error": "Could not find options at specified strikes/expiries"}

    net_debit = long_opt["mid"] - short_opt["mid"]

    if option_type == "call":
        direction = (
            "bullish (poor man's covered call)"
            if long_strike <= short_strike
            else "bearish"
        )
    else:
        direction = (
            "bearish (poor man's covered put)"
            if long_strike >= short_strike
            else "bullish"
        )

    return {
        "symbol": symbol.upper(),
        "source": source,
        "strategy": f"Diagonal {option_type.title()} Spread",
        "direction": direction,
        "long_leg": {"action": "buy", "expiry": long_expiry, **long_opt},
        "short_leg": {"action": "sell", "expiry": short_expiry, **short_opt},
        "underlying_price": round(underlying, 2) if underlying else None,
        "net_debit": round(net_debit, 2),
        "net_debit_total": round(net_debit * 100, 2),
        "max_loss": round(net_debit * 100, 2),
        "short_premium_collected": round(short_opt["mid"] * 100, 2),
        "notes": "Max profit depends on IV at short expiry. Can sell again if short expires OTM.",
    }


def analyze_straddle(
    symbol: str,
    expiry: str,
    strike: float,
    tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Analyze long straddle (buy call + put at same strike).

    Args:
        tradier_options: Pre-loaded Tradier options list for real Greeks.
        underlying_price: Current stock price (required when using Tradier).
    """
    if tradier_options is not None:
        call = get_option_price_from_tradier(tradier_options, strike, "call")
        put = get_option_price_from_tradier(tradier_options, strike, "put")
        underlying = underlying_price
        source = "tradier"
    else:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(expiry)
        info = ticker.info
        underlying = get_current_price(info)
        call = get_option_price(chain.calls, chain.puts, strike, "call")
        put = get_option_price(chain.calls, chain.puts, strike, "put")
        source = "yfinance"

    if not call or not put:
        return {"error": "Could not find options at specified strike"}

    total_cost = call["mid"] + put["mid"]

    return {
        "symbol": symbol.upper(),
        "source": source,
        "strategy": "Long Straddle",
        "direction": "neutral (expects big move)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2) if underlying else None,
        "legs": [{"action": "buy", **call}, {"action": "buy", **put}],
        "total_cost": round(total_cost * 100, 2),
        "max_profit": "unlimited",
        "max_loss": round(total_cost * 100, 2),
        "breakeven_up": round(strike + total_cost, 2),
        "breakeven_down": round(strike - total_cost, 2),
        "move_needed_pct": round((total_cost / strike) * 100, 2),
    }


def analyze_strangle(
    symbol: str,
    expiry: str,
    put_strike: float,
    call_strike: float,
    tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Analyze long strangle (buy OTM call + OTM put).

    Args:
        tradier_options: Pre-loaded Tradier options list for real Greeks.
        underlying_price: Current stock price (required when using Tradier).
    """
    if tradier_options is not None:
        call = get_option_price_from_tradier(tradier_options, call_strike, "call")
        put = get_option_price_from_tradier(tradier_options, put_strike, "put")
        underlying = underlying_price
        source = "tradier"
    else:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(expiry)
        info = ticker.info
        underlying = get_current_price(info)
        call = get_option_price(chain.calls, chain.puts, call_strike, "call")
        put = get_option_price(chain.calls, chain.puts, put_strike, "put")
        source = "yfinance"

    if not call or not put:
        return {"error": "Could not find options at specified strikes"}

    total_cost = call["mid"] + put["mid"]

    return {
        "symbol": symbol.upper(),
        "source": source,
        "strategy": "Long Strangle",
        "direction": "neutral (expects big move)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2) if underlying else None,
        "legs": [{"action": "buy", **call}, {"action": "buy", **put}],
        "total_cost": round(total_cost * 100, 2),
        "max_profit": "unlimited",
        "max_loss": round(total_cost * 100, 2),
        "breakeven_up": round(call_strike + total_cost, 2),
        "breakeven_down": round(put_strike - total_cost, 2),
    }


def analyze_iron_condor(
    symbol: str,
    expiry: str,
    put_long: float,
    put_short: float,
    call_short: float,
    call_long: float,
    tradier_options: list | None = None,
    underlying_price: float | None = None,
) -> dict:
    """Analyze iron condor (sell strangle + buy wider strangle for protection).

    Args:
        tradier_options: Pre-loaded Tradier options list for real Greeks.
        underlying_price: Current stock price (required when using Tradier).
    """
    if tradier_options is not None:
        put_buy = get_option_price_from_tradier(tradier_options, put_long, "put")
        put_sell = get_option_price_from_tradier(tradier_options, put_short, "put")
        call_sell = get_option_price_from_tradier(tradier_options, call_short, "call")
        call_buy = get_option_price_from_tradier(tradier_options, call_long, "call")
        underlying = underlying_price
        source = "tradier"
    else:
        ticker = yf.Ticker(symbol)
        chain = ticker.option_chain(expiry)
        info = ticker.info
        underlying = get_current_price(info)
        put_buy = get_option_price(chain.calls, chain.puts, put_long, "put")
        put_sell = get_option_price(chain.calls, chain.puts, put_short, "put")
        call_sell = get_option_price(chain.calls, chain.puts, call_short, "call")
        call_buy = get_option_price(chain.calls, chain.puts, call_long, "call")
        source = "yfinance"

    if not all([put_buy, put_sell, call_sell, call_buy]):
        return {"error": "Could not find options at all specified strikes"}

    net_credit = (put_sell["mid"] + call_sell["mid"]) - (put_buy["mid"] + call_buy["mid"])
    put_width = put_short - put_long
    call_width = call_long - call_short
    max_loss = max(put_width, call_width) - net_credit

    return {
        "symbol": symbol.upper(),
        "source": source,
        "strategy": "Iron Condor",
        "direction": "neutral (expects low volatility)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2) if underlying else None,
        "legs": [
            {"action": "buy", **put_buy},
            {"action": "sell", **put_sell},
            {"action": "sell", **call_sell},
            {"action": "buy", **call_buy},
        ],
        "net_credit": round(net_credit * 100, 2),
        "max_profit": round(net_credit * 100, 2),
        "max_loss": round(max_loss * 100, 2),
        "breakeven_down": round(put_short - net_credit, 2),
        "breakeven_up": round(call_short + net_credit, 2),
        "profit_range": f"{put_short} - {call_short}",
    }
