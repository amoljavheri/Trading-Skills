# ABOUTME: Scans symbols for PMCC (Poor Man's Covered Call) suitability.
# ABOUTME: Scores on delta accuracy, liquidity, spread, IV, yield, earnings, downside protection.

from datetime import datetime

import pandas as pd
import yfinance as yf

from trading_skills.black_scholes import black_scholes_delta
from trading_skills.earnings import get_earnings_info
from trading_skills.utils import get_current_price

# LEAPS target DTE: midpoint of 12–18 month range (365–540 days)
_LEAPS_TARGET_DTE = 452
_LEAPS_IDEAL_MIN_DTE = 365
_LEAPS_IDEAL_MAX_DTE = 540
_LEAPS_FALLBACK_MIN_DTE = 270


def format_scan_results(results: list[dict]) -> dict:
    """Sort and wrap PMCC scan results into output dict.

    Filters valid results (with pmcc_score), sorts by score then realistic yield,
    and separates errors.
    """
    valid_results = [r for r in results if "pmcc_score" in r]
    valid_results.sort(
        key=lambda x: (
            x["pmcc_score"],
            x.get("metrics", {}).get("annual_yield_realistic_pct", 0),
        ),
        reverse=True,
    )
    return {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(valid_results),
        "results": valid_results,
        "errors": [r for r in results if "error" in r],
    }


def find_strike_by_delta(
    chain,
    current_price,
    target_delta,
    expiry_days,
    iv,
    r=0.05,
    min_strike=None,
    max_strike=None,
):
    """Find strike closest to target delta with optional strike constraints.

    Uses a two-pass approach:
    Pass 1 (preferred): candidates with bid > 0 AND openInterest >= 50
    Pass 2 (fallback):  candidates with bid > 0 only (preserves original behavior)
    """
    _MIN_OI = 50
    T = expiry_days / 365

    def _best_from(candidates: pd.DataFrame):
        best_diff = float("inf")
        best = None
        for _, row in candidates.iterrows():
            option_iv = row.get("impliedVolatility", iv)
            if pd.isna(option_iv) or option_iv <= 0:
                option_iv = iv
            delta = black_scholes_delta(current_price, row["strike"], T, r, option_iv, "call")
            diff = abs(delta - target_delta)
            if diff < best_diff:
                best_diff = diff
                best = row.copy()
                best["calculated_delta"] = delta
        return best

    def _apply_constraints(df: pd.DataFrame) -> pd.DataFrame:
        if min_strike is not None:
            df = df[df["strike"] >= min_strike]
        if max_strike is not None:
            df = df[df["strike"] <= max_strike]
        return df

    # Pass 1: liquid strikes (OI >= 50)
    liquid = chain[
        chain["bid"].notna() & (chain["bid"] > 0) & (chain["openInterest"].fillna(0) >= _MIN_OI)
    ]
    best_option = _best_from(_apply_constraints(liquid))

    # Pass 2 fallback: any positive bid (original behavior, guarantees no regression)
    if best_option is None:
        all_bids = chain[chain["bid"].notna() & (chain["bid"] > 0)]
        best_option = _best_from(_apply_constraints(all_bids))

    if best_option is None:
        return None, None
    return best_option["strike"], best_option


def _compute_atm_iv_median(chain_df: pd.DataFrame, current_price: float) -> float | None:
    """Return median implied volatility of ATM calls (strike within ±5% of price)."""
    atm = chain_df[
        (chain_df["strike"] >= current_price * 0.95) & (chain_df["strike"] <= current_price * 1.05)
    ]
    if atm.empty:
        return None
    vals = atm["impliedVolatility"].dropna()
    if vals.empty:
        return None
    med = float(vals.median())
    return med if med > 0 else None


def analyze_pmcc(
    symbol: str,
    min_leaps_days: int = 270,
    short_days_range: tuple = (7, 21),
    leaps_delta: float = 0.80,
    short_delta: float = 0.20,
    ticker=None,
) -> dict | None:
    """Analyze a symbol for PMCC suitability.

    Returns a result dict with pmcc_score (0–10), detailed LEAPS/short leg data,
    metrics (breakeven, yield, downside protection), risk_flags, and earnings info.
    Returns a dict with 'error' key when a hard disqualification is hit.
    Returns None when basic data (price, options list) is unavailable.
    """
    try:
        ticker = ticker or yf.Ticker(symbol)
        info = ticker.info
        current_price = get_current_price(info)

        if not current_price:
            hist = ticker.history(period="5d")
            if hist.empty:
                return None
            current_price = float(hist["Close"].iloc[-1])

        expirations = ticker.options
        if not expirations:
            return {"symbol": symbol, "error": "No options available"}

        today = datetime.now()

        # --- Step 1: LEAPS expiry selection ---
        # Primary: closest to 452 DTE within 365–540 day ideal range
        # Fallback: nearest expiry >= 270 days
        ideal_candidates: list[tuple[str, int]] = []
        fallback_expiry: str | None = None
        fallback_days = 0

        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_to_exp = (exp_date - today).days
            if _LEAPS_IDEAL_MIN_DTE <= days_to_exp <= _LEAPS_IDEAL_MAX_DTE:
                ideal_candidates.append((exp, days_to_exp))
            if days_to_exp >= _LEAPS_FALLBACK_MIN_DTE and fallback_expiry is None:
                fallback_expiry = exp
                fallback_days = days_to_exp

        if ideal_candidates:
            best = min(ideal_candidates, key=lambda x: abs(x[1] - _LEAPS_TARGET_DTE))
            leaps_expiry, leaps_days = best
        elif fallback_expiry:
            leaps_expiry, leaps_days = fallback_expiry, fallback_days
        else:
            return {
                "symbol": symbol,
                "error": f"No LEAPS expiry >= {_LEAPS_FALLBACK_MIN_DTE} days found",
            }

        # --- Step 3: Short-term expiry selection ---
        # Primary: 21–45 DTE; Fallback: 7–21 DTE; Hard floor: 7 DTE
        short_expiry: str | None = None
        short_days = 0

        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_to_exp = (exp_date - today).days
            if 21 <= days_to_exp <= 45:
                short_expiry = exp
                short_days = days_to_exp
                break

        if not short_expiry:
            for exp in expirations:
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                days_to_exp = (exp_date - today).days
                if 7 <= days_to_exp <= 20:
                    short_expiry = exp
                    short_days = days_to_exp
                    break

        if not short_expiry:
            return {
                "symbol": symbol,
                "error": "No suitable short-term expiry found (min 7 DTE required)",
            }

        # Fetch option chains
        leaps_chain = ticker.option_chain(leaps_expiry)
        short_chain = ticker.option_chain(short_expiry)

        # --- Step 2: Compute separate IVs using median of ATM calls ---
        leaps_iv = _compute_atm_iv_median(leaps_chain.calls, current_price)
        if leaps_iv is None or leaps_iv < 0.05:
            return {"symbol": symbol, "error": "IV data unavailable or implausible"}

        short_iv_fallback_used = False
        short_iv = _compute_atm_iv_median(short_chain.calls, current_price)
        if short_iv is None or short_iv <= 0:
            short_iv = leaps_iv
            short_iv_fallback_used = True

        # --- Find LEAPS call (delta search uses leaps_iv) ---
        leaps_strike, leaps_option = find_strike_by_delta(
            leaps_chain.calls,
            current_price,
            leaps_delta,
            leaps_days,
            leaps_iv,
            max_strike=current_price * 1.02,
        )
        if leaps_option is None:
            return {
                "symbol": symbol,
                "error": f"Could not find suitable LEAPS strike with delta ~{leaps_delta}",
            }

        # Hard reject: LEAPS OI < 20
        leaps_oi = int(leaps_option.get("openInterest") or 0)
        if leaps_oi < 20:
            return {"symbol": symbol, "error": f"LEAPS liquidity too low (OI={leaps_oi})"}

        leaps_bid = float(leaps_option.get("bid") or 0)
        leaps_ask = float(leaps_option.get("ask") or 0)
        leaps_mid = round((leaps_bid + leaps_ask) / 2, 2)
        leaps_spread_pct = (leaps_ask - leaps_bid) / leaps_mid * 100 if leaps_mid > 0 else 100.0

        # Hard reject: LEAPS spread > 25%
        if leaps_spread_pct > 25:
            return {
                "symbol": symbol,
                "error": (f"LEAPS spread too wide ({leaps_spread_pct:.0f}%) — untradeable"),
            }

        # --- Find short call (delta search uses short_iv; must be above LEAPS strike) ---
        short_strike, short_option = find_strike_by_delta(
            short_chain.calls,
            current_price,
            short_delta,
            short_days,
            short_iv,
            min_strike=leaps_strike + 0.01,
        )
        if short_option is None:
            return {
                "symbol": symbol,
                "error": f"Could not find short strike > LEAPS strike ${leaps_strike}",
            }

        short_bid = float(short_option.get("bid") or 0)
        if short_bid <= 0:
            return {"symbol": symbol, "error": "Short call has no executable bid"}
        short_ask = float(short_option.get("ask") or 0)
        short_mid = round((short_bid + short_ask) / 2, 2)
        short_spread_pct = (short_ask - short_bid) / short_mid * 100 if short_mid > 0 else 100.0

        actual_leaps_delta = float(leaps_option.get("calculated_delta") or 0)
        actual_short_delta = float(short_option.get("calculated_delta") or 0)
        short_oi = int(short_option.get("openInterest") or 0)

        # --- Step 4: Yield calculation ---
        # Theoretical: mid-based, no capture rate — shows the ceiling
        # Realistic: bid-based with 65% capture rate — practical income estimate
        annual_yield_theoretical = (
            (short_mid / leaps_mid) * (365 / short_days) * 100 if leaps_mid > 0 else 0.0
        )
        annual_yield_realistic = (
            (short_bid / leaps_mid) * (365 / short_days) * 100 * 0.65 if leaps_mid > 0 else 0.0
        )

        # --- Step 5: Breakeven and downside metrics ---
        # net_debit = cost of trade per share (leaps cost minus short credit received)
        # breakeven = leaps_strike + net_debit  (stock price where P&L = 0 at LEAPS expiry)
        net_debit = leaps_mid - short_bid
        breakeven_price = leaps_strike + net_debit
        pct_to_breakeven = (
            (current_price - breakeven_price) / current_price * 100 if current_price > 0 else 0.0
        )
        max_loss = net_debit * 100  # per contract (100 shares)

        leaps_intrinsic = max(0.0, current_price - leaps_strike)
        leaps_extrinsic = max(0.0, leaps_mid - leaps_intrinsic)
        leaps_extrinsic_pct = (leaps_extrinsic / leaps_mid * 100) if leaps_mid > 0 else 0.0

        capital_required = leaps_mid * 100

        # --- Step 6: Earnings risk check ---
        earnings_info = get_earnings_info(symbol)
        earnings_date_str = earnings_info.get("earnings_date")
        earnings_within_window = False
        days_to_earnings: int | None = None

        if earnings_date_str:
            try:
                earnings_dt = datetime.strptime(earnings_date_str, "%Y-%m-%d")
                days_to_earnings = (earnings_dt - today).days
                earnings_within_window = 0 <= days_to_earnings <= (short_days + 3)
            except ValueError:
                pass

        # --- Step 7: Delta spread ---
        delta_spread = actual_leaps_delta - actual_short_delta

        # --- Step 8: Scoring (raw max = 13; normalized to 0–10) ---
        score = 0.0

        # LEAPS delta accuracy (0–2 pts)
        if abs(actual_leaps_delta - leaps_delta) <= 0.05:
            score += 2
        elif abs(actual_leaps_delta - leaps_delta) <= 0.10:
            score += 1

        # Short call delta accuracy (0–1 pt)
        if abs(actual_short_delta - short_delta) <= 0.05:
            score += 1
        elif abs(actual_short_delta - short_delta) <= 0.10:
            score += 0.5

        # Delta spread quality (0–1 pt)
        if delta_spread >= 0.55:
            score += 1
        elif delta_spread >= 0.45:
            score += 0.5

        # LEAPS OI liquidity (0–1 pt; OI < 20 already hard-rejected above)
        if leaps_oi >= 500:
            score += 1
        elif leaps_oi >= 100:
            score += 0.5

        # Short call OI (0–1 pt)
        if short_oi >= 1000:
            score += 1
        elif short_oi >= 200:
            score += 0.5

        # LEAPS spread (0–1 pt; >25% already hard-rejected above)
        if leaps_spread_pct < 10:
            score += 1
        elif leaps_spread_pct < 15:
            score += 0.5

        # Short call spread (0–1 pt)
        if short_spread_pct < 10:
            score += 1
        elif short_spread_pct < 20:
            score += 0.5

        # IV quality — sweet spot 25–40% (0–2 pts); >50% gets 0 pts + risk flag
        if 0.25 <= leaps_iv <= 0.40:
            score += 2
        elif (0.20 <= leaps_iv < 0.25) or (0.40 < leaps_iv <= 0.50):
            score += 1

        # Realistic yield (0–2 pts)
        if annual_yield_realistic >= 35:
            score += 2
        elif annual_yield_realistic >= 20:
            score += 1
        elif annual_yield_realistic >= 10:
            score += 0.5

        # Downside protection (0–1 pt)
        if pct_to_breakeven >= 15:
            score += 1
        elif pct_to_breakeven >= 8:
            score += 0.5

        # Penalties
        if earnings_within_window:
            score -= 2
        if short_strike < current_price * 1.03:
            score -= 0.5

        # Normalize raw score to 0–10 scale
        pmcc_score = round(max(0.0, min(10.0, score / 13.0 * 10)), 1)

        # --- Step 9: Risk flags ---
        risk_flags: list[str] = []
        if earnings_within_window and days_to_earnings is not None:
            risk_flags.append(f"Earnings in {days_to_earnings}d — within short call window")
        if leaps_iv > 0.50:
            risk_flags.append(
                f"High IV ({leaps_iv * 100:.0f}%) — elevated risk, not rewarded in score"
            )
        if leaps_spread_pct > 15:
            risk_flags.append(f"Wide LEAPS spread ({leaps_spread_pct:.0f}%) — execution risk")
        if short_spread_pct > 20:
            risk_flags.append(f"Wide short call spread ({short_spread_pct:.0f}%)")
        if short_strike < current_price * 1.03:
            risk_flags.append("Short call near ATM — elevated assignment risk")
        if leaps_strike > current_price * 0.92:
            risk_flags.append("LEAPS less than 8% ITM — limited intrinsic value")
        if pct_to_breakeven < 10:
            risk_flags.append(f"Low downside cushion ({pct_to_breakeven:.1f}% to breakeven)")
        if leaps_oi < 100:
            risk_flags.append(f"Low LEAPS OI ({leaps_oi}) — execution risk")
        if int(leaps_option.get("volume") or 0) == 0:
            risk_flags.append("No LEAPS volume today — verify liquidity before entry")
        if short_iv_fallback_used:
            risk_flags.append("Short chain IV unavailable — using LEAPS IV estimate")

        return {
            "symbol": symbol,
            "price": round(current_price, 2),
            "leaps_iv_pct": round(leaps_iv * 100, 1),
            "short_iv_pct": round(short_iv * 100, 1),
            "pmcc_score": pmcc_score,
            "earnings_date": earnings_date_str,
            "earnings_risk": earnings_within_window,
            "leaps": {
                "expiry": leaps_expiry,
                "days": leaps_days,
                "strike": leaps_strike,
                "delta": round(actual_leaps_delta, 3),
                "bid": round(leaps_bid, 2),
                "ask": round(leaps_ask, 2),
                "mid": round(leaps_mid, 2),
                "intrinsic": round(leaps_intrinsic, 2),
                "extrinsic": round(leaps_extrinsic, 2),
                "spread_pct": round(leaps_spread_pct, 1),
                "volume": int(leaps_option.get("volume") or 0),
                "oi": leaps_oi,
            },
            "short": {
                "expiry": short_expiry,
                "days": short_days,
                "strike": short_strike,
                "delta": round(actual_short_delta, 3),
                "bid": round(short_bid, 2),
                "ask": round(short_ask, 2),
                "mid": round(short_mid, 2),
                "spread_pct": round(short_spread_pct, 1),
                "volume": int(short_option.get("volume") or 0),
                "oi": short_oi,
            },
            "metrics": {
                "net_debit": round(net_debit, 2),
                "max_loss": round(max_loss, 2),
                "breakeven_price": round(breakeven_price, 2),
                "pct_to_breakeven": round(pct_to_breakeven, 1),
                "annual_yield_theoretical_pct": round(annual_yield_theoretical, 1),
                "annual_yield_realistic_pct": round(annual_yield_realistic, 1),
                "short_bid": round(short_bid, 2),
                "short_mid": round(short_mid, 2),
                "leaps_extrinsic_pct": round(leaps_extrinsic_pct, 1),
                "capital_required": round(capital_required, 2),
                "capital_efficiency_pct": round(annual_yield_realistic, 1),
                "delta_spread": round(delta_spread, 3),
            },
            "risk_flags": risk_flags,
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}
