# ABOUTME: Tests for stock quote module using real Yahoo Finance data and mock Tradier data.
# ABOUTME: Validates price retrieval, field presence, and error handling.


from trading_skills.quote import get_quote, parse_tradier_quote


class TestGetQuote:
    """Tests for get_quote with real Yahoo Finance data."""

    def test_valid_symbol(self):
        result = get_quote("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["price"] is not None
        assert isinstance(result["price"], (int, float))
        assert result["price"] > 0

    def test_expected_fields(self):
        result = get_quote("MSFT")
        for field in ["symbol", "name", "price", "volume", "market_cap"]:
            assert field in result, f"Missing field: {field}"

    def test_numeric_fields(self):
        result = get_quote("AAPL")
        assert isinstance(result["volume"], (int, type(None)))
        assert isinstance(result["market_cap"], (int, float, type(None)))

    def test_invalid_symbol(self):
        result = get_quote("INVALIDXYZ123")
        assert "error" in result

    def test_case_insensitive(self):
        result = get_quote("aapl")
        assert result["symbol"] == "AAPL"

    def test_source_field(self):
        result = get_quote("AAPL")
        assert result.get("source") == "yfinance"


class TestParseTradierQuote:
    """Tests for parse_tradier_quote with mock Tradier data."""

    _sample = {
        "quotes": {
            "quote": {
                "symbol": "AAPL",
                "description": "Apple Inc",
                "last": 189.50,
                "change": 2.30,
                "change_percentage": 1.23,
                "volume": 48000000,
                "average_volume": 55000000,
                "week_52_high": 199.62,
                "week_52_low": 124.17,
            }
        }
    }

    def test_valid_response(self):
        result = parse_tradier_quote(self._sample)
        assert result["symbol"] == "AAPL"
        assert result["name"] == "Apple Inc"
        assert result["price"] == 189.50
        assert result["change"] == 2.30
        assert result["change_percent"] == 1.23
        assert result["volume"] == 48000000
        assert result["avg_volume"] == 55000000
        assert result["high_52w"] == 199.62
        assert result["low_52w"] == 124.17
        assert result["source"] == "tradier"

    def test_tradier_only_fields_are_null(self):
        result = parse_tradier_quote(self._sample)
        assert result["market_cap"] is None
        assert result["pe_ratio"] is None
        assert result["dividend_yield"] is None
        assert result["beta"] is None

    def test_missing_optional_fields(self):
        minimal = {"quotes": {"quote": {"symbol": "XYZ", "last": 10.0}}}
        result = parse_tradier_quote(minimal)
        assert result["symbol"] == "XYZ"
        assert result["price"] == 10.0
        assert result["change"] is None
        assert result["high_52w"] is None

    def test_error_response(self):
        result = parse_tradier_quote({"quotes": {"quote": {"type": "error"}}})
        assert "error" in result

    def test_empty_input(self):
        result = parse_tradier_quote({})
        assert "error" in result

    def test_quote_as_array(self):
        """Tradier returns quote as a list when called via get_market_quotes."""
        data = {"quotes": {"quote": [self._sample["quotes"]["quote"]]}}
        result = parse_tradier_quote(data)
        assert result["symbol"] == "AAPL"
        assert result["price"] == 189.50
        assert result["source"] == "tradier"
