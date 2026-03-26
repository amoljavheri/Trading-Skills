# ABOUTME: Deterministic portfolio analysis engine (stocks + options).
# ABOUTME: Scores, analyzes, and generates decisions per position — no LLM reasoning.

import logging
from datetime import datetime, timezone

from trading_skills.fundamentals import get_fundamentals
from trading_skills.news import get_news
from trading_skills.options import get_expiries, get_option_chain
from trading_skills.quote import get_quote
from trading_skills.risk import calculate_risk_metrics
from trading_skills.scanner_bullish import compute_bullish_score

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORTFOLIO_CONFIG: dict = {
    "stock_weights": {
        "trend": 0.25,
        "fundamentals": 0.25,
        "sentiment": 0.10,
        "volatility": 0.10,
        "options_edge": 0.20,
        "earnings_safety": 0.10,
    },
    "option_weights": {
        "trend": 0.25,
        "iv_score": 0.25,
        "premium_quality": 0.25,
        "earnings_safety": 0.15,
        "sentiment": 0.10,
    },
    "decision_thresholds": {
        "add": 70.0,
        "hold_min": 50.0,
        "trim_min": 30.0,
        "profit_hard_close_pct": 75.0,
        "profit_soft_close_pct": 50.0,
        "itm_threshold_pct": 2.0,
        "bull_trend_roll": 60.0,
        "bull_trend_strong": 70.0,
        "dte_gamma_risk": 5,
        "dte_monitor": 14,
        "long_option_trim_pct": 100.0,
    },
    "risk_thresholds": {
        "concentration_pct": 25.0,
        "earnings_warn_days": 7,
        "drawdown_warn_pct": -25.0,
        "drawdown_stop_pct": -35.0,
        "gain_trim_pct": 50.0,
    },
    "opportunity_thresholds": {
        "csp_min_score": 60.0,
        "csp_max_earnings_risk": 50.0,
        "cc_min_score": 50.0,
        "add_min_score": 75.0,
        "cash_deploy_min_pct": 20.0,
        "early_roll_trend": 70.0,
    },
    "sentiment_keywords": {
        "positive": [
            "beat", "upgrade", "buy", "surge", "strong", "growth", "record",
            "bullish", "outperform", "raise", "expanded", "partnership", "wins",
        ],
        "negative": [
            "miss", "downgrade", "sell", "crash", "weak", "loss", "decline",
            "bearish", "underperform", "cut", "layoff", "lawsuit", "fraud", "warning",
        ],
    },
    "iv_normalization_cap": 60.0,
    "nearest_expiry_target_dte": 30,
    "near_support_range": (-3.0, 5.0),
    "near_resistance_pct": 3.0,
    "fundamentals_accept_assignment": 60.0,
    "data_quality_thresholds": {"good": 1, "partial": 3},
}

_DELTA_APPROX = 0.40  # uniform delta approximation for net-delta estimate


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_positions(positions: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate position dicts. Returns (valid_positions, warning_strings)."""
    valid: list[dict] = []
    warnings: list[str] = []
    valid_types = {"stock", "call", "put"}

    for i, pos in enumerate(positions):
        sym = pos.get("symbol")
        label = f"Position[{i}] symbol={sym!r}"

        if not sym or not isinstance(sym, str) or not sym.strip():
            warnings.append(f"{label}: missing or empty 'symbol' — skipped")
            continue

        pos_type = pos.get("type")
        if pos_type not in valid_types:
            warnings.append(
                f"{label}: invalid type {pos_type!r} (must be stock/call/put) — skipped"
            )
            continue

        qty = pos.get("quantity")
        if qty is None or not isinstance(qty, (int, float)) or int(qty) == 0:
            warnings.append(f"{label}: quantity must be a non-zero number — skipped")
            continue

        cb = pos.get("cost_basis")
        if cb is None or not isinstance(cb, (int, float)) or float(cb) <= 0:
            warnings.append(f"{label}: cost_basis must be > 0 — skipped")
            continue

        if pos_type in ("call", "put"):
            expiry = pos.get("expiry")
            if not expiry:
                warnings.append(f"{label}: options require 'expiry' (YYYY-MM-DD) — skipped")
                continue
            try:
                datetime.strptime(str(expiry), "%Y-%m-%d")
            except ValueError:
                warnings.append(
                    f"{label}: expiry {expiry!r} is not valid YYYY-MM-DD — skipped"
                )
                continue

            strike = pos.get("strike")
            if strike is None or not isinstance(strike, (int, float)) or float(strike) <= 0:
                warnings.append(f"{label}: options require 'strike' > 0 — skipped")
                continue

        valid.append({
            "symbol": str(sym).strip().upper(),
            "type": pos_type,
            "quantity": int(qty),
            "cost_basis": float(cb),
            "expiry": pos.get("expiry"),
            "strike": float(pos["strike"]) if pos_type in ("call", "put") else None,
        })

    return valid, warnings


# ---------------------------------------------------------------------------
# Data Fetching (Cached)
# ---------------------------------------------------------------------------


def _get_atm_iv(options: list[dict], price: float) -> float | None:
    """Return IV% of the option whose strike is closest to price."""
    if not options or price <= 0:
        return None
    atm = min(options, key=lambda o: abs((o.get("strike") or 0) - price))
    iv = atm.get("impliedVolatility")
    return float(iv) if iv and iv > 0 else None


def _get_nearest_expiry(expiries: list[str], target_dte: int) -> str | None:
    """Find the expiry closest to target_dte calendar days from today."""
    if not expiries:
        return None
    today = datetime.now(tz=timezone.utc).date()
    best: str | None = None
    best_diff = float("inf")
    for exp in expiries:
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            diff = abs((exp_date - today).days - target_dte)
            if diff < best_diff:
                best_diff = diff
                best = exp
        except ValueError:
            continue
    return best


def _fetch_symbol_data(symbol: str, cache: dict[str, dict], config: dict) -> dict:
    """Fetch all scoring data for a symbol (cached by symbol key).

    Returns a dict with keys:
        quote, bull, fundamentals, news, risk, chain, atm_iv, fallback_count
    Each failed data source increments fallback_count.
    """
    key = symbol.upper()
    if key in cache:
        return cache[key]

    data: dict = {
        "quote": None,
        "bull": None,
        "fundamentals": None,
        "news": None,
        "risk": None,
        "chain": None,
        "atm_iv": None,
        "fallback_count": 0,
    }

    try:
        q = get_quote(symbol)
        data["quote"] = q if "error" not in q and q.get("price") else None
        if data["quote"] is None:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    try:
        b = compute_bullish_score(symbol)
        data["bull"] = b if b else None
        if data["bull"] is None:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    try:
        f = get_fundamentals(symbol, data_type="info")
        data["fundamentals"] = f if "error" not in f else None
        if data["fundamentals"] is None:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    try:
        n = get_news(symbol, limit=10)
        data["news"] = n if "error" not in n else None
        if data["news"] is None:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    try:
        r = calculate_risk_metrics(symbol, period="1y")
        data["risk"] = r if "error" not in r and r.get("volatility") else None
        if data["risk"] is None:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    # Nearest ~30-DTE chain for options_edge_score and atm_iv
    try:
        price = float((data["quote"] or {}).get("price") or 0)
        expiries_list: list[str] = get_expiries(symbol)
        nearest_exp = _get_nearest_expiry(expiries_list, config["nearest_expiry_target_dte"])
        if nearest_exp and price > 0:
            chain = get_option_chain(symbol, nearest_exp)
            if "error" not in chain:
                data["chain"] = chain
                puts = chain.get("puts", [])
                calls = chain.get("calls", [])
                data["atm_iv"] = _get_atm_iv(puts, price) or _get_atm_iv(calls, price)
            else:
                data["fallback_count"] += 1
        else:
            data["fallback_count"] += 1
    except Exception:
        data["fallback_count"] += 1

    cache[key] = data
    return data


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_fundamentals(info: dict) -> float:
    """Map fundamentals info dict to 0–100 score (average of 4 sub-scores)."""
    if not info:
        return 50.0

    sub_scores: list[float] = []

    pm = info.get("profitMargin")
    if pm is not None:
        pm_pct = float(pm) * 100
        if pm_pct >= 15:
            sub_scores.append(100.0)
        elif pm_pct >= 5:
            sub_scores.append(50.0 + (pm_pct - 5) / 10 * 50.0)
        else:
            sub_scores.append(max(0.0, pm_pct / 5 * 50.0))

    roe = info.get("returnOnEquity")
    if roe is not None:
        roe_pct = float(roe) * 100
        if roe_pct >= 25:
            sub_scores.append(100.0)
        elif roe_pct >= 10:
            sub_scores.append(50.0 + (roe_pct - 10) / 15 * 50.0)
        elif roe_pct >= 0:
            sub_scores.append(roe_pct / 10 * 50.0)
        else:
            sub_scores.append(0.0)

    de = info.get("debtToEquity")
    if de is not None:
        de_val = float(de)
        if de_val <= 0:
            sub_scores.append(100.0)
        elif de_val <= 2:
            sub_scores.append(100.0 - de_val / 2 * 50.0)
        elif de_val <= 4:
            sub_scores.append(50.0 - (de_val - 2) / 2 * 50.0)
        else:
            sub_scores.append(0.0)
    else:
        sub_scores.append(50.0)

    eg = info.get("earningsGrowth")
    if eg is not None:
        eg_pct = float(eg) * 100
        if eg_pct >= 30:
            sub_scores.append(100.0)
        elif eg_pct >= 0:
            sub_scores.append(50.0 + eg_pct / 30 * 50.0)
        else:
            sub_scores.append(0.0)

    return round(sum(sub_scores) / len(sub_scores), 1) if sub_scores else 50.0


def _score_sentiment(articles: list[dict], config: dict) -> float:
    """Keyword-based news sentiment score. Returns 0–100 (50 = neutral)."""
    if not articles:
        return 50.0
    pos_kw = config["sentiment_keywords"]["positive"]
    neg_kw = config["sentiment_keywords"]["negative"]
    pos_count = 0
    neg_count = 0
    for article in articles:
        title = (article.get("title") or "").lower()
        pos_count += sum(1 for kw in pos_kw if kw in title)
        neg_count += sum(1 for kw in neg_kw if kw in title)
    return round(max(0.0, min(100.0, 50.0 + (pos_count - neg_count) * 5.0)), 1)


def _score_volatility(annual_vol_pct: float | None) -> float:
    """Inverse piecewise linear volatility score. Lower vol → higher score (0–100)."""
    if annual_vol_pct is None:
        return 50.0
    v = float(annual_vol_pct)
    if v <= 20:
        return 100.0
    if v <= 40:
        return 100.0 - (v - 20) / 20 * 30.0
    if v <= 60:
        return 70.0 - (v - 40) / 20 * 30.0
    if v <= 80:
        return 40.0 - (v - 60) / 20 * 30.0
    return max(0.0, 10.0 - (v - 80) / 20 * 10.0)


def _compute_earnings_risk(days: int | None) -> float:
    """Earnings proximity risk score: 0–100 (higher = more risk)."""
    if days is None or days > 30:
        return 0.0
    if days <= 5:
        return 100.0
    if days <= 14:
        return 100.0 - (days - 5) / 9 * 50.0
    return max(0.0, 50.0 - (days - 14) / 16 * 40.0)


def _compute_yield_score(annualized_yield_pct: float) -> float:
    """Map annualized yield % to 0–100 score (same thresholds as csp_candidates)."""
    excellent, good, fair = 25.0, 15.0, 10.0
    if annualized_yield_pct >= excellent:
        return 100.0
    if annualized_yield_pct >= good:
        return 70.0 + (annualized_yield_pct - good) / (excellent - good) * 30.0
    if annualized_yield_pct >= fair:
        return 50.0 + (annualized_yield_pct - fair) / (good - fair) * 20.0
    return max(0.0, annualized_yield_pct / fair * 50.0)


def _classify_iv_context(iv_pct: float | None) -> str | None:
    """Classify IV level: high_iv (≥50%) / normal_iv (25–50%) / low_iv (<25%)."""
    if iv_pct is None:
        return None
    if iv_pct >= 50:
        return "high_iv"
    if iv_pct >= 25:
        return "normal_iv"
    return "low_iv"


def _get_earnings_days(data: dict) -> int | None:
    """Extract days-to-next-earnings from cached data (bull_result.next_earnings)."""
    bull_data = data.get("bull") or {}
    next_earnings = bull_data.get("next_earnings")
    if not next_earnings:
        return None
    try:
        today = datetime.now(tz=timezone.utc).date()
        return (datetime.strptime(next_earnings, "%Y-%m-%d").date() - today).days
    except ValueError:
        return None


def _score_stock_position(data: dict, config: dict) -> dict:
    """Compute stock composite score from cached data. Returns scores dict."""
    w = config["stock_weights"]
    iv_cap = config["iv_normalization_cap"]

    bull = data.get("bull")
    trend_score = float(bull.get("normalized_score") or 0) * 100 if bull else 50.0

    info = (data.get("fundamentals") or {}).get("info") or {}
    fundamentals_score = _score_fundamentals(info)

    articles = (data.get("news") or {}).get("articles") or []
    sentiment_score = _score_sentiment(articles, config)

    annual_vol = (data.get("risk") or {}).get("volatility", {}).get("annual")
    volatility_score = _score_volatility(annual_vol)

    atm_iv = data.get("atm_iv")
    options_edge_score = min((atm_iv / iv_cap) * 100, 100.0) if atm_iv else 50.0

    earnings_risk = _compute_earnings_risk(_get_earnings_days(data))
    earnings_safety = 100.0 - earnings_risk

    composite = (
        w["trend"] * trend_score
        + w["fundamentals"] * fundamentals_score
        + w["sentiment"] * sentiment_score
        + w["volatility"] * volatility_score
        + w["options_edge"] * options_edge_score
        + w["earnings_safety"] * earnings_safety
    )
    return {
        "trend": round(trend_score, 1),
        "fundamentals": round(fundamentals_score, 1),
        "sentiment": round(sentiment_score, 1),
        "volatility": round(volatility_score, 1),
        "options_edge": round(options_edge_score, 1),
        "earnings_risk": round(earnings_risk, 1),
        "composite": round(max(0.0, min(100.0, composite)), 1),
    }


def _score_option_position(
    position: dict,
    current_mid: float | None,
    dte: int,
    atm_iv: float | None,
    data: dict,
    config: dict,
) -> dict:
    """Compute option composite score (position health). Returns scores dict."""
    w = config["option_weights"]
    iv_cap = config["iv_normalization_cap"]

    bull = data.get("bull")
    trend_score = float(bull.get("normalized_score") or 0) * 100 if bull else 50.0

    iv_score = min((atm_iv / iv_cap) * 100, 100.0) if atm_iv else 50.0

    strike = position.get("strike") or 0
    premium_quality_score = 50.0
    if current_mid and strike > 0 and dte > 0:
        annualized_yield = (current_mid / strike) * (365 / dte) * 100
        premium_quality_score = _compute_yield_score(annualized_yield)

    earnings_risk = _compute_earnings_risk(_get_earnings_days(data))
    earnings_safety = 100.0 - earnings_risk

    articles = (data.get("news") or {}).get("articles") or []
    sentiment_score = _score_sentiment(articles, config)

    composite = (
        w["trend"] * trend_score
        + w["iv_score"] * iv_score
        + w["premium_quality"] * premium_quality_score
        + w["earnings_safety"] * earnings_safety
        + w["sentiment"] * sentiment_score
    )
    return {
        "trend": round(trend_score, 1),
        "iv_score": round(iv_score, 1),
        "premium_quality": round(premium_quality_score, 1),
        "earnings_risk": round(earnings_risk, 1),
        "sentiment": round(sentiment_score, 1),
        "composite": round(max(0.0, min(100.0, composite)), 1),
    }


# ---------------------------------------------------------------------------
# Support / Resistance Context
# ---------------------------------------------------------------------------


def _compute_sr_context(price: float, bull_result: dict | None, config: dict) -> dict:
    """Derive S/R proximity from already-fetched bull_result (no extra API calls)."""
    default: dict = {
        "near_support": None,
        "near_resistance": None,
        "pct_from_sma20": None,
        "pct_below_20d_high": None,
    }
    if not bull_result or price <= 0:
        return default

    pct_from_sma20 = bull_result.get("pct_from_sma20")
    high_20d = bull_result.get("high_20d")

    sr_lo, sr_hi = config["near_support_range"]
    nr_pct = config["near_resistance_pct"]

    near_support: bool | None = None
    if pct_from_sma20 is not None:
        near_support = sr_lo <= float(pct_from_sma20) <= sr_hi

    near_resistance: bool | None = None
    pct_below_20d_high: float | None = None
    if high_20d and float(high_20d) > 0:
        pct_below_20d_high = (float(high_20d) - price) / float(high_20d) * 100
        near_resistance = 0.0 <= pct_below_20d_high <= nr_pct

    return {
        "near_support": near_support,
        "near_resistance": near_resistance,
        "pct_from_sma20": round(float(pct_from_sma20), 2) if pct_from_sma20 is not None else None,
        "pct_below_20d_high": (
            round(pct_below_20d_high, 2) if pct_below_20d_high is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# Decision Engine
# ---------------------------------------------------------------------------


def _make_stock_decision(
    composite: float,
    pnl_pct: float,
    days_to_earnings: int | None,
    portfolio_cash: float,
    config: dict,
) -> tuple[str, list[str], list[str]]:
    """Return (decision, reasoning, risk_flags) for a stock position."""
    t = config["decision_thresholds"]
    rt = config["risk_thresholds"]
    reasoning: list[str] = []
    risk_flags: list[str] = []

    if composite >= t["add"]:
        if portfolio_cash > 0:
            decision = "ADD"
            reasoning.append(
                f"Strong score ({composite:.0f}) — favorable entry for additional shares"
            )
        else:
            decision = "HOLD"
            reasoning.append(
                f"Strong score ({composite:.0f}) — hold; no cash available to add"
            )
    elif composite >= t["hold_min"]:
        decision = "HOLD"
        reasoning.append(f"Solid score ({composite:.0f}) — maintain position")
    elif composite >= t["trim_min"]:
        decision = "TRIM"
        reasoning.append(f"Weakening score ({composite:.0f}) — reduce exposure by 25–50%")
    else:
        decision = "SELL"
        reasoning.append(f"Low score ({composite:.0f}) — exit position")

    if days_to_earnings is not None and days_to_earnings <= 14:
        reasoning.append(f"Earnings in {days_to_earnings} days — monitor closely")

    if pnl_pct >= rt["gain_trim_pct"]:
        risk_flags.append(
            f"Large unrealized gain ({pnl_pct:.0f}%) — consider partial profit taking"
        )
    if pnl_pct <= rt["drawdown_stop_pct"]:
        risk_flags.append(
            f"Large drawdown ({pnl_pct:.0f}%) — stop-loss consideration"
        )
    elif pnl_pct <= rt["drawdown_warn_pct"]:
        risk_flags.append(
            f"Significant drawdown ({pnl_pct:.0f}%) — review investment thesis"
        )

    return decision, reasoning, risk_flags


def _make_option_decision(
    position: dict,
    current_mid: float | None,
    price: float,
    dte: int,
    trend_score: float,
    fundamentals_score: float,
    sr: dict,
    config: dict,
) -> tuple[str, list[str], list[str]]:
    """Return (decision, reasoning, risk_flags) for an option position."""
    t = config["decision_thresholds"]
    pos_type = position["type"]
    strike = position.get("strike") or 0
    quantity = position["quantity"]
    cost_basis = position["cost_basis"]
    is_short = quantity < 0

    reasoning: list[str] = []
    risk_flags: list[str] = []

    # Profit capture % for short options
    profit_pct = 0.0
    if is_short and current_mid is not None and cost_basis > 0:
        profit_pct = (cost_basis - current_mid) / cost_basis * 100

    # ITM check
    is_itm = False
    itm_pct = 0.0
    if strike > 0 and price > 0:
        if pos_type == "call":
            itm_pct = (price - strike) / price * 100
        else:
            itm_pct = (strike - price) / price * 100
        is_itm = itm_pct > t["itm_threshold_pct"]

    # Priority 1 (hard): ≥75% profit
    if is_short and profit_pct >= t["profit_hard_close_pct"]:
        reasoning.append(f"Profit captured {profit_pct:.0f}% — take profits (hard rule)")
        return "CLOSE", reasoning, risk_flags

    # Priority 2: gamma risk
    if dte <= t["dte_gamma_risk"]:
        reasoning.append(f"DTE={dte} — close to expiry, elevated gamma risk")
        return "CLOSE", reasoning, risk_flags

    # Priority 3–4: ITM short options
    if is_itm and is_short:
        if pos_type == "put":
            if trend_score >= t["bull_trend_roll"]:
                reasoning.append(
                    f"Short put ITM ({itm_pct:.1f}%) + bullish trend ({trend_score:.0f})"
                    " — roll out for credit"
                )
                decision = "ROLL"
            elif fundamentals_score >= config["fundamentals_accept_assignment"]:
                reasoning.append(
                    f"Short put ITM ({itm_pct:.1f}%) + quality stock"
                    f" (fundamentals={fundamentals_score:.0f}) — acceptable to own at strike"
                )
                decision = "ACCEPT_ASSIGNMENT"
            else:
                reasoning.append(
                    f"Short put ITM ({itm_pct:.1f}%) + weak fundamentals"
                    f" ({fundamentals_score:.0f}) — close to avoid assignment"
                )
                decision = "CLOSE"
        else:  # short call
            if trend_score >= t["bull_trend_strong"]:
                reasoning.append(
                    f"Short call ITM ({itm_pct:.1f}%) + strong bull trend ({trend_score:.0f})"
                    " — roll up to recapture upside"
                )
                decision = "ROLL"
            else:
                reasoning.append(
                    f"Short call ITM ({itm_pct:.1f}%) + neutral/weak trend ({trend_score:.0f})"
                    " — allow assignment"
                )
                decision = "HOLD"
        risk_flags.append(f"{'Short ' + pos_type} ITM by {itm_pct:.1f}%")
        return decision, reasoning, risk_flags

    # Priority 5 (soft): ≥50% profit
    if is_short and profit_pct >= t["profit_soft_close_pct"]:
        reasoning.append(f"Profit captured {profit_pct:.0f}% — consider closing early")
        if sr.get("near_support") and pos_type == "put":
            reasoning.append("Near SMA20 support — holding also acceptable")
            return "HOLD", reasoning, risk_flags
        return "CLOSE", reasoning, risk_flags

    # Near-support confirmation for short puts
    if is_short and pos_type == "put" and sr.get("near_support"):
        reasoning.append("Near SMA20 support — short put position is well-supported")

    # DTE monitor
    if dte <= t["dte_monitor"]:
        reasoning.append(f"DTE={dte} — monitor closely for roll or close decision")
        return "MONITOR", reasoning, risk_flags

    # Long option: large gain
    if not is_short and current_mid and cost_basis > 0:
        gain_pct = (current_mid - cost_basis) / cost_basis * 100
        if gain_pct >= t["long_option_trim_pct"]:
            reasoning.append(f"Long option up {gain_pct:.0f}% — trim to lock in gains")
            return "TRIM", reasoning, risk_flags

    moneyness_str = "OTM" if not is_itm else "ATM"
    reasoning.append(f"DTE={dte}, {moneyness_str} — hold current position")
    return "HOLD", reasoning, risk_flags


# ---------------------------------------------------------------------------
# Output Builders
# ---------------------------------------------------------------------------


def _build_portfolio_risks(
    positions_analysis: list[dict],
    total_account_value: float,
    config: dict,
) -> dict:
    """Scan all analyzed positions and build the risk summary dict."""
    rt = config["risk_thresholds"]
    t = config["decision_thresholds"]
    risks: dict = {
        "concentration": [],
        "earnings_this_week": [],
        "high_gamma_options": [],
        "itm_short_calls": [],
        "itm_short_puts": [],
        "profit_capture_ready": [],
        "large_drawdowns": [],
    }

    # Concentration: sum market value per symbol
    symbol_values: dict[str, float] = {}
    for p in positions_analysis:
        sym = p["symbol"]
        symbol_values[sym] = symbol_values.get(sym, 0) + abs(p.get("market_value", 0))

    if total_account_value > 0:
        for sym, val in symbol_values.items():
            pct = val / total_account_value * 100
            if pct > rt["concentration_pct"]:
                risks["concentration"].append(f"{sym} ({pct:.0f}% of portfolio)")

    seen_earnings: set[str] = set()
    for p in positions_analysis:
        sym = p["symbol"]
        pos_type = p["type"]
        scores = p.get("scores", {})

        # Earnings this week (earnings_risk ≥ 80 ≈ ≤7 days)
        earnings_risk = scores.get("earnings_risk", 0)
        if earnings_risk >= 80 and sym not in seen_earnings:
            risks["earnings_this_week"].append(sym)
            seen_earnings.add(sym)

        if pos_type in ("call", "put"):
            dte = p.get("dte") or 9999
            qty = p.get("quantity", 1)
            is_short = qty < 0

            if is_short and dte <= t["dte_gamma_risk"]:
                risks["high_gamma_options"].append(f"{sym} {pos_type} (DTE={dte})")

            if is_short and p.get("moneyness") == "ITM":
                strike_str = str(p.get("strike", "?"))
                if pos_type == "call":
                    risks["itm_short_calls"].append(f"{sym} call @{strike_str}")
                else:
                    risks["itm_short_puts"].append(f"{sym} put @{strike_str}")

            if is_short and p.get("pnl_pct", 0) >= 50:
                risks["profit_capture_ready"].append(
                    f"{sym} {pos_type} ({p['pnl_pct']:.0f}% profit)"
                )

        if pos_type == "stock" and p.get("pnl_pct", 0) <= rt["drawdown_stop_pct"]:
            risks["large_drawdowns"].append(f"{sym} ({p['pnl_pct']:.0f}%)")

    return risks


def _build_portfolio_exposure(
    positions_analysis: list[dict],
    total_account_value: float,
    symbols_with_short_calls: set[str],
) -> dict:
    """Compute capital allocation and directional exposure metrics."""
    if total_account_value <= 0:
        return {
            "short_put_exposure_pct": 0.0,
            "covered_call_exposure_pct": 0.0,
            "largest_position_pct": 0.0,
            "cash_pct": 0.0,
            "net_delta_estimate": 0.0,
        }

    short_put_capital = sum(
        (p.get("strike") or 0) * 100 * abs(p["quantity"])
        for p in positions_analysis
        if p["type"] == "put" and p["quantity"] < 0
    )

    cc_stock_value = sum(
        abs(p.get("market_value", 0))
        for p in positions_analysis
        if p["type"] == "stock" and p["symbol"] in symbols_with_short_calls
    )

    symbol_values: dict[str, float] = {}
    for p in positions_analysis:
        sym = p["symbol"]
        symbol_values[sym] = symbol_values.get(sym, 0) + abs(p.get("market_value", 0))
    largest = max(symbol_values.values()) if symbol_values else 0.0

    # Net delta: +1 per stock share; options use ±0.40 approximation
    net_delta = 0.0
    for p in positions_analysis:
        qty = p["quantity"]
        pos_type = p["type"]
        if pos_type == "stock":
            net_delta += qty
        elif pos_type == "put":
            net_delta += qty * (-_DELTA_APPROX) * 100
        elif pos_type == "call":
            net_delta += qty * _DELTA_APPROX * 100

    return {
        "short_put_exposure_pct": round(short_put_capital / total_account_value * 100, 1),
        "covered_call_exposure_pct": round(cc_stock_value / total_account_value * 100, 1),
        "largest_position_pct": round(largest / total_account_value * 100, 1),
        "cash_pct": 0.0,  # filled by main function
        "net_delta_estimate": round(net_delta, 0),
    }


def _build_opportunities(
    positions_analysis: list[dict],
    portfolio_cash: float,
    total_account_value: float,
    config: dict,
) -> list[dict]:
    """Generate and rank action opportunities from existing portfolio positions."""
    ot = config["opportunity_thresholds"]
    opportunities: list[dict] = []

    symbols_with_short_puts: set[str] = {
        p["symbol"] for p in positions_analysis if p["type"] == "put" and p["quantity"] < 0
    }
    symbols_with_short_calls: set[str] = {
        p["symbol"] for p in positions_analysis if p["type"] == "call" and p["quantity"] < 0
    }
    owned_symbols: set[str] = {
        p["symbol"] for p in positions_analysis if p["type"] == "stock" and p["quantity"] > 0
    }
    cash_pct = portfolio_cash / total_account_value * 100 if total_account_value > 0 else 0.0

    for p in positions_analysis:
        sym = p["symbol"]
        pos_type = p["type"]
        scores = p.get("scores", {})
        composite = scores.get("composite", 50.0)
        iv_context = p.get("iv_context")
        near_support = p.get("near_support")
        near_resistance = p.get("near_resistance")
        earnings_risk = scores.get("earnings_risk", 0)
        iv_score = scores.get("iv_score") or scores.get("options_edge", 50.0)
        pnl_pct = p.get("pnl_pct", 0)
        qty = p.get("quantity", 0)

        if pos_type == "stock":
            # CSP opportunity
            if (
                sym not in symbols_with_short_puts
                and composite >= ot["csp_min_score"]
                and iv_context != "low_iv"
                and earnings_risk < ot["csp_max_earnings_risk"]
            ):
                priority = "high" if near_support else "medium"
                opportunities.append({
                    "symbol": sym,
                    "type": "csp",
                    "reasoning": (
                        f"Score={composite:.0f}"
                        f"{', near SMA20 support' if near_support else ''}"
                        f", IV={iv_context or 'n/a'} — CSP entry opportunity"
                    ),
                    "priority": priority,
                    "_sort_score": composite,
                    "_sort_iv": iv_score,
                    "_sort_support": 1 if near_support else 0,
                })

            # CC opportunity
            if (
                sym in owned_symbols
                and sym not in symbols_with_short_calls
                and composite >= ot["cc_min_score"]
            ):
                if near_resistance:
                    priority = "high" if iv_context != "low_iv" else "medium"
                else:
                    priority = "medium" if iv_context != "low_iv" else "low"
                opportunities.append({
                    "symbol": sym,
                    "type": "cc",
                    "reasoning": (
                        f"Own stock, score={composite:.0f}"
                        f"{', near 20d resistance' if near_resistance else ''}"
                        " — sell covered call for income"
                    ),
                    "priority": priority,
                    "_sort_score": composite,
                    "_sort_iv": iv_score,
                    "_sort_support": 1 if near_resistance else 0,
                })

            # Add opportunity
            if composite >= ot["add_min_score"] and cash_pct >= ot["cash_deploy_min_pct"]:
                opportunities.append({
                    "symbol": sym,
                    "type": "add",
                    "reasoning": (
                        f"High score ({composite:.0f}) + cash available ({cash_pct:.0f}%)"
                        " — deploy capital"
                    ),
                    "priority": "high",
                    "_sort_score": composite,
                    "_sort_iv": 0,
                    "_sort_support": 0,
                })

            # Exit opportunity
            if composite < 30.0 or pnl_pct <= -30.0:
                reasons = []
                if composite < 30.0:
                    reasons.append(f"low score ({composite:.0f})")
                if pnl_pct <= -30.0:
                    reasons.append(f"drawdown ({pnl_pct:.0f}%)")
                opportunities.append({
                    "symbol": sym,
                    "type": "exit",
                    "reasoning": f"Exit signal: {', '.join(reasons)}",
                    "priority": "high",
                    "_sort_score": 100.0 - composite,
                    "_sort_iv": 0,
                    "_sort_support": 0,
                })

        elif pos_type == "call" and qty < 0:
            # Early CC roll for OTM short calls in strong uptrend
            trend_score = scores.get("trend", 50.0)
            if (
                p.get("moneyness") == "OTM"
                and trend_score >= ot["early_roll_trend"]
                and not near_resistance
            ):
                opportunities.append({
                    "symbol": sym,
                    "type": "cc_roll_early",
                    "reasoning": (
                        f"Short call OTM but strong uptrend ({trend_score:.0f})"
                        " — consider rolling up preemptively"
                    ),
                    "priority": "medium",
                    "_sort_score": trend_score,
                    "_sort_iv": 0,
                    "_sort_support": 0,
                })

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    opportunities.sort(key=lambda o: (
        priority_rank.get(o["priority"], 2),
        -o.get("_sort_score", 0),
        -o.get("_sort_iv", 0),
        -o.get("_sort_support", 0),
    ))
    for o in opportunities:
        o.pop("_sort_score", None)
        o.pop("_sort_iv", None)
        o.pop("_sort_support", None)

    return opportunities


# ---------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------


def analyze_portfolio(
    positions: list[dict],
    portfolio_cash: float = 0.0,
    risk_profile: str = "moderate",
    config: dict = PORTFOLIO_CONFIG,
) -> dict:
    """Analyze a full portfolio of stock and option positions deterministically.

    Results depend only on live market data and the config dict.
    No LLM reasoning involved — all scoring and decisions are computed here.

    Note on determinism: live yfinance/API prices change intraday — this is the
    same constraint shared by all MCP tools in this server.

    Args:
        positions:       List of position dicts (symbol, type, quantity, cost_basis, ...).
        portfolio_cash:  Uninvested cash in account ($).
        risk_profile:    "conservative" | "moderate" | "aggressive" (informational).
        config:          Scoring/filtering config (defaults to PORTFOLIO_CONFIG).

    Returns:
        Dict with portfolio_summary, portfolio_exposure, positions_analysis,
        portfolio_risks, opportunities, validation_warnings.
    """
    as_of = datetime.now(tz=timezone.utc).isoformat()

    # 1. Validate
    valid_positions, validation_warnings = _validate_positions(positions)
    if not valid_positions:
        return {
            "error": "No valid positions to analyze",
            "validation_warnings": validation_warnings,
            "as_of": as_of,
        }

    # 2. Deduplicate symbols; initialize caches
    symbols = list({p["symbol"] for p in valid_positions})
    cache: dict[str, dict] = {}
    chain_cache: dict[tuple, dict] = {}

    # 3. Pre-fetch all symbol data (one round of API calls per unique symbol)
    for sym in symbols:
        try:
            _fetch_symbol_data(sym, cache, config)
        except Exception as exc:
            logger.error("[%s] Data fetch failed: %s", sym, exc)

    # 4. Analyze each position
    positions_analysis: list[dict] = []
    total_market_value = 0.0
    total_cost_signed = 0.0
    total_cost_abs = 0.0
    symbols_with_short_calls: set[str] = set()

    for pos in valid_positions:
        sym = pos["symbol"]
        pos_type = pos["type"]
        qty = pos["quantity"]
        cost_basis = pos["cost_basis"]

        data = cache.get(sym, {})
        quote = data.get("quote") or {}
        price = float(quote.get("price") or 0)

        if price <= 0:
            validation_warnings.append(
                f"{sym} {pos_type}: no valid price returned — skipped"
            )
            logger.warning("[%s] No valid price — skipping position", sym)
            continue

        sr = _compute_sr_context(price, data.get("bull"), config)
        atm_iv_base = data.get("atm_iv")
        iv_context = _classify_iv_context(atm_iv_base)

        entry: dict = {
            "symbol": sym,
            "type": pos_type,
            "quantity": qty,
            "cost_basis": cost_basis,
            "near_support": sr.get("near_support"),
            "near_resistance": sr.get("near_resistance"),
            "iv_context": iv_context,
            "dte": None,
            "moneyness": None,
            "data_quality": "GOOD",
        }

        fallback_count = data.get("fallback_count", 0)

        if pos_type == "stock":
            scores = _score_stock_position(data, config)

            multiplier = 1
            market_value = round(price * qty * multiplier, 2)
            cost_total_signed = round(cost_basis * qty * multiplier, 2)
            pnl = round(market_value - cost_total_signed, 2)
            pnl_pct = (
                round(pnl / abs(cost_total_signed) * 100, 2) if cost_total_signed != 0 else 0.0
            )

            days_to_earnings = _get_earnings_days(data)
            decision, reasoning, risk_flags = _make_stock_decision(
                scores["composite"], pnl_pct, days_to_earnings, portfolio_cash, config
            )

            entry.update({
                "current_price": round(price, 2),
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "scores": scores,
                "decision": decision,
                "reasoning": reasoning,
                "risk_flags": risk_flags,
            })

            total_market_value += market_value
            total_cost_signed += cost_total_signed
            total_cost_abs += abs(cost_total_signed)

        else:
            # Option position
            expiry = pos["expiry"]
            strike = pos["strike"]

            dte = 0
            try:
                today = datetime.now(tz=timezone.utc).date()
                dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days
            except ValueError:
                pass
            dte = max(0, dte)

            moneyness: str | None = None
            if price > 0 and strike > 0:
                if pos_type == "call":
                    itm_pct = (price - strike) / price * 100
                else:
                    itm_pct = (strike - price) / price * 100
                itm_thr = config["decision_thresholds"]["itm_threshold_pct"]
                if itm_pct > itm_thr:
                    moneyness = "ITM"
                elif itm_pct < -itm_thr:
                    moneyness = "OTM"
                else:
                    moneyness = "ATM"

            if pos_type == "call" and qty < 0:
                symbols_with_short_calls.add(sym)

            # Fetch position-specific chain
            chain_key = (sym, expiry)
            if chain_key not in chain_cache:
                try:
                    pos_chain = get_option_chain(sym, expiry)
                    chain_cache[chain_key] = pos_chain if "error" not in pos_chain else {}
                except Exception:
                    chain_cache[chain_key] = {}

            pos_chain = chain_cache.get(chain_key, {})
            legs = pos_chain.get("puts" if pos_type == "put" else "calls", [])
            atm_iv_pos = _get_atm_iv(legs, price)

            # Find current mid for this exact strike
            current_mid: float | None = None
            for leg in legs:
                leg_strike = leg.get("strike")
                if leg_strike is not None and abs(float(leg_strike) - strike) < 0.51:
                    m = leg.get("mid")
                    if m and float(m) > 0:
                        current_mid = float(m)
                    break

            if current_mid is None:
                fallback_count += 1

            scores = _score_option_position(pos, current_mid, dte, atm_iv_pos, data, config)

            info = (data.get("fundamentals") or {}).get("info") or {}
            fundamentals_score = _score_fundamentals(info)

            multiplier = 100
            curr_for_pnl = current_mid if current_mid is not None else cost_basis
            market_value = round(curr_for_pnl * qty * multiplier, 2)
            cost_total_signed = round(cost_basis * qty * multiplier, 2)
            pnl = round(market_value - cost_total_signed, 2)
            pnl_pct = (
                round(pnl / abs(cost_total_signed) * 100, 2) if cost_total_signed != 0 else 0.0
            )

            decision, reasoning, risk_flags = _make_option_decision(
                pos, current_mid, price, dte,
                trend_score=scores["trend"],
                fundamentals_score=fundamentals_score,
                sr=sr,
                config=config,
            )

            entry.update({
                "strike": round(strike, 2),
                "dte": dte,
                "moneyness": moneyness,
                "current_price": round(current_mid, 2) if current_mid is not None else None,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "scores": scores,
                "decision": decision,
                "reasoning": reasoning,
                "risk_flags": risk_flags,
            })

            total_market_value += market_value
            total_cost_signed += cost_total_signed
            total_cost_abs += abs(cost_total_signed)

        dq = config["data_quality_thresholds"]
        if fallback_count <= dq["good"]:
            entry["data_quality"] = "GOOD"
        elif fallback_count <= dq["partial"]:
            entry["data_quality"] = "PARTIAL"
        else:
            entry["data_quality"] = "POOR"

        positions_analysis.append(entry)

    # 5. Portfolio summary
    total_market_value = round(total_market_value, 2)
    total_account_value = total_market_value + portfolio_cash
    total_pnl = round(total_market_value - total_cost_signed, 2)
    total_pnl_pct = round(total_pnl / total_cost_abs * 100, 2) if total_cost_abs > 0 else 0.0

    stock_composites = [
        p["scores"]["composite"]
        for p in positions_analysis
        if p["type"] == "stock" and "composite" in p.get("scores", {})
    ]
    overall_score = (
        round(sum(stock_composites) / len(stock_composites), 1) if stock_composites else 0.0
    )

    portfolio_summary = {
        "total_positions": len({p["symbol"] for p in positions_analysis}),
        "total_legs": len(positions_analysis),
        "total_market_value": total_market_value,
        "total_cost_basis": round(total_cost_abs, 2),
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "portfolio_cash": round(portfolio_cash, 2),
        "total_account_value": round(total_account_value, 2),
        "overall_score": overall_score,
        "risk_profile": risk_profile,
        "as_of": as_of,
    }

    # 6. Exposure
    exposure = _build_portfolio_exposure(
        positions_analysis, total_account_value, symbols_with_short_calls
    )
    exposure["cash_pct"] = (
        round(portfolio_cash / total_account_value * 100, 1)
        if total_account_value > 0 else 0.0
    )

    # 7. Risks
    portfolio_risks = _build_portfolio_risks(
        positions_analysis, total_account_value, config
    )

    # 8. Opportunities
    opportunities = _build_opportunities(
        positions_analysis, portfolio_cash, total_account_value, config
    )

    return {
        "portfolio_summary": portfolio_summary,
        "portfolio_exposure": exposure,
        "positions_analysis": positions_analysis,
        "portfolio_risks": portfolio_risks,
        "opportunities": opportunities,
        "validation_warnings": validation_warnings,
    }
