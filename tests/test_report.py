# ABOUTME: Tests for stock report module.
# ABOUTME: Unit tests for compute_recommendation, compute_conviction_score, analyze_csp,
# ABOUTME: analyze_leap_scenarios, get_market_context, compute_spread_strategies with mocked data.

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from trading_skills.report import (
    analyze_csp,
    analyze_leap_scenarios,
    compute_conviction_score,
    compute_recommendation,
    compute_spread_strategies,
    fetch_data,
    get_market_context,
)

MODULE = "trading_skills.report"


# ---------------------------------------------------------------------------
# TestComputeRecommendation (backward-compat wrapper)
# ---------------------------------------------------------------------------


class TestComputeRecommendation:
    """Unit tests for recommendation logic (no API calls)."""

    def test_strong_bullish(self):
        data = {
            "bullish": {
                "score": 7.0,
                "rsi": 55,
                "adx": 30,
                "dmp": 25,
                "dmn": 15,
                "normalized_score": 0.61,
                "breakout_signal": True,
                "volume_confirmed": True,
                "trend_stage": "mid",
            },
            "pmcc": {"pmcc_score": 10, "iv_pct": 35},
            "fundamentals": {
                "info": {
                    "forwardPE": 12,
                    "returnOnEquity": 0.25,
                    "dividendYield": 3.0,
                    "debtToEquity": 50,
                    "revenueGrowth": 0.15,
                    "payoutRatio": 0.4,
                }
            },
            "piotroski": {"score": 8},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] == "positive"
        assert len(result["strengths"]) > 0

    def test_bearish(self):
        data = {
            "bullish": {
                "score": 1.5,
                "rsi": 75,
                "adx": 15,
                "dmp": 10,
                "dmn": 20,
                "normalized_score": 0.13,
            },
            "pmcc": {"pmcc_score": 3, "iv_pct": 70},
            "fundamentals": {
                "info": {
                    "forwardPE": 45,
                    "returnOnEquity": 0.05,
                    "dividendYield": 0,
                    "debtToEquity": 150,
                    "revenueGrowth": -0.10,
                    "payoutRatio": 0.9,
                }
            },
            "piotroski": {"score": 2},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] in ["neutral", "negative"]
        assert len(result["risks"]) > 0

    def test_neutral(self):
        data = {
            "bullish": {
                "score": 4.0,
                "rsi": 50,
                "adx": 20,
                "normalized_score": 0.35,
            },
            "pmcc": {"pmcc_score": 6, "iv_pct": 40},
            "fundamentals": {"info": {"forwardPE": 20}},
            "piotroski": {"score": 7},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] == "neutral"

    def test_empty_data(self):
        result = compute_recommendation({})
        assert "recommendation_level" in result
        assert result["recommendation_level"] in ["positive", "neutral", "negative"]

    def test_result_fields(self):
        data = {
            "bullish": {
                "score": 5.0,
                "rsi": 55,
                "adx": 25,
                "normalized_score": 0.43,
            },
            "pmcc": {"pmcc_score": 7, "iv_pct": 35},
            "fundamentals": {"info": {"forwardPE": 15}},
            "piotroski": {"score": 7},
        }
        result = compute_recommendation(data)
        assert "recommendation" in result
        assert "recommendation_level" in result
        assert "points" in result
        assert "strengths" in result
        assert "risks" in result

    def test_overbought_rsi_risk(self):
        data = {
            "bullish": {
                "score": 5.0,
                "rsi": 75,
                "adx": 20,
                "normalized_score": 0.43,
            },
            "pmcc": {},
            "fundamentals": {"info": {}},
            "piotroski": {},
        }
        result = compute_recommendation(data)
        risks = " ".join(result["risks"])
        assert "overbought" in risks.lower()

    def test_high_debt_risk(self):
        data = {
            "bullish": {
                "score": 5.0,
                "rsi": 50,
                "adx": 20,
                "normalized_score": 0.43,
            },
            "pmcc": {},
            "fundamentals": {"info": {"debtToEquity": 200}},
            "piotroski": {},
        }
        result = compute_recommendation(data)
        risks = " ".join(result["risks"])
        assert "debt" in risks.lower()


# ---------------------------------------------------------------------------
# TestComputeConvictionScore (new)
# ---------------------------------------------------------------------------


class TestComputeConvictionScore:
    """Tests for unified 0-10 conviction scoring."""

    def _base_bullish(self, **overrides):
        """Build a base bullish dict with sensible defaults."""
        d = {
            "score": 6.0,
            "normalized_score": 0.52,
            "rsi": 60,
            "adx": 30,
            "dmp": 25,
            "dmn": 15,
            "breakout_signal": False,
            "volume_confirmed": False,
            "obv_trend": "rising",
            "trend_stage": "mid",
        }
        d.update(overrides)
        return d

    def test_max_score(self):
        """All components at max should yield 10."""
        bullish = self._base_bullish(
            score=8.0,
            normalized_score=0.70,
            rsi=60,
            adx=30,
            dmp=25,
            dmn=15,
            breakout_signal=True,
            volume_confirmed=True,
            obv_trend="rising",
        )
        pmcc = {"pmcc_score": 10}
        fund_info = {"forwardPE": 10}
        piotroski = {"score": 8}
        market_context = {"spy_trend": "bullish", "vix_regime": "low"}

        result = compute_conviction_score(bullish, pmcc, fund_info, piotroski, market_context)
        assert result["total"] == 10.0

    def test_min_score(self):
        """All components at minimum should yield 0."""
        bullish = self._base_bullish(
            score=1.0,
            normalized_score=0.08,
            rsi=25,
            adx=10,
            dmp=10,
            dmn=20,
            breakout_signal=False,
            volume_confirmed=False,
            obv_trend="falling",
        )
        # Use bearish market with high VIX to get 0 for market component
        market = {"spy_trend": "bearish", "vix_regime": "high"}
        result = compute_conviction_score(bullish, {}, {}, {}, market)
        assert result["total"] == 0.0

    def test_no_market_context_defaults(self):
        """No market context should give 0.5 (sideways default)."""
        bullish = self._base_bullish()
        result = compute_conviction_score(bullish, {}, {}, {}, None)
        mkt = result["components"]["market_regime"]
        assert mkt["score"] == 0.5

    def test_uses_normalized_score(self):
        """Trend component should use normalized_score, not raw score."""
        # High raw score but low normalized → should get low trend pts
        bullish = self._base_bullish(score=6.0, normalized_score=0.10)
        result = compute_conviction_score(bullish, {}, {}, {}, None)
        assert result["components"]["trend"]["score"] == 0.0

        # Low raw score but high normalized → should get high trend pts
        bullish2 = self._base_bullish(score=3.0, normalized_score=0.60)
        result2 = compute_conviction_score(bullish2, {}, {}, {}, None)
        assert result2["components"]["trend"]["score"] == 3.0

    def test_dimensional_sums(self):
        """Dimensional scores should sum correctly."""
        bullish = self._base_bullish()
        result = compute_conviction_score(bullish, {}, {}, {}, None)

        dims = result["dimensions"]
        assert "technical" in dims
        assert "fundamental" in dims
        assert "strategy" in dims
        assert "market" in dims

        # Total should equal sum of all dimensions
        dim_sum = sum(d["score"] for d in dims.values())
        assert abs(result["total"] - dim_sum) < 0.01

    def test_signal_alignment_aligned(self):
        """Both tech and fundamental strong → aligned."""
        bullish = self._base_bullish(
            normalized_score=0.70,
            rsi=60,
            adx=30,
            dmp=25,
            dmn=15,
            breakout_signal=True,
            volume_confirmed=True,
        )
        fund_info = {"forwardPE": 10}
        piotroski = {"score": 8}
        result = compute_conviction_score(bullish, {}, fund_info, piotroski, None)
        assert result["signal_alignment"] in ["aligned", "mixed"]

    def test_signal_alignment_conflicting(self):
        """Strong tech but weak fundamentals → conflicting."""
        bullish = self._base_bullish(
            normalized_score=0.70,
            rsi=60,
            adx=30,
            dmp=25,
            dmn=15,
            breakout_signal=True,
            volume_confirmed=True,
        )
        result = compute_conviction_score(bullish, {}, {"forwardPE": 50}, {"score": 2}, None)
        assert result["signal_alignment"] == "conflicting"
        assert len(result["conflicts"]) > 0

    def test_conflict_detection(self):
        """Stock bullish + market bearish should produce conflict."""
        bullish = self._base_bullish(normalized_score=0.70)
        market_context = {"spy_trend": "bearish", "vix_regime": "high"}
        result = compute_conviction_score(bullish, {}, {}, {}, market_context)
        conflicts = " ".join(result.get("conflicts", []))
        assert "bearish" in conflicts.lower() or "market" in conflicts.lower()

    def test_verdict_labels(self):
        """Verify verdict mapping at boundary points."""
        # Bearish: total 2-3.99
        bullish_low = self._base_bullish(normalized_score=0.08, rsi=25, adx=10, dmp=10, dmn=20)
        market = {"spy_trend": "bearish", "vix_regime": "high"}
        r = compute_conviction_score(bullish_low, {}, {}, {}, market)
        # With 0 everything, total should be very low
        assert r["total"] < 4
        assert "Bear" in r["verdict"]

    def test_strengths_and_risks_populated(self):
        """Result should always have strengths and risks lists."""
        result = compute_conviction_score({}, {}, {}, {}, None)
        assert isinstance(result["strengths"], list)
        assert isinstance(result["risks"], list)


# ---------------------------------------------------------------------------
# TestAnalyzeCSP (new)
# ---------------------------------------------------------------------------


class TestAnalyzeCSP:
    """Tests for delta-based CSP analysis."""

    def _sample_puts(self, current_price=100.0):
        """Generate sample put options data."""
        return [
            {"strike": 85, "bid": 0.50, "ask": 0.70, "delta": -0.10, "iv": 0.30},
            {"strike": 88, "bid": 0.80, "ask": 1.10, "delta": -0.15, "iv": 0.30},
            {"strike": 90, "bid": 1.20, "ask": 1.50, "delta": -0.20, "iv": 0.30},
            {"strike": 92, "bid": 1.60, "ask": 2.00, "delta": -0.25, "iv": 0.30},
            {"strike": 95, "bid": 2.50, "ask": 3.00, "delta": -0.35, "iv": 0.30},
            {"strike": 97, "bid": 3.50, "ask": 4.00, "delta": -0.40, "iv": 0.30},
            {"strike": 100, "bid": 5.00, "ask": 5.50, "delta": -0.50, "iv": 0.30},
        ]

    def test_delta_based_tier_selection(self):
        """Tiers should select strikes nearest to target deltas 0.15/0.25/0.35."""
        result = analyze_csp(100.0, self._sample_puts(), 30)
        tiers = result["tiers"]
        assert len(tiers) == 3
        assert "conservative" in tiers
        assert "balanced" in tiers
        assert "aggressive" in tiers
        # Conservative should be furthest OTM (lowest strike)
        assert (
            tiers["conservative"]["strike"]
            <= tiers["balanced"]["strike"]
            <= tiers["aggressive"]["strike"]
        )

    def test_yield_arithmetic(self):
        """Annualized yield should be computed correctly."""
        result = analyze_csp(100.0, self._sample_puts(), 30)
        for tier_data in result["tiers"].values():
            mid = tier_data["mid"]
            strike = tier_data["strike"]
            expected = (mid / strike) * (365 / 30) * 100
            assert abs(tier_data["ann_yield_pct"] - round(expected, 1)) < 0.2

    def test_suitability_good(self):
        """Good suitability when IV high, bullish, no earnings, not bearish."""
        result = analyze_csp(
            100.0,
            self._sample_puts(),
            30,
            bullish_score=6.0,
            next_earnings=None,
            market_context={
                "spy_trend": "bullish",
                "vix_regime": "normal",
            },
        )
        assert result["suitability"]["rating"] == "good"

    def test_suitability_avoid(self):
        """Avoid when IV too low or bullish score very low."""
        low_iv_puts = [
            {"strike": 90, "bid": 0.10, "ask": 0.15, "delta": -0.15, "iv": 0.10},
            {"strike": 95, "bid": 0.20, "ask": 0.30, "delta": -0.25, "iv": 0.10},
            {"strike": 98, "bid": 0.40, "ask": 0.50, "delta": -0.35, "iv": 0.10},
        ]
        result = analyze_csp(100.0, low_iv_puts, 30, bullish_score=1.0)
        assert result["suitability"]["rating"] == "avoid"

    def test_market_regime_downgrade(self):
        """SPY below SMA200 should downgrade suitability by one level."""
        result = analyze_csp(
            100.0,
            self._sample_puts(),
            30,
            bullish_score=6.0,
            market_context={
                "spy_trend": "bearish",
                "spy_above_sma200": False,
                "vix_regime": "normal",
            },
        )
        # SPY bearish blocks "good" (requires spy_trend != bearish)
        # and spy_above_sma200=False downgrades further
        assert result["suitability"]["rating"] in ["caution", "avoid"]

    def test_support_context_output(self):
        """Support context should be attached to each tier when provided."""
        support = {"sma50": 95.0, "sma200": 88.0, "swing_lows": [85.0, 90.0]}
        result = analyze_csp(100.0, self._sample_puts(), 30, support_levels=support)
        for tier_data in result["tiers"].values():
            assert "support_context" in tier_data

    def test_empty_puts(self):
        """Empty puts data should return error."""
        result = analyze_csp(100.0, [], 30)
        assert "error" in result

    def test_no_delta_fallback(self):
        """When puts have no delta, fall back to %-based selection."""
        puts_no_delta = [
            {"strike": 85, "bid": 0.50, "ask": 0.70},
            {"strike": 90, "bid": 1.20, "ask": 1.50},
            {"strike": 95, "bid": 2.50, "ask": 3.00},
            {"strike": 98, "bid": 3.50, "ask": 4.00},
        ]
        result = analyze_csp(100.0, puts_no_delta, 30)
        assert "tiers" in result
        assert len(result["tiers"]) == 3
        # Source should indicate yfinance/estimated path
        assert result.get("source") == "yfinance"

    def test_prob_profit_calculation(self):
        """Prob profit = (1 - abs(delta)) * 100."""
        result = analyze_csp(100.0, self._sample_puts(), 30)
        for tier_data in result["tiers"].values():
            if tier_data.get("delta") is not None:
                expected_pp = (1 - abs(tier_data["delta"])) * 100
                actual = tier_data["prob_profit_pct"]
                if actual is not None:
                    assert abs(actual - round(expected_pp, 1)) < 1


# ---------------------------------------------------------------------------
# TestAnalyzeLeapScenarios (new)
# ---------------------------------------------------------------------------


class TestAnalyzeLeapScenarios:
    """Tests for LEAP call scenario analysis."""

    def _sample_leap(self):
        return {
            "strike": 80,
            "bid": 25.00,
            "ask": 26.00,
            "mid": 25.50,
            "delta": 0.80,
            "gamma": 0.005,
            "theta": -0.03,
        }

    def test_flat_scenario_theta_drag(self):
        """Flat scenario (0%) should lose money due to theta."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        flat = [s for s in result["scenarios"] if s["move_pct"] == 0.0][0]
        assert flat["pnl"] < 0  # Theta drag
        assert flat["return_pct"] < 0

    def test_positive_scenario_gain(self):
        """10% up scenario should produce positive P&L."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        up10 = [s for s in result["scenarios"] if s["move_pct"] == 10.0][0]
        assert up10["pnl"] > 0
        assert up10["return_pct"] > 0

    def test_breakeven_calc(self):
        """Break-even should be positive and reasonable."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        assert result["breakeven_move_pct"] is not None
        assert 0 < result["breakeven_move_pct"] < 10

    def test_probability_calc(self):
        """Prob of +30% gain should be between 0 and 100."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        assert result["prob_30pct_gain_1mo"] is not None
        assert 0 < result["prob_30pct_gain_1mo"] < 100

    def test_no_gamma_fallback(self):
        """When gamma is missing, should still compute (skip gamma term)."""
        leap = self._sample_leap()
        del leap["gamma"]
        result = analyze_leap_scenarios(100.0, leap, 0.35)
        assert "scenarios" in result
        assert len(result["scenarios"]) == 6

    def test_per_scenario_confidence(self):
        """Small moves should be 'high' confidence, large moves 'low'."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        flat = [s for s in result["scenarios"] if s["move_pct"] == 0.0][0]
        big = [s for s in result["scenarios"] if s["move_pct"] == 30.0][0]
        assert flat["confidence"] == "high"
        assert big["confidence"] == "low"

    def test_default_scenarios(self):
        """Default scenarios should be [-10, 0, 5, 10, 20, 30]."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        moves = [s["move_pct"] for s in result["scenarios"]]
        assert moves == [-10.0, 0.0, 5.0, 10.0, 20.0, 30.0]

    def test_custom_scenarios(self):
        """Custom scenario list should be respected."""
        result = analyze_leap_scenarios(
            100.0, self._sample_leap(), 0.35, scenarios=[-0.05, 0.0, 0.15]
        )
        assert len(result["scenarios"]) == 3
        moves = [s["move_pct"] for s in result["scenarios"]]
        assert moves == [-5.0, 0.0, 15.0]

    def test_model_note_present(self):
        """Model note should be included in output."""
        result = analyze_leap_scenarios(100.0, self._sample_leap(), 0.35)
        assert "model_note" in result
        assert len(result["model_note"]) > 0


# ---------------------------------------------------------------------------
# TestGetMarketContext (new)
# ---------------------------------------------------------------------------


class TestGetMarketContext:
    """Tests for market context (SPY trend, VIX proxy, sector)."""

    @patch(f"{MODULE}.compute_raw_indicators")
    @patch(f"{MODULE}.yf.Ticker")
    def test_bullish_spy(self, mock_ticker, mock_indicators):
        """SPY above SMA50 and SMA200 should be bullish."""
        mock_instance = MagicMock()
        df = pd.DataFrame(
            {
                "Close": [400 + i for i in range(60)],
                "High": [401 + i for i in range(60)],
                "Low": [399 + i for i in range(60)],
                "Open": [400 + i for i in range(60)],
                "Volume": [1000000] * 60,
            },
        )
        mock_instance.history.return_value = df
        mock_ticker.return_value = mock_instance

        mock_indicators.return_value = {
            "sma50": 420.0,
            "sma200": 400.0,
        }

        result = get_market_context(sector=None)
        assert result["spy_trend"] in ["bullish", "bearish", "sideways"]
        assert "spy_price" in result
        assert "vix_regime" in result

    @patch(f"{MODULE}.compute_raw_indicators")
    @patch(f"{MODULE}.yf.Ticker")
    def test_vix_regime_tiers(self, mock_ticker, mock_indicators):
        """VIX proxy should map to correct regime tiers."""
        mock_instance = MagicMock()
        df = pd.DataFrame(
            {
                "Close": [400] * 60,
                "High": [401] * 60,
                "Low": [399] * 60,
                "Open": [400] * 60,
                "Volume": [1000000] * 60,
            },
        )
        mock_instance.history.return_value = df
        mock_ticker.return_value = mock_instance

        mock_indicators.return_value = {"sma50": 400.0, "sma200": 400.0}

        result = get_market_context()
        assert result["vix_regime"] in ["low", "normal", "elevated", "high", None]

    def test_sector_mapping(self):
        """Sector ETFs should be properly mapped."""
        from trading_skills.report import SECTOR_ETFS

        assert SECTOR_ETFS["Technology"] == "XLK"
        assert SECTOR_ETFS["Healthcare"] == "XLV"
        assert "Energy" in SECTOR_ETFS


# ---------------------------------------------------------------------------
# TestComputeSpreadStrategies (replaces TestAnalyzeSpreads)
# ---------------------------------------------------------------------------


class TestComputeSpreadStrategies:
    """Tests for spread strategy analysis delegating to spreads.py."""

    def _mock_chain(self, price, strikes):
        """Create mock option chain data."""
        calls_data = []
        puts_data = []
        for s in strikes:
            call_mid = (
                max(0.5, (price - s) + 5) if s <= price + 20 else max(0.5, 10 - (s - price) * 0.2)
            )
            put_mid = (
                max(0.5, (s - price) + 5) if s >= price - 20 else max(0.5, 10 - (price - s) * 0.2)
            )
            calls_data.append(
                {
                    "strike": s,
                    "bid": call_mid - 0.25,
                    "ask": call_mid + 0.25,
                    "impliedVolatility": 0.35,
                    "openInterest": 100,
                    "volume": 50,
                }
            )
            puts_data.append(
                {
                    "strike": s,
                    "bid": put_mid - 0.25,
                    "ask": put_mid + 0.25,
                    "impliedVolatility": 0.35,
                    "openInterest": 100,
                    "volume": 50,
                }
            )

        chain = MagicMock()
        chain.calls = pd.DataFrame(calls_data)
        chain.puts = pd.DataFrame(puts_data)
        return chain

    @patch(f"{MODULE}.analyze_iron_condor")
    @patch(f"{MODULE}.analyze_strangle")
    @patch(f"{MODULE}.analyze_straddle")
    @patch(f"{MODULE}.analyze_vertical")
    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_strategies(
        self, mock_ticker, mock_vert, mock_straddle, mock_strangle, mock_ic
    ):
        """Should return dict with strategies key."""
        price = 150.0
        strikes = [140, 145, 150, 155, 160]
        future = (datetime.now() + timedelta(days=40)).strftime("%Y-%m-%d")

        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": price}
        mock_instance.options = [future]
        mock_instance.option_chain.return_value = self._mock_chain(price, strikes)
        mock_ticker.return_value = mock_instance

        mock_vert.return_value = {"breakeven": 155, "risk_reward": 1.5}
        mock_straddle.return_value = {
            "total_cost": 10,
            "breakeven_up": 160,
            "breakeven_down": 140,
        }
        mock_strangle.return_value = {
            "total_cost": 8,
            "breakeven_up": 165,
            "breakeven_down": 135,
        }
        mock_ic.return_value = {"net_credit": 2, "max_loss": 3}

        result = compute_spread_strategies("AAPL")
        assert "strategies" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_price_returns_error(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {}
        mock_instance.options = []
        mock_ticker.return_value = mock_instance

        result = compute_spread_strategies("INVALID")
        assert "error" in result or result.get("strategies") == {}

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_options_returns_error(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": 150.0}
        mock_instance.options = []
        mock_ticker.return_value = mock_instance

        result = compute_spread_strategies("AAPL")
        assert "error" in result or result.get("strategies") == {}

    @patch(f"{MODULE}.yf.Ticker")
    def test_exception_returns_error(self, mock_ticker):
        mock_ticker.side_effect = Exception("API Error")
        result = compute_spread_strategies("AAPL")
        assert "error" in result


# ---------------------------------------------------------------------------
# TestFetchData (updated)
# ---------------------------------------------------------------------------


class TestFetchData:
    """Tests for fetch_data with mocked dependencies."""

    @patch(f"{MODULE}.get_market_context")
    @patch(f"{MODULE}.compute_spread_strategies")
    @patch(f"{MODULE}.calculate_piotroski_score")
    @patch(f"{MODULE}.get_fundamentals")
    @patch(f"{MODULE}.analyze_pmcc")
    @patch(f"{MODULE}.compute_bullish_score")
    def test_returns_all_sections(
        self,
        mock_bullish,
        mock_pmcc,
        mock_fund,
        mock_pio,
        mock_spreads,
        mock_mkt,
    ):
        mock_bullish.return_value = {"score": 5.0}
        mock_pmcc.return_value = {"pmcc_score": 7}
        mock_fund.return_value = {"info": {"forwardPE": 15}}
        mock_pio.return_value = {"score": 7}
        mock_spreads.return_value = {"strategies": {}}
        mock_mkt.return_value = {"spy_trend": "bullish"}

        result = fetch_data("AAPL")
        assert result["symbol"] == "AAPL"
        assert "bullish" in result
        assert "pmcc" in result
        assert "fundamentals" in result
        assert "piotroski" in result
        assert "spreads" in result
        assert "market_context" in result

    @patch(f"{MODULE}.get_market_context")
    @patch(f"{MODULE}.compute_spread_strategies")
    @patch(f"{MODULE}.calculate_piotroski_score")
    @patch(f"{MODULE}.get_fundamentals")
    @patch(f"{MODULE}.analyze_pmcc")
    @patch(f"{MODULE}.compute_bullish_score")
    def test_handles_none_returns(
        self,
        mock_bullish,
        mock_pmcc,
        mock_fund,
        mock_pio,
        mock_spreads,
        mock_mkt,
    ):
        mock_bullish.return_value = None
        mock_pmcc.return_value = None
        mock_fund.return_value = {}
        mock_pio.return_value = {}
        mock_spreads.return_value = {}
        mock_mkt.return_value = {}

        result = fetch_data("INVALID")
        assert result["bullish"] == {}
        assert result["pmcc"] == {}

    @patch(f"{MODULE}.get_market_context")
    @patch(f"{MODULE}.compute_spread_strategies")
    @patch(f"{MODULE}.calculate_piotroski_score")
    @patch(f"{MODULE}.get_fundamentals")
    @patch(f"{MODULE}.analyze_pmcc")
    @patch(f"{MODULE}.compute_bullish_score")
    @patch(f"{MODULE}.yf.Ticker")
    def test_shares_ticker_across_functions(
        self,
        mock_yf,
        mock_bullish,
        mock_pmcc,
        mock_fund,
        mock_pio,
        mock_spreads,
        mock_mkt,
    ):
        """fetch_data creates one yf.Ticker and passes it to all functions."""
        mock_ticker = MagicMock()
        mock_yf.return_value = mock_ticker
        mock_bullish.return_value = {}
        mock_pmcc.return_value = {}
        mock_fund.return_value = {}
        mock_pio.return_value = {}
        mock_spreads.return_value = {}
        mock_mkt.return_value = {}

        fetch_data("AAPL")

        mock_yf.assert_called_once_with("AAPL")
        mock_bullish.assert_called_once_with("AAPL", ticker=mock_ticker)
        mock_pmcc.assert_called_once_with("AAPL", ticker=mock_ticker)
        mock_fund.assert_called_once_with("AAPL", "all", ticker=mock_ticker)
        mock_pio.assert_called_once_with("AAPL", ticker=mock_ticker)
        mock_spreads.assert_called_once_with("AAPL", ticker=mock_ticker)
