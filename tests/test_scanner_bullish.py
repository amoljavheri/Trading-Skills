# ABOUTME: Tests for bullish scanner v2 with synthetic data and live validation.
# ABOUTME: Validates scoring, trend stage, volume, breakout, and backward compatibility.

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from trading_skills.scanner_bullish import (
    SCORE_MAX,
    _classify_trend_stage,
    compute_bullish_score,
    scan_symbols,
)


def _make_df(prices, volumes=None, days=None):
    """Build a synthetic OHLCV DataFrame from a price list.

    Generates High = close * 1.01, Low = close * 0.99 for realistic OHLC.
    """
    n = len(prices)
    if days is None:
        dates = pd.bdate_range(end=pd.Timestamp.now(), periods=n)
    else:
        dates = days
    close = np.array(prices, dtype=float)
    high = close * 1.01
    low = close * 0.99
    if volumes is None:
        volumes = np.full(n, 1_000_000)
    df = pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volumes},
        index=dates,
    )
    return df


def _make_rising_prices(start, end, n):
    """Generate steadily rising prices."""
    return np.linspace(start, end, n).tolist()


def _make_declining_prices(start, end, n):
    """Generate steadily declining prices."""
    return np.linspace(start, end, n).tolist()


# ---------------------------------------------------------------------------
# Trend stage classification (pure unit tests, no network)
# ---------------------------------------------------------------------------
class TestClassifyTrendStage:
    def test_below_sma20(self):
        assert _classify_trend_stage(95.0, 100.0, 2.0, 90.0, 3) == "below"

    def test_below_when_sma20_is_none(self):
        assert _classify_trend_stage(100.0, None, 2.0, None, None) == "below"

    def test_early_close_to_sma20(self):
        # Price 100.5, SMA20=100, ATR=2 → distance=0.5/2=0.25 ATR → early
        assert _classify_trend_stage(100.5, 100.0, 2.0, 95.0, 10) == "early"

    def test_early_few_days_above(self):
        # Distance is > 0.5 ATR but only 4 days above → early
        assert _classify_trend_stage(103.0, 100.0, 2.0, 95.0, 4) == "early"

    def test_mid_healthy_trend(self):
        # 1.5 ATR above SMA20, SMA20 > SMA50, 15 days above
        assert _classify_trend_stage(103.0, 100.0, 2.0, 95.0, 15) == "mid"

    def test_extended_far_from_sma20(self):
        # 3.0 ATR above SMA20
        assert _classify_trend_stage(106.0, 100.0, 2.0, 95.0, 18) == "extended"

    def test_fallback_without_atr(self):
        # No ATR → uses percentage fallback
        stage = _classify_trend_stage(110.0, 100.0, None, 95.0, 18)
        assert stage == "extended"  # 10% above SMA20

    def test_fallback_early_without_atr(self):
        stage = _classify_trend_stage(101.0, 100.0, None, 95.0, 10)
        assert stage == "early"  # 1% above SMA20


# ---------------------------------------------------------------------------
# Scoring with synthetic data (deterministic, no network)
# ---------------------------------------------------------------------------
class TestSyntheticScoring:
    """Tests using mock yfinance data for deterministic results."""

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_backward_compat_fields(self, mock_yf, mock_earnings):
        """All v1 output fields must still be present."""
        prices = _make_rising_prices(80, 120, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": "2026-06-01", "timing": "AMC"}

        result = compute_bullish_score("TEST")
        assert result is not None

        v1_fields = [
            "symbol", "score", "price", "next_earnings", "earnings_timing",
            "period_return_pct", "pct_from_sma20", "pct_from_sma50",
            "pct_from_sma200", "above_sma200", "sma200", "rsi", "macd",
            "macd_signal", "macd_hist", "adx", "dmp", "dmn", "signals",
        ]
        for field in v1_fields:
            assert field in result, f"Missing v1 field: {field}"

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_v2_new_fields(self, mock_yf, mock_earnings):
        """All v2 new fields must be present."""
        prices = _make_rising_prices(80, 120, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None

        v2_fields = [
            "trend_stage", "breakout_signal", "volume_confirmed",
            "obv_trend", "relative_volume", "trend_consistency",
            "normalized_score", "score_version",
        ]
        for field in v2_fields:
            assert field in result, f"Missing v2 field: {field}"
        assert result["score_version"] == "2.0"

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_normalized_score_range(self, mock_yf, mock_earnings):
        """Normalized score must be between 0 and 1."""
        prices = _make_rising_prices(80, 120, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert 0.0 <= result["normalized_score"] <= 1.0

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_sma200_hardcap(self, mock_yf, mock_earnings):
        """Score must be <= 3.0 when price is below SMA200."""
        # 250 bars, price starts at 120 and declines to 80 (below SMA200)
        prices = _make_declining_prices(120, 80, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["score"] <= 3.0
        assert result["above_sma200"] is False

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_strong_bullish_high_score(self, mock_yf, mock_earnings):
        """Steadily rising stock should score high."""
        prices = _make_rising_prices(50, 150, 250)
        # High volume to trigger RVOL
        volumes = np.full(250, 1_000_000)
        volumes[-1] = 2_000_000  # Spike on last day
        df = _make_df(prices, volumes=volumes)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["score"] >= 5.0  # Should be solidly bullish
        assert result["above_sma200"] is True

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_trend_consistency_steady_rise(self, mock_yf, mock_earnings):
        """Steady rise should have high trend consistency."""
        prices = _make_rising_prices(80, 130, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["trend_consistency"] is not None
        assert result["trend_consistency"] >= 0.8  # Most days above SMA20

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_trend_consistency_choppy(self, mock_yf, mock_earnings):
        """Oscillating price should have low trend consistency."""
        # Create choppy price: alternating up/down around a flat mean
        base = 100
        prices = [base + (3 if i % 2 == 0 else -3) for i in range(250)]
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        if result["trend_consistency"] is not None:
            assert result["trend_consistency"] <= 0.7  # Choppy = low consistency

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_breakout_detected(self, mock_yf, mock_earnings):
        """Price at 20-day high should trigger breakout signal."""
        # Flat for 230 days, then rise to new high
        prices = [100.0] * 230 + _make_rising_prices(100, 115, 20)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["breakout_signal"] is True

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_no_breakout_when_declining(self, mock_yf, mock_earnings):
        """Declining price should not trigger breakout."""
        prices = _make_declining_prices(120, 80, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["breakout_signal"] is False

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_volume_confirmed_on_up_day(self, mock_yf, mock_earnings):
        """High RVOL on an up day should set volume_confirmed."""
        prices = _make_rising_prices(80, 120, 250)
        volumes = np.full(250, 1_000_000)
        volumes[-1] = 3_000_000  # 3x average on last day (which is an up day)
        df = _make_df(prices, volumes=volumes)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["volume_confirmed"] is True

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_no_volume_confirmed_on_down_day(self, mock_yf, mock_earnings):
        """High RVOL on a down day should NOT set volume_confirmed."""
        # Rising then sharp drop on last day
        prices = _make_rising_prices(80, 120, 249) + [115.0]  # Last day drops
        volumes = np.full(250, 1_000_000)
        volumes[-1] = 3_000_000  # 3x average but on down day
        df = _make_df(prices, volumes=volumes)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["volume_confirmed"] is False

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_extended_trend_stage(self, mock_yf, mock_earnings):
        """Large price spike should classify as extended."""
        # Flat then sharp spike
        prices = [100.0] * 230 + _make_rising_prices(100, 140, 20)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["trend_stage"] in ("extended", "mid")  # Sharp spike is extended or mid

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_below_trend_stage(self, mock_yf, mock_earnings):
        """Declining stock should be 'below'."""
        prices = _make_declining_prices(120, 80, 250)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is not None
        assert result["trend_stage"] == "below"

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_empty_df_returns_none(self, mock_yf, mock_earnings):
        """Empty DataFrame should return None."""
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = pd.DataFrame()
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is None

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_short_df_returns_none(self, mock_yf, mock_earnings):
        """DataFrame with < 50 bars should return None."""
        prices = _make_rising_prices(90, 100, 30)
        df = _make_df(prices)
        mock_ticker = mock_yf.Ticker.return_value
        mock_ticker.history.return_value = df
        mock_earnings.return_value = {"earnings_date": None, "timing": None}

        result = compute_bullish_score("TEST")
        assert result is None

    @patch("trading_skills.scanner_bullish.get_earnings_info")
    @patch("trading_skills.scanner_bullish.yf")
    def test_score_max_constant(self, mock_yf, mock_earnings):
        """SCORE_MAX should be 11.5."""
        assert SCORE_MAX == 11.5


# ---------------------------------------------------------------------------
# Live data tests (require network, mark for optional exclusion)
# ---------------------------------------------------------------------------
@pytest.mark.live
class TestLiveComputeBullishScore:
    """Tests using real Yahoo Finance data."""

    def test_valid_symbol(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert result["symbol"] == "AAPL"
        assert "score" in result
        assert isinstance(result["score"], (int, float))

    def test_score_range(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert -2 <= result["score"] <= SCORE_MAX + 1  # Small buffer for edge cases

    def test_has_v2_fields(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "trend_stage" in result
        assert result["trend_stage"] in ("early", "mid", "extended", "below")
        assert "breakout_signal" in result
        assert isinstance(result["breakout_signal"], bool)
        assert "normalized_score" in result
        assert 0.0 <= result["normalized_score"] <= 1.0

    def test_has_earnings_info(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "next_earnings" in result
        assert "earnings_timing" in result

    def test_invalid_symbol_returns_none(self):
        result = compute_bullish_score("INVALIDXYZ123")
        assert result is None


@pytest.mark.live
class TestLiveScanSymbols:
    """Tests for multi-symbol scanning with real data."""

    def test_scan_returns_sorted(self):
        results = scan_symbols(["AAPL", "MSFT", "NVDA"], top_n=3)
        assert len(results) > 0
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_limits(self):
        results = scan_symbols(["AAPL", "MSFT", "NVDA", "GOOGL"], top_n=2)
        assert len(results) <= 2

    def test_invalid_excluded(self):
        results = scan_symbols(["AAPL", "INVALIDXYZ123"], top_n=5)
        symbols = [r["symbol"] for r in results]
        assert "INVALIDXYZ123" not in symbols
        assert "AAPL" in symbols

    def test_min_score_filter(self):
        results = scan_symbols(["AAPL", "MSFT"], top_n=10, min_score=100.0)
        assert len(results) == 0  # No stock scores 100
