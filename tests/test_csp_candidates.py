# ABOUTME: Unit tests for the deterministic CSP candidate engine.
# ABOUTME: All tests use synthetic data — no live API calls.

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from trading_skills.csp_candidates import (
    CSP_CONFIG,
    _build_notes,
    _build_risk_flags,
    _compute_csp_score,
    _compute_dte,
    _compute_yield_score,
    _days_until,
    _get_atm_iv,
    _select_strike,
    calculate_csp_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_put(
    strike: float,
    bid: float = 1.55,
    ask: float = 1.65,
    mid: float | None = None,
    oi: int = 1000,
    iv: float = 35.0,
) -> dict:
    if mid is None:
        mid = round((bid + ask) / 2, 2)
    return {
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "openInterest": oi,
        "impliedVolatility": iv,
        "volume": 200,
        "inTheMoney": False,
    }


def _future_expiry(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")


def _future_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")


THRESHOLDS = CSP_CONFIG["yield_score_thresholds"]
WEIGHTS = CSP_CONFIG["weights"]


# ---------------------------------------------------------------------------
# _compute_yield_score
# ---------------------------------------------------------------------------


class TestComputeYieldScore:
    def test_zero_yield(self):
        assert _compute_yield_score(0.0, THRESHOLDS) == 0.0

    def test_below_fair(self):
        # 5% → 0–50 linear → 5/10 * 50 = 25
        assert _compute_yield_score(5.0, THRESHOLDS) == pytest.approx(25.0)

    def test_at_fair_boundary(self):
        # 10% → 50
        assert _compute_yield_score(10.0, THRESHOLDS) == pytest.approx(50.0)

    def test_between_fair_and_good(self):
        # 12.5% midpoint between 10–15 → 50 + (2.5/5)*20 = 60
        assert _compute_yield_score(12.5, THRESHOLDS) == pytest.approx(60.0)

    def test_at_good_boundary(self):
        # 15% → 70
        assert _compute_yield_score(15.0, THRESHOLDS) == pytest.approx(70.0)

    def test_between_good_and_excellent(self):
        # 20% midpoint between 15–25 → 70 + (5/10)*30 = 85
        assert _compute_yield_score(20.0, THRESHOLDS) == pytest.approx(85.0)

    def test_at_excellent_boundary(self):
        # 25% → 100
        assert _compute_yield_score(25.0, THRESHOLDS) == pytest.approx(100.0)

    def test_above_excellent(self):
        # 40% → still 100 (capped)
        assert _compute_yield_score(40.0, THRESHOLDS) == pytest.approx(100.0)

    def test_smooth_no_jump_at_fair(self):
        """Scores just below and just above fair boundary should be close."""
        below = _compute_yield_score(9.99, THRESHOLDS)
        above = _compute_yield_score(10.01, THRESHOLDS)
        assert abs(above - below) < 0.5

    def test_smooth_no_jump_at_good(self):
        below = _compute_yield_score(14.99, THRESHOLDS)
        above = _compute_yield_score(15.01, THRESHOLDS)
        assert abs(above - below) < 0.5


# ---------------------------------------------------------------------------
# _compute_csp_score
# ---------------------------------------------------------------------------


class TestComputeCspScore:
    def test_formula(self):
        # 0.40*60 + 0.30*50 + 0.30*80 = 24 + 15 + 24 = 63.0
        score = _compute_csp_score(60.0, 50.0, 80.0, WEIGHTS)
        assert score == pytest.approx(63.0, abs=0.1)

    def test_all_zero(self):
        assert _compute_csp_score(0.0, 0.0, 0.0, WEIGHTS) == 0.0

    def test_all_hundred(self):
        assert _compute_csp_score(100.0, 100.0, 100.0, WEIGHTS) == 100.0

    def test_clamp_no_exceed_100(self):
        assert _compute_csp_score(100.0, 120.0, 110.0, WEIGHTS) == 100.0

    def test_clamp_no_below_zero(self):
        assert _compute_csp_score(-10.0, -5.0, 0.0, WEIGHTS) == 0.0


# ---------------------------------------------------------------------------
# IV normalization
# ---------------------------------------------------------------------------


class TestIvNormalization:
    def test_cap_60_maps_to_100(self):
        iv_cap = 60.0
        iv_score = min((60.0 / iv_cap) * 100, 100)
        assert iv_score == 100.0

    def test_half_cap_maps_to_50(self):
        iv_cap = 60.0
        iv_score = min((30.0 / iv_cap) * 100, 100)
        assert iv_score == pytest.approx(50.0)

    def test_above_cap_clamped(self):
        iv_cap = 60.0
        iv_score = min((80.0 / iv_cap) * 100, 100)
        assert iv_score == 100.0


# ---------------------------------------------------------------------------
# _select_strike
# ---------------------------------------------------------------------------


class TestSelectStrike:
    def setup_method(self):
        self.price = 100.0
        self.config = CSP_CONFIG

    def test_picks_highest_oi(self):
        """Two valid strikes — should return the one with higher OI."""
        puts = [
            _make_put(91.0, oi=2000),
            _make_put(93.0, oi=800),
        ]
        selected = _select_strike(puts, self.price, self.config)
        assert selected is not None
        assert selected["strike"] == 91.0

    def test_oi_tie_picks_higher_premium(self):
        """Equal OI — should return strike with higher mid premium."""
        puts = [
            _make_put(91.0, bid=1.15, ask=1.25, oi=1000),  # mid=1.20, spread ~8%
            _make_put(93.0, bid=1.75, ask=1.85, oi=1000),  # mid=1.80, spread ~6%
        ]
        selected = _select_strike(puts, self.price, self.config)
        assert selected is not None
        assert selected["strike"] == 93.0

    def test_filters_low_oi(self):
        puts = [_make_put(91.0, oi=100)]
        assert _select_strike(puts, self.price, self.config) is None

    def test_filters_low_bid(self):
        puts = [_make_put(91.0, bid=0.10, ask=0.20, oi=1000)]
        assert _select_strike(puts, self.price, self.config) is None

    def test_filters_wide_spread(self):
        # spread = (2.50 - 0.50) / 1.50 * 100 = 133% >> 10%
        puts = [_make_put(91.0, bid=0.50, ask=2.50, mid=1.50, oi=1000)]
        assert _select_strike(puts, self.price, self.config) is None

    def test_filters_outside_otm_window_too_close(self):
        # 5% OTM (strike=95) — outside [90, 93] window
        puts = [_make_put(95.0, oi=1000)]
        assert _select_strike(puts, self.price, self.config) is None

    def test_filters_outside_otm_window_too_far(self):
        # 15% OTM (strike=85) — below window floor
        puts = [_make_put(85.0, oi=1000)]
        assert _select_strike(puts, self.price, self.config) is None

    def test_valid_strike_at_window_edge(self):
        # 10% OTM is exactly on the boundary (otm_min=0.90)
        puts = [_make_put(90.0, oi=600)]
        selected = _select_strike(puts, self.price, self.config)
        assert selected is not None
        assert selected["strike"] == 90.0

    def test_empty_puts_returns_none(self):
        assert _select_strike([], self.price, self.config) is None


# ---------------------------------------------------------------------------
# _get_atm_iv
# ---------------------------------------------------------------------------


class TestGetAtmIv:
    def test_returns_closest_strike_iv(self):
        puts = [
            _make_put(90.0, iv=25.0),
            _make_put(95.0, iv=40.0),  # closest to price=96
            _make_put(100.0, iv=30.0),
        ]
        iv = _get_atm_iv(puts, 96.0)
        assert iv == pytest.approx(40.0)

    def test_returns_none_for_empty(self):
        assert _get_atm_iv([], 100.0) is None

    def test_returns_none_for_zero_iv(self):
        puts = [_make_put(95.0, iv=0.0)]
        assert _get_atm_iv(puts, 100.0) is None


# ---------------------------------------------------------------------------
# _compute_dte
# ---------------------------------------------------------------------------


class TestComputeDte:
    def test_future_date(self):
        expiry = _future_expiry(30)
        dte = _compute_dte(expiry)
        assert dte == 30

    def test_past_date_raises(self):
        past = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        with pytest.raises(ValueError):
            _compute_dte(past)

    def test_today_raises(self):
        today = date.today().strftime("%Y-%m-%d")
        with pytest.raises(ValueError):
            _compute_dte(today)


# ---------------------------------------------------------------------------
# _days_until
# ---------------------------------------------------------------------------


class TestDaysUntil:
    def test_future(self):
        d = _future_date(10)
        assert _days_until(d) == 10

    def test_none_input(self):
        assert _days_until(None) is None

    def test_invalid_string(self):
        assert _days_until("not-a-date") is None


# ---------------------------------------------------------------------------
# _build_notes and _build_risk_flags
# ---------------------------------------------------------------------------


class TestBuildNotes:
    def test_high_oi_note(self):
        notes = _build_notes(20.0, 35.0, 60.0, 3000, None, CSP_CONFIG)
        assert "High OI support" in notes

    def test_earnings_warning(self):
        notes = _build_notes(20.0, 35.0, 60.0, 1000, 10, CSP_CONFIG)
        assert any("Earnings in 10 days" in n for n in notes)

    def test_no_earnings_warning_if_far(self):
        notes = _build_notes(20.0, 35.0, 60.0, 1000, 30, CSP_CONFIG)
        assert not any("Earnings" in n for n in notes)

    def test_excellent_yield_note(self):
        notes = _build_notes(30.0, 35.0, 60.0, 1000, None, CSP_CONFIG)
        assert "Excellent yield" in notes

    def test_good_yield_note(self):
        notes = _build_notes(18.0, 35.0, 60.0, 1000, None, CSP_CONFIG)
        assert "Good yield" in notes

    def test_strong_bull_note(self):
        notes = _build_notes(20.0, 35.0, 75.0, 1000, None, CSP_CONFIG)
        assert "Strong bullish trend" in notes


class TestBuildRiskFlags:
    def test_high_iv_flag(self):
        flags = _build_risk_flags(65.0, 1.0, CSP_CONFIG)
        assert any("High IV" in f for f in flags)

    def test_high_beta_flag(self):
        flags = _build_risk_flags(30.0, 2.5, CSP_CONFIG)
        assert any("High beta" in f for f in flags)

    def test_no_flags_for_normal_stock(self):
        flags = _build_risk_flags(35.0, 1.2, CSP_CONFIG)
        assert flags == []

    def test_none_beta_no_flag(self):
        flags = _build_risk_flags(35.0, None, CSP_CONFIG)
        assert not any("beta" in f.lower() for f in flags)


# ---------------------------------------------------------------------------
# Full pipeline — mocked API calls
# ---------------------------------------------------------------------------


def _mock_quote(symbol: str) -> dict:
    prices = {"AMD": 102.5, "NVDA": 450.0, "LOWPRICE": 15.0}
    betas = {"AMD": 1.5, "NVDA": 1.8, "LOWPRICE": 0.9}
    if symbol not in prices:
        return {"error": "not found"}
    return {"symbol": symbol, "price": prices[symbol], "beta": betas[symbol]}


def _mock_chain(symbol: str, expiry: str) -> dict:
    price = {"AMD": 102.5, "NVDA": 450.0}.get(symbol, 100.0)
    puts = [
        _make_put(price * 0.91, bid=1.62, ask=1.72, oi=2500, iv=38.0),  # spread ~6%
        _make_put(price * 0.92, bid=1.32, ask=1.42, oi=800, iv=36.0),   # spread ~7%
    ]
    return {"symbol": symbol, "expiry": expiry, "underlying_price": price,
            "puts": puts, "calls": []}


def _mock_bull(symbol: str, *args, **kwargs):
    scores = {"AMD": {"normalized_score": 0.72, "next_earnings": None},
              "NVDA": {"normalized_score": 0.55, "next_earnings": None}}
    return scores.get(symbol)


class TestFullPipeline:
    @patch("trading_skills.csp_candidates.compute_bullish_score", side_effect=_mock_bull)
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_returns_sorted_by_score(self, mock_quote, mock_chain, mock_bull):
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD", "NVDA"], expiry)
        assert len(results) == 2
        assert results[0]["csp_score"] >= results[1]["csp_score"]

    @patch("trading_skills.csp_candidates.compute_bullish_score", side_effect=_mock_bull)
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_required_output_fields(self, mock_quote, mock_chain, mock_bull):
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD"], expiry)
        assert len(results) == 1
        r = results[0]
        for field in [
            "symbol", "price", "selected_strike", "dte", "premium",
            "capital_required", "yield_pct", "annualized_yield", "breakeven",
            "bull_score", "iv_percentile", "csp_score", "oi", "notes", "risk_flags",
        ]:
            assert field in r, f"Missing field: {field}"

    @patch("trading_skills.csp_candidates.compute_bullish_score", side_effect=_mock_bull)
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_low_price_symbol_excluded(self, mock_quote, mock_chain, mock_bull):
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["LOWPRICE"], expiry)
        assert len(results) == 0

    @patch("trading_skills.csp_candidates.compute_bullish_score", side_effect=_mock_bull)
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_score_range(self, mock_quote, mock_chain, mock_bull):
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD", "NVDA"], expiry)
        for r in results:
            assert 0.0 <= r["csp_score"] <= 100.0

    @patch("trading_skills.csp_candidates.compute_bullish_score", side_effect=_mock_bull)
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_math_consistency(self, mock_quote, mock_chain, mock_bull):
        """Verify breakeven and capital_required calculations."""
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD"], expiry)
        r = results[0]
        assert r["capital_required"] == pytest.approx(r["selected_strike"] * 100, abs=0.01)
        assert r["breakeven"] == pytest.approx(r["selected_strike"] - r["premium"], abs=0.01)
        assert r["annualized_yield"] == pytest.approx(
            r["yield_pct"] * (365 / r["dte"]), abs=0.1
        )


class TestEarningsFilter:
    @patch("trading_skills.csp_candidates.compute_bullish_score")
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_earnings_hard_filter(self, mock_quote, mock_chain, mock_bull):
        """Symbol with earnings in 3 days should be excluded."""
        mock_bull.return_value = {
            "normalized_score": 0.72,
            "next_earnings": _future_date(3),
        }
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD"], expiry)
        assert len(results) == 0

    @patch("trading_skills.csp_candidates.compute_bullish_score")
    @patch("trading_skills.csp_candidates.get_option_chain", side_effect=_mock_chain)
    @patch("trading_skills.csp_candidates.get_quote", side_effect=_mock_quote)
    def test_earnings_warning_note(self, mock_quote, mock_chain, mock_bull):
        """Symbol with earnings in 10 days should be included but have a warning note."""
        mock_bull.return_value = {
            "normalized_score": 0.72,
            "next_earnings": _future_date(10),
        }
        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["AMD"], expiry)
        assert len(results) == 1
        assert any("Earnings in 10 days" in n for n in results[0]["notes"])


class TestTieBreaker:
    @patch("trading_skills.csp_candidates.compute_bullish_score")
    @patch("trading_skills.csp_candidates.get_option_chain")
    @patch("trading_skills.csp_candidates.get_quote")
    def test_higher_oi_ranks_first_on_equal_score(
        self, mock_quote, mock_chain, mock_bull
    ):
        """When csp_scores are equal, higher OI should rank first."""
        price = 100.0

        def quote_side(symbol):
            return {"symbol": symbol, "price": price, "beta": 1.0}

        def chain_side(symbol, expiry):
            oi_map = {"SYM1": 3000, "SYM2": 800}
            puts = [_make_put(91.0, oi=oi_map[symbol], iv=35.0)]
            return {"symbol": symbol, "expiry": expiry, "underlying_price": price,
            "puts": puts, "calls": []}

        def bull_side(symbol, *args, **kwargs):
            return {"normalized_score": 0.60, "next_earnings": None}

        mock_quote.side_effect = quote_side
        mock_chain.side_effect = chain_side
        mock_bull.side_effect = bull_side

        expiry = _future_expiry(30)
        results = calculate_csp_candidates(["SYM1", "SYM2"], expiry)
        assert len(results) == 2
        assert results[0]["symbol"] == "SYM1"  # higher OI
        assert results[0]["oi"] > results[1]["oi"]
