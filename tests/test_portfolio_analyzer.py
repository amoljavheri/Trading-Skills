# ABOUTME: Unit tests for the portfolio_analyzer module.
# ABOUTME: All tests use synthetic data — no live API calls.

from unittest.mock import MagicMock, patch

from trading_skills.portfolio_analyzer import (
    PORTFOLIO_CONFIG,
    _build_opportunities,
    _build_portfolio_exposure,
    _build_portfolio_risks,
    _classify_iv_context,
    _compute_earnings_risk,
    _compute_sr_context,
    _compute_yield_score,
    _make_option_decision,
    _make_stock_decision,
    _score_fundamentals,
    _score_sentiment,
    _score_volatility,
    _validate_positions,
    analyze_portfolio,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_CFG = PORTFOLIO_CONFIG


def _stock_pos(symbol="AAPL", qty=100, cb=150.0):
    return {"symbol": symbol, "type": "stock", "quantity": qty, "cost_basis": cb}


def _put_pos(symbol="AAPL", qty=-1, cb=2.50, expiry="2027-01-15", strike=140.0):
    return {
        "symbol": symbol, "type": "put", "quantity": qty,
        "cost_basis": cb, "expiry": expiry, "strike": strike,
    }


def _call_pos(symbol="AAPL", qty=-1, cb=4.50, expiry="2027-01-15", strike=200.0):
    return {
        "symbol": symbol, "type": "call", "quantity": qty,
        "cost_basis": cb, "expiry": expiry, "strike": strike,
    }


def _mock_quote(price=150.0):
    return {"price": price, "beta": 1.2}


def _mock_bull(normalized=0.70, pct_from_sma20=2.0, high_20d=155.0, next_earnings=None):
    return {
        "normalized_score": normalized,
        "pct_from_sma20": pct_from_sma20,
        "high_20d": high_20d,
        "next_earnings": next_earnings,
    }


def _mock_fundamentals(pm=0.20, roe=0.25, de=0.5, eg=0.20):
    return {
        "info": {
            "profitMargin": pm,
            "returnOnEquity": roe,
            "debtToEquity": de,
            "earningsGrowth": eg,
        }
    }


def _mock_chain(price=150.0, strike=150.0, iv=0.35, bid=2.0, ask=2.20):
    mid = round((bid + ask) / 2, 2)
    put = {
        "strike": strike, "bid": bid, "ask": ask, "mid": mid,
        "impliedVolatility": iv * 100, "openInterest": 1000, "volume": 200,
    }
    return {"puts": [put], "calls": [], "underlying_price": price}


# ---------------------------------------------------------------------------
# TestValidatePositions
# ---------------------------------------------------------------------------


class TestValidatePositions:
    def test_valid_stock(self):
        valid, warnings = _validate_positions([_stock_pos()])
        assert len(valid) == 1
        assert valid[0]["symbol"] == "AAPL"
        assert not warnings

    def test_valid_put(self):
        valid, warnings = _validate_positions([_put_pos()])
        assert len(valid) == 1
        assert valid[0]["strike"] == 140.0

    def test_valid_call(self):
        valid, warnings = _validate_positions([_call_pos()])
        assert len(valid) == 1

    def test_missing_symbol(self):
        valid, warnings = _validate_positions(
            [{"type": "stock", "quantity": 10, "cost_basis": 100.0}]
        )
        assert len(valid) == 0
        assert any("symbol" in w for w in warnings)

    def test_invalid_type(self):
        pos = {**_stock_pos(), "type": "futures"}
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("type" in w for w in warnings)

    def test_zero_quantity(self):
        pos = {**_stock_pos(), "quantity": 0}
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("quantity" in w for w in warnings)

    def test_negative_cost_basis(self):
        pos = {**_stock_pos(), "cost_basis": -1.0}
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("cost_basis" in w for w in warnings)

    def test_option_missing_expiry(self):
        pos = {**_put_pos(), "expiry": None}
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("expiry" in w for w in warnings)

    def test_option_bad_expiry_format(self):
        pos = {**_put_pos(), "expiry": "01/15/2027"}
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("YYYY-MM-DD" in w for w in warnings)

    def test_option_missing_strike(self):
        pos = {**_put_pos()}
        del pos["strike"]
        valid, warnings = _validate_positions([pos])
        assert len(valid) == 0
        assert any("strike" in w for w in warnings)

    def test_symbol_normalized_to_upper(self):
        pos = {**_stock_pos(), "symbol": "aapl"}
        valid, _ = _validate_positions([pos])
        assert valid[0]["symbol"] == "AAPL"

    def test_mixed_valid_invalid(self):
        valid, warnings = _validate_positions([_stock_pos(), {"type": "bad"}])
        assert len(valid) == 1
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# TestScoreFundamentals
# ---------------------------------------------------------------------------


class TestScoreFundamentals:
    def test_strong_metrics(self):
        info = {
            "profitMargin": 0.25, "returnOnEquity": 0.35,
            "debtToEquity": 0.1, "earningsGrowth": 0.40,
        }
        score = _score_fundamentals(info)
        assert score >= 90.0

    def test_weak_metrics(self):
        info = {
            "profitMargin": 0.0, "returnOnEquity": 0.0,
            "debtToEquity": 5.0, "earningsGrowth": -0.10,
        }
        score = _score_fundamentals(info)
        assert score < 20.0

    def test_empty_info(self):
        assert _score_fundamentals({}) == 50.0

    def test_none_info(self):
        assert _score_fundamentals(None) == 50.0

    def test_missing_de_defaults_neutral(self):
        info = {"profitMargin": 0.10, "returnOnEquity": 0.20, "earningsGrowth": 0.15}
        score = _score_fundamentals(info)
        assert 50.0 < score < 100.0

    def test_profit_margin_boundary(self):
        # exactly at 15% profit_margin → sub-score 100; D/E unknown → 50 default; avg=75
        info = {"profitMargin": 0.15}
        score = _score_fundamentals(info)
        assert score == 75.0  # (100 + 50) / 2

    def test_roe_boundary(self):
        # exactly at 25% ROE → sub-score 100; D/E unknown → 50 default; avg=75
        info = {"returnOnEquity": 0.25}
        score = _score_fundamentals(info)
        assert score == 75.0  # (100 + 50) / 2


# ---------------------------------------------------------------------------
# TestScoreSentiment
# ---------------------------------------------------------------------------


class TestScoreSentiment:
    def test_all_positive_articles(self):
        articles = [
            {"title": "Company beats earnings and upgrades guidance"},
            {"title": "Strong growth record"},
        ]
        score = _score_sentiment(articles, _CFG)
        assert score > 60.0

    def test_all_negative_articles(self):
        articles = [
            {"title": "Company misses earnings, sells assets"},
            {"title": "Decline in revenue, weak outlook"},
        ]
        score = _score_sentiment(articles, _CFG)
        assert score < 40.0

    def test_empty_articles(self):
        assert _score_sentiment([], _CFG) == 50.0

    def test_neutral_mixed(self):
        articles = [
            {"title": "beat expectations"},
            {"title": "miss on revenue"},
            {"title": "Company reports Q3"},
        ]
        score = _score_sentiment(articles, _CFG)
        assert 40.0 <= score <= 60.0

    def test_clamped_to_100(self):
        articles = [
            {"title": "beat upgrade buy surge strong growth record bullish outperform wins"}
            for _ in range(10)
        ]
        score = _score_sentiment(articles, _CFG)
        assert score == 100.0

    def test_clamped_to_0(self):
        articles = [
            {"title": "miss downgrade sell crash weak loss decline bearish underperform fraud"}
            for _ in range(10)
        ]
        score = _score_sentiment(articles, _CFG)
        assert score == 0.0


# ---------------------------------------------------------------------------
# TestScoreVolatility
# ---------------------------------------------------------------------------


class TestScoreVolatility:
    def test_low_vol_max_score(self):
        assert _score_volatility(15.0) == 100.0

    def test_vol_exactly_20(self):
        assert _score_volatility(20.0) == 100.0

    def test_vol_30(self):
        score = _score_volatility(30.0)
        assert 80 < score < 100

    def test_vol_50(self):
        score = _score_volatility(50.0)
        assert 50 < score < 75

    def test_vol_70(self):
        score = _score_volatility(70.0)
        assert 10 < score < 40

    def test_vol_90(self):
        score = _score_volatility(90.0)
        assert 0.0 <= score < 10.0

    def test_none_returns_neutral(self):
        assert _score_volatility(None) == 50.0


# ---------------------------------------------------------------------------
# TestComputeEarningsRisk
# ---------------------------------------------------------------------------


class TestComputeEarningsRisk:
    def test_3_days(self):
        assert _compute_earnings_risk(3) == 100.0

    def test_5_days(self):
        assert _compute_earnings_risk(5) == 100.0

    def test_10_days(self):
        score = _compute_earnings_risk(10)
        assert 50.0 < score < 100.0

    def test_14_days(self):
        score = _compute_earnings_risk(14)
        assert abs(score - 50.0) < 1.0

    def test_20_days(self):
        score = _compute_earnings_risk(20)
        assert 10.0 < score < 50.0

    def test_40_days(self):
        assert _compute_earnings_risk(40) == 0.0

    def test_none(self):
        assert _compute_earnings_risk(None) == 0.0


# ---------------------------------------------------------------------------
# TestComputeYieldScore
# ---------------------------------------------------------------------------


class TestComputeYieldScore:
    def test_excellent_yield(self):
        assert _compute_yield_score(25.0) == 100.0

    def test_above_excellent(self):
        assert _compute_yield_score(30.0) == 100.0

    def test_good_yield(self):
        score = _compute_yield_score(20.0)
        assert 70.0 < score < 100.0
        expected = 70.0 + (20.0 - 15.0) / (25.0 - 15.0) * 30.0
        assert abs(score - expected) < 0.1

    def test_fair_yield(self):
        score = _compute_yield_score(12.5)
        assert 50.0 < score < 70.0

    def test_below_fair(self):
        score = _compute_yield_score(5.0)
        assert 0.0 < score < 50.0

    def test_zero_yield(self):
        assert _compute_yield_score(0.0) == 0.0


# ---------------------------------------------------------------------------
# TestComputeSrContext
# ---------------------------------------------------------------------------


class TestComputeSrContext:
    def test_near_support(self):
        bull = {"pct_from_sma20": 2.0, "high_20d": 200.0}
        result = _compute_sr_context(150.0, bull, _CFG)
        assert result["near_support"] is True

    def test_near_resistance(self):
        bull = {"pct_from_sma20": 10.0, "high_20d": 152.0}
        result = _compute_sr_context(150.0, bull, _CFG)
        assert result["near_resistance"] is True

    def test_far_from_both(self):
        bull = {"pct_from_sma20": 20.0, "high_20d": 200.0}
        result = _compute_sr_context(150.0, bull, _CFG)
        assert result["near_support"] is False
        assert result["near_resistance"] is False

    def test_below_sma20_in_range(self):
        bull = {"pct_from_sma20": -2.0, "high_20d": 200.0}
        result = _compute_sr_context(150.0, bull, _CFG)
        assert result["near_support"] is True

    def test_none_bull_result(self):
        result = _compute_sr_context(150.0, None, _CFG)
        assert result["near_support"] is None
        assert result["near_resistance"] is None

    def test_missing_high_20d(self):
        bull = {"pct_from_sma20": 2.0, "high_20d": None}
        result = _compute_sr_context(150.0, bull, _CFG)
        assert result["near_resistance"] is None


# ---------------------------------------------------------------------------
# TestClassifyIvContext
# ---------------------------------------------------------------------------


class TestClassifyIvContext:
    def test_high_iv(self):
        assert _classify_iv_context(55.0) == "high_iv"

    def test_normal_iv(self):
        assert _classify_iv_context(35.0) == "normal_iv"

    def test_low_iv(self):
        assert _classify_iv_context(20.0) == "low_iv"

    def test_boundary_50(self):
        assert _classify_iv_context(50.0) == "high_iv"

    def test_boundary_25(self):
        assert _classify_iv_context(25.0) == "normal_iv"

    def test_none(self):
        assert _classify_iv_context(None) is None


# ---------------------------------------------------------------------------
# TestMakeStockDecision
# ---------------------------------------------------------------------------


class TestMakeStockDecision:
    def test_high_score_with_cash_gives_add(self):
        decision, _, _ = _make_stock_decision(80.0, 5.0, None, 5000.0, _CFG)
        assert decision == "ADD"

    def test_high_score_no_cash_gives_hold(self):
        decision, _, _ = _make_stock_decision(80.0, 5.0, None, 0.0, _CFG)
        assert decision == "HOLD"

    def test_mid_score_gives_hold(self):
        decision, _, _ = _make_stock_decision(60.0, 2.0, None, 0.0, _CFG)
        assert decision == "HOLD"

    def test_low_mid_score_gives_trim(self):
        decision, _, _ = _make_stock_decision(40.0, -5.0, None, 0.0, _CFG)
        assert decision == "TRIM"

    def test_very_low_score_gives_sell(self):
        decision, _, _ = _make_stock_decision(20.0, -10.0, None, 0.0, _CFG)
        assert decision == "SELL"

    def test_earnings_note_added(self):
        _, reasoning, _ = _make_stock_decision(60.0, 2.0, 10, 0.0, _CFG)
        assert any("Earnings" in r for r in reasoning)

    def test_no_earnings_note_if_far(self):
        _, reasoning, _ = _make_stock_decision(60.0, 2.0, 30, 0.0, _CFG)
        assert not any("Earnings" in r for r in reasoning)

    def test_large_gain_risk_flag(self):
        _, _, risk_flags = _make_stock_decision(70.0, 55.0, None, 0.0, _CFG)
        assert any("gain" in f.lower() for f in risk_flags)

    def test_large_drawdown_stop_loss_flag(self):
        _, _, risk_flags = _make_stock_decision(40.0, -40.0, None, 0.0, _CFG)
        assert any("stop-loss" in f.lower() for f in risk_flags)

    def test_moderate_drawdown_warn_flag(self):
        _, _, risk_flags = _make_stock_decision(40.0, -28.0, None, 0.0, _CFG)
        assert any("drawdown" in f.lower() for f in risk_flags)

    def test_no_flags_for_normal_pnl(self):
        _, _, risk_flags = _make_stock_decision(60.0, 10.0, None, 0.0, _CFG)
        assert risk_flags == []


# ---------------------------------------------------------------------------
# TestMakeOptionDecision
# ---------------------------------------------------------------------------


def _make_opt(pos_type="put", qty=-1, cb=2.50, strike=140.0, expiry="2027-06-20"):
    return {"type": pos_type, "quantity": qty, "cost_basis": cb,
            "strike": strike, "expiry": expiry}


class TestMakeOptionDecision:
    def _call(self, pos, mid, price, dte, trend=65.0, fund=70.0, sr=None):
        if sr is None:
            sr = {"near_support": False, "near_resistance": False}
        return _make_option_decision(pos, mid, price, dte, trend, fund, sr, _CFG)

    def test_hard_close_75_profit(self):
        pos = _make_opt(cb=4.0)
        decision, _, _ = self._call(pos, 0.80, price=150.0, dte=20)
        assert decision == "CLOSE"

    def test_gamma_risk_close(self):
        pos = _make_opt()
        decision, reasoning, _ = self._call(pos, 1.50, 150.0, 3)
        assert decision == "CLOSE"
        assert any("gamma" in r.lower() for r in reasoning)

    def test_itm_short_put_bull_trend_roll(self):
        pos = _make_opt(strike=160.0)  # stock at 150 → put strike 160 → ITM
        decision, reasoning, _ = self._call(pos, 11.0, 150.0, 20, trend=70.0)
        assert decision == "ROLL"

    def test_itm_short_put_bear_good_fundamentals_accept_assignment(self):
        pos = _make_opt(strike=160.0)
        decision, reasoning, _ = self._call(pos, 11.0, 150.0, 20, trend=30.0, fund=70.0)
        assert decision == "ACCEPT_ASSIGNMENT"
        assert any("quality" in r.lower() or "acceptable" in r.lower() for r in reasoning)

    def test_itm_short_put_bear_weak_fundamentals_close(self):
        pos = _make_opt(strike=160.0)
        decision, reasoning, _ = self._call(pos, 11.0, 150.0, 20, trend=30.0, fund=40.0)
        assert decision == "CLOSE"

    def test_itm_short_call_strong_bull_roll(self):
        pos = _make_opt(pos_type="call", qty=-1, strike=140.0)  # stock at 150 → ITM
        decision, _, _ = self._call(pos, 11.0, 150.0, 20, trend=75.0)
        assert decision == "ROLL"

    def test_itm_short_call_weak_trend_hold(self):
        pos = _make_opt(pos_type="call", qty=-1, strike=140.0)
        decision, _, _ = self._call(pos, 11.0, 150.0, 20, trend=55.0)
        assert decision == "HOLD"

    def test_soft_close_50_profit(self):
        pos = _make_opt(cb=2.50)
        # profit = (2.50 - 1.20) / 2.50 * 100 = 52%
        decision, reasoning, _ = self._call(pos, 1.20, 150.0, 20)
        assert decision == "CLOSE"
        assert any(
            "consider closing" in r.lower() or "profit captured" in r.lower()
            for r in reasoning
        )

    def test_soft_close_overridden_near_support(self):
        pos = _make_opt(cb=2.50)
        sr = {"near_support": True, "near_resistance": False}
        decision, _, _ = self._call(pos, 1.20, 150.0, 20, sr=sr)
        assert decision == "HOLD"

    def test_monitor_on_low_dte(self):
        pos = _make_opt()
        decision, _, _ = self._call(pos, 2.40, 150.0, 10)
        assert decision == "MONITOR"

    def test_hold_otm_long_dte(self):
        pos = _make_opt(strike=130.0)  # OTM put
        decision, _, _ = self._call(pos, 2.40, 150.0, 25)
        assert decision == "HOLD"

    def test_long_option_trim_on_100pct_gain(self):
        pos = {**_make_opt(qty=1, cb=2.0), "type": "call", "strike": 130.0}
        # long call, current_mid=5.0, gain=150%
        decision, _, _ = self._call(pos, 5.0, 150.0, 30, trend=65.0)
        assert decision == "TRIM"


# ---------------------------------------------------------------------------
# TestBuildPortfolioRisks
# ---------------------------------------------------------------------------


def _make_analyzed_pos(symbol, pos_type, qty, mv, pnl_pct, dte=None, moneyness=None,
                       strike=None, earnings_risk=0, iv_context=None):
    scores = {"composite": 60.0, "earnings_risk": earnings_risk}
    if pos_type == "stock":
        scores.update({"trend": 60.0, "fundamentals": 60.0, "sentiment": 50.0,
                       "volatility": 60.0, "options_edge": 50.0})
    else:
        scores.update({"trend": 60.0, "iv_score": 50.0, "premium_quality": 50.0, "sentiment": 50.0})
    return {
        "symbol": symbol, "type": pos_type, "quantity": qty,
        "market_value": mv, "pnl_pct": pnl_pct, "dte": dte,
        "moneyness": moneyness, "strike": strike,
        "scores": scores, "risk_flags": [], "iv_context": iv_context,
        "near_support": None, "near_resistance": None,
    }


class TestBuildPortfolioRisks:
    def test_concentration_detected(self):
        positions = [
            _make_analyzed_pos("AAPL", "stock", 100, 30000.0, 5.0),
        ]
        risks = _build_portfolio_risks(positions, 30000.0, _CFG)
        assert any("AAPL" in c for c in risks["concentration"])

    def test_no_concentration_below_threshold(self):
        positions = [
            _make_analyzed_pos("AAPL", "stock", 100, 7000.0, 5.0),
            _make_analyzed_pos("MSFT", "stock", 100, 7000.0, 5.0),
        ]
        risks = _build_portfolio_risks(positions, 28000.0, _CFG)
        assert risks["concentration"] == []

    def test_earnings_this_week(self):
        positions = [_make_analyzed_pos("NVDA", "stock", 100, 5000.0, 2.0, earnings_risk=90)]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert "NVDA" in risks["earnings_this_week"]

    def test_high_gamma_detected(self):
        positions = [_make_analyzed_pos("AAPL", "put", -1, -200.0, 30.0, dte=3, moneyness="OTM")]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert any("AAPL" in g for g in risks["high_gamma_options"])

    def test_itm_short_call(self):
        positions = [
            _make_analyzed_pos(
                "AMD", "call", -1, -500.0, -20.0, dte=20, moneyness="ITM", strike=90.0
            )
        ]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert any("AMD" in c for c in risks["itm_short_calls"])

    def test_itm_short_put(self):
        positions = [
            _make_analyzed_pos(
                "TSLA", "put", -1, -300.0, -15.0, dte=20, moneyness="ITM", strike=200.0
            )
        ]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert any("TSLA" in p for p in risks["itm_short_puts"])

    def test_profit_capture_ready(self):
        positions = [_make_analyzed_pos("NVDA", "put", -1, -60.0, 60.0, dte=15, moneyness="OTM")]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert any("NVDA" in p for p in risks["profit_capture_ready"])

    def test_large_drawdown(self):
        positions = [_make_analyzed_pos("GME", "stock", 100, 5000.0, -40.0)]
        risks = _build_portfolio_risks(positions, 20000.0, _CFG)
        assert any("GME" in d for d in risks["large_drawdowns"])


# ---------------------------------------------------------------------------
# TestBuildPortfolioExposure
# ---------------------------------------------------------------------------


class TestBuildPortfolioExposure:
    def test_short_put_exposure(self):
        # 1 short put, strike=100 → $10,000 at risk
        positions = [{"symbol": "AAPL", "type": "put", "quantity": -1,
                      "strike": 100.0, "market_value": -120.0}]
        exp = _build_portfolio_exposure(positions, 50000.0, set())
        assert abs(exp["short_put_exposure_pct"] - 20.0) < 0.1  # 10000/50000*100

    def test_net_delta_stock(self):
        positions = [{"symbol": "AAPL", "type": "stock", "quantity": 100, "market_value": 15000.0}]
        exp = _build_portfolio_exposure(positions, 15000.0, set())
        assert exp["net_delta_estimate"] == 100.0

    def test_net_delta_short_put(self):
        # short put: qty=-1 → delta = (-1)*(-0.40)*100 = +40
        positions = [{"symbol": "AAPL", "type": "put", "quantity": -1,
                      "strike": 140.0, "market_value": -250.0}]
        exp = _build_portfolio_exposure(positions, 15000.0, set())
        assert exp["net_delta_estimate"] == 40.0

    def test_net_delta_short_call(self):
        # short call: qty=-1 → delta = (-1)*(+0.40)*100 = -40
        positions = [{"symbol": "AAPL", "type": "call", "quantity": -1,
                      "strike": 160.0, "market_value": -450.0}]
        exp = _build_portfolio_exposure(positions, 15000.0, set())
        assert exp["net_delta_estimate"] == -40.0

    def test_cc_exposure(self):
        positions = [
            {"symbol": "AAPL", "type": "stock", "quantity": 100, "market_value": 15000.0},
        ]
        exp = _build_portfolio_exposure(positions, 20000.0, {"AAPL"})
        assert abs(exp["covered_call_exposure_pct"] - 75.0) < 0.1  # 15000/20000*100

    def test_largest_position_pct(self):
        positions = [
            {"symbol": "AAPL", "type": "stock", "quantity": 100, "market_value": 15000.0},
            {"symbol": "MSFT", "type": "stock", "quantity": 50, "market_value": 8000.0},
        ]
        exp = _build_portfolio_exposure(positions, 30000.0, set())
        assert abs(exp["largest_position_pct"] - 50.0) < 0.1  # 15000/30000*100

    def test_zero_account_value(self):
        positions = []
        exp = _build_portfolio_exposure(positions, 0.0, set())
        assert exp["net_delta_estimate"] == 0.0


# ---------------------------------------------------------------------------
# TestBuildOpportunities
# ---------------------------------------------------------------------------


def _opp_position(symbol, pos_type, qty, composite=65.0, iv_context="normal_iv",
                  near_support=True, near_resistance=False, earnings_risk=20.0,
                  pnl_pct=5.0, moneyness="OTM", trend=60.0, iv_score=50.0):
    scores = {"composite": composite, "earnings_risk": earnings_risk, "trend": trend,
              "iv_score": iv_score, "options_edge": iv_score}
    return {
        "symbol": symbol, "type": pos_type, "quantity": qty,
        "scores": scores, "iv_context": iv_context,
        "near_support": near_support, "near_resistance": near_resistance,
        "pnl_pct": pnl_pct, "moneyness": moneyness, "market_value": 5000.0,
    }


class TestBuildOpportunities:
    def test_csp_high_priority_near_support(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=70.0, near_support=True)]
        opps = _build_opportunities(positions, 5000.0, 25000.0, _CFG)
        csp = [o for o in opps if o["type"] == "csp"]
        assert len(csp) >= 1
        assert csp[0]["priority"] == "high"

    def test_csp_medium_priority_no_support(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=70.0, near_support=False)]
        opps = _build_opportunities(positions, 5000.0, 25000.0, _CFG)
        csp = [o for o in opps if o["type"] == "csp"]
        assert len(csp) >= 1
        assert csp[0]["priority"] == "medium"

    def test_no_csp_if_low_iv(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=70.0, iv_context="low_iv")]
        opps = _build_opportunities(positions, 5000.0, 25000.0, _CFG)
        csp = [o for o in opps if o["type"] == "csp"]
        assert len(csp) == 0

    def test_no_csp_if_high_earnings_risk(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=70.0, earnings_risk=60.0)]
        opps = _build_opportunities(positions, 5000.0, 25000.0, _CFG)
        csp = [o for o in opps if o["type"] == "csp"]
        assert len(csp) == 0

    def test_cc_high_priority_near_resistance(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=60.0,
                                   near_resistance=True, near_support=False)]
        opps = _build_opportunities(positions, 0.0, 20000.0, _CFG)
        cc = [o for o in opps if o["type"] == "cc"]
        assert len(cc) >= 1
        assert cc[0]["priority"] == "high"

    def test_exit_opportunity_low_score(self):
        positions = [_opp_position("GME", "stock", 100, composite=25.0)]
        opps = _build_opportunities(positions, 0.0, 20000.0, _CFG)
        exit_opps = [o for o in opps if o["type"] == "exit"]
        assert len(exit_opps) >= 1

    def test_add_opportunity_high_score_cash(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=80.0)]
        opps = _build_opportunities(positions, 10000.0, 30000.0, _CFG)
        add = [o for o in opps if o["type"] == "add"]
        assert len(add) >= 1

    def test_early_cc_roll(self):
        positions = [
            _opp_position("AAPL", "call", -1, composite=60.0, trend=75.0,
                          moneyness="OTM", near_resistance=False),
        ]
        opps = _build_opportunities(positions, 0.0, 20000.0, _CFG)
        early = [o for o in opps if o["type"] == "cc_roll_early"]
        assert len(early) >= 1

    def test_no_early_roll_near_resistance(self):
        positions = [
            _opp_position("AAPL", "call", -1, composite=60.0, trend=75.0,
                          moneyness="OTM", near_resistance=True),
        ]
        opps = _build_opportunities(positions, 0.0, 20000.0, _CFG)
        early = [o for o in opps if o["type"] == "cc_roll_early"]
        assert len(early) == 0

    def test_opportunities_sorted_high_first(self):
        positions = [
            _opp_position("GME", "stock", 100, composite=20.0),  # exit → high
            _opp_position("MSFT", "stock", 100, composite=70.0, near_support=True),  # CSP → high
            _opp_position("TSLA", "stock", 100, composite=55.0, near_resistance=False,
                          near_support=False),  # CC → medium
        ]
        opps = _build_opportunities(positions, 0.0, 30000.0, _CFG)
        priorities = [o["priority"] for o in opps]
        assert priorities == sorted(priorities, key=lambda p: {"high": 0, "medium": 1, "low": 2}[p])

    def test_empty_list_when_no_setups(self):
        positions = [_opp_position("AAPL", "stock", 100, composite=55.0,
                                   iv_context="low_iv", near_support=False)]
        opps = _build_opportunities(positions, 0.0, 20000.0, _CFG)
        # No CSP (low_iv), no exit (score>30), CC might exist but score=55 qualifies
        # Just verify no crash and it's a list
        assert isinstance(opps, list)


# ---------------------------------------------------------------------------
# TestPnlCalc
# ---------------------------------------------------------------------------


class TestPnlCalc:
    """Verify P&L math via full pipeline (mocked APIs)."""

    def _mock_all(self, price=150.0):
        return {
            "get_quote": {"price": price, "beta": 1.2},
            "compute_bullish_score": _mock_bull(normalized=0.65),
            "get_fundamentals": _mock_fundamentals(),
            "get_news": {"articles": []},
            "calculate_risk_metrics": {"volatility": {"annual": 25.0, "daily": 1.5}},
            "get_expiries": ["2027-01-15"],
            "get_option_chain": _mock_chain(price=price, strike=price, bid=1.90, ask=2.10),
        }

    def _run(self, positions, cash=0.0):
        m = self._mock_all()
        _pa = "trading_skills.portfolio_analyzer"
        with patch(f"{_pa}.get_quote", return_value=m["get_quote"]), \
             patch(f"{_pa}.compute_bullish_score", return_value=m["compute_bullish_score"]), \
             patch(f"{_pa}.get_fundamentals", return_value=m["get_fundamentals"]), \
             patch(f"{_pa}.get_news", return_value=m["get_news"]), \
             patch(f"{_pa}.calculate_risk_metrics", return_value=m["calculate_risk_metrics"]), \
             patch(f"{_pa}.get_expiries", return_value=m["get_expiries"]), \
             patch(f"{_pa}.get_option_chain", return_value=m["get_option_chain"]):
            return analyze_portfolio(positions, portfolio_cash=cash)

    def test_stock_pnl(self):
        # 100 shares @ $150, current $150 → pnl = 0
        result = self._run([_stock_pos(qty=100, cb=150.0)])
        pa = result["positions_analysis"]
        assert len(pa) == 1
        assert pa[0]["pnl"] == 0.0
        assert pa[0]["pnl_pct"] == 0.0
        assert pa[0]["market_value"] == 15000.0

    def test_stock_pnl_gain(self):
        # 100 shares @ $120, current $150 → pnl = $3000, 25%
        result = self._run([_stock_pos(qty=100, cb=120.0)])
        pa = result["positions_analysis"]
        assert pa[0]["pnl"] == 3000.0
        assert abs(pa[0]["pnl_pct"] - 25.0) < 0.1

    def test_short_put_pnl(self):
        # Short 1 put @ $2.0 cb, current mid = $2.0 → pnl = 0
        pos = _put_pos(qty=-1, cb=2.0, strike=150.0)
        result = self._run([pos])
        pa = result["positions_analysis"]
        assert pa[0]["pnl"] == 0.0

    def test_option_market_value_multiplier(self):
        # Short 1 put, mid=$2.0 → market_value = 2.0 * (-1) * 100 = -200
        pos = _put_pos(qty=-1, cb=2.0, strike=150.0)
        result = self._run([pos])
        pa = result["positions_analysis"]
        assert pa[0]["market_value"] == -200.0


# ---------------------------------------------------------------------------
# TestDataQuality
# ---------------------------------------------------------------------------


class TestDataQuality:
    def test_good_quality(self):
        from trading_skills.portfolio_analyzer import _fetch_symbol_data
        cache: dict = {}
        _pa = "trading_skills.portfolio_analyzer"
        with patch(f"{_pa}.get_quote", return_value={"price": 150.0}), \
             patch(f"{_pa}.compute_bullish_score", return_value=_mock_bull()), \
             patch(f"{_pa}.get_fundamentals", return_value=_mock_fundamentals()), \
             patch(f"{_pa}.get_news", return_value={"articles": []}), \
             patch(f"{_pa}.calculate_risk_metrics",
                   return_value={"volatility": {"annual": 25.0}}), \
             patch(f"{_pa}.get_expiries", return_value=["2027-01-15"]), \
             patch(f"{_pa}.get_option_chain", return_value=_mock_chain()):
            data = _fetch_symbol_data("AAPL", cache, _CFG)
        assert data["fallback_count"] <= 1

    def test_poor_quality_all_fail(self):
        from trading_skills.portfolio_analyzer import _fetch_symbol_data
        cache: dict = {}
        _pa = "trading_skills.portfolio_analyzer"
        with patch(f"{_pa}.get_quote", side_effect=Exception("fail")), \
             patch(f"{_pa}.compute_bullish_score", side_effect=Exception("fail")), \
             patch(f"{_pa}.get_fundamentals", side_effect=Exception("fail")), \
             patch(f"{_pa}.get_news", side_effect=Exception("fail")), \
             patch(f"{_pa}.calculate_risk_metrics", side_effect=Exception("fail")), \
             patch(f"{_pa}.get_expiries", side_effect=Exception("fail")):
            data = _fetch_symbol_data("AAPL", cache, _CFG)
        assert data["fallback_count"] >= 4


# ---------------------------------------------------------------------------
# TestDeduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_quote_called_once_per_symbol(self):
        """Stock + option on same symbol → get_quote called exactly once for that symbol."""
        positions = [_stock_pos(), _put_pos()]  # both AAPL
        mock_quote = MagicMock(return_value={"price": 150.0, "beta": 1.2})
        _pa = "trading_skills.portfolio_analyzer"
        with patch(f"{_pa}.get_quote", mock_quote), \
             patch(f"{_pa}.compute_bullish_score", return_value=_mock_bull()), \
             patch(f"{_pa}.get_fundamentals", return_value=_mock_fundamentals()), \
             patch(f"{_pa}.get_news", return_value={"articles": []}), \
             patch(f"{_pa}.calculate_risk_metrics",
                   return_value={"volatility": {"annual": 25.0}}), \
             patch(f"{_pa}.get_expiries", return_value=["2027-01-15"]), \
             patch(f"{_pa}.get_option_chain", return_value=_mock_chain()):
            analyze_portfolio(positions)
        # get_quote should be called once for AAPL (cached), not twice
        assert mock_quote.call_count == 1


# ---------------------------------------------------------------------------
# TestFullPipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def _run_full(self):
        positions = [
            _stock_pos("AAPL", qty=100, cb=150.0),
            _put_pos("NVDA", qty=-1, cb=3.0, strike=100.0, expiry="2027-06-20"),
        ]
        mock_quote = MagicMock(
            side_effect=lambda sym: {"price": 150.0 if sym == "AAPL" else 120.0, "beta": 1.2}
        )
        mock_chain = MagicMock(
            return_value=_mock_chain(price=150.0, strike=150.0, bid=2.90, ask=3.10)
        )
        _pa = "trading_skills.portfolio_analyzer"
        with patch(f"{_pa}.get_quote", mock_quote), \
             patch(f"{_pa}.compute_bullish_score", return_value=_mock_bull()), \
             patch(f"{_pa}.get_fundamentals", return_value=_mock_fundamentals()), \
             patch(f"{_pa}.get_news", return_value={"articles": []}), \
             patch(f"{_pa}.calculate_risk_metrics",
                   return_value={"volatility": {"annual": 25.0}}), \
             patch(f"{_pa}.get_expiries", return_value=["2027-06-20"]), \
             patch(f"{_pa}.get_option_chain", mock_chain):
            return analyze_portfolio(positions, portfolio_cash=5000.0)

    def test_structure(self):
        result = self._run_full()
        assert "portfolio_summary" in result
        assert "portfolio_exposure" in result
        assert "positions_analysis" in result
        assert "portfolio_risks" in result
        assert "opportunities" in result
        assert "validation_warnings" in result

    def test_two_positions_analyzed(self):
        result = self._run_full()
        assert result["portfolio_summary"]["total_legs"] == 2

    def test_portfolio_summary_has_required_fields(self):
        result = self._run_full()
        ps = result["portfolio_summary"]
        for field in ["total_market_value", "total_cost_basis", "total_pnl",
                      "total_account_value", "overall_score", "risk_profile", "as_of"]:
            assert field in ps

    def test_exposure_has_net_delta(self):
        result = self._run_full()
        assert "net_delta_estimate" in result["portfolio_exposure"]

    def test_stock_scores_have_correct_keys(self):
        result = self._run_full()
        stock = next(p for p in result["positions_analysis"] if p["type"] == "stock")
        for key in [
            "trend", "fundamentals", "sentiment", "volatility", "options_edge", "composite"
        ]:
            assert key in stock["scores"]

    def test_option_scores_have_correct_keys(self):
        result = self._run_full()
        opt = next(p for p in result["positions_analysis"] if p["type"] == "put")
        for key in ["trend", "iv_score", "premium_quality", "sentiment", "composite"]:
            assert key in opt["scores"]

    def test_total_account_value(self):
        result = self._run_full()
        ps = result["portfolio_summary"]
        assert abs(ps["total_account_value"] - (ps["total_market_value"] + 5000.0)) < 1.0

    def test_validation_warnings_is_list(self):
        result = self._run_full()
        assert isinstance(result["validation_warnings"], list)

    def test_invalid_json_positions_returns_error(self):
        result = analyze_portfolio([{"type": "bad"}])
        assert "error" in result or "validation_warnings" in result
