# ABOUTME: Tests for options.py — Tradier parse_tradier_chain and yfinance get_option_chain.
# ABOUTME: Synthetic tests only (no network calls). Live tests marked with @pytest.mark.live.

import json

import pytest

from trading_skills.options import get_expiries, get_option_chain, parse_tradier_chain
from trading_skills.spreads import _load_tradier_options_list, get_option_price_from_tradier

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_tradier_option(
    option_type: str,
    strike: float,
    bid: float = 1.00,
    ask: float = 1.10,
    last: float = 1.05,
    volume: int = 100,
    open_interest: int = 500,
    delta: float = 0.40,
    gamma: float = 0.02,
    theta: float = -0.03,
    vega: float = 0.15,
    mid_iv: float = 0.35,
) -> dict:
    return {
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": last,
        "volume": volume,
        "open_interest": open_interest,
        "greeks": {
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "mid_iv": mid_iv,
        },
    }


def _make_tradier_chain(options: list) -> dict:
    return {"options": {"option": options}}


UNDERLYING = 190.0

SAMPLE_OPTIONS = [
    _make_tradier_option("call", 185.0, bid=6.00, ask=6.20, delta=0.65, mid_iv=0.30),
    _make_tradier_option("call", 190.0, bid=3.00, ask=3.20, delta=0.50, mid_iv=0.32),
    _make_tradier_option("call", 195.0, bid=1.20, ask=1.40, delta=0.30, mid_iv=0.34),
    _make_tradier_option("put", 185.0, bid=1.10, ask=1.30, delta=-0.35, mid_iv=0.31),
    _make_tradier_option("put", 190.0, bid=3.00, ask=3.20, delta=-0.50, mid_iv=0.32),
    _make_tradier_option("put", 195.0, bid=6.10, ask=6.30, delta=-0.70, mid_iv=0.33),
]

CHAIN_DATA = _make_tradier_chain(SAMPLE_OPTIONS)


# ---------------------------------------------------------------------------
# parse_tradier_chain — calls
# ---------------------------------------------------------------------------

class TestParseTradierChainCalls:
    def setup_method(self):
        self.result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", UNDERLYING)
        self.calls = self.result["calls"]

    def test_metadata(self):
        assert self.result["symbol"] == "AAPL"
        assert self.result["source"] == "tradier"
        assert self.result["expiry"] == "2026-04-17"
        assert self.result["underlying_price"] == UNDERLYING

    def test_calls_count(self):
        assert len(self.calls) == 3

    def test_calls_sorted_by_strike(self):
        strikes = [c["strike"] for c in self.calls]
        assert strikes == sorted(strikes)

    def test_call_fields_present(self):
        c = self.calls[0]
        for field in (
            "strike", "bid", "ask", "mid", "lastPrice", "volume",
            "openInterest", "impliedVolatility", "inTheMoney",
            "delta", "gamma", "theta", "vega", "prob_profit_pct", "spread_pct",
        ):
            assert field in c, f"Missing field: {field}"

    def test_call_mid_calculation(self):
        c = next(c for c in self.calls if c["strike"] == 190.0)
        assert c["mid"] == round((3.00 + 3.20) / 2, 2)

    def test_call_iv_converted_to_percent(self):
        c = next(c for c in self.calls if c["strike"] == 190.0)
        assert c["impliedVolatility"] == round(0.32 * 100, 1)

    def test_call_delta(self):
        c = next(c for c in self.calls if c["strike"] == 190.0)
        assert c["delta"] == 0.50

    def test_call_prob_profit_pct(self):
        # prob_profit = (1 - abs(delta)) * 100
        c = next(c for c in self.calls if c["strike"] == 190.0)
        assert c["prob_profit_pct"] == round((1 - 0.50) * 100, 1)

    def test_call_spread_pct(self):
        # spread_pct = (ask - bid) / mid * 100
        c = next(c for c in self.calls if c["strike"] == 190.0)
        mid = (3.00 + 3.20) / 2
        expected = round((3.20 - 3.00) / mid * 100, 1)
        assert c["spread_pct"] == expected


# ---------------------------------------------------------------------------
# parse_tradier_chain — puts
# ---------------------------------------------------------------------------

class TestParseTradierChainPuts:
    def setup_method(self):
        self.result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", UNDERLYING)
        self.puts = self.result["puts"]

    def test_puts_count(self):
        assert len(self.puts) == 3

    def test_puts_sorted_by_strike(self):
        strikes = [p["strike"] for p in self.puts]
        assert strikes == sorted(strikes)

    def test_put_delta_negative(self):
        p = next(p for p in self.puts if p["strike"] == 190.0)
        assert p["delta"] == -0.50

    def test_put_prob_profit_pct(self):
        p = next(p for p in self.puts if p["strike"] == 190.0)
        # abs(-0.50) = 0.50, prob = 50.0
        assert p["prob_profit_pct"] == 50.0


# ---------------------------------------------------------------------------
# parse_tradier_chain — ITM detection
# ---------------------------------------------------------------------------

class TestParseTradierChainITM:
    def test_call_itm_below_underlying(self):
        result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", 190.0)
        calls = {c["strike"]: c for c in result["calls"]}
        # Strike 185 < 190 = ITM for calls
        assert calls[185.0]["inTheMoney"] is True

    def test_call_otm_above_underlying(self):
        result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", 190.0)
        calls = {c["strike"]: c for c in result["calls"]}
        # Strike 195 > 190 = OTM for calls
        assert calls[195.0]["inTheMoney"] is False

    def test_put_itm_above_underlying(self):
        result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", 190.0)
        puts = {p["strike"]: p for p in result["puts"]}
        # Strike 195 > 190 = ITM for puts
        assert puts[195.0]["inTheMoney"] is True

    def test_put_otm_below_underlying(self):
        result = parse_tradier_chain(CHAIN_DATA, "AAPL", "2026-04-17", 190.0)
        puts = {p["strike"]: p for p in result["puts"]}
        # Strike 185 < 190 = OTM for puts
        assert puts[185.0]["inTheMoney"] is False


# ---------------------------------------------------------------------------
# parse_tradier_chain — missing/null Greeks
# ---------------------------------------------------------------------------

class TestParseTradierChainMissingGreeks:
    def test_missing_greeks_dict(self):
        """Option with no 'greeks' key should produce null Greek fields."""
        option = {
            "option_type": "call",
            "strike": 200.0,
            "bid": 0.50,
            "ask": 0.60,
            "last": 0.55,
            "volume": 10,
            "open_interest": 50,
            # No 'greeks' key at all
        }
        data = _make_tradier_chain([option])
        result = parse_tradier_chain(data, "AAPL", "2026-04-17", 190.0)
        c = result["calls"][0]
        assert c["delta"] is None
        assert c["gamma"] is None
        assert c["theta"] is None
        assert c["vega"] is None
        assert c["impliedVolatility"] is None
        assert c["prob_profit_pct"] is None

    def test_empty_greeks_dict(self):
        """Option with empty 'greeks' dict should also produce null Greek fields."""
        option = _make_tradier_option("call", 200.0)
        option["greeks"] = {}
        data = _make_tradier_chain([option])
        result = parse_tradier_chain(data, "AAPL", "2026-04-17", 190.0)
        c = result["calls"][0]
        assert c["delta"] is None
        assert c["impliedVolatility"] is None

    def test_empty_options_list(self):
        """Chain with no options should return empty calls/puts lists."""
        data = {"options": {"option": []}}
        result = parse_tradier_chain(data, "AAPL", "2026-04-17", 190.0)
        assert result["calls"] == []
        assert result["puts"] == []

    def test_malformed_options_key(self):
        """Chain with missing options key should return empty calls/puts."""
        result = parse_tradier_chain({}, "AAPL", "2026-04-17", 190.0)
        assert result["calls"] == []
        assert result["puts"] == []


# ---------------------------------------------------------------------------
# parse_tradier_chain — MCP wrapper format
# ---------------------------------------------------------------------------

class TestParseTradierChainMCPWrapper:
    def test_mcp_wrapper_format(self):
        """Should handle [{"type":"text","text":"<json>"}] MCP wrapper format."""
        raw_json = json.dumps(CHAIN_DATA)
        wrapped = [{"type": "text", "text": raw_json}]
        result = parse_tradier_chain(wrapped, "AAPL", "2026-04-17", UNDERLYING)
        assert len(result["calls"]) == 3
        assert len(result["puts"]) == 3
        assert result["source"] == "tradier"


# ---------------------------------------------------------------------------
# get_option_price_from_tradier (spreads module)
# ---------------------------------------------------------------------------

class TestGetOptionPriceFromTradier:
    def test_find_call_by_strike(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 190.0, "call")
        assert result is not None
        assert result["strike"] == 190.0
        assert result["type"] == "call"
        assert result["mid"] == round((3.00 + 3.20) / 2, 2)

    def test_find_put_by_strike(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 190.0, "put")
        assert result is not None
        assert result["strike"] == 190.0
        assert result["type"] == "put"
        assert result["delta"] == -0.50

    def test_returns_none_for_missing_strike(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 999.0, "call")
        assert result is None

    def test_call_found_at_correct_type(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 185.0, "call")
        assert result is not None
        assert result["type"] == "call"

    def test_includes_all_greek_fields(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 185.0, "call")
        assert "delta" in result
        assert "gamma" in result
        assert "theta" in result
        assert "vega" in result
        assert "iv" in result

    def test_iv_converted_to_percent(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 185.0, "call")
        # mid_iv=0.30 → iv=30.0
        assert result["iv"] == 30.0

    def test_bid_ask_rounded(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        result = get_option_price_from_tradier(opts, 185.0, "call")
        assert result["bid"] == 6.00
        assert result["ask"] == 6.20


# ---------------------------------------------------------------------------
# _load_tradier_options_list
# ---------------------------------------------------------------------------

class TestLoadTradierOptionsList:
    def test_loads_from_dict(self):
        opts = _load_tradier_options_list(CHAIN_DATA)
        assert len(opts) == 6

    def test_loads_from_mcp_wrapper(self):
        wrapped = [{"type": "text", "text": json.dumps(CHAIN_DATA)}]
        opts = _load_tradier_options_list(wrapped)
        assert len(opts) == 6

    def test_returns_empty_for_bad_input(self):
        opts = _load_tradier_options_list({})
        assert opts == []

    def test_returns_empty_for_empty_options(self):
        data = {"options": {"option": []}}
        opts = _load_tradier_options_list(data)
        assert opts == []


# ---------------------------------------------------------------------------
# Live tests (require network — run with: pytest -m live)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestLiveGetExpiries:
    def test_valid_symbol_returns_list(self):
        expiries = get_expiries("AAPL")
        assert isinstance(expiries, list)
        assert len(expiries) > 0

    def test_expiry_format(self):
        """Expiries should be YYYY-MM-DD strings."""
        expiries = get_expiries("AAPL")
        for exp in expiries[:3]:
            assert len(exp) == 10
            assert exp[4] == "-" and exp[7] == "-"

    def test_invalid_symbol_returns_empty(self):
        expiries = get_expiries("INVALIDXYZ123")
        assert expiries == []


@pytest.mark.live
class TestLiveGetOptionChain:
    @pytest.fixture
    def aapl_expiry(self):
        expiries = get_expiries("AAPL")
        assert len(expiries) > 0
        return expiries[0]

    def test_chain_structure(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        assert result["symbol"] == "AAPL"
        assert result["expiry"] == aapl_expiry
        assert "calls" in result
        assert "puts" in result
        assert len(result["calls"]) > 0
        assert len(result["puts"]) > 0

    def test_option_fields(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        call = result["calls"][0]
        for field in ["strike", "bid", "ask", "volume", "openInterest"]:
            assert field in call, f"Missing field: {field}"

    def test_has_underlying_price(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        assert result["underlying_price"] is not None
        assert result["underlying_price"] > 0

    def test_invalid_expiry(self):
        result = get_option_chain("AAPL", "2020-01-01")
        assert "error" in result

    def test_source_is_yfinance(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        assert result["source"] == "yfinance"

    def test_greeks_are_null_for_yfinance(self, aapl_expiry):
        """yfinance path should return null Greeks — schema consistent with Tradier."""
        result = get_option_chain("AAPL", aapl_expiry)
        if result["calls"]:
            c = result["calls"][0]
            assert c["delta"] is None
            assert c["gamma"] is None
            assert c["theta"] is None
            assert c["vega"] is None
