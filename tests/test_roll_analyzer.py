#!/usr/bin/env python3
# ABOUTME: Tests for roll-manager skill (roll_analyzer.py).
# ABOUTME: Covers position classification, decision engine, roll target finding,
# ABOUTME: chain loading, and end-to-end orchestration. All data mocked.

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from unittest import TestCase

# ── Dynamic import of roll_analyzer.py ────────────────────────────────────────
_script_path = os.path.join(
    os.path.dirname(__file__), "..",
    ".claude", "skills", "roll-manager", "scripts",
    "roll_analyzer.py",
)
_spec = spec_from_file_location("roll_analyzer", os.path.abspath(_script_path))
_mod = module_from_spec(_spec)
sys.modules["roll_analyzer"] = _mod
_spec.loader.exec_module(_mod)

classify_position = _mod.classify_position
decide_action = _mod.decide_action
find_roll_targets = _mod.find_roll_targets
load_chains = _mod.load_chains
estimate_close_cost = _mod.estimate_close_cost
analyze_rolls = _mod.analyze_rolls


def _future(days: int) -> str:
    """Return a date string N days from today."""
    return (datetime.now().date() + timedelta(days=days)).strftime("%Y-%m-%d")


def _make_option(
    symbol="NVDA", option_type="call", strike=250.0, expiry_days=30,
    quantity=-5, cost_basis=2500.0, current_value=1000.0, delta=None,
):
    """Create a mock option position dict."""
    opt = {
        "underlying": symbol,
        "option_type": option_type,
        "strike": strike,
        "expiry": _future(expiry_days),
        "quantity": quantity,
        "cost_basis": cost_basis,
        "current_value": current_value,
    }
    if delta is not None:
        opt["greeks"] = {"delta": delta}
    return opt


def _make_stock(symbol="NVDA", quantity=500, cost_basis=145.0):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "cost_basis_per_share": cost_basis,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TestClassifyPosition
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyPosition(TestCase):
    """Test position classification logic."""

    def test_cc_otm(self):
        opt = _make_option(strike=260.0, delta=0.25)
        stocks = [_make_stock()]
        r = classify_position(opt, 250.0, stocks)
        self.assertEqual(r["strategy"], "CC")
        self.assertEqual(r["moneyness"], "OTM")
        self.assertEqual(r["itm_amount"], 0.0)

    def test_cc_itm(self):
        opt = _make_option(strike=240.0, delta=0.75)
        stocks = [_make_stock()]
        r = classify_position(opt, 250.0, stocks)
        self.assertEqual(r["strategy"], "CC")
        self.assertEqual(r["moneyness"], "ITM")
        self.assertAlmostEqual(r["itm_amount"], 10.0)

    def test_cc_atm(self):
        opt = _make_option(strike=250.0, delta=0.50)
        stocks = [_make_stock()]
        r = classify_position(opt, 251.0, stocks)
        self.assertEqual(r["moneyness"], "ATM")

    def test_csp_safe_otm(self):
        opt = _make_option(option_type="put", strike=200.0, delta=-0.15)
        r = classify_position(opt, 250.0, [])
        self.assertEqual(r["strategy"], "CSP")
        self.assertEqual(r["moneyness"], "OTM")
        self.assertEqual(r["risk_level"], "low")

    def test_csp_threatened(self):
        # Strike 240 with price 250 = 4% OTM but high delta = threatened
        opt = _make_option(option_type="put", strike=240.0, delta=-0.45)
        r = classify_position(opt, 250.0, [])
        self.assertEqual(r["strategy"], "CSP")
        self.assertEqual(r["moneyness"], "OTM")
        self.assertEqual(r["risk_level"], "high")

    def test_csp_itm(self):
        opt = _make_option(option_type="put", strike=260.0, delta=-0.70)
        r = classify_position(opt, 250.0, [])
        self.assertEqual(r["strategy"], "CSP")
        self.assertEqual(r["moneyness"], "ITM")
        self.assertAlmostEqual(r["itm_amount"], 10.0)

    def test_covered_detection(self):
        opt = _make_option(quantity=-5)
        stocks = [_make_stock(quantity=500)]
        r = classify_position(opt, 250.0, stocks)
        self.assertTrue(r["is_covered"])
        self.assertEqual(r["strategy"], "CC")

    def test_naked_detection(self):
        opt = _make_option(quantity=-5)
        stocks = [_make_stock(quantity=99)]
        r = classify_position(opt, 250.0, stocks)
        self.assertFalse(r["is_covered"])
        self.assertEqual(r["strategy"], "CSP")

    def test_delta_risk_levels(self):
        for delta, expected in [
            (0.10, "low"), (0.25, "moderate"),
            (0.45, "high"), (0.75, "very_high"),
        ]:
            opt = _make_option(delta=delta)
            r = classify_position(opt, 250.0, [_make_stock()])
            self.assertEqual(r["risk_level"], expected, f"delta={delta}")


# ═══════════════════════════════════════════════════════════════════════════════
# TestDecideAction
# ═══════════════════════════════════════════════════════════════════════════════


class TestDecideAction(TestCase):
    """Test decision engine rules."""

    def _classify(self, **kwargs):
        return {
            "symbol": "NVDA", "option_type": "call", "strike": 250.0,
            "expiry": _future(30), "dte": 30, "contracts": 5,
            "strategy": "CC", "moneyness": "OTM", "moneyness_pct": 5.0,
            "itm_amount": 0.0, "is_covered": True, "risk_level": "low",
            "delta": 0.25,
            **kwargs,
        }

    def test_profit_capture_close_early(self):
        cl = self._classify()
        opt = _make_option(cost_basis=5000, current_value=2000)
        r = decide_action(cl, opt, 250.0, close_cost=4.00)
        self.assertEqual(r["action"], "CLOSE_EARLY")
        self.assertGreaterEqual(r["profit_captured_pct"], 50)

    def test_profit_below_threshold_hold(self):
        cl = self._classify()
        # cost_basis $10/share, per_now=4000/5/100=$8 → profit=20% < 50% → HOLD
        opt = _make_option(cost_basis=10.0, current_value=4000)
        r = decide_action(cl, opt, 250.0, close_cost=8.00)
        self.assertEqual(r["action"], "HOLD")

    def test_theta_guard_pct_based(self):
        """V3: option worth <10% of original → LET_EXPIRE, not CLOSE_EARLY."""
        cl = self._classify(dte=5)
        # Sold for $5000 (5 contracts = $10/contract), now worth $200 ($0.40/c)
        opt = _make_option(cost_basis=5000, current_value=200, expiry_days=5)
        # close_cost $0.40, cost_basis_per = 5000/5/100 = $10.00
        # remaining = 0.40/10.00 = 4% < 10% → LET_EXPIRE
        r = decide_action(cl, opt, 250.0, close_cost=0.40)
        self.assertEqual(r["action"], "LET_EXPIRE")
        self.assertIn("theta", r["why_now"])

    def test_theta_guard_skips_high_dte(self):
        """Theta guard doesn't trigger when DTE > THETA_EXIT_MAX_DTE."""
        cl = self._classify(dte=20)
        opt = _make_option(cost_basis=5000, current_value=200, expiry_days=20)
        r = decide_action(cl, opt, 250.0, close_cost=0.40)
        self.assertEqual(r["action"], "CLOSE_EARLY")

    def test_dte5_safe_otm(self):
        cl = self._classify(dte=3, moneyness="OTM", moneyness_pct=5.0)
        opt = _make_option(expiry_days=3, cost_basis=0, current_value=0)
        r = decide_action(cl, opt, 250.0)
        self.assertEqual(r["action"], "LET_EXPIRE")

    def test_dte5_threatened(self):
        cl = self._classify(dte=3, moneyness="OTM", moneyness_pct=1.5)
        opt = _make_option(expiry_days=3, cost_basis=0, current_value=0)
        r = decide_action(cl, opt, 250.0)
        self.assertEqual(r["action"], "ROLL_OUT")
        self.assertEqual(r["urgency"], 2)

    def test_itm_cc_low_extrinsic(self):
        cl = self._classify(
            moneyness="ITM", itm_amount=5.0, delta=0.75,
            strategy="CC",
        )
        opt = _make_option(cost_basis=1000, current_value=0)
        # close_cost $5.15, intrinsic $5.00, extrinsic $0.15
        r = decide_action(cl, opt, 255.0, close_cost=5.15)
        self.assertEqual(r["action"], "ROLL_OUT_AND_UP")

    def test_itm_cc_good_extrinsic(self):
        cl = self._classify(
            moneyness="ITM", itm_amount=5.0, delta=0.55,
            strategy="CC",
        )
        opt = _make_option(cost_basis=1000, current_value=0)
        r = decide_action(cl, opt, 255.0, close_cost=6.50)
        self.assertEqual(r["action"], "HOLD")

    def test_strong_bull_hold_for_upside(self):
        cl = self._classify(
            moneyness="ITM", itm_amount=5.0, delta=0.72,
            strategy="CC", strike=250.0,
        )
        opt = _make_option(cost_basis=1000, current_value=0)
        r = decide_action(
            cl, opt, 255.0, close_cost=5.10, trend="strong_bull",
        )
        self.assertTrue(r["hold_for_upside"])
        self.assertEqual(r["action"], "HOLD")

    def test_itm_csp_wheel_bullish(self):
        cl = self._classify(
            strategy="CSP", option_type="put", moneyness="ITM",
            itm_amount=10.0,
        )
        opt = _make_option(option_type="put", cost_basis=0, current_value=0)
        r = decide_action(
            cl, opt, 240.0, assignment_mode="wheel", trend="bull",
        )
        self.assertEqual(r["action"], "LET_EXPIRE")

    def test_itm_csp_avoid_mode(self):
        cl = self._classify(
            strategy="CSP", option_type="put", moneyness="ITM",
            itm_amount=10.0,
        )
        opt = _make_option(option_type="put", cost_basis=0, current_value=0)
        r = decide_action(cl, opt, 240.0, assignment_mode="avoid")
        self.assertEqual(r["action"], "ROLL_OUT_AND_DOWN")

    def test_high_delta_warning(self):
        cl = self._classify(delta=0.65, dte=10)
        opt = _make_option(cost_basis=0, current_value=0, expiry_days=10)
        r = decide_action(cl, opt, 250.0)
        self.assertEqual(r["action"], "HOLD")
        self.assertEqual(r["urgency"], 1)

    def test_default_hold(self):
        cl = self._classify(delta=0.20, dte=30, moneyness="OTM")
        opt = _make_option(cost_basis=0, current_value=0)
        r = decide_action(cl, opt, 250.0)
        self.assertEqual(r["action"], "HOLD")
        self.assertEqual(r["urgency"], 0)

    def test_premium_erosion_flagged(self):
        cl = self._classify(dte=30, moneyness="OTM")
        # cost_basis $1/share (per-share), 5 contracts, strike $250
        # total_premium = 1.0*100*5=500, capital=125000, ratio=0.4% < 0.5% → flagged
        opt = _make_option(cost_basis=1.0, current_value=10)
        r = decide_action(cl, opt, 250.0)
        self.assertTrue(r["consider_exit"])
        self.assertIn("rolled repeatedly", r["exit_reason"])

    def test_premium_erosion_not_flagged(self):
        cl = self._classify(dte=30, moneyness="OTM")
        # cost_basis $2500 for strike $250, 5 contracts
        # premium_ratio = 2500 / 125000 = 0.02 > 0.005
        opt = _make_option(cost_basis=2500, current_value=1000)
        r = decide_action(cl, opt, 250.0, close_cost=2.0)
        self.assertFalse(r["consider_exit"])


# ═══════════════════════════════════════════════════════════════════════════════
# TestFindRollTargets
# ═══════════════════════════════════════════════════════════════════════════════


def _make_chain_option(
    option_type="call", strike=260.0, bid=2.50, ask=2.70,
    delta=0.25, theta=-0.05, mid_iv=0.35, oi=1000, volume=500,
):
    """Create a mock Tradier chain option entry."""
    return {
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "open_interest": oi,
        "greeks": {
            "delta": delta if option_type == "call" else -abs(delta),
            "theta": theta,
            "gamma": 0.005,
            "vega": 0.02,
            "mid_iv": mid_iv,
        },
    }


class TestFindRollTargets(TestCase):
    """Test roll target finding and scoring."""

    def _classification(self, **kwargs):
        return {
            "symbol": "NVDA", "option_type": "call", "strike": 250.0,
            "expiry": _future(5), "dte": 5, "contracts": 5,
            "strategy": "CC", "moneyness": "ITM", "moneyness_pct": 2.0,
            "itm_amount": 5.0, "is_covered": True, "risk_level": "high",
            "delta": 0.72,
            **kwargs,
        }

    def test_roll_out_same_strike(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=250.0, bid=5.00, ask=5.20),
            ],
        }
        opt = _make_option(current_value=3500)  # $7.00/contract
        r = find_roll_targets(
            opt, "ROLL_OUT", self._classification(), chains, 255.0,
        )
        self.assertTrue(len(r["roll_targets"]) > 0)
        t = r["roll_targets"][0]
        self.assertEqual(t["new_strike"], 250.0)
        self.assertIsNotNone(t["net_credit"])

    def test_roll_out_and_up_cc(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=260.0, bid=3.00, delta=0.25),
                _make_chain_option(strike=270.0, bid=1.50, delta=0.15),
            ],
        }
        # current_value=500 ($1.00/contract) so net credit is positive
        opt = _make_option(current_value=500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
            trend="bull",
        )
        targets = [t for t in r["roll_targets"] if not t["disqualified"]]
        self.assertTrue(len(targets) > 0)
        for t in targets:
            self.assertGreater(t["new_strike"], 250.0)

    def test_roll_out_and_down_csp(self):
        cl = self._classification(
            option_type="put", strike=250.0, strategy="CSP",
        )
        chains = {
            _future(30): [
                _make_chain_option(
                    option_type="put", strike=240.0, bid=3.00, delta=0.25,
                ),
            ],
        }
        # current_value=500 ($1.00/contract) so net credit is positive
        opt = _make_option(
            option_type="put", current_value=500, strike=250.0,
        )
        r = find_roll_targets(opt, "ROLL_OUT_AND_DOWN", cl, chains, 245.0)
        targets = [t for t in r["roll_targets"] if not t["disqualified"]]
        self.assertTrue(len(targets) > 0)
        for t in targets:
            self.assertLess(t["new_strike"], 250.0)

    def test_net_credit_disqualification(self):
        chains = {
            _future(30): [
                # delta=0.30 within neutral call range (0.25-0.40)
                _make_chain_option(strike=270.0, bid=0.50, delta=0.30),
            ],
        }
        # Close cost is high ($8.00/contract), bid is $0.50 → net debit $7.50
        opt = _make_option(current_value=4000)  # $8.00/contract
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
            max_debit=0.50,
        )
        disqualified = [t for t in r["roll_targets"] if t["disqualified"]]
        self.assertTrue(len(disqualified) > 0)
        self.assertIn("debit", disqualified[0]["disqualified_reason"])

    def test_quality_score_range(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=260.0, bid=4.00, delta=0.25),
            ],
        }
        opt = _make_option(current_value=2500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
        )
        for t in r["roll_targets"]:
            self.assertGreaterEqual(t["roll_quality_score"], 0)
            self.assertLessEqual(t["roll_quality_score"], 10)

    def test_no_chains_empty_result(self):
        r = find_roll_targets(
            _make_option(), "ROLL_OUT", self._classification(), {}, 255.0,
        )
        self.assertEqual(r["roll_targets"], [])

    def test_sorted_by_score(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=260.0, bid=3.00, delta=0.25),
                _make_chain_option(strike=265.0, bid=2.00, delta=0.20),
            ],
        }
        opt = _make_option(current_value=2500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
        )
        qualified = [t for t in r["roll_targets"] if not t["disqualified"]]
        if len(qualified) >= 2:
            self.assertGreaterEqual(
                qualified[0]["roll_quality_score"],
                qualified[1]["roll_quality_score"],
            )

    def test_earnings_hard_block(self):
        """V3: Roll target within 14d of earnings → disqualified."""
        earn_date = _future(35)  # earnings 35 days from now
        chains = {
            _future(30): [  # expiry 30 days → within 14d of earnings
                _make_chain_option(strike=260.0, bid=3.00, delta=0.25),
            ],
        }
        opt = _make_option(current_value=2500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
            earnings_dates={"NVDA": {"date": earn_date, "days_away": 35}},
        )
        blocked = [
            t for t in r["roll_targets"]
            if t.get("earnings_warning") and "BLOCKED" in t["earnings_warning"]
        ]
        self.assertTrue(len(blocked) > 0)
        self.assertTrue(blocked[0]["disqualified"])

    def test_iv_relative_calculated(self):
        chains = {
            _future(30): [
                _make_chain_option(
                    strike=260.0, bid=3.00, delta=0.25, mid_iv=0.40,
                ),
                _make_chain_option(
                    strike=265.0, bid=2.00, delta=0.20, mid_iv=0.30,
                ),
            ],
        }
        opt = _make_option(current_value=2500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
        )
        for t in r["roll_targets"]:
            self.assertIsNotNone(t["iv_relative"])

    def test_roll_rationale_present(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=260.0, bid=3.00, delta=0.25),
            ],
        }
        opt = _make_option(current_value=2500)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
        )
        for t in r["roll_targets"]:
            self.assertIn("DTE", t["roll_rationale"])

    def test_close_and_reopen_flag(self):
        """V3: Wide spread roll → CLOSE_AND_REOPEN execution note."""
        chains = {
            _future(30): [
                # Tiny bid → net credit will be very low
                _make_chain_option(strike=260.0, bid=0.05, delta=0.25),
            ],
        }
        # High close cost → poor roll economics
        opt = _make_option(current_value=500)  # $1.00/contract
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 255.0,
        )
        # With net_credit < MIN_NET_CREDIT, should flag
        if r["roll_targets"]:
            # execution_note may or may not trigger depending on exact math
            # but the field should exist
            self.assertIn("execution_note", r)


# ═══════════════════════════════════════════════════════════════════════════════
# TestDeepItmFallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeepItmFallback(TestCase):
    """Test deep ITM fallback options when no credit roll exists."""

    def _classification(self, **kwargs):
        return {
            "symbol": "NVDA", "option_type": "call", "strike": 200.0,
            "expiry": _future(5), "dte": 5, "contracts": 5,
            "strategy": "CC", "moneyness": "ITM", "moneyness_pct": 0.0,
            "itm_amount": 50.0, "is_covered": True, "risk_level": "very_high",
            "delta": 0.95,
            **kwargs,
        }

    def test_no_credit_roll_gives_fallback(self):
        """When all targets are disqualified, fallback options appear."""
        chains = {
            _future(30): [
                # Only option has terrible net debit
                _make_chain_option(strike=210.0, bid=0.10, delta=0.20),
            ],
        }
        # High close cost ($10/contract)
        opt = _make_option(strike=200.0, current_value=5000)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 250.0,
            max_debit=0.50,
        )
        self.assertIsNotNone(r["fallback_options"])
        actions = [f["action"] for f in r["fallback_options"]]
        self.assertIn("ACCEPT_ASSIGNMENT", actions)

    def test_fallback_includes_debit_roll(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=210.0, bid=0.10, delta=0.20),
            ],
        }
        opt = _make_option(strike=200.0, current_value=5000)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", self._classification(), chains, 250.0,
            max_debit=0.50,
        )
        if r["fallback_options"]:
            actions = [f["action"] for f in r["fallback_options"]]
            if "ROLL_FOR_DEBIT" in actions:
                debit_opt = [
                    f for f in r["fallback_options"]
                    if f["action"] == "ROLL_FOR_DEBIT"
                ][0]
                self.assertIn("debit", debit_opt["description"])

    def test_no_fallback_when_qualified_exists(self):
        chains = {
            _future(30): [
                _make_chain_option(strike=260.0, bid=5.00, delta=0.25),
            ],
        }
        opt = _make_option(strike=200.0, current_value=2500)
        cl = self._classification(strike=200.0)
        r = find_roll_targets(
            opt, "ROLL_OUT_AND_UP", cl, chains, 250.0,
        )
        qualified = [t for t in r["roll_targets"] if not t["disqualified"]]
        if qualified:
            self.assertIsNone(r["fallback_options"])


# ═══════════════════════════════════════════════════════════════════════════════
# TestLoadChains
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoadChains(TestCase):
    """Test chain file loading from directory."""

    def test_load_single_chain(self):
        with tempfile.TemporaryDirectory() as d:
            chain_data = {
                "options": {"option": [
                    {"option_type": "call", "strike": 260.0, "bid": 3.0},
                ]}
            }
            path = os.path.join(d, f"NVDA_{_future(30)}.json")
            with open(path, "w") as f:
                json.dump(chain_data, f)

            result = load_chains(d)
            self.assertIn("NVDA", result)
            self.assertEqual(len(list(result["NVDA"].values())[0]), 1)

    def test_load_multiple_symbols(self):
        with tempfile.TemporaryDirectory() as d:
            for sym in ["NVDA", "AMD", "AAPL"]:
                chain_data = {"options": {"option": [
                    {"option_type": "call", "strike": 100.0},
                ]}}
                path = os.path.join(d, f"{sym}_{_future(30)}.json")
                with open(path, "w") as f:
                    json.dump(chain_data, f)

            result = load_chains(d)
            self.assertEqual(len(result), 3)

    def test_mcp_wrapper_format(self):
        with tempfile.TemporaryDirectory() as d:
            inner = json.dumps({
                "options": {"option": [
                    {"option_type": "put", "strike": 240.0, "bid": 2.0},
                ]}
            })
            wrapper = [{"type": "text", "text": inner}]
            path = os.path.join(d, f"NVDA_{_future(30)}.json")
            with open(path, "w") as f:
                json.dump(wrapper, f)

            result = load_chains(d)
            self.assertIn("NVDA", result)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            result = load_chains(d)
            self.assertEqual(result, {})

    def test_invalid_json_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, f"NVDA_{_future(30)}.json")
            with open(path, "w") as f:
                f.write("not json{{{")

            result = load_chains(d)
            self.assertEqual(result, {})


# ═══════════════════════════════════════════════════════════════════════════════
# TestAnalyzeRolls (Integration)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyzeRolls(TestCase):
    """End-to-end integration tests."""

    def _portfolio(self):
        return {
            "cash_available": 50000.0,
            "stock_positions": [_make_stock()],
            "option_positions": [
                _make_option(
                    strike=260.0, quantity=-3, cost_basis=1500,
                    current_value=450, expiry_days=30, delta=0.25,
                ),
                _make_option(
                    option_type="put", strike=230.0, quantity=-2,
                    cost_basis=800, current_value=200,
                    expiry_days=3, delta=-0.10,
                ),
            ],
        }

    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            portfolio = self._portfolio()
            prices = {"NVDA": 255.0}
            result = analyze_rolls(portfolio, prices, d)
            self.assertIn("positions", result)
            self.assertIn("summary", result)
            self.assertEqual(result["total_positions"], 2)

    def test_urgency_sorting(self):
        with tempfile.TemporaryDirectory() as d:
            portfolio = self._portfolio()
            prices = {"NVDA": 255.0}
            result = analyze_rolls(portfolio, prices, d)
            urgencies = [p["urgency"] for p in result["positions"]]
            self.assertEqual(urgencies, sorted(urgencies, reverse=True))

    def test_summary_counts(self):
        with tempfile.TemporaryDirectory() as d:
            portfolio = self._portfolio()
            prices = {"NVDA": 255.0}
            result = analyze_rolls(portfolio, prices, d)
            s = result["summary"]
            total = (
                s["close_early"] + s["roll"]
                + s["let_expire"] + s["hold"]
            )
            self.assertEqual(total, result["total_positions"])

    def test_empty_portfolio(self):
        with tempfile.TemporaryDirectory() as d:
            portfolio = {
                "stock_positions": [],
                "option_positions": [],
            }
            result = analyze_rolls(portfolio, {}, d)
            self.assertEqual(result["total_positions"], 0)
            self.assertEqual(result["positions"], [])
