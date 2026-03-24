"""Tests for the enhanced extract_strikes.py script."""

import json
import os
from importlib.util import module_from_spec, spec_from_file_location

# ── Import the module under test ──────────────────────────────────────────
_script_path = os.path.join(
    os.path.dirname(__file__), "..",
    ".claude", "skills", "portfolio-income-plan", "scripts",
    "extract_strikes.py",
)
_spec = spec_from_file_location(
    "extract_strikes", os.path.abspath(_script_path),
)
_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_strikes = _mod.extract_strikes


# ── Helper to create a mock Tradier chain file ─────────────────────────────

def _make_chain_file(options: list[dict], tmp_path) -> str:
    """Create a mock Tradier chain JSON file."""
    chain = {"options": {"option": options}}
    wrapper = [{"text": json.dumps(chain)}]
    filepath = os.path.join(str(tmp_path), "test_chain.json")
    with open(filepath, "w") as f:
        json.dump(wrapper, f)
    return filepath


def _make_option(
    strike, option_type, bid, ask, delta,
    oi=500, volume=200, mid_iv=0.35, theta=-0.10,
):
    """Create a mock option dict matching Tradier format."""
    return {
        "strike": strike,
        "option_type": option_type,
        "bid": bid,
        "ask": ask,
        "greeks": {
            "delta": delta if option_type == "call" else -abs(delta),
            "theta": theta,
            "mid_iv": mid_iv,
        },
        "open_interest": oi,
        "volume": volume,
    }


# ── Tests ───────────────────────────────────────────────────────────────────

class TestDeltaBasedSelection:
    """Test delta-range strike selection by trend class."""

    def test_neutral_trend_calls(self, tmp_path):
        """Neutral trend: CC delta 0.25-0.40 should pick strikes in that range."""
        options = [
            _make_option(180, "call", 5.0, 5.5, 0.50),  # too high delta
            _make_option(185, "call", 3.0, 3.2, 0.35),   # in range
            _make_option(190, "call", 1.5, 1.7, 0.28),   # in range
            _make_option(195, "call", 0.5, 0.7, 0.15),   # too low delta
            _make_option(200, "call", 0.2, 0.3, 0.08),   # too low delta
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30)

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 185 in strikes
        assert 190 in strikes
        assert 180 not in strikes  # delta 0.50 > 0.40
        assert 195 not in strikes  # delta 0.15 < 0.25

    def test_strong_bull_uses_lower_delta(self, tmp_path):
        """Strong bull: CC delta 0.15-0.25 picks farther OTM."""
        options = [
            _make_option(185, "call", 3.0, 3.1, 0.35),    # too high delta
            _make_option(190, "call", 1.5, 1.55, 0.22),   # in range
            _make_option(195, "call", 0.80, 0.85, 0.18),  # in range
            _make_option(200, "call", 0.30, 0.35, 0.10),  # too low delta
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="strong_bull", dte=30)

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 190 in strikes
        assert 195 in strikes
        assert 185 not in strikes

    def test_bear_trend_puts(self, tmp_path):
        """Bear: CSP delta 0.10-0.20 picks farther OTM puts."""
        options = [
            _make_option(170, "put", 3.0, 3.1, 0.30),   # too high delta
            _make_option(165, "put", 1.50, 1.55, 0.18),  # in range
            _make_option(160, "put", 0.80, 0.85, 0.12),  # in range
            _make_option(155, "put", 0.30, 0.33, 0.06),  # too low delta
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="put",
                                 trend="bear", dte=30)

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 165 in strikes
        assert 160 in strikes
        assert 170 not in strikes
        assert 155 not in strikes


class TestPremiumFilter:
    """Test minimum premium and annualized yield filters."""

    def test_filters_low_premium(self, tmp_path):
        """Options below min_premium should be filtered out."""
        options = [
            _make_option(185, "call", 2.0, 2.2, 0.30),  # mid=2.10 ✓
            _make_option(190, "call", 0.3, 0.4, 0.28),   # mid=0.35 ✗ (< 0.50)
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30, min_premium=0.50)

        assert result["action"] == "TRADE"
        assert len(result["strikes"]) == 1
        assert result["strikes"][0]["strike"] == 185
        assert result["filtered_strikes"] is not None
        assert any("premium" in s.get("filtered_reason", "") for s in result["filtered_strikes"])

    def test_skip_when_all_filtered(self, tmp_path):
        """If all strikes fail filters, return SKIP."""
        options = [
            _make_option(190, "call", 0.2, 0.3, 0.28),   # mid=0.25
            _make_option(195, "call", 0.1, 0.2, 0.18),   # mid=0.15
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30, min_premium=0.50)

        assert result["action"] == "SKIP"
        assert len(result["reasons"]) > 0


class TestLiquidityFilter:
    """Test improved liquidity checks."""

    def test_wide_spread_filtered(self, tmp_path):
        """Options with > 15% bid-ask spread should fail liquidity."""
        options = [
            _make_option(185, "call", 1.0, 3.0, 0.30, oi=500),  # spread 100%!
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30)

        assert result["action"] == "SKIP"

    def test_low_oi_filtered(self, tmp_path):
        """Options with OI < 100 should fail liquidity."""
        options = [
            _make_option(185, "call", 2.0, 2.2, 0.30, oi=50, volume=10),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30)

        assert result["action"] == "SKIP"

    def test_no_bid_filtered(self, tmp_path):
        """Options with bid=0 should fail liquidity."""
        options = [
            _make_option(185, "call", 0, 2.0, 0.30, oi=500),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30)

        assert result["action"] == "SKIP"

    def test_good_liquidity_passes(self, tmp_path):
        """Options with tight spread, good OI, and real bid should pass."""
        options = [
            _make_option(185, "call", 2.0, 2.1, 0.30, oi=5000, volume=1000),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30)

        assert result["action"] == "TRADE"
        assert result["strikes"][0]["liquidity_pass"] is True
        assert result["strikes"][0]["spread_pct"] < 15


class TestCostBasisFlag:
    """Test cost basis awareness for covered calls."""

    def test_flags_below_cost_basis(self, tmp_path):
        """CC strike below cost basis should be flagged."""
        options = [
            _make_option(185, "call", 2.0, 2.05, 0.30),
            _make_option(190, "call", 1.0, 1.05, 0.25),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30, cost_basis=188.0)

        assert result["action"] == "TRADE"
        strike_185 = next(s for s in result["strikes"] if s["strike"] == 185)
        strike_190 = next(s for s in result["strikes"] if s["strike"] == 190)
        assert strike_185["below_cost_basis"] is True
        assert strike_190["below_cost_basis"] is False


class TestCustomStrikes:
    """Test backward compatibility with custom strike selection."""

    def test_custom_strikes_bypass_delta(self, tmp_path):
        """Custom strikes should work regardless of trend/delta settings."""
        options = [
            _make_option(185, "call", 2.0, 2.2, 0.80),  # high delta — normally filtered
            _make_option(190, "call", 1.0, 1.2, 0.05),   # low delta — normally filtered
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30,
                                 custom_strikes=[185.0, 190.0])

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 185 in strikes
        assert 190 in strikes


class TestLegacyFallback:
    """Test that legacy % OTM mode still works when no trend specified."""

    def test_legacy_neutral_market(self, tmp_path):
        """Without --trend, should use legacy % OTM selection."""
        options = [
            _make_option(182.5, "call", 3.0, 3.2, 0.45),
            _make_option(185, "call", 2.0, 2.2, 0.35),
            _make_option(190, "call", 1.0, 1.2, 0.25),
            _make_option(195, "call", 0.5, 0.7, 0.15),
        ]
        filepath = _make_chain_file(options, tmp_path)

        # No trend = legacy mode
        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 market="neutral", dte=30)

        assert result["action"] == "TRADE"
        # Legacy neutral pcts are [1.02, 1.05, 1.08] → 183.6, 189, 194.4
        # Rounded to step=2.5 → 182.5, 190.0, 195.0
        strikes = [s["strike"] for s in result["strikes"]]
        assert len(strikes) > 0


class TestDynamicPremiumThreshold:
    """Test dynamic premium floor that scales with stock price."""

    def test_expensive_stock_higher_floor(self, tmp_path):
        """For a $500 stock, dynamic floor = max(0.50, 500*0.002) = $1.00."""
        options = [
            _make_option(510, "call", 0.70, 0.90, 0.30, oi=500),  # mid=0.80 < $1.00
            _make_option(520, "call", 1.50, 1.60, 0.25, oi=500),   # mid=1.55 > $1.00
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=500.0, option_type="call",
                                 trend="neutral", dte=30, min_premium=0.50)

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 520 in strikes
        assert 510 not in strikes  # filtered by dynamic floor

    def test_cheap_stock_uses_explicit_min(self, tmp_path):
        """For a $20 stock, dynamic floor = max(0.50, 20*0.002) = $0.50 (explicit wins)."""
        options = [
            _make_option(21, "call", 0.40, 0.50, 0.30, oi=500),   # mid=0.45 < $0.50
            _make_option(22, "call", 0.60, 0.65, 0.25, oi=500),   # mid=0.625 > $0.50
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=20.0, option_type="call",
                                 trend="neutral", dte=30, min_premium=0.50)

        assert result["action"] == "TRADE"
        strikes = [s["strike"] for s in result["strikes"]]
        assert 22 in strikes
        assert 21 not in strikes


class TestUseMidPrice:
    """Test --use-mid flag for yield calculation on liquid options."""

    def test_use_mid_tight_spread(self, tmp_path):
        """With use_mid=True and tight spread (<5%), yield uses mid."""
        options = [
            _make_option(185, "call", 2.00, 2.08, 0.30, oi=5000),  # spread ~3.9%
        ]
        filepath = _make_chain_file(options, tmp_path)

        result_bid = extract_strikes(filepath, current_price=180.0, option_type="call",
                                     trend="neutral", dte=30, use_mid=False)
        result_mid = extract_strikes(filepath, current_price=180.0, option_type="call",
                                     trend="neutral", dte=30, use_mid=True)

        bid_yield = result_bid["strikes"][0]["ann_yield_pct"]
        mid_yield = result_mid["strikes"][0]["ann_yield_pct"]
        # Mid yield should be higher than bid yield
        assert mid_yield > bid_yield

    def test_use_mid_wide_spread_falls_back_to_bid(self, tmp_path):
        """With use_mid=True but wide spread (>5%), yield falls back to bid."""
        # Spread = (2.30-2.00)/2.15 = ~14% — passes liquidity (<=15%) but > 5% threshold
        options = [
            _make_option(185, "call", 2.00, 2.30, 0.30, oi=5000),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result_bid = extract_strikes(filepath, current_price=180.0, option_type="call",
                                     trend="neutral", dte=30, use_mid=False)
        result_mid = extract_strikes(filepath, current_price=180.0, option_type="call",
                                     trend="neutral", dte=30, use_mid=True)

        # Wide spread → both should use bid → same yield
        assert result_bid["action"] == "TRADE"
        assert result_mid["action"] == "TRADE"
        bid_yield = result_bid["strikes"][0]["ann_yield_pct"]
        mid_yield = result_mid["strikes"][0]["ann_yield_pct"]
        assert bid_yield == mid_yield


class TestOutputFields:
    """Test that output includes all expected fields."""

    def test_enriched_fields(self, tmp_path):
        """Each strike should have all expected metric fields."""
        options = [
            _make_option(185, "call", 2.0, 2.2, 0.30, oi=5000, volume=1000),
        ]
        filepath = _make_chain_file(options, tmp_path)

        result = extract_strikes(filepath, current_price=180.0, option_type="call",
                                 trend="neutral", dte=30, cost_basis=188.0)

        assert result["action"] == "TRADE"
        s = result["strikes"][0]

        # Core fields
        assert "strike" in s
        assert "bid" in s
        assert "ask" in s
        assert "mid" in s
        assert "delta" in s
        assert "theta" in s
        assert "iv_pct" in s
        assert "prob_profit_pct" in s
        assert "ann_yield_pct" in s
        assert "otm_pct" in s

        # New liquidity fields
        assert "spread_pct" in s
        assert "liquidity_pass" in s
        assert "liquidity_issues" in s
        assert isinstance(s["liquidity_issues"], list)

        # Cost basis field
        assert "below_cost_basis" in s
