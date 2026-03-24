"""Tests for rolling_checks.py — option position roll/close recommendations."""

import os
from datetime import datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location

# ── Import the module under test ──────────────────────────────────────────
_script_path = os.path.join(
    os.path.dirname(__file__), "..",
    ".claude", "skills", "portfolio-income-plan", "scripts",
    "rolling_checks.py",
)
_spec = spec_from_file_location(
    "rolling_checks", os.path.abspath(_script_path),
)
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)
check_rolling = _mod.check_rolling


def _future_date(days: int) -> str:
    return (datetime.now().date() + timedelta(days=days)).isoformat()


def _short_option(symbol, option_type, strike, expiry, qty=-1,
                  cost_basis=500, current_value=200):
    return {
        "underlying": symbol,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "quantity": qty,
        "cost_basis": cost_basis,
        "current_value": current_value,
    }


class TestRollingChecks:
    def test_hold_when_no_profit(self):
        """Position with minimal profit should HOLD."""
        positions = [
            _short_option("NVDA", "call", 200, _future_date(20),
                          cost_basis=500, current_value=400),  # 20% profit
        ]
        results = check_rolling(positions, {"NVDA": 190.0})
        assert len(results) == 1
        assert results[0]["action"] == "HOLD"

    def test_roll_early_at_60pct_profit(self):
        """Position with 60%+ profit should ROLL_EARLY."""
        positions = [
            _short_option("NVDA", "call", 200, _future_date(20),
                          cost_basis=500, current_value=150),  # 70% profit
        ]
        results = check_rolling(positions, {"NVDA": 190.0})
        assert len(results) == 1
        assert results[0]["action"] == "ROLL_EARLY"
        assert "60%" in results[0]["reason"]

    def test_roll_decision_near_money_low_dte(self):
        """<5 DTE and within 2% of strike → ROLL_DECISION."""
        positions = [
            _short_option("AAPL", "call", 200, _future_date(3),
                          cost_basis=300, current_value=250),
        ]
        results = check_rolling(positions, {"AAPL": 199.0})  # 0.5% from strike
        assert len(results) == 1
        assert results[0]["action"] == "ROLL_DECISION"
        assert "DTE" in results[0]["reason"]

    def test_roll_urgent_itm_put_low_dte(self):
        """Short put ITM with <=7 DTE → ROLL_URGENT."""
        positions = [
            _short_option("AMD", "put", 200, _future_date(5),
                          cost_basis=400, current_value=600),
        ]
        results = check_rolling(positions, {"AMD": 190.0})  # put ITM (price < strike)
        assert len(results) == 1
        assert results[0]["action"] == "ROLL_URGENT"
        assert "ITM" in results[0]["reason"]

    def test_roll_urgent_itm_call_low_dte(self):
        """Short call ITM with <=7 DTE → ROLL_URGENT."""
        positions = [
            _short_option("NVDA", "call", 180, _future_date(4),
                          cost_basis=500, current_value=800),
        ]
        results = check_rolling(positions, {"NVDA": 195.0})  # call ITM (price > strike)
        assert len(results) == 1
        assert results[0]["action"] == "ROLL_URGENT"

    def test_long_positions_skipped(self):
        """Long positions (qty > 0) should be ignored."""
        positions = [
            _short_option("AAPL", "call", 200, _future_date(10), qty=1),
        ]
        results = check_rolling(positions, {"AAPL": 210.0})
        assert len(results) == 0

    def test_sorted_by_urgency(self):
        """Results sorted by urgency descending (most urgent first)."""
        positions = [
            _short_option("AAPL", "call", 200, _future_date(20),
                          cost_basis=500, current_value=400),  # HOLD (urgency 0)
            _short_option("AMD", "put", 200, _future_date(3),
                          cost_basis=400, current_value=600),  # ROLL_URGENT (urgency 2)
            _short_option("NVDA", "call", 185, _future_date(15),
                          cost_basis=500, current_value=100),  # ROLL_EARLY (urgency 1)
        ]
        results = check_rolling(positions, {"AAPL": 190, "AMD": 190, "NVDA": 180})
        assert results[0]["urgency"] >= results[-1]["urgency"]

    def test_empty_positions(self):
        """No positions → empty results."""
        results = check_rolling([], {})
        assert results == []
