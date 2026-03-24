# ABOUTME: Scans symbols for bullish trends and ranks them by composite score (v2).
# ABOUTME: Uses SMA, RSI, MACD, ADX, volume, breakout, trend consistency, and overextension.

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from trading_skills.earnings import get_earnings_info
from trading_skills.technicals import compute_raw_indicators

# Maximum theoretical score for v2 scoring model.
# SMA20(1) + SMA50(1) + SMA200(1.5) + RSI(1) + MACD(1.5) + ADX(1.5)
# + Consistency(2) + Volume(1) + Breakout(1) = 11.5
# Penalties (not counted in max): overextension(-0.5), weak ADX(-0.5), RSI overbought(-0.5)
SCORE_MAX = 11.5


def _classify_trend_stage(
    current_price: float,
    sma20_val: float | None,
    atr_val: float | None,
    sma50_val: float | None,
    days_above: int | None,
) -> str:
    """Classify trend stage using ATR-normalized distance from SMA20.

    Returns: 'early', 'mid', 'extended', or 'below'.
    """
    if sma20_val is None or current_price <= sma20_val:
        return "below"

    # Without ATR, fall back to percentage-based classification
    if atr_val is None or atr_val <= 0:
        pct = (current_price - sma20_val) / sma20_val * 100
        if pct < 2:
            return "early"
        elif pct < 8:
            return "mid"
        return "extended"

    distance_in_atr = (current_price - sma20_val) / atr_val

    # Early: just crossed above OR very close to SMA20
    # Also early if only recently above (< 5 of last 20 days)
    if distance_in_atr < 0.5:
        return "early"
    if days_above is not None and days_above <= 5:
        return "early"

    # Extended: stretched too far from SMA20
    if distance_in_atr > 2.0:
        return "extended"

    # Mid: healthy trending position
    # Bonus confidence if SMA20 > SMA50 (intermediate trend aligned)
    if sma50_val is not None and sma20_val > sma50_val:
        return "mid"

    # Above SMA20 but SMA20 not yet above SMA50 — still early/developing
    return "early" if distance_in_atr < 1.0 else "mid"


def compute_bullish_score(symbol: str, period: str = "12mo", ticker=None) -> dict | None:
    """Compute bullish trend score for a symbol (v2).

    Scoring model (max ~11.5):
    - SMA20 above: +1.0, SMA50 above: +1.0, SMA200 above: +1.5
    - SMA200 below: HARD-CAP score at 3.0 (bear market override)
    - RSI graduated: +1.0 (55-70), +0.5 (45-55), +0.25 (70-80), -0.5 (>80 w/ ADX<20)
    - MACD above signal: +1.0, histogram rising: +0.5
    - ADX >25 + bullish DI: +1.5, bullish DI only: +0.5, ADX<15 + bearish DI: -0.5
    - Trend consistency: (days_above_sma20/20) * 2.0 (replaces naive momentum)
    - Volume: OBV accumulation: +0.5, RVOL>1.3 on up day: +0.5
    - Breakout: 20-day high: +1.0
    - Overextension: >2x ATR above SMA20: -0.5

    NOTE: period defaults to "12mo" to enable SMA200 calculation.
    """
    try:
        ticker = ticker or yf.Ticker(symbol)
        df = ticker.history(period=period)

        if df.empty or len(df) < 50:
            return None

        # Guard against NaN prices (yfinance data quality issue)
        import math as _math

        last_close = df["Close"].iloc[-1]
        is_nan = isinstance(last_close, float) and _math.isnan(last_close)
        if last_close is None or is_nan:
            # Try second-to-last row
            if len(df) > 1:
                last_close = df["Close"].iloc[-2]
                if last_close is None or _math.isnan(last_close):
                    return None
                df = df.iloc[:-1]  # Drop the NaN row
            else:
                return None

        earnings_info = get_earnings_info(symbol)
        next_earnings = earnings_info.get("earnings_date")
        earnings_timing = earnings_info.get("timing")

        score = 0.0
        signals = []
        current_price = float(df["Close"].iloc[-1])

        period_return = (current_price / df["Close"].iloc[0] - 1) * 100

        raw = compute_raw_indicators(df)

        # --- SMA analysis (unchanged from v1) ---
        sma20_val = raw["sma20"]
        sma50_val = raw["sma50"]
        sma200_val = raw["sma200"]

        if sma20_val is not None:
            if current_price > sma20_val:
                score += 1.0
                signals.append("Above SMA20")
            pct_from_sma20 = ((current_price - sma20_val) / sma20_val) * 100
        else:
            pct_from_sma20 = 0

        if sma50_val is not None:
            if current_price > sma50_val:
                score += 1.0
                signals.append("Above SMA50")
            pct_from_sma50 = ((current_price - sma50_val) / sma50_val) * 100
        else:
            pct_from_sma50 = 0

        # SMA200 — most important regime filter (backtest-validated)
        # Bull market (price > SMA200): bonus points — confirms macro uptrend
        # Bear market (price < SMA200): hard cap score at 3.0 (forces neutral/bear class)
        above_sma200 = None
        pct_from_sma200 = 0
        if sma200_val is not None:
            above_sma200 = current_price > sma200_val
            pct_from_sma200 = ((current_price - sma200_val) / sma200_val) * 100
            if above_sma200:
                score += 1.5
                signals.append(f"Above SMA200 — bull market (+{pct_from_sma200:.1f}%)")
            else:
                score = min(score, 3.0)
                signals.append(f"Below SMA200 — bear market ({pct_from_sma200:.1f}%) ⚠️")

        # --- RSI analysis (v2: graduated with conditional overbought penalty) ---
        rsi_val = raw["rsi"]
        adx_val = raw["adx"]
        if rsi_val is not None:
            if 55 <= rsi_val <= 70:
                score += 1.0
                signals.append(f"RSI sweet spot ({rsi_val:.1f})")
            elif 45 <= rsi_val < 55:
                score += 0.5
                signals.append(f"RSI neutral ({rsi_val:.1f})")
            elif 70 < rsi_val <= 80:
                score += 0.25
                signals.append(f"RSI strong but caution ({rsi_val:.1f})")
            elif rsi_val > 80:
                # Penalize only when ADX is weak (no trend support)
                if adx_val is not None and adx_val < 20:
                    score -= 0.5
                    signals.append(
                        f"RSI overbought no trend support ({rsi_val:.1f}, ADX={adx_val:.0f}) ⚠️"
                    )
                else:
                    score += 0.25
                    signals.append(f"RSI overbought but strong trend ({rsi_val:.1f})")
            elif 30 <= rsi_val < 45:
                score += 0.25
                signals.append(f"RSI weak ({rsi_val:.1f})")
            elif rsi_val < 30:
                score += 0.25
                signals.append(f"RSI oversold ({rsi_val:.1f})")

        # --- MACD analysis (unchanged from v1) ---
        macd_val = raw["macd_line"]
        macd_signal_val = raw["macd_signal"]
        macd_hist = raw["macd_hist"]
        prev_hist = raw["prev_macd_hist"]

        if macd_val is not None and macd_signal_val is not None:
            if macd_val > macd_signal_val:
                score += 1.0
                signals.append("MACD above signal")
        if macd_hist is not None and prev_hist is not None:
            if macd_hist > prev_hist:
                score += 0.5
                signals.append("MACD momentum rising")

        # --- ADX analysis (v2: adds weak-trend penalty) ---
        dmp = raw["dmp"]
        dmn = raw["dmn"]

        if adx_val is not None and dmp is not None and dmn is not None:
            if adx_val > 25 and dmp > dmn:
                score += 1.5
                signals.append(f"Strong bullish trend (ADX={adx_val:.1f})")
            elif dmp > dmn:
                score += 0.5
                signals.append("Bullish direction (+DI > -DI)")
            elif adx_val < 15 and dmn > dmp:
                score -= 0.5
                signals.append(f"Weak directionless trend (ADX={adx_val:.1f}, -DI>{'+'}DI) ⚠️")

        # --- Trend consistency (v2: replaces naive momentum) ---
        days_above = raw.get("days_above_sma20")
        if days_above is not None:
            consistency = days_above / 20.0
            consistency_bonus = min(consistency * 2.0, 2.0)
            score += consistency_bonus
            if consistency >= 0.8:
                signals.append(f"Strong trend consistency ({days_above}/20 days above SMA20)")
            elif consistency >= 0.5:
                signals.append(f"Moderate trend consistency ({days_above}/20 days above SMA20)")
            else:
                signals.append(f"Weak trend consistency ({days_above}/20 days above SMA20)")
        else:
            # Fallback to v1 momentum if consistency unavailable
            momentum_bonus = min(max(period_return / 20, -1), 2)
            score += momentum_bonus

        # --- Volume confirmation (v2: new) ---
        obv_val = raw.get("obv")
        obv_sma20 = raw.get("obv_sma20")
        rvol = raw.get("relative_volume")

        obv_trend = None
        volume_confirmed = False

        if obv_val is not None and obv_sma20 is not None:
            if obv_val > obv_sma20:
                obv_trend = "rising"
                score += 0.5
                signals.append("OBV rising (accumulation)")
            else:
                obv_trend = "falling"

        # RVOL bonus only on up-close days
        daily_return = 0.0
        if len(df) >= 2:
            daily_return = (df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100

        if rvol is not None and rvol > 1.3 and daily_return > 0:
            score += 0.5
            volume_confirmed = True
            signals.append(f"Volume-confirmed up move (RVOL={rvol:.1f}x)")

        # --- Breakout detection (v2: new) ---
        high_20d = raw.get("high_20d")
        breakout_signal = False
        if high_20d is not None and "High" in df.columns:
            current_high = float(df["High"].iloc[-1])
            if current_high >= high_20d:
                breakout_signal = True
                score += 1.0
                signals.append("20-day high breakout")

        # --- Trend stage classification (v2: new, informational only) ---
        atr_val = raw.get("atr")
        trend_stage = _classify_trend_stage(
            current_price, sma20_val, atr_val, sma50_val, days_above
        )

        # --- Overextension penalty (v2: new) ---
        if (
            trend_stage == "extended"
            and atr_val is not None
            and sma20_val is not None
            and current_price > sma20_val
        ):
            score -= 0.5
            signals.append(
                f"Overextended ({(current_price - sma20_val) / atr_val:.1f}x ATR above SMA20) ⚠️"
            )

        # --- SMA200 hard cap re-applied LAST (unchanged from v1) ---
        if sma200_val is not None and not above_sma200:
            score = min(score, 3.0)

        # Compute normalized score (0.0 - 1.0)
        normalized = max(0.0, min(score / SCORE_MAX, 1.0))

        # Trend consistency ratio
        consistency_ratio = (days_above / 20.0) if days_above is not None else None

        return {
            # Original fields (backward compatible)
            "symbol": symbol,
            "score": round(score, 2),
            "price": round(current_price, 2),
            "next_earnings": next_earnings,
            "earnings_timing": earnings_timing,
            "period_return_pct": round(period_return, 2),
            "pct_from_sma20": round(pct_from_sma20, 2),
            "pct_from_sma50": round(pct_from_sma50, 2),
            "pct_from_sma200": round(pct_from_sma200, 2),
            "above_sma200": above_sma200,
            "sma200": round(sma200_val, 2) if sma200_val else None,
            "rsi": round(rsi_val, 2) if rsi_val else None,
            "macd": round(macd_val, 4) if macd_val else None,
            "macd_signal": round(macd_signal_val, 4) if macd_signal_val else None,
            "macd_hist": round(macd_hist, 4) if macd_hist else None,
            "adx": round(adx_val, 2) if adx_val else None,
            "dmp": round(dmp, 2) if dmp else None,
            "dmn": round(dmn, 2) if dmn else None,
            "signals": signals,
            # v2 new fields
            "trend_stage": trend_stage,
            "breakout_signal": breakout_signal,
            "volume_confirmed": volume_confirmed,
            "obv_trend": obv_trend,
            "relative_volume": round(rvol, 2) if rvol else None,
            "trend_consistency": (
                round(consistency_ratio, 2) if consistency_ratio is not None else None
            ),
            "normalized_score": round(normalized, 3),
            "score_version": "2.0",
        }
    except Exception as e:
        print(f"Error processing {symbol}: {e}", file=sys.stderr)
        return None


def scan_symbols(
    symbols: list[str],
    top_n: int = 30,
    period: str = "12mo",
    workers: int = 10,
    min_score: float | None = None,
) -> list[dict]:
    """Scan all symbols and return top N by bullish score.

    Args:
        symbols: List of ticker symbols to scan.
        top_n: Maximum number of results to return.
        period: Historical period for analysis (default: 12mo for SMA200).
        workers: Number of concurrent threads.
        min_score: If set, filter out results below this score.
    """
    results = []
    total = len(symbols)

    print(f"Scanning {total} symbols...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(compute_bullish_score, sym, period): sym for sym in symbols}

        for i, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                if result:
                    if min_score is not None and result["score"] < min_score:
                        continue
                    results.append(result)
                if i % 50 == 0:
                    print(f"  Processed {i}/{total}...", file=sys.stderr)
            except Exception as e:
                print(f"  Failed {symbol}: {e}", file=sys.stderr)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
