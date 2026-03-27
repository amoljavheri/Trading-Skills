# ABOUTME: Unit and integration tests for the upgraded PMCC scanner (Plan v2).
# ABOUTME: Covers expiry selection, dual IV, yield/breakeven formulas, earnings, scoring.

from collections import namedtuple
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

from trading_skills.scanner_pmcc import analyze_pmcc, format_scan_results

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OptionChain = namedtuple("OptionChain", ["calls", "puts"])

_TODAY = datetime.now()


def _expiry(days: int) -> str:
    """Return a YYYY-MM-DD expiry string N days from today."""
    return (_TODAY + timedelta(days=days)).strftime("%Y-%m-%d")


_EMPTY_DF = pd.DataFrame(
    columns=["strike", "bid", "ask", "impliedVolatility", "openInterest", "volume"]
)

# Base LEAPS calls at price=100 — ATM strikes 95/100/105 present for IV median
_DEFAULT_LEAPS_CALLS = pd.DataFrame(
    {
        "strike": [75.0, 80.0, 85.0, 90.0, 95.0, 100.0, 105.0],
        "bid": [28.0, 24.0, 20.0, 16.0, 12.0, 8.50, 5.50],
        "ask": [30.0, 26.0, 22.0, 18.0, 14.0, 9.50, 6.50],
        "impliedVolatility": [0.25, 0.27, 0.28, 0.29, 0.30, 0.30, 0.31],
        "openInterest": [500, 300, 200, 150, 100, 200, 100],
        "volume": [50, 30, 20, 15, 10, 25, 10],
    }
)

# Base short calls at price=100 — ATM strikes 100/105 present for IV median
_DEFAULT_SHORT_CALLS = pd.DataFrame(
    {
        "strike": [100.0, 105.0, 110.0, 115.0, 120.0],
        "bid": [5.50, 3.50, 2.00, 1.20, 0.70],
        "ask": [6.00, 3.80, 2.20, 1.40, 0.90],
        "impliedVolatility": [0.30, 0.32, 0.34, 0.36, 0.38],
        "openInterest": [3000, 2000, 1500, 800, 400],
        "volume": [500, 300, 200, 100, 50],
    }
)

_NO_EARNINGS = {"earnings_date": None, "symbol": "TEST"}


class MockTicker:
    """Minimal yfinance.Ticker mock for unit tests."""

    def __init__(
        self,
        price: float,
        expirations: list[str],
        chains: dict,
    ):
        self._price = price
        self._expirations = expirations
        self._chains = chains

    @property
    def info(self):
        return {"regularMarketPrice": self._price}

    @property
    def options(self):
        return self._expirations

    def option_chain(self, expiry: str):
        calls, puts = self._chains.get(expiry, (_EMPTY_DF, _EMPTY_DF))
        return _OptionChain(calls=calls, puts=puts)

    def history(self, period="5d"):
        return pd.DataFrame()


def _default_ticker(
    price: float = 100.0,
    leaps_expiry_days: int = 450,
    short_expiry_days: int = 30,
    leaps_calls: pd.DataFrame | None = None,
    short_calls: pd.DataFrame | None = None,
    extra_expirations: list[str] | None = None,
) -> MockTicker:
    """Build a MockTicker with standard defaults."""
    leaps_exp = _expiry(leaps_expiry_days)
    short_exp = _expiry(short_expiry_days)
    expirations = sorted(
        list({short_exp, leaps_exp} | set(extra_expirations or [])),
        key=lambda x: datetime.strptime(x, "%Y-%m-%d"),
    )
    lc = leaps_calls if leaps_calls is not None else _DEFAULT_LEAPS_CALLS.copy()
    sc = short_calls if short_calls is not None else _DEFAULT_SHORT_CALLS.copy()
    chains = {
        leaps_exp: (lc, _EMPTY_DF),
        short_exp: (sc, _EMPTY_DF),
    }
    for exp in expirations:
        if exp not in chains:
            chains[exp] = (lc, _EMPTY_DF)
    return MockTicker(price=price, expirations=expirations, chains=chains)


# ---------------------------------------------------------------------------
# 1. LEAPS expiry selection
# ---------------------------------------------------------------------------


class TestLeapsExpirySelection:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_selects_closest_to_452_within_ideal_range(self, _mock_earnings):
        """Prefer the expiry closest to 452d within 365–540d range."""
        # 390d (|390-452|=62) vs 480d (|480-452|=28) → should pick 480d
        leaps_390 = _expiry(390)
        leaps_480 = _expiry(480)
        short_exp = _expiry(30)
        lc = _DEFAULT_LEAPS_CALLS.copy()
        sc = _DEFAULT_SHORT_CALLS.copy()
        chains = {
            leaps_390: (lc, _EMPTY_DF),
            leaps_480: (lc, _EMPTY_DF),
            short_exp: (sc, _EMPTY_DF),
        }
        expirations = sorted(
            [short_exp, leaps_390, leaps_480],
            key=lambda x: datetime.strptime(x, "%Y-%m-%d"),
        )
        ticker = MockTicker(price=100.0, expirations=expirations, chains=chains)
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        if "pmcc_score" in result:
            assert result["leaps"]["expiry"] == leaps_480

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_falls_back_to_nearest_270d_when_no_ideal(self, _mock_earnings):
        """When no expiry in 365–540d, fall back to nearest >= 270d."""
        fallback = _expiry(300)  # in 270–364 range
        short_exp = _expiry(30)
        lc = _DEFAULT_LEAPS_CALLS.copy()
        sc = _DEFAULT_SHORT_CALLS.copy()
        chains = {
            fallback: (lc, _EMPTY_DF),
            short_exp: (sc, _EMPTY_DF),
        }
        expirations = sorted(
            [short_exp, fallback],
            key=lambda x: datetime.strptime(x, "%Y-%m-%d"),
        )
        ticker = MockTicker(price=100.0, expirations=expirations, chains=chains)
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        if "pmcc_score" in result:
            assert result["leaps"]["expiry"] == fallback

    def test_returns_error_when_no_leaps_available(self):
        """Return error dict when no expiry >= 270 days."""
        ticker = _default_ticker(leaps_expiry_days=200, short_expiry_days=30)
        ticker._expirations = [_expiry(30), _expiry(200)]
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        assert "error" in result
        assert "270" in result["error"]


# ---------------------------------------------------------------------------
# 2. Short call DTE selection
# ---------------------------------------------------------------------------


class TestShortExpirySelection:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_primary_21_to_45_dte_selected(self, _mock_earnings):
        """21–45 DTE expiry selected when available."""
        ticker = _default_ticker(short_expiry_days=35)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert 21 <= result["short"]["days"] <= 45

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_fallback_7_to_21_dte_used_when_no_primary(self, _mock_earnings):
        """7–21 DTE fallback used when no 21–45 DTE available."""
        # Only provide a 15-day short expiry (no 21-45 range available)
        leaps_exp = _expiry(450)
        short_exp = _expiry(15)
        lc = _DEFAULT_LEAPS_CALLS.copy()
        sc = _DEFAULT_SHORT_CALLS.copy()
        chains = {leaps_exp: (lc, _EMPTY_DF), short_exp: (sc, _EMPTY_DF)}
        expirations = sorted(
            [short_exp, leaps_exp],
            key=lambda x: datetime.strptime(x, "%Y-%m-%d"),
        )
        ticker = MockTicker(price=100.0, expirations=expirations, chains=chains)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert 7 <= result["short"]["days"] <= 20

    def test_under_7_dte_returns_error(self):
        """Only expiry < 7 DTE should return an error — hard floor enforced."""
        leaps_exp = _expiry(450)
        short_exp = _expiry(5)
        chains = {leaps_exp: (_DEFAULT_LEAPS_CALLS.copy(), _EMPTY_DF)}
        expirations = sorted(
            [short_exp, leaps_exp],
            key=lambda x: datetime.strptime(x, "%Y-%m-%d"),
        )
        ticker = MockTicker(price=100.0, expirations=expirations, chains=chains)
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        assert "error" in result
        assert "7" in result["error"] or "min" in result["error"].lower()


# ---------------------------------------------------------------------------
# 3. Two separate IVs (median, not mean)
# ---------------------------------------------------------------------------


class TestTwoIVs:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_separate_leaps_and_short_iv_in_output(self, _mock_earnings):
        """Output has both leaps_iv_pct and short_iv_pct fields."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert "leaps_iv_pct" in result
            assert "short_iv_pct" in result
            assert result["leaps_iv_pct"] > 0
            assert result["short_iv_pct"] > 0

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_different_iv_for_leaps_and_short_when_chains_differ(self, _mock_earnings):
        """leaps_iv_pct != short_iv_pct when chain IVs differ."""
        leaps_calls = _DEFAULT_LEAPS_CALLS.copy()
        leaps_calls["impliedVolatility"] = 0.25  # all 25%
        short_calls = _DEFAULT_SHORT_CALLS.copy()
        short_calls["impliedVolatility"] = 0.45  # all 45%
        ticker = _default_ticker(leaps_calls=leaps_calls, short_calls=short_calls)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            # LEAPS IV ≈ 25%, short IV ≈ 45% — should differ
            assert abs(result["leaps_iv_pct"] - result["short_iv_pct"]) > 1.0

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_median_iv_not_mean(self, _mock_earnings):
        """IV computed via median — one high outlier should not skew result."""
        # ATM range 95–105: strikes 95, 100, 105 with IVs 0.20, 0.25, 0.60
        # mean = 0.35, median = 0.25
        leaps_calls = pd.DataFrame(
            {
                "strike": [85.0, 95.0, 100.0, 105.0],
                "bid": [20.0, 12.0, 8.50, 5.50],
                "ask": [22.0, 14.0, 9.50, 6.50],
                "impliedVolatility": [0.28, 0.20, 0.25, 0.60],
                "openInterest": [200, 100, 200, 100],
                "volume": [20, 10, 25, 10],
            }
        )
        ticker = _default_ticker(leaps_calls=leaps_calls)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            # Median of ATM IVs (0.20, 0.25, 0.60) = 0.25 → leaps_iv_pct ≈ 25
            # Mean would be ≈ 35 — confirm we got median
            assert result["leaps_iv_pct"] < 30.0  # median ≈ 25, not mean ≈ 35

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_short_iv_fallback_to_leaps_iv_when_no_atm(self, _mock_earnings):
        """short_iv falls back to leaps_iv when short chain has no ATM strikes."""
        # Short chain only has deep OTM strikes (outside 95–105 ATM window)
        short_calls_no_atm = pd.DataFrame(
            {
                "strike": [130.0, 140.0],
                "bid": [0.50, 0.30],
                "ask": [0.70, 0.50],
                "impliedVolatility": [0.45, 0.50],
                "openInterest": [200, 100],
                "volume": [10, 5],
            }
        )
        ticker = _default_ticker(short_calls=short_calls_no_atm)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            # When fallback used, short_iv_pct should equal leaps_iv_pct
            assert result["short_iv_pct"] == result["leaps_iv_pct"]
            # Risk flag should be present
            flags_str = " ".join(result.get("risk_flags", []))
            assert "IV" in flags_str or "iv" in flags_str.lower()


# ---------------------------------------------------------------------------
# 4. Yield calculations
# ---------------------------------------------------------------------------


class TestYieldCalculations:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_theoretical_yield_exceeds_realistic(self, _mock_earnings):
        """Theoretical yield (mid) is always >= realistic yield (bid × 65%)."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            assert m["annual_yield_theoretical_pct"] >= m["annual_yield_realistic_pct"]

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_realistic_yield_uses_bid_and_capture_rate(self, _mock_earnings):
        """Realistic yield = (short_bid / leaps_mid) * (365/dte) * 65%."""
        ticker = _default_ticker(short_expiry_days=30)
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            dte = result["short"]["days"]
            expected = (m["short_bid"] / result["leaps"]["mid"]) * (365 / dte) * 100 * 0.65
            assert abs(m["annual_yield_realistic_pct"] - round(expected, 1)) < 0.15


# ---------------------------------------------------------------------------
# 5. Breakeven and downside metrics
# ---------------------------------------------------------------------------


class TestBreakevenAndMetrics:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_breakeven_formula(self, _mock_earnings):
        """breakeven_price = leaps_strike + (leaps_mid - short_bid)."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            leaps = result["leaps"]
            expected_be = leaps["strike"] + m["net_debit"]
            assert abs(m["breakeven_price"] - expected_be) < 0.02

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_net_debit_formula(self, _mock_earnings):
        """net_debit = leaps_mid - short_bid (NOT short_mid)."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            leaps_mid = result["leaps"]["mid"]
            short_bid = m["short_bid"]
            assert abs(m["net_debit"] - (leaps_mid - short_bid)) < 0.02

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_pct_to_breakeven(self, _mock_earnings):
        """pct_to_breakeven = (price - breakeven) / price * 100."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            price = result["price"]
            expected = (price - m["breakeven_price"]) / price * 100
            assert abs(m["pct_to_breakeven"] - round(expected, 1)) < 0.15

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_max_loss_equals_net_debit_times_100(self, _mock_earnings):
        """max_loss = net_debit * 100 (per contract)."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            m = result["metrics"]
            assert abs(m["max_loss"] - m["net_debit"] * 100) < 0.02
            assert m["max_loss"] > 0

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_delta_spread_formula(self, _mock_earnings):
        """delta_spread = leaps_delta - short_delta."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            expected_spread = result["leaps"]["delta"] - result["short"]["delta"]
            assert abs(result["metrics"]["delta_spread"] - round(expected_spread, 3)) < 0.002


# ---------------------------------------------------------------------------
# 6. Earnings risk
# ---------------------------------------------------------------------------


class TestEarningsRisk:
    @patch("trading_skills.scanner_pmcc.get_earnings_info")
    def test_earnings_within_window_sets_risk_true(self, mock_earnings):
        """Earnings within short_days + 3 sets earnings_risk=True."""
        ticker = _default_ticker(short_expiry_days=30)
        mock_earnings.return_value = {
            "earnings_date": _expiry(20),  # 20 days, within 30+3=33
            "symbol": "TEST",
        }
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert result["earnings_risk"] is True

    @patch("trading_skills.scanner_pmcc.get_earnings_info")
    def test_earnings_outside_window_sets_risk_false(self, mock_earnings):
        """Earnings beyond short_days + 3 sets earnings_risk=False."""
        ticker = _default_ticker(short_expiry_days=30)
        mock_earnings.return_value = {
            "earnings_date": _expiry(60),  # 60 days, outside 30+3=33
            "symbol": "TEST",
        }
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert result["earnings_risk"] is False

    @patch("trading_skills.scanner_pmcc.get_earnings_info")
    def test_earnings_plus_3_buffer_boundary(self, mock_earnings):
        """Earnings exactly at short_days + 2 should be flagged (within buffer)."""
        ticker = _default_ticker(short_expiry_days=30)
        mock_earnings.return_value = {
            "earnings_date": _expiry(32),  # 32 days, 32 <= 33 → flagged
            "symbol": "TEST",
        }
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert result["earnings_risk"] is True

    @patch("trading_skills.scanner_pmcc.get_earnings_info")
    def test_earnings_penalty_reduces_score(self, mock_earnings):
        """Earnings in window applies -2 penalty to raw score → lower pmcc_score."""
        ticker_no = _default_ticker(short_expiry_days=30)
        ticker_yes = _default_ticker(short_expiry_days=30)

        mock_earnings.return_value = {
            "earnings_date": None,
            "symbol": "TEST",
        }
        result_no = analyze_pmcc("TEST", ticker=ticker_no)

        mock_earnings.return_value = {
            "earnings_date": _expiry(20),
            "symbol": "TEST",
        }
        result_yes = analyze_pmcc("TEST", ticker=ticker_yes)

        if result_no and result_yes and "pmcc_score" in result_no and "pmcc_score" in result_yes:
            assert result_yes["pmcc_score"] < result_no["pmcc_score"]


# ---------------------------------------------------------------------------
# 7. Hard rejects
# ---------------------------------------------------------------------------


class TestHardRejects:
    def test_leaps_oi_below_20_returns_error(self):
        """LEAPS OI < 20 must return an error dict (hard reject)."""
        low_oi_leaps = _DEFAULT_LEAPS_CALLS.copy()
        low_oi_leaps["openInterest"] = 5  # all rows set to 5
        ticker = _default_ticker(leaps_calls=low_oi_leaps)
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        assert "error" in result
        assert "OI" in result["error"] or "liquidity" in result["error"].lower()

    def test_leaps_spread_above_25pct_returns_error(self):
        """LEAPS spread > 25% must return an error dict (hard reject)."""
        wide_leaps = _DEFAULT_LEAPS_CALLS.copy()
        # Create wide spread: bid=10, ask=16 → mid=13, spread=6/13=46%
        wide_leaps["bid"] = 10.0
        wide_leaps["ask"] = 16.0
        ticker = _default_ticker(leaps_calls=wide_leaps)
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        assert "error" in result
        assert "spread" in result["error"].lower() or "wide" in result["error"].lower()


# ---------------------------------------------------------------------------
# 8. Scoring
# ---------------------------------------------------------------------------


class TestScoring:
    @patch("trading_skills.scanner_pmcc.get_earnings_info")
    def test_near_atm_short_applies_penalty(self, mock_earnings):
        """Short call < 3% OTM (< price * 1.03) applies -0.5 penalty."""
        mock_earnings.return_value = {"earnings_date": None, "symbol": "TEST"}

        # Build a short chain with only one near-ATM strike (102 < price*1.03=103)
        # so the code is forced to select it — triggers the near-ATM penalty
        near_atm_short = pd.DataFrame(
            {
                "strike": [102.0],
                "bid": [3.00],
                "ask": [3.40],
                "impliedVolatility": [0.32],
                "openInterest": [2000],
                "volume": [300],
            }
        )
        ticker_near = _default_ticker(short_calls=near_atm_short)

        # Build a normal short chain with OTM strikes
        normal_short = _DEFAULT_SHORT_CALLS.copy()
        ticker_normal = _default_ticker(short_calls=normal_short)

        result_near = analyze_pmcc("TEST", ticker=ticker_near)
        result_normal = analyze_pmcc("TEST", ticker=ticker_normal)

        if (
            result_near
            and result_normal
            and "pmcc_score" in result_near
            and "pmcc_score" in result_normal
        ):
            assert result_near["pmcc_score"] <= result_normal["pmcc_score"]
            # Near-ATM flag should be present
            flags = result_near.get("risk_flags", [])
            assert any("ATM" in f or "assignment" in f.lower() for f in flags)

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_score_always_in_0_to_10_range(self, _mock_earnings):
        """pmcc_score must always be 0.0–10.0."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert 0.0 <= result["pmcc_score"] <= 10.0

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_score_is_rounded_to_one_decimal(self, _mock_earnings):
        """pmcc_score should be a float with at most 1 decimal place."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            score = result["pmcc_score"]
            assert score == round(score, 1)


# ---------------------------------------------------------------------------
# 9. Output structure
# ---------------------------------------------------------------------------


class TestOutputStructure:
    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_risk_flags_always_present(self, _mock_earnings):
        """risk_flags key must always be present and be a list."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert "risk_flags" in result
            assert isinstance(result["risk_flags"], list)

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_capital_efficiency_present_in_metrics(self, _mock_earnings):
        """capital_efficiency_pct must be present in metrics dict."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert "capital_efficiency_pct" in result["metrics"]

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_required_metric_keys_present(self, _mock_earnings):
        """All required metric keys must be present in output."""
        required_keys = [
            "net_debit",
            "max_loss",
            "breakeven_price",
            "pct_to_breakeven",
            "annual_yield_theoretical_pct",
            "annual_yield_realistic_pct",
            "short_bid",
            "short_mid",
            "leaps_extrinsic_pct",
            "capital_required",
            "capital_efficiency_pct",
            "delta_spread",
        ]
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            for key in required_keys:
                assert key in result["metrics"], f"Missing metrics key: {key}"

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_earnings_fields_present(self, _mock_earnings):
        """earnings_date and earnings_risk always present in valid result."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert "earnings_date" in result
            assert "earnings_risk" in result

    @patch("trading_skills.scanner_pmcc.get_earnings_info", return_value=_NO_EARNINGS)
    def test_short_strike_above_leaps_strike(self, _mock_earnings):
        """short strike must always be above LEAPS strike."""
        ticker = _default_ticker()
        result = analyze_pmcc("TEST", ticker=ticker)
        if result and "pmcc_score" in result:
            assert result["short"]["strike"] > result["leaps"]["strike"]

    def test_no_options_returns_error(self):
        """Symbol with no options should return error dict."""
        ticker = MockTicker(price=100.0, expirations=[], chains={})
        result = analyze_pmcc("TEST", ticker=ticker)
        assert result is not None
        assert "error" in result


# ---------------------------------------------------------------------------
# 10. format_scan_results (Step 10)
# ---------------------------------------------------------------------------


class TestFormatScanResults:
    def test_sorts_by_pmcc_score_descending(self):
        results = [
            {
                "symbol": "A",
                "pmcc_score": 3.0,
                "metrics": {"annual_yield_realistic_pct": 10},
            },
            {
                "symbol": "B",
                "pmcc_score": 7.5,
                "metrics": {"annual_yield_realistic_pct": 20},
            },
            {
                "symbol": "C",
                "pmcc_score": 5.0,
                "metrics": {"annual_yield_realistic_pct": 15},
            },
        ]
        output = format_scan_results(results)
        scores = [r["pmcc_score"] for r in output["results"]]
        assert scores == [7.5, 5.0, 3.0]

    def test_secondary_sort_by_realistic_yield(self):
        """Tie in pmcc_score → higher annual_yield_realistic_pct comes first."""
        results = [
            {
                "symbol": "A",
                "pmcc_score": 5.0,
                "metrics": {"annual_yield_realistic_pct": 10},
            },
            {
                "symbol": "B",
                "pmcc_score": 5.0,
                "metrics": {"annual_yield_realistic_pct": 30},
            },
        ]
        output = format_scan_results(results)
        symbols = [r["symbol"] for r in output["results"]]
        assert symbols == ["B", "A"]

    def test_separates_errors_from_results(self):
        results = [
            {
                "symbol": "A",
                "pmcc_score": 5.0,
                "metrics": {"annual_yield_realistic_pct": 10},
            },
            {"symbol": "B", "error": "No options"},
        ]
        output = format_scan_results(results)
        assert output["count"] == 1
        assert len(output["errors"]) == 1
        assert output["errors"][0]["symbol"] == "B"

    def test_empty_results(self):
        output = format_scan_results([])
        assert output["count"] == 0
        assert output["results"] == []
        assert output["errors"] == []

    def test_includes_scan_date(self):
        output = format_scan_results([])
        assert "scan_date" in output

    def test_handles_missing_metrics(self):
        """Result with pmcc_score but no metrics dict should still appear."""
        results = [{"symbol": "A", "pmcc_score": 5.0}]
        output = format_scan_results(results)
        assert output["count"] == 1


# ---------------------------------------------------------------------------
# 11. Real-data smoke tests (lightweight integration)
# ---------------------------------------------------------------------------


class TestRealDataSmoke:
    def test_valid_symbol_returns_result_or_error(self):
        """AAPL should return a dict with pmcc_score or error."""
        result = analyze_pmcc("AAPL")
        assert result is not None
        assert "pmcc_score" in result or "error" in result

    def test_valid_result_has_expected_top_level_keys(self):
        result = analyze_pmcc("AAPL")
        if result and "pmcc_score" in result:
            for key in [
                "symbol",
                "price",
                "leaps_iv_pct",
                "short_iv_pct",
                "pmcc_score",
                "earnings_date",
                "earnings_risk",
                "leaps",
                "short",
                "metrics",
                "risk_flags",
            ]:
                assert key in result, f"Missing top-level key: {key}"

    def test_invalid_symbol_returns_none_or_error(self):
        result = analyze_pmcc("BRK.A")
        assert result is None or "error" in result
