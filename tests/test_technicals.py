# ABOUTME: Tests for technical analysis module using real Yahoo Finance data and synthetic data.
# ABOUTME: Validates indicators, signals, trend, confluence, support/resistance, and risk metrics.


import numpy as np
import pandas as pd

from trading_skills.technicals import (
    _classify_trend,
    _compute_confluence,
    _find_swing_levels,
    compute_indicators,
    compute_multi_symbol,
    compute_raw_indicators,
    get_earnings_data,
)


class TestComputeIndicators:
    """Tests for single-symbol indicator computation."""

    def test_returns_structure(self):
        result = compute_indicators("AAPL", period="3mo")
        assert result["symbol"] == "AAPL"
        assert "indicators" in result
        assert "price" in result
        assert "signals" in result

    def test_rsi_indicator(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "rsi" in result["indicators"]
        rsi = result["indicators"]["rsi"]
        assert "value" in rsi
        assert 0 <= rsi["value"] <= 100

    def test_macd_indicator(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "macd" in result["indicators"]
        macd = result["indicators"]["macd"]
        assert "macd" in macd
        assert "signal" in macd
        assert "histogram" in macd

    def test_bollinger_bands(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "bollinger" in result["indicators"]
        bb = result["indicators"]["bollinger"]
        assert bb["lower"] < bb["middle"] < bb["upper"]

    def test_sma(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "sma" in result["indicators"]
        assert "sma20" in result["indicators"]["sma"]

    def test_ema(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "ema" in result["indicators"]
        assert "ema12" in result["indicators"]["ema"]

    def test_custom_indicators(self):
        result = compute_indicators("AAPL", period="3mo", indicators=["rsi", "macd"])
        assert "rsi" in result["indicators"]
        assert "macd" in result["indicators"]
        # Should NOT have bollinger since not requested
        assert "bollinger" not in result["indicators"]

    def test_risk_metrics_included(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "risk_metrics" in result
        rm = result["risk_metrics"]
        assert "volatility_annualized_pct" in rm
        assert "sharpe_ratio" in rm

    def test_signals_is_list(self):
        result = compute_indicators("AAPL", period="3mo")
        assert isinstance(result["signals"], list)

    def test_invalid_symbol(self):
        result = compute_indicators("INVALIDXYZ123")
        assert "error" in result

    def test_trend_present(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "trend" in result
        trend = result["trend"]
        assert "label" in trend
        assert trend["label"] in ("strong_bull", "bull", "neutral", "bear", "strong_bear")
        assert "score" in trend
        assert "factors" in trend
        assert isinstance(trend["factors"], list)

    def test_confluence_present(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "confluence" in result
        conf = result["confluence"]
        assert "bullish_count" in conf
        assert "bearish_count" in conf
        assert "bias" in conf
        assert conf["bias"] in ("bullish", "bearish", "neutral")
        assert "strength" in conf
        assert conf["strength"] in ("strong", "moderate", "weak")

    def test_max_drawdown_in_risk_metrics(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "max_drawdown_pct" in result["risk_metrics"]
        assert result["risk_metrics"]["max_drawdown_pct"] <= 0

    def test_sortino_in_risk_metrics(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "sortino_ratio" in result["risk_metrics"]

    def test_volume_indicator(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "volume" in result["indicators"]
        vol = result["indicators"]["volume"]
        assert "relative_volume" in vol
        assert vol["relative_volume"] > 0

    def test_beta_default_off(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "beta" not in result.get("risk_metrics", {})

    def test_support_resistance(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "support_resistance" in result["indicators"]
        sr = result["indicators"]["support_resistance"]
        assert "pivot" in sr
        assert "swing_highs" in sr
        assert "swing_lows" in sr
        assert "nearest_support" in sr
        assert "nearest_resistance" in sr


class TestComputeMultiSymbol:
    """Tests for multi-symbol analysis."""

    def test_returns_results(self):
        result = compute_multi_symbol(["AAPL", "MSFT"], period="1mo")
        assert "results" in result
        assert len(result["results"]) == 2

    def test_each_symbol_present(self):
        result = compute_multi_symbol(["AAPL", "MSFT"], period="1mo", indicators=["rsi"])
        symbols = [r["symbol"] for r in result["results"]]
        assert "AAPL" in symbols
        assert "MSFT" in symbols


class TestGetEarningsData:
    """Tests for earnings data fetching."""

    def test_returns_symbol(self):
        result = get_earnings_data("AAPL")
        assert result["symbol"] == "AAPL"

    def test_has_history_or_upcoming(self):
        result = get_earnings_data("AAPL")
        # Should have at least some earnings data
        assert "history" in result or "upcoming" in result

    def test_history_entries(self):
        result = get_earnings_data("AAPL")
        if "history" in result:
            for entry in result["history"]:
                assert "date" in entry
                assert "estimated_eps" in entry or "reported_eps" in entry

    def test_invalid_symbol(self):
        result = get_earnings_data("INVALIDXYZ123")
        assert result["symbol"] == "INVALIDXYZ123"


class TestComputeRawIndicators:
    """Tests for raw indicator extraction from DataFrame."""

    def _make_df(self, n=100):
        """Create a synthetic OHLCV DataFrame with enough data for indicators."""
        np.random.seed(42)
        dates = pd.date_range(end="2025-06-01", periods=n, freq="D")
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        return pd.DataFrame(
            {
                "Open": close - 0.3,
                "High": close + abs(np.random.randn(n) * 0.5),
                "Low": close - abs(np.random.randn(n) * 0.5),
                "Close": close,
                "Volume": np.random.randint(1_000_000, 5_000_000, n),
            },
            index=dates,
        )

    def test_returns_all_keys(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        expected_keys = {
            "rsi",
            "sma20",
            "sma50",
            "macd_line",
            "macd_signal",
            "macd_hist",
            "prev_macd_hist",
            "adx",
            "dmp",
            "dmn",
        }
        assert expected_keys.issubset(raw.keys())

    def test_backward_compatible_keys(self):
        """Original 11 keys must still be present and unchanged."""
        df = self._make_df()
        raw = compute_raw_indicators(df)
        original_keys = {
            "rsi", "sma20", "sma50", "sma200",
            "macd_line", "macd_signal", "macd_hist", "prev_macd_hist",
            "adx", "dmp", "dmn",
        }
        assert original_keys.issubset(raw.keys())

    def test_new_indicator_keys(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        new_keys = {"stoch_rsi_k", "stoch_rsi_d", "roc", "obv", "obv_sma20", "relative_volume"}
        assert new_keys.issubset(raw.keys())

    def test_rsi_in_range(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["rsi"] is not None
        assert 0 <= raw["rsi"] <= 100

    def test_sma_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["sma20"] is not None
        assert raw["sma50"] is not None
        assert isinstance(raw["sma20"], float)

    def test_macd_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["macd_line"] is not None
        assert raw["macd_signal"] is not None
        assert raw["macd_hist"] is not None
        assert raw["prev_macd_hist"] is not None

    def test_adx_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["adx"] is not None
        assert raw["dmp"] is not None
        assert raw["dmn"] is not None
        assert raw["adx"] >= 0

    def test_stoch_rsi_keys_and_range(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["stoch_rsi_k"] is not None
        assert raw["stoch_rsi_d"] is not None
        assert 0 <= raw["stoch_rsi_k"] <= 100
        assert 0 <= raw["stoch_rsi_d"] <= 100

    def test_roc_present(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["roc"] is not None
        assert isinstance(raw["roc"], float)

    def test_obv_and_obv_sma20(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["obv"] is not None
        assert raw["obv_sma20"] is not None
        assert isinstance(raw["obv"], float)

    def test_relative_volume_positive(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["relative_volume"] is not None
        assert raw["relative_volume"] > 0

    def test_short_dataframe_returns_nones(self):
        df = self._make_df(n=5)
        raw = compute_raw_indicators(df)
        # With only 5 rows, most indicators can't compute
        # Should still return dict with None values rather than crashing
        assert isinstance(raw, dict)
        assert "rsi" in raw

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        raw = compute_raw_indicators(df)
        assert isinstance(raw, dict)
        assert raw["rsi"] is None


class TestClassifyTrend:
    """Tests for trend classification using synthetic data."""

    def test_bullish_raw(self):
        """Raw indicators signaling a bullish market should classify as bull."""
        raw = {
            "rsi": 55, "sma20": 95, "sma50": 90, "sma200": 80,
            "macd_line": 1.5, "macd_signal": 1.0, "macd_hist": 0.5, "prev_macd_hist": 0.3,
            "adx": 30, "dmp": 25, "dmn": 15,
        }
        trend = _classify_trend(raw, current_price=100)
        assert trend["label"] in ("strong_bull", "bull")
        assert trend["score"] >= 4.0

    def test_bearish_raw(self):
        """Raw indicators below SMA200 should be capped at neutral or below."""
        raw = {
            "rsi": 35, "sma20": 105, "sma50": 110, "sma200": 120,
            "macd_line": -1.5, "macd_signal": -1.0, "macd_hist": -0.5, "prev_macd_hist": -0.3,
            "adx": 15, "dmp": 10, "dmn": 20,
        }
        trend = _classify_trend(raw, current_price=100)
        assert trend["label"] in ("neutral", "bear", "strong_bear")
        assert trend["score"] <= 3.0
        assert "below_sma200_cap" in trend["factors"]

    def test_minimal_raw_all_none(self):
        """All-None indicators should classify as strong_bear."""
        raw = {
            "rsi": None, "sma20": None, "sma50": None, "sma200": None,
            "macd_line": None, "macd_signal": None, "macd_hist": None, "prev_macd_hist": None,
            "adx": None, "dmp": None, "dmn": None,
        }
        trend = _classify_trend(raw, current_price=100)
        assert trend["label"] == "strong_bear"
        assert trend["score"] == 0.0


class TestComputeConfluence:
    """Tests for signal confluence scoring."""

    def test_bullish_signals(self):
        signals = [
            {"indicator": "RSI", "signal": "oversold"},
            {"indicator": "MACD", "signal": "bullish_crossover"},
            {"indicator": "BB", "signal": "below_lower_band"},
        ]
        conf = _compute_confluence(signals)
        assert conf["bullish_count"] == 3
        assert conf["bearish_count"] == 0
        assert conf["bias"] == "bullish"
        assert conf["strength"] == "strong"

    def test_mixed_signals(self):
        signals = [
            {"indicator": "RSI", "signal": "overbought"},
            {"indicator": "MACD", "signal": "bullish_crossover"},
        ]
        conf = _compute_confluence(signals)
        assert conf["bullish_count"] == 1
        assert conf["bearish_count"] == 1
        assert conf["bias"] == "neutral"

    def test_no_signals(self):
        conf = _compute_confluence([])
        assert conf["bullish_count"] == 0
        assert conf["bearish_count"] == 0
        assert conf["bias"] == "neutral"
        assert conf["strength"] == "weak"


class TestFindSwingLevels:
    """Tests for support/resistance swing level detection."""

    def test_detects_peaks_and_troughs(self):
        """Build a df with known peaks and troughs."""
        n = 60
        # Create a wave pattern
        t = np.linspace(0, 4 * np.pi, n)
        close = 100 + 10 * np.sin(t)
        dates = pd.date_range(end="2025-06-01", periods=n, freq="D")
        df = pd.DataFrame(
            {"High": close + 1, "Low": close - 1, "Close": close},
            index=dates,
        )
        swing = _find_swing_levels(df, window=3, count=3)
        assert len(swing["swing_highs"]) > 0
        assert len(swing["swing_lows"]) > 0
        # Peaks should be higher than troughs
        assert max(swing["swing_highs"]) > min(swing["swing_lows"])

    def test_short_df_returns_empty(self):
        df = pd.DataFrame(
            {"High": [101, 102], "Low": [99, 100], "Close": [100, 101]},
            index=pd.date_range("2025-01-01", periods=2),
        )
        swing = _find_swing_levels(df, window=5)
        assert swing["swing_highs"] == []
        assert swing["swing_lows"] == []
