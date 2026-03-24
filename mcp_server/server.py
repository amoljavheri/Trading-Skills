# ABOUTME: FastMCP Streamable HTTP server for trading-skills library.
# ABOUTME: Exposes 20 trading analysis tools over HTTP for Claude Desktop remote access.

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from trading_skills.correlation import compute_correlation
from trading_skills.earnings import get_earnings_info, get_multiple_earnings
from trading_skills.fundamentals import get_fundamentals
from trading_skills.greeks import calculate_greeks
from trading_skills.history import get_history
from trading_skills.news import get_news
from trading_skills.options import get_expiries, get_option_chain
from trading_skills.piotroski import calculate_piotroski_score
from trading_skills.quote import get_quote
from trading_skills.report import generate_report_data
from trading_skills.risk import calculate_risk_metrics
from trading_skills.scanner_bullish import compute_bullish_score, scan_symbols
from trading_skills.scanner_pmcc import analyze_pmcc, format_scan_results
from trading_skills.spreads import (
    analyze_diagonal,
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)
from trading_skills.technicals import compute_indicators

mcp = FastMCP("trading-skills")


@mcp.tool()
def stock_quote(symbol: str) -> dict:
    """Get current stock quote: price, change, volume, 52-week range, P/E, beta."""
    try:
        return get_quote(symbol)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def price_history(symbol: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Get OHLCV price history. period: 1d/5d/1mo/3mo/6mo/1y/2y/5y. interval: 1m/5m/1h/1d/1wk."""
    try:
        return get_history(symbol, period, interval)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def news_sentiment(symbol: str, limit: int = 10) -> dict:
    """Get recent news articles for a stock symbol."""
    try:
        return get_news(symbol, limit)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def fundamentals(symbol: str, data_type: str = "all") -> dict:
    """Get fundamental financial data. data_type: all/info/financials/cashflow/balance."""
    try:
        return get_fundamentals(symbol, data_type)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def piotroski_score(symbol: str) -> dict:
    """Calculate Piotroski F-Score (0-9) measuring financial strength."""
    try:
        return calculate_piotroski_score(symbol)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def earnings_calendar(symbol: str) -> dict:
    """Get upcoming earnings date, timing (BMO/AMC), and EPS estimate.
    Pass comma-separated symbols for multiple (e.g. 'AAPL,MSFT,NVDA').
    """
    try:
        if "," in symbol:
            symbols_list = [s.strip().upper() for s in symbol.split(",")]
            return get_multiple_earnings(symbols_list)
        return get_earnings_info(symbol)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def technical_indicators(symbol: str, period: str = "3mo", indicators: str = "") -> dict:
    """Compute technical indicators. indicators: comma-separated list of rsi,macd,bb,sma,ema,atr,adx,vwap,sr."""
    try:
        indicators_list = (
            [i.strip() for i in indicators.split(",") if i.strip()] if indicators else None
        )
        return compute_indicators(symbol, period, indicators_list)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def price_correlation(symbols: str, period: str = "3mo") -> dict:
    """Compute price correlation matrix. symbols: comma-separated (e.g. 'AAPL,MSFT,SPY')."""
    try:
        symbols_list = [s.strip().upper() for s in symbols.split(",")]
        return compute_correlation(symbols_list, period)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def risk_assessment(
    symbol: str,
    period: str = "1y",
    position_size: Optional[float] = None,
) -> dict:
    """Calculate risk metrics: volatility, beta, VaR, Sharpe ratio, max drawdown."""
    try:
        return calculate_risk_metrics(symbol, period, position_size)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def option_expiries(symbol: str) -> dict:
    """Get list of available option expiration dates for a symbol."""
    try:
        expiries = get_expiries(symbol)
        return {"symbol": symbol.upper(), "expiries": expiries}
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def option_chain(symbol: str, expiry: str) -> dict:
    """Get full option chain (calls + puts) for a symbol and expiry date (YYYY-MM-DD)."""
    try:
        return get_option_chain(symbol, expiry)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def option_greeks(
    spot: float,
    strike: float,
    option_type: str,
    dte: Optional[int] = None,
    expiry: Optional[str] = None,
    market_price: Optional[float] = None,
    rate: float = 0.05,
    volatility: Optional[float] = None,
) -> dict:
    """Calculate option Greeks using Black-Scholes. Provide either dte (int) or expiry (YYYY-MM-DD).
    option_type: 'call' or 'put'. market_price triggers IV calculation.
    """
    try:
        return calculate_greeks(
            spot=spot,
            strike=strike,
            option_type=option_type,
            expiry=expiry,
            dte=dte,
            market_price=market_price,
            rate=rate,
            volatility=volatility,
        )
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def spread_vertical(
    symbol: str,
    expiry: str,
    option_type: str,
    long_strike: float,
    short_strike: float,
) -> dict:
    """Analyze vertical spread (bull/bear call/put). option_type: 'call' or 'put'."""
    try:
        return analyze_vertical(symbol, expiry, option_type, long_strike, short_strike)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def spread_diagonal(
    symbol: str,
    option_type: str,
    long_expiry: str,
    long_strike: float,
    short_expiry: str,
    short_strike: float,
) -> dict:
    """Analyze diagonal spread (different expiries + strikes). option_type: 'call' or 'put'."""
    try:
        return analyze_diagonal(
            symbol, option_type, long_expiry, long_strike, short_expiry, short_strike
        )
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def spread_straddle(symbol: str, expiry: str, strike: float) -> dict:
    """Analyze long straddle (buy call + put at same strike). Profits from large moves."""
    try:
        return analyze_straddle(symbol, expiry, strike)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def spread_strangle(
    symbol: str, expiry: str, call_strike: float, put_strike: float
) -> dict:
    """Analyze long strangle (buy OTM call + OTM put). call_strike > put_strike."""
    try:
        return analyze_strangle(symbol, expiry, put_strike, call_strike)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def spread_iron_condor(
    symbol: str,
    expiry: str,
    put_long_strike: float,
    put_short_strike: float,
    call_short_strike: float,
    call_long_strike: float,
) -> dict:
    """Analyze iron condor. Strikes order: put_long < put_short < call_short < call_long."""
    try:
        return analyze_iron_condor(
            symbol,
            expiry,
            put_long_strike,
            put_short_strike,
            call_short_strike,
            call_long_strike,
        )
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def scan_bullish(symbol: str, period: str = "12mo") -> dict:
    """Score a symbol for bullish trend (0-11.5 scale). Pass comma-separated symbols for batch scan."""
    try:
        if "," in symbol:
            symbols_list = [s.strip().upper() for s in symbol.split(",")]
            results = scan_symbols(symbols_list, period=period)
            return {"symbols": symbols_list, "count": len(results), "results": results}
        result = compute_bullish_score(symbol, period)
        if result is None:
            return {"error": f"Insufficient data for {symbol}", "symbol": symbol.upper()}
        return result
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def scan_pmcc(symbol: str) -> dict:
    """Analyze symbol for PMCC (Poor Man's Covered Call) suitability. Pass comma-separated for batch."""
    try:
        if "," in symbol:
            symbols_list = [s.strip().upper() for s in symbol.split(",")]
            results = [analyze_pmcc(s) for s in symbols_list]
            results = [r for r in results if r is not None]
            return format_scan_results(results)
        result = analyze_pmcc(symbol)
        if result is None:
            return {"error": f"No PMCC data for {symbol}", "symbol": symbol.upper()}
        return result
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


@mcp.tool()
def report_stock(symbol: str) -> dict:
    """Generate comprehensive stock analysis report with conviction score, trend, fundamentals, spreads."""
    try:
        return generate_report_data(symbol)
    except Exception as e:
        return {"error": str(e), "symbol": symbol.upper()}


def main() -> None:
    """Entry point for trading-skills-mcp script and Docker CMD."""
    port = int(os.environ.get("PORT", 8080))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
