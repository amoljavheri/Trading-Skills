"""Tests for shared_utils.py — shared portfolio income plan utilities."""

import os
import sys
from importlib.util import module_from_spec, spec_from_file_location

# ── Import the module under test ──────────────────────────────────────────
_script_path = os.path.join(
    os.path.dirname(__file__), "..",
    ".claude", "skills", "portfolio-income-plan", "scripts",
    "shared_utils.py",
)
_spec = spec_from_file_location(
    "shared_utils", os.path.abspath(_script_path),
)
_mod = module_from_spec(_spec)
sys.modules["shared_utils"] = _mod
_spec.loader.exec_module(_mod)

classify_trend = _mod.classify_trend
classify_earnings_risk = _mod.classify_earnings_risk
enforce_sma200_cap = _mod.enforce_sma200_cap
enforce_sector_limits = _mod.enforce_sector_limits
compute_stress_test = _mod.compute_stress_test


# ── Tests: classify_trend ────────────────────────────────────────────────────

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

    def test_boundary_6(self):
        assert classify_trend(6.0) == "strong_bull"

    def test_boundary_4(self):
        assert classify_trend(4.0) == "bull"

    def test_boundary_2(self):
        assert classify_trend(2.0) == "neutral"

    def test_boundary_1(self):
        assert classify_trend(1.0) == "bear"


# ── Tests: classify_earnings_risk ────────────────────────────────────────────

class TestClassifyEarningsRisk:
    def test_none_is_unknown(self):
        assert classify_earnings_risk(None) == "UNKNOWN"

    def test_past(self):
        assert classify_earnings_risk(-1) == "PAST"
        assert classify_earnings_risk(0) == "PAST"

    def test_block(self):
        assert classify_earnings_risk(7) == "BLOCK"
        assert classify_earnings_risk(14) == "BLOCK"

    def test_short_dte(self):
        assert classify_earnings_risk(15) == "SHORT_DTE_ONLY"
        assert classify_earnings_risk(21) == "SHORT_DTE_ONLY"

    def test_safe(self):
        assert classify_earnings_risk(22) == "SAFE"
        assert classify_earnings_risk(60) == "SAFE"


# ── Tests: enforce_sma200_cap ────────────────────────────────────────────────

class TestEnforceSma200Cap:
    def test_bull_below_sma200_capped_to_neutral(self):
        """Bull trend below SMA200 must be capped to neutral."""
        assert enforce_sma200_cap("bull", above_sma200=False) == "neutral"

    def test_strong_bull_below_sma200_capped(self):
        assert enforce_sma200_cap("strong_bull", above_sma200=False) == "neutral"

    def test_neutral_below_sma200_unchanged(self):
        """Neutral and below should stay neutral (already at/below cap)."""
        assert enforce_sma200_cap("neutral", above_sma200=False) == "neutral"

    def test_bear_below_sma200_unchanged(self):
        assert enforce_sma200_cap("bear", above_sma200=False) == "bear"

    def test_bull_above_sma200_unchanged(self):
        """Above SMA200 — no cap applied."""
        assert enforce_sma200_cap("bull", above_sma200=True) == "bull"

    def test_strong_bull_above_sma200_unchanged(self):
        assert enforce_sma200_cap("strong_bull", above_sma200=True) == "strong_bull"

    def test_none_sma200_no_cap(self):
        """If SMA200 data unavailable, don't cap."""
        assert enforce_sma200_cap("bull", above_sma200=None) == "bull"


# ── Tests: enforce_sector_limits ─────────────────────────────────────────────

class TestEnforceSectorLimits:
    def _cand(self, symbol, sector, capital, score):
        return {
            "symbol": symbol,
            "sector": sector,
            "csp_capital_needed": capital,
            "wheel_score": score,
        }

    def test_empty_list(self):
        kept, dropped = enforce_sector_limits([])
        assert kept == []
        assert dropped == []

    def test_no_concentration_issue(self):
        """3 different sectors — all should pass."""
        candidates = [
            self._cand("AAPL", "Technology", 10000, 9.0),
            self._cand("JPM", "Financial", 10000, 8.0),
            self._cand("UNH", "Healthcare", 10000, 7.0),
        ]
        kept, dropped = enforce_sector_limits(candidates)
        assert len(kept) == 3
        assert len(dropped) == 0

    def test_tech_over_30pct_dropped(self):
        """4 tech candidates out of 5 — weakest tech should be dropped."""
        candidates = [
            self._cand("AAPL", "Technology", 10000, 10.0),
            self._cand("MSFT", "Technology", 10000, 9.0),
            self._cand("JPM", "Financial", 10000, 8.0),
            self._cand("NVDA", "Technology", 10000, 7.0),
            self._cand("AMD", "Technology", 10000, 6.0),
        ]
        # Total = 50000. Tech = 40000 (80%) if all kept.
        # At 30% threshold (15000 of 50000):
        # AAPL(10k) passes (10k/50k=20%), MSFT would be 20k/50k=40% > 30% → dropped
        kept, dropped = enforce_sector_limits(candidates)
        tech_kept = [c for c in kept if c["sector"] == "Technology"]
        assert len(tech_kept) <= 2  # At most ~30% of total capital
        assert len(dropped) >= 2
        # Dropped candidates should have a reason
        for d in dropped:
            assert "dropped_reason" in d
            assert "concentration" in d["dropped_reason"].lower()

    def test_single_sector_all_pass_if_within_limit(self):
        """If total capital is small, all pass."""
        candidates = [
            self._cand("AAPL", "Technology", 5000, 9.0),
        ]
        kept, dropped = enforce_sector_limits(candidates)
        assert len(kept) == 1
        assert len(dropped) == 0

    def test_custom_limit(self):
        """Custom 50% limit should be more permissive."""
        candidates = [
            self._cand("AAPL", "Technology", 10000, 9.0),
            self._cand("MSFT", "Technology", 10000, 8.0),
            self._cand("JPM", "Financial", 10000, 7.0),
        ]
        kept, dropped = enforce_sector_limits(candidates, max_sector_pct=0.50)
        # AAPL passes (first in sector), MSFT would be 20k/30k=67% > 50% → dropped
        assert len(kept) == 2
        assert len(dropped) == 1
        assert dropped[0]["symbol"] == "MSFT"


# ── Tests: compute_stress_test ───────────────────────────────────────────────

class TestComputeStressTest:
    def test_no_short_puts(self):
        """Portfolio with no CSPs should trivially pass."""
        portfolio = {
            "cash_available": 50000,
            "option_positions": [],
        }
        result = compute_stress_test(portfolio)
        assert result["stress_pass"] is True
        assert result["total_assignment_capital"] == 0
        assert result["shortfall"] == 0

    def test_csps_within_cash(self):
        """Short puts fully covered by cash."""
        portfolio = {
            "cash_available": 100000,
            "option_positions": [
                {"option_type": "put", "strike": 200, "quantity": -1, "underlying": "AAPL"},
                {"option_type": "put", "strike": 150, "quantity": -2, "underlying": "AMD"},
            ],
        }
        result = compute_stress_test(portfolio)
        # AAPL: 200*100*1 = 20000, AMD: 150*100*2 = 30000 → total = 50000
        assert result["total_assignment_capital"] == 50000
        assert result["stress_pass"] is True
        assert result["shortfall"] == 0
        assert result["coverage_pct"] == 200.0

    def test_csps_exceed_cash(self):
        """Short puts exceed available cash — stress test fails."""
        portfolio = {
            "cash_available": 30000,
            "option_positions": [
                {"option_type": "put", "strike": 200, "quantity": -1, "underlying": "AAPL"},
                {"option_type": "put", "strike": 150, "quantity": -2, "underlying": "AMD"},
            ],
        }
        result = compute_stress_test(portfolio)
        assert result["stress_pass"] is False
        assert result["shortfall"] == 20000  # 50000 - 30000
        assert "REDUCE" in result["recommendation"]

    def test_long_puts_ignored(self):
        """Long puts (positive quantity) are not CSPs."""
        portfolio = {
            "cash_available": 10000,
            "option_positions": [
                {"option_type": "put", "strike": 200, "quantity": 1, "underlying": "AAPL"},
            ],
        }
        result = compute_stress_test(portfolio)
        assert result["stress_pass"] is True
        assert result["total_assignment_capital"] == 0

    def test_calls_ignored(self):
        """Short calls are not CSPs."""
        portfolio = {
            "cash_available": 10000,
            "option_positions": [
                {"option_type": "call", "strike": 200, "quantity": -1, "underlying": "AAPL"},
            ],
        }
        result = compute_stress_test(portfolio)
        assert result["stress_pass"] is True
        assert result["total_assignment_capital"] == 0
