# ABOUTME: Deterministic CSP (Cash Secured Put) candidate engine.
# ABOUTME: Scores, filters, and ranks symbols — no LLM reasoning involved.

import logging
from datetime import datetime, timezone

from trading_skills.options import get_option_chain
from trading_skills.quote import get_quote
from trading_skills.scanner_bullish import compute_bullish_score

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — all weights and thresholds in one place
# ---------------------------------------------------------------------------

CSP_CONFIG: dict = {
    "weights": {
        "bull_score": 0.40,
        "iv_score": 0.30,
        "yield_score": 0.30,
    },
    "filters": {
        "min_price": 20.0,
        "min_iv_pct": 20.0,          # Hard exclude below this IV
        "min_oi": 500,
        "min_bid": 0.30,
        "max_spread_pct": 10.0,      # (ask - bid) / mid * 100
        "earnings_buffer_days": 5,   # Hard exclude
        "earnings_warning_days": 14, # Soft warning in notes
    },
    "strike_selection": {
        "otm_min": 0.90,             # 10% OTM lower bound
        "otm_max": 0.93,             # 7% OTM upper bound
    },
    "yield_score_thresholds": {
        "excellent": 25.0,           # annualized yield % → score 100
        "good": 15.0,                # → score 70
        "fair": 10.0,                # → score 50
    },
    "iv_normalization_cap": 60.0,    # IV% at which iv_score reaches 100
    "risk_flag_thresholds": {
        "high_iv_pct": 60.0,
        "high_beta": 2.0,
    },
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _compute_dte(expiry: str) -> int:
    """Return calendar days from today to expiry (YYYY-MM-DD).

    Raises ValueError if expiry is today or in the past.
    """
    today = datetime.now(tz=timezone.utc).date()
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    dte = (exp_date - today).days
    if dte <= 0:
        raise ValueError(f"Expiry {expiry} is today or in the past (dte={dte})")
    return dte


def _days_until(date_str: str | None) -> int | None:
    """Days from today until date_str (YYYY-MM-DD). Returns None if unparseable."""
    if not date_str:
        return None
    try:
        today = datetime.now(tz=timezone.utc).date()
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (target - today).days
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# IV helper
# ---------------------------------------------------------------------------


def _get_atm_iv(puts: list[dict], price: float) -> float | None:
    """Return impliedVolatility (%) of the put whose strike is closest to price."""
    if not puts:
        return None
    atm = min(puts, key=lambda p: abs((p.get("strike") or 0) - price))
    iv = atm.get("impliedVolatility")
    if iv is None or iv <= 0:
        return None
    return float(iv)


# ---------------------------------------------------------------------------
# Strike selection
# ---------------------------------------------------------------------------


def _select_strike(puts: list[dict], price: float, config: dict) -> dict | None:
    """Find the best OTM put strike for a CSP entry.

    Selection criteria (in order):
    1. Strike within OTM window: price * otm_min <= strike <= price * otm_max
    2. OI >= min_oi
    3. bid >= min_bid
    4. Spread tightness: (ask - bid) / mid * 100 < max_spread_pct
    5. Among survivors: highest OI, then highest mid premium
    """
    f = config["filters"]
    s = config["strike_selection"]
    lo = price * s["otm_min"]
    hi = price * s["otm_max"]

    survivors = []
    for put in puts:
        strike = put.get("strike")
        bid = put.get("bid") or 0.0
        ask = put.get("ask") or 0.0
        mid = put.get("mid") or (bid + ask) / 2
        oi = put.get("openInterest") or 0

        if strike is None:
            continue

        if not (lo <= strike <= hi):
            logger.debug("%s strike %.2f outside OTM window [%.2f, %.2f]", strike, strike, lo, hi)
            continue

        if oi < f["min_oi"]:
            logger.debug("Strike %.2f filtered: OI %d < %d", strike, oi, f["min_oi"])
            continue

        if bid < f["min_bid"]:
            logger.debug("Strike %.2f filtered: bid %.2f < %.2f", strike, bid, f["min_bid"])
            continue

        if mid > 0:
            spread_pct = (ask - bid) / mid * 100
            if spread_pct >= f["max_spread_pct"]:
                logger.debug(
                    "Strike %.2f filtered: spread %.1f%% >= %.1f%%",
                    strike, spread_pct, f["max_spread_pct"],
                )
                continue
        else:
            logger.debug("Strike %.2f filtered: mid is zero", strike)
            continue

        survivors.append(put)

    if not survivors:
        return None

    survivors.sort(key=lambda p: (-(p.get("openInterest") or 0), -(p.get("mid") or 0)))
    return survivors[0]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _compute_yield_score(annualized_yield_pct: float, thresholds: dict) -> float:
    """Map annualized yield % to a 0–100 score with smooth linear interpolation."""
    excellent = thresholds["excellent"]  # 25%
    good = thresholds["good"]           # 15%
    fair = thresholds["fair"]           # 10%

    if annualized_yield_pct >= excellent:
        return 100.0
    if annualized_yield_pct >= good:
        # 15–25% → 70–100 (linear)
        return 70.0 + (annualized_yield_pct - good) / (excellent - good) * 30.0
    if annualized_yield_pct >= fair:
        # 10–15% → 50–70 (linear)
        return 50.0 + (annualized_yield_pct - fair) / (good - fair) * 20.0
    # 0–10% → 0–50 (linear)
    return max(0.0, annualized_yield_pct / fair * 50.0)


def _compute_csp_score(
    bull_score: float,
    iv_score: float,
    yield_score: float,
    weights: dict,
) -> float:
    """Compute weighted CSP composite score (0–100).

    Formula (strict — do not change weights):
        CSP Score = 0.40 * bull_score + 0.30 * iv_score + 0.30 * yield_score
    """
    raw = (
        weights["bull_score"] * bull_score
        + weights["iv_score"] * iv_score
        + weights["yield_score"] * yield_score
    )
    return round(max(0.0, min(100.0, raw)), 1)


# ---------------------------------------------------------------------------
# Notes and risk flags
# ---------------------------------------------------------------------------


def _build_notes(
    annualized_yield: float,
    iv_pct: float,
    bull_score_norm: float,
    oi: int,
    days_to_earnings: int | None,
    config: dict,
) -> list[str]:
    """Build human-readable observation notes for a candidate."""
    notes: list[str] = []
    f = config["filters"]

    if oi > 2000:
        notes.append("High OI support")
    if iv_pct > 35:
        notes.append("Elevated IV — rich premium")
    elif iv_pct > 20:
        notes.append("Healthy IV")
    if annualized_yield >= config["yield_score_thresholds"]["excellent"]:
        notes.append("Excellent yield")
    elif annualized_yield >= config["yield_score_thresholds"]["good"]:
        notes.append("Good yield")
    if bull_score_norm >= 70:
        notes.append("Strong bullish trend")
    if days_to_earnings is not None and days_to_earnings < f["earnings_warning_days"]:
        notes.append(f"Earnings in {days_to_earnings} days — monitor closely")

    return notes


def _build_risk_flags(iv_pct: float, beta: float | None, config: dict) -> list[str]:
    """Build risk warning flags for a candidate."""
    flags: list[str] = []
    rf = config["risk_flag_thresholds"]

    if iv_pct > rf["high_iv_pct"]:
        flags.append(f"High IV ({iv_pct:.0f}%) — elevated assignment risk")
    if beta is not None and beta > rf["high_beta"]:
        flags.append(f"High beta ({beta:.1f}) — volatile stock")

    return flags


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def calculate_csp_candidates(
    symbols: list[str],
    expiry: str,
    config: dict = CSP_CONFIG,
) -> list[dict]:
    """Find and rank Cash Secured Put candidates deterministically.

    Results depend only on live market data and the config dict.
    No LLM reasoning is involved — all scoring and selection is computed here.

    Note on determinism: given identical market data snapshots, results are
    fully reproducible. Live yfinance prices change intraday — this is the
    same constraint shared by all MCP tools in this server.

    Args:
        symbols:  List of ticker symbols to evaluate.
        expiry:   Option expiration date (YYYY-MM-DD).
        config:   Scoring/filtering config dict (defaults to CSP_CONFIG).

    Returns:
        Sorted list of candidate dicts (highest csp_score first).
        Secondary sort: higher OI, then lower (safer) strike.
    """
    try:
        dte = _compute_dte(expiry)
    except ValueError as exc:
        logger.error("Invalid expiry %s: %s", expiry, exc)
        return []

    results: list[dict] = []
    filters = config["filters"]
    weights = config["weights"]
    thresholds = config["yield_score_thresholds"]
    iv_cap = config["iv_normalization_cap"]

    for symbol in symbols:
        try:
            logger.info("[%s] Starting CSP evaluation", symbol)

            # --- Step 1: Quote (price + beta) ---
            quote = get_quote(symbol)
            if "error" in quote:
                logger.warning("[%s] Quote failed: %s", symbol, quote["error"])
                continue
            price = float(quote.get("price") or 0)
            beta = quote.get("beta")
            if beta is not None:
                try:
                    beta = float(beta)
                except (TypeError, ValueError):
                    beta = None

            if price < filters["min_price"]:
                logger.info(
                    "[%s] Filtered: price $%.2f < min $%.2f",
                    symbol, price, filters["min_price"],
                )
                continue

            # --- Step 2: Option chain (puts) ---
            chain = get_option_chain(symbol, expiry)
            if "error" in chain:
                logger.warning("[%s] Option chain failed: %s", symbol, chain["error"])
                continue
            puts = chain.get("puts", [])
            if not puts:
                logger.warning("[%s] No puts available for %s", symbol, expiry)
                continue

            # --- Step 3: IV from ATM put ---
            iv_pct = _get_atm_iv(puts, price)
            if iv_pct is None:
                logger.info("[%s] Filtered: could not determine IV", symbol)
                continue
            if iv_pct < filters["min_iv_pct"]:
                logger.info(
                    "[%s] Filtered: IV %.1f%% < min %.1f%%",
                    symbol, iv_pct, filters["min_iv_pct"],
                )
                continue

            # --- Step 4: Bullish score + earnings date ---
            bull_result = compute_bullish_score(symbol)
            if bull_result is None:
                logger.warning("[%s] Bullish score unavailable — defaulting to 0", symbol)
                bull_score_norm = 0.0
                next_earnings = None
            else:
                bull_score_norm = float(bull_result.get("normalized_score") or 0) * 100
                next_earnings = bull_result.get("next_earnings")

            # --- Step 5: Earnings hard filter ---
            days_to_earnings = _days_until(next_earnings)
            if (
                days_to_earnings is not None
                and days_to_earnings <= filters["earnings_buffer_days"]
            ):
                logger.info(
                    "[%s] Filtered: earnings in %d days (buffer=%d)",
                    symbol, days_to_earnings, filters["earnings_buffer_days"],
                )
                continue

            # --- Step 6: Strike selection ---
            selected = _select_strike(puts, price, config)
            if selected is None:
                logger.info("[%s] No suitable strike found after filters", symbol)
                continue

            strike = round(float(selected["strike"]), 2)
            bid = float(selected.get("bid") or 0)
            ask = float(selected.get("ask") or 0)
            mid = float(selected.get("mid") or (bid + ask) / 2)
            oi = int(selected.get("openInterest") or 0)

            # --- Step 7: Calculations (all derived from the already-rounded strike) ---
            premium = mid
            capital_required = strike * 100
            yield_pct = (premium / strike) * 100
            annualized_yield = yield_pct * (365 / dte)
            breakeven = strike - premium

            # --- Step 8: Scores ---
            iv_score = min((iv_pct / iv_cap) * 100, 100.0)
            yield_score = _compute_yield_score(annualized_yield, thresholds)
            csp_score = _compute_csp_score(bull_score_norm, iv_score, yield_score, weights)

            # --- Step 9: Notes + risk flags ---
            notes = _build_notes(
                annualized_yield, iv_pct, bull_score_norm, oi, days_to_earnings, config
            )
            risk_flags = _build_risk_flags(iv_pct, beta, config)

            logger.info(
                "[%s] Qualified: strike=%.2f dte=%d ann_yield=%.1f%% csp_score=%.1f",
                symbol, strike, dte, annualized_yield, csp_score,
            )

            results.append({
                "symbol": symbol.upper(),
                "price": round(price, 2),
                "selected_strike": round(strike, 2),
                "dte": dte,
                "premium": round(premium, 2),
                "capital_required": round(capital_required, 2),
                "yield_pct": round(yield_pct, 2),
                "annualized_yield": round(annualized_yield, 1),
                "breakeven": round(breakeven, 2),
                "bull_score": round(bull_score_norm, 1),
                "iv_percentile": round(iv_pct, 1),
                "csp_score": csp_score,
                "oi": oi,
                "notes": notes,
                "risk_flags": risk_flags,
            })

        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", symbol, exc, exc_info=True)
            continue

    # Primary: highest csp_score; Secondary: highest OI; Tertiary: lower strike (safer)
    return sorted(results, key=lambda x: (-x["csp_score"], -x["oi"], x["selected_strike"]))
