"""Tests for scan_candidates.py — large-cap wheel strategy candidate scanner."""

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from unittest.mock import patch

# ── Import the module under test and register in sys.modules ──────────────────
_script_path = os.path.join(
    os.path.dirname(__file__), "..",
    ".claude", "skills", "portfolio-income-plan", "scripts",
    "scan_candidates.py",
)
_spec = spec_from_file_location(
    "scan_candidates", os.path.abspath(_script_path),
)
_mod = module_from_spec(_spec)
sys.modules["scan_candidates"] = _mod  # needed so @patch("scan_candidates.*") works
_spec.loader.exec_module(_mod)

classify_trend = _mod.classify_trend
classify_earnings_risk = _mod.classify_earnings_risk
compute_wheel_score = _mod.compute_wheel_score
recommendation = _mod.recommendation
analyze_symbol = _mod.analyze_symbol
scan_candidates = _mod.scan_candidates


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _portfolio(positions: list[dict]) -> dict:
    return {"stock_positions": positions, "option_positions": []}


def _pos(symbol: str, quantity: int) -> dict:
    return {"symbol": symbol, "quantity": quantity}


# ── Tests: classify_trend ─────────────────────────────────────────────────────

class TestClassifyTrend:
    def test_strong_bull(self):
        assert classify_trend(6.5) == "strong_bull"

    def test_bull(self):
        assert classify_trend(4.5) == "bull"

    def test_neutral(self):
        assert classify_trend(3.0) == "neutral"

    def test_bear(self):
        assert classify_trend(1.5) == "bear"

    def test_strong_bear(self):
        assert classify_trend(0.5) == "strong_bear"


# ── Tests: classify_earnings_risk ────────────────────────────────────────────

class TestClassifyEarningsRisk:
    def test_none_is_unknown(self):
        assert classify_earnings_risk(None) == "UNKNOWN"

    def test_past(self):
        assert classify_earnings_risk(-1) == "PAST"

    def test_block_within_14_days(self):
        assert classify_earnings_risk(10) == "BLOCK"
        assert classify_earnings_risk(14) == "BLOCK"

    def test_short_dte_15_to_21(self):
        assert classify_earnings_risk(15) == "SHORT_DTE_ONLY"
        assert classify_earnings_risk(21) == "SHORT_DTE_ONLY"

    def test_safe_beyond_21(self):
        assert classify_earnings_risk(22) == "SAFE"
        assert classify_earnings_risk(60) == "SAFE"


# ── Tests: compute_wheel_score ────────────────────────────────────────────────

class TestComputeWheelScore:
    def test_perfect_score(self):
        """strong_bull + 40% IV + 30d earnings + affordable + profitable = 10"""
        score = compute_wheel_score(
            trend_class="strong_bull",
            iv_pct=40.0,
            earnings_days=30,
            csp_affordable=True,
            profit_margin=0.20,
        )
        assert score == 10.0

    def test_strong_bear_zero_trend(self):
        score = compute_wheel_score(
            trend_class="strong_bear",
            iv_pct=40.0,
            earnings_days=30,
            csp_affordable=True,
            profit_margin=0.20,
        )
        assert score == 7.0  # 0 + 3 + 2 + 1 + 1

    def test_earnings_block_zero_points(self):
        score = compute_wheel_score(
            trend_class="bull",
            iv_pct=40.0,
            earnings_days=5,
            csp_affordable=True,
            profit_margin=0.20,
        )
        assert score == 8.0  # 3 + 3 + 0 + 1 + 1

    def test_low_iv_zero_points(self):
        score = compute_wheel_score(
            trend_class="neutral",
            iv_pct=15.0,  # < 20% → 0
            earnings_days=30,
            csp_affordable=True,
            profit_margin=0.20,
        )
        assert score == 6.0  # 2 + 0 + 2 + 1 + 1

    def test_not_affordable_no_point(self):
        score = compute_wheel_score(
            trend_class="neutral",
            iv_pct=40.0,
            earnings_days=30,
            csp_affordable=False,
            profit_margin=None,
        )
        assert score == 7.0  # 2 + 3 + 2 + 0 + 0

    def test_unknown_earnings_partial_credit(self):
        score = compute_wheel_score(
            trend_class="bull",
            iv_pct=40.0,
            earnings_days=None,
            csp_affordable=True,
            profit_margin=None,
        )
        assert score == 8.0  # 3 + 3 + 1 + 1 + 0


# ── Tests: recommendation ────────────────────────────────────────────────────

class TestRecommendation:
    def test_add_at_7(self):
        assert recommendation(7.0) == "ADD"

    def test_add_at_10(self):
        assert recommendation(10.0) == "ADD"

    def test_watch_at_5(self):
        assert recommendation(5.0) == "WATCH"

    def test_watch_at_6(self):
        assert recommendation(6.5) == "WATCH"

    def test_skip_below_5(self):
        assert recommendation(4.9) == "SKIP"


# ── Tests: scan_candidates (mocked) ──────────────────────────────────────────

class TestScanCandidates:

    def _make_fund_return(self, market_cap: int, profit_margin: float = 0.20):
        return {
            "info": {
                "name": "Test Corp",
                "sector": "Technology",
                "marketCap": market_cap,
                "profitMargins": profit_margin,
                "beta": 1.2,
                "trailingPE": 25.0,
            }
        }

    def _make_bull_return(self, score: float, price: float):
        return {
            "score": score,
            "price": price,
            "signals": ["Above SMA20"],
        }

    def _make_pmcc_return(self, iv_pct: float):
        return {"iv_pct": iv_pct}

    def _make_earnings_return(self, days_away: int):
        from datetime import datetime, timedelta
        earn_date = (datetime.now() + timedelta(days=days_away)).strftime("%Y-%m-%d")
        return {"earnings_date": earn_date, "timing": "AMC"}

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_sub_200b_excluded(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """Stocks below $200B market cap must be excluded."""
        mock_fund.return_value = self._make_fund_return(150_000_000_000)
        mock_bull.return_value = self._make_bull_return(4.0, 100.0)
        mock_pmcc.return_value = self._make_pmcc_return(35.0)
        mock_earn.return_value = self._make_earnings_return(30)

        result = scan_candidates(
            portfolio_data=_portfolio([]),
            budget=12000,
            market_cap_min_b=200.0,
            top_n=5,
        )
        # All symbols below threshold → zero candidates
        assert result["candidate_count"] == 0
        assert result["candidates"] == []

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_owned_100plus_is_eligible_not_candidate(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """Stocks with 100+ shares already owned → OWNED_ELIGIBLE, excluded from candidates."""
        mock_fund.return_value = self._make_fund_return(300_000_000_000)
        mock_bull.return_value = self._make_bull_return(5.0, 100.0)
        mock_pmcc.return_value = self._make_pmcc_return(40.0)
        mock_earn.return_value = self._make_earnings_return(30)

        portfolio = _portfolio([_pos("AAPL", 100)])

        result = scan_candidates(
            portfolio_data=portfolio,
            budget=15000,
            market_cap_min_b=200.0,
            top_n=10,
        )
        eligible = result.get("owned_eligible", [])
        candidate_symbols = [c["symbol"] for c in result["candidates"]]
        # AAPL should be in eligible, not in candidates
        assert "AAPL" in eligible
        assert "AAPL" not in candidate_symbols

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_partial_ownership_is_topup(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """Stocks with 1-99 shares → OWNED_TOPUP with top-up metadata."""
        mock_fund.return_value = self._make_fund_return(300_000_000_000)
        mock_bull.return_value = self._make_bull_return(5.0, 200.0)
        mock_pmcc.return_value = self._make_pmcc_return(40.0)
        mock_earn.return_value = self._make_earnings_return(30)

        portfolio = _portfolio([_pos("AMD", 25)])

        result = scan_candidates(
            portfolio_data=portfolio,
            budget=20000,
            market_cap_min_b=200.0,
            top_n=10,
        )
        candidates = {c["symbol"]: c for c in result["candidates"]}
        assert "AMD" in candidates
        amd = candidates["AMD"]
        assert amd["type"] == "OWNED_TOPUP"
        assert amd["shares_owned"] == 25
        assert amd["shares_needed"] == 75
        assert amd["topup_cost_estimate"] == 75 * 200.0

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_csp_affordability_flag(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """CSP affordable when price×100 <= budget."""
        mock_fund.return_value = self._make_fund_return(300_000_000_000)
        mock_bull.return_value = self._make_bull_return(4.0, 50.0)  # $50 stock
        mock_pmcc.return_value = self._make_pmcc_return(35.0)
        mock_earn.return_value = self._make_earnings_return(30)

        # Budget $6000 → $50×100 = $5000 ≤ $6000
        result = scan_candidates(
            portfolio_data=_portfolio([]),
            budget=6000,
            market_cap_min_b=200.0,
            top_n=5,
        )
        for cand in result["candidates"]:
            if cand["price"] == 50.0:
                assert cand["csp_affordable"] is True

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_top_n_limits_output(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """Output candidates list respects top_n limit."""
        mock_fund.return_value = self._make_fund_return(300_000_000_000)
        mock_bull.return_value = self._make_bull_return(5.0, 100.0)
        mock_pmcc.return_value = self._make_pmcc_return(40.0)
        mock_earn.return_value = self._make_earnings_return(30)

        result = scan_candidates(
            portfolio_data=_portfolio([]),
            budget=12000,
            market_cap_min_b=200.0,
            top_n=3,
        )
        assert len(result["candidates"]) <= 3

    @patch("scan_candidates.get_fundamentals")
    @patch("scan_candidates.compute_bullish_score")
    @patch("scan_candidates.analyze_pmcc")
    @patch("scan_candidates.get_earnings_info")
    def test_ranked_by_wheel_score(
        self, mock_earn, mock_pmcc, mock_bull, mock_fund
    ):
        """Candidates are sorted descending by wheel_score."""
        # Different scores based on trend
        call_count = [0]

        def fund_side(sym, data_type="all"):
            return self._make_fund_return(300_000_000_000)

        def bull_side(sym):
            call_count[0] += 1
            # Alternate high/low scores
            score = 6.0 if call_count[0] % 2 == 0 else 1.0
            return {"score": score, "price": 100.0, "signals": []}

        mock_fund.side_effect = fund_side
        mock_bull.side_effect = bull_side
        mock_pmcc.return_value = self._make_pmcc_return(40.0)
        mock_earn.return_value = self._make_earnings_return(30)

        result = scan_candidates(
            portfolio_data=_portfolio([]),
            budget=12000,
            market_cap_min_b=200.0,
            top_n=20,
        )
        scores = [c["wheel_score"] for c in result["candidates"]]
        assert scores == sorted(scores, reverse=True)
