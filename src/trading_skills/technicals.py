# ABOUTME: Computes technical indicators using pandas-ta.
# ABOUTME: Trend, volume, support/resistance, confluence, and risk metrics.

import math

import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf

from trading_skills.earnings import get_next_earnings_date
from trading_skills.utils import annualized_volatility

# Signal classification sets for confluence scoring
BULLISH_SIGNALS = {
    "oversold",
    "bullish_crossover",
    "below_lower_band",
    "golden_cross",
    "stoch_rsi_oversold",
    "stoch_rsi_bullish_cross",
}
BEARISH_SIGNALS = {
    "overbought",
    "bearish_crossover",
    "above_upper_band",
    "death_cross",
    "stoch_rsi_overbought",
    "stoch_rsi_bearish_cross",
}


def get_earnings_data(symbol: str) -> dict:
    """Get upcoming and historical earnings data for a symbol."""
    ticker = yf.Ticker(symbol)
    result = {"symbol": symbol.upper()}

    # Get upcoming earnings date
    upcoming = get_next_earnings_date(symbol)
    if upcoming:
        result["upcoming"] = upcoming

    # Get historical earnings
    try:
        earnings_dates = ticker.earnings_dates
        if earnings_dates is not None and not earnings_dates.empty:
            history = []
            for idx in earnings_dates.head(8).index:
                row = earnings_dates.loc[idx]
                entry = {"date": str(idx.date()) if hasattr(idx, "date") else str(idx)}

                if "EPS Estimate" in row and pd.notna(row["EPS Estimate"]):
                    entry["estimated_eps"] = round(float(row["EPS Estimate"]), 3)
                if "Reported EPS" in row and pd.notna(row["Reported EPS"]):
                    entry["reported_eps"] = round(float(row["Reported EPS"]), 3)
                if "Surprise(%)" in row and pd.notna(row["Surprise(%)"]):
                    entry["surprise_pct"] = round(float(row["Surprise(%)"]), 2)

                if "estimated_eps" in entry or "reported_eps" in entry:
                    history.append(entry)

            if history:
                result["history"] = history
    except Exception:
        pass

    return result


def compute_raw_indicators(df: pd.DataFrame) -> dict:
    """Extract raw technical indicator values from an OHLCV DataFrame.

    Returns dict with keys for SMA, RSI, MACD, ADX, plus volume and momentum
    indicators. Values are None when insufficient data.
    """
    result = {
        # Original indicators
        "rsi": None,
        "sma20": None,
        "sma50": None,
        "sma200": None,
        "macd_line": None,
        "macd_signal": None,
        "macd_hist": None,
        "prev_macd_hist": None,
        "adx": None,
        "dmp": None,
        "dmn": None,
        # Stochastic RSI
        "stoch_rsi_k": None,
        "stoch_rsi_d": None,
        # Momentum
        "roc": None,
        # Volume
        "obv": None,
        "obv_sma20": None,
        "relative_volume": None,
        # Bollinger Bands
        "bb_lower": None,
        "bb_mid": None,
        "bb_upper": None,
        "bb_bandwidth": None,
        # ATR
        "atr": None,
        # Trend consistency & breakout
        "days_above_sma20": None,
        "high_20d": None,
    }

    if df.empty or "Close" not in df.columns:
        return result

    close = df["Close"]

    # RSI
    rsi = ta.rsi(close, length=14)
    if rsi is not None and len(rsi) > 0:
        val = rsi.iloc[-1]
        if pd.notna(val):
            result["rsi"] = float(val)

    # SMA
    sma20 = ta.sma(close, length=20)
    if sma20 is not None and len(sma20) > 0:
        val = sma20.iloc[-1]
        if pd.notna(val):
            result["sma20"] = float(val)

    sma50 = ta.sma(close, length=50)
    if sma50 is not None and len(sma50) > 0:
        val = sma50.iloc[-1]
        if pd.notna(val):
            result["sma50"] = float(val)

    # SMA200 — requires at least 200 bars (need period="12mo" or longer)
    sma200 = ta.sma(close, length=200)
    if sma200 is not None and len(sma200) > 0:
        val = sma200.iloc[-1]
        if pd.notna(val):
            result["sma200"] = float(val)

    # MACD
    macd = ta.macd(close)
    if macd is not None and len(macd) > 0:
        line = macd.iloc[-1, 0]
        signal = macd.iloc[-1, 1]
        hist = macd.iloc[-1, 2]
        if pd.notna(line):
            result["macd_line"] = float(line)
        if pd.notna(signal):
            result["macd_signal"] = float(signal)
        if pd.notna(hist):
            result["macd_hist"] = float(hist)
        if len(macd) > 1:
            prev = macd.iloc[-2, 2]
            if pd.notna(prev):
                result["prev_macd_hist"] = float(prev)

    # ADX
    if "High" in df.columns and "Low" in df.columns:
        adx = ta.adx(df["High"], df["Low"], close, length=14)
        if adx is not None and len(adx) > 0:
            adx_val = adx.iloc[-1, 0]
            dmp_val = adx.iloc[-1, 1]
            dmn_val = adx.iloc[-1, 2]
            if pd.notna(adx_val):
                result["adx"] = float(adx_val)
            if pd.notna(dmp_val):
                result["dmp"] = float(dmp_val)
            if pd.notna(dmn_val):
                result["dmn"] = float(dmn_val)

    # Stochastic RSI
    stoch_rsi = ta.stochrsi(close, length=14, rsi_length=14, k=3, d=3)
    if stoch_rsi is not None and len(stoch_rsi) > 0:
        k_val = stoch_rsi.iloc[-1, 0]
        d_val = stoch_rsi.iloc[-1, 1]
        if pd.notna(k_val):
            result["stoch_rsi_k"] = float(k_val)
        if pd.notna(d_val):
            result["stoch_rsi_d"] = float(d_val)

    # Rate of Change (12-period)
    roc = ta.roc(close, length=12)
    if roc is not None and len(roc) > 0:
        val = roc.iloc[-1]
        if pd.notna(val):
            result["roc"] = float(val)

    # Volume indicators
    if "Volume" in df.columns:
        volume = df["Volume"]

        # On Balance Volume
        obv = ta.obv(close, volume)
        if obv is not None and len(obv) > 0:
            val = obv.iloc[-1]
            if pd.notna(val):
                result["obv"] = float(val)
            obv_sma = ta.sma(obv, length=20)
            if obv_sma is not None and len(obv_sma) > 0:
                sma_val = obv_sma.iloc[-1]
                if pd.notna(sma_val):
                    result["obv_sma20"] = float(sma_val)

        # Relative Volume (current bar vs 20-day average)
        vol_avg = volume.rolling(20).mean()
        if vol_avg is not None and len(vol_avg) > 0:
            avg_val = vol_avg.iloc[-1]
            cur_val = volume.iloc[-1]
            if pd.notna(avg_val) and avg_val > 0 and pd.notna(cur_val):
                result["relative_volume"] = float(cur_val / avg_val)

    # Bollinger Bands (20, 2)
    bb = ta.bbands(close, length=20, std=2)
    if bb is not None and len(bb) > 0:
        lower = bb.iloc[-1, 0]
        mid = bb.iloc[-1, 1]
        upper = bb.iloc[-1, 2]
        if pd.notna(lower):
            result["bb_lower"] = float(lower)
        if pd.notna(mid):
            result["bb_mid"] = float(mid)
        if pd.notna(upper):
            result["bb_upper"] = float(upper)
        if pd.notna(lower) and pd.notna(mid) and pd.notna(upper) and mid > 0:
            result["bb_bandwidth"] = float((upper - lower) / mid * 100)

    # ATR (14-period)
    if "High" in df.columns and "Low" in df.columns:
        atr = ta.atr(df["High"], df["Low"], close, length=14)
        if atr is not None and len(atr) > 0:
            val = atr.iloc[-1]
            if pd.notna(val):
                result["atr"] = float(val)

    # Trend consistency: count of last 20 days where close > SMA20
    sma20_for_consistency = ta.sma(close, length=20)
    if sma20_for_consistency is not None and len(sma20_for_consistency) >= 20:
        last_20_close = close.iloc[-20:]
        last_20_sma = sma20_for_consistency.iloc[-20:]
        valid = last_20_sma.notna()
        if valid.sum() > 0:
            above = (last_20_close[valid] > last_20_sma[valid]).sum()
            result["days_above_sma20"] = int(above)

    # 20-day rolling high (for breakout detection)
    if len(close) >= 20:
        high_col = df["High"] if "High" in df.columns else close
        rolling_high = high_col.rolling(20).max()
        if rolling_high is not None and len(rolling_high) > 0:
            val = rolling_high.iloc[-1]
            if pd.notna(val):
                result["high_20d"] = float(val)

    return result


def _classify_trend(raw: dict, current_price: float) -> dict:
    """Classify trend from raw indicators using scanner_bullish scoring logic.

    Returns dict with label, score, and contributing factors.
    """
    score = 0.0
    factors = []

    # SMA positioning
    if raw["sma20"] and current_price > raw["sma20"]:
        score += 1.0
        factors.append("above_sma20")
    if raw["sma50"] and current_price > raw["sma50"]:
        score += 1.0
        factors.append("above_sma50")
    if raw["sma200"] and current_price > raw["sma200"]:
        score += 1.5
        factors.append("above_sma200")
    elif raw["sma200"]:
        score = min(score, 3.0)
        factors.append("below_sma200_cap")

    # RSI
    if raw["rsi"] and 50 <= raw["rsi"] <= 70:
        score += 1.0
    elif raw["rsi"] and 30 <= raw["rsi"] < 50:
        score += 0.5

    # MACD
    if raw["macd_line"] and raw["macd_signal"] and raw["macd_line"] > raw["macd_signal"]:
        score += 1.0
        factors.append("macd_bullish")
    if raw["macd_hist"] and raw["prev_macd_hist"] and raw["macd_hist"] > raw["prev_macd_hist"]:
        score += 0.5
        factors.append("macd_momentum_rising")

    # ADX
    if raw["adx"] and raw["dmp"] and raw["dmn"]:
        if raw["adx"] > 25 and raw["dmp"] > raw["dmn"]:
            score += 1.5
            factors.append("strong_bullish_trend")
        elif raw["dmp"] > raw["dmn"]:
            score += 0.5
            factors.append("bullish_direction")

    # Re-apply SMA200 cap
    if raw["sma200"] and current_price < raw["sma200"]:
        score = min(score, 3.0)

    # Classify
    if score >= 6.0:
        label = "strong_bull"
    elif score >= 4.0:
        label = "bull"
    elif score >= 2.0:
        label = "neutral"
    elif score >= 1.0:
        label = "bear"
    else:
        label = "strong_bear"

    return {"label": label, "score": round(score, 2), "factors": factors}


def _find_swing_levels(df: pd.DataFrame, window: int = 5, count: int = 3) -> dict:
    """Find recent swing highs and lows from OHLCV data.

    Uses a rolling window to identify local extremes.
    """
    highs = []
    lows = []

    if len(df) < window * 2 + 1:
        return {"swing_highs": [], "swing_lows": []}

    high_col = df["High"] if "High" in df.columns else df["Close"]
    low_col = df["Low"] if "Low" in df.columns else df["Close"]

    # Scan for local maxima/minima
    for i in range(window, len(df) - window):
        # Swing high: current high is highest in window on both sides
        is_high = True
        for j in range(i - window, i + window + 1):
            if j != i and high_col.iloc[j] >= high_col.iloc[i]:
                is_high = False
                break
        if is_high:
            highs.append(round(float(high_col.iloc[i]), 2))

        # Swing low: current low is lowest in window on both sides
        is_low = True
        for j in range(i - window, i + window + 1):
            if j != i and low_col.iloc[j] <= low_col.iloc[i]:
                is_low = False
                break
        if is_low:
            lows.append(round(float(low_col.iloc[i]), 2))

    return {
        "swing_highs": highs[-count:] if highs else [],
        "swing_lows": lows[-count:] if lows else [],
    }


def _compute_confluence(signals: list[dict]) -> dict:
    """Score signal confluence — how many bullish vs bearish signals align."""
    bullish = [s for s in signals if s.get("signal") in BULLISH_SIGNALS]
    bearish = [s for s in signals if s.get("signal") in BEARISH_SIGNALS]

    bc = len(bullish)
    brc = len(bearish)

    if bc > brc:
        bias = "bullish"
    elif brc > bc:
        bias = "bearish"
    else:
        bias = "neutral"

    total = bc + brc
    if total >= 3:
        strength = "strong"
    elif total >= 2:
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "bullish_count": bc,
        "bearish_count": brc,
        "bias": bias,
        "strength": strength,
    }


def compute_indicators(
    symbol: str,
    period: str = "3mo",
    indicators: list[str] | None = None,
    include_earnings: bool = False,
    include_beta: bool = False,
) -> dict:
    """Compute technical indicators for a symbol.

    Args:
        symbol: Ticker symbol
        period: Historical period (1mo, 3mo, 6mo, 1y)
        indicators: List of indicator names to compute (default: all)
        include_earnings: Include earnings data
        include_beta: Include beta vs SPY (requires extra data fetch)
    """
    if indicators is None:
        indicators = ["rsi", "macd", "bb", "sma", "ema", "atr", "adx", "vwap", "sr"]

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)

    if df.empty:
        return {"error": f"No data for {symbol}"}

    current_price = df["Close"].iloc[-1]

    result = {
        "symbol": symbol.upper(),
        "period": period,
        "price": {
            "current": round(current_price, 2),
            "change": round(current_price - df["Close"].iloc[-2], 2),
            "change_pct": round((current_price / df["Close"].iloc[-2] - 1) * 100, 2),
        },
        "indicators": {},
        "signals": [],
    }

    raw = compute_raw_indicators(df)

    # --- RSI ---
    if "rsi" in indicators and raw["rsi"] is not None:
        current_rsi = raw["rsi"]
        result["indicators"]["rsi"] = {
            "value": round(current_rsi, 2),
            "period": 14,
        }
        # Stochastic RSI sub-section
        if raw["stoch_rsi_k"] is not None:
            result["indicators"]["rsi"]["stoch_rsi_k"] = round(raw["stoch_rsi_k"], 2)
            result["indicators"]["rsi"]["stoch_rsi_d"] = round(raw["stoch_rsi_d"], 2)

        if current_rsi > 70:
            strength = min((current_rsi - 70) / 30, 1.0)
            result["signals"].append(
                {
                    "indicator": "RSI",
                    "signal": "overbought",
                    "value": round(current_rsi, 2),
                    "strength": round(strength, 2),
                }
            )
        elif current_rsi < 30:
            strength = min((30 - current_rsi) / 30, 1.0)
            result["signals"].append(
                {
                    "indicator": "RSI",
                    "signal": "oversold",
                    "value": round(current_rsi, 2),
                    "strength": round(strength, 2),
                }
            )

        # Stochastic RSI signals
        if raw["stoch_rsi_k"] is not None and raw["stoch_rsi_d"] is not None:
            k, d = raw["stoch_rsi_k"], raw["stoch_rsi_d"]
            if k > 80 and d > 80:
                result["signals"].append(
                    {"indicator": "StochRSI", "signal": "stoch_rsi_overbought",
                     "value": round(k, 2)}
                )
            elif k < 20 and d < 20:
                result["signals"].append(
                    {"indicator": "StochRSI", "signal": "stoch_rsi_oversold", "value": round(k, 2)}
                )

    # --- MACD ---
    vol_confirmed = raw.get("relative_volume") and raw["relative_volume"] > 1.5
    if "macd" in indicators and raw["macd_line"] is not None:
        result["indicators"]["macd"] = {
            "macd": round(raw["macd_line"], 4),
            "signal": round(raw["macd_signal"], 4),
            "histogram": round(raw["macd_hist"], 4),
        }
        if raw["prev_macd_hist"] is not None:
            if raw["prev_macd_hist"] < 0 and raw["macd_hist"] > 0:
                sig = {"indicator": "MACD", "signal": "bullish_crossover"}
                if vol_confirmed:
                    sig["volume_confirmed"] = True
                result["signals"].append(sig)
            elif raw["prev_macd_hist"] > 0 and raw["macd_hist"] < 0:
                sig = {"indicator": "MACD", "signal": "bearish_crossover"}
                if vol_confirmed:
                    sig["volume_confirmed"] = True
                result["signals"].append(sig)

    # --- Bollinger Bands ---
    if "bb" in indicators:
        bb = ta.bbands(df["Close"], length=20, std=2)
        if bb is not None and len(bb) > 0:
            lower = bb.iloc[-1, 0]
            mid = bb.iloc[-1, 1]
            upper = bb.iloc[-1, 2]
            result["indicators"]["bollinger"] = {
                "lower": round(lower, 2),
                "middle": round(mid, 2),
                "upper": round(upper, 2),
                "bandwidth": round((upper - lower) / mid * 100, 2),
            }
            if current_price < lower:
                sig = {"indicator": "BB", "signal": "below_lower_band"}
                if vol_confirmed:
                    sig["volume_confirmed"] = True
                result["signals"].append(sig)
            elif current_price > upper:
                sig = {"indicator": "BB", "signal": "above_upper_band"}
                if vol_confirmed:
                    sig["volume_confirmed"] = True
                result["signals"].append(sig)

    # --- SMA ---
    if "sma" in indicators:
        result["indicators"]["sma"] = {}
        if raw["sma20"] is not None:
            result["indicators"]["sma"]["sma20"] = round(raw["sma20"], 2)
        if raw["sma50"] is not None:
            result["indicators"]["sma"]["sma50"] = round(raw["sma50"], 2)
            # Golden/death cross needs previous values
            sma20 = ta.sma(df["Close"], length=20)
            sma50 = ta.sma(df["Close"], length=50)
            if sma20 is not None and sma50 is not None and len(sma20) > 1 and len(sma50) > 1:
                if sma20.iloc[-2] < sma50.iloc[-2] and sma20.iloc[-1] > sma50.iloc[-1]:
                    sig = {"indicator": "SMA", "signal": "golden_cross"}
                    if vol_confirmed:
                        sig["volume_confirmed"] = True
                    result["signals"].append(sig)
                elif sma20.iloc[-2] > sma50.iloc[-2] and sma20.iloc[-1] < sma50.iloc[-1]:
                    sig = {"indicator": "SMA", "signal": "death_cross"}
                    if vol_confirmed:
                        sig["volume_confirmed"] = True
                    result["signals"].append(sig)
        if raw["sma200"] is not None:
            result["indicators"]["sma"]["sma200"] = round(raw["sma200"], 2)

    # --- EMA ---
    if "ema" in indicators:
        ema12 = ta.ema(df["Close"], length=12)
        ema26 = ta.ema(df["Close"], length=26)
        result["indicators"]["ema"] = {}
        if ema12 is not None and len(ema12) > 0:
            result["indicators"]["ema"]["ema12"] = round(ema12.iloc[-1], 2)
        if ema26 is not None and len(ema26) > 0:
            result["indicators"]["ema"]["ema26"] = round(ema26.iloc[-1], 2)

    # --- ATR ---
    if "atr" in indicators:
        atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
        if atr is not None and len(atr) > 0:
            result["indicators"]["atr"] = {
                "value": round(atr.iloc[-1], 2),
                "percent": round(atr.iloc[-1] / current_price * 100, 2),
            }

    # --- ADX ---
    if "adx" in indicators and raw["adx"] is not None:
        result["indicators"]["adx"] = {
            "adx": round(raw["adx"], 2),
            "dmp": round(raw["dmp"], 2),
            "dmn": round(raw["dmn"], 2),
        }
        if raw["adx"] > 25:
            strength = min((raw["adx"] - 25) / 50, 1.0)
            result["signals"].append(
                {
                    "indicator": "ADX",
                    "signal": "strong_trend",
                    "value": round(raw["adx"], 2),
                    "strength": round(strength, 2),
                }
            )

    # --- VWAP ---
    if "vwap" in indicators and "Volume" in df.columns:
        vwap = ta.vwap(df["High"], df["Low"], df["Close"], df["Volume"])
        if vwap is not None and len(vwap) > 0:
            vwap_val = vwap.iloc[-1]
            if pd.notna(vwap_val):
                result["indicators"]["vwap"] = {
                    "value": round(float(vwap_val), 2),
                    "price_vs_vwap": "above" if current_price > vwap_val else "below",
                }

    # --- Volume ---
    if raw.get("relative_volume") is not None:
        obv_trend = None
        if raw["obv"] is not None and raw["obv_sma20"] is not None:
            obv_trend = "rising" if raw["obv"] > raw["obv_sma20"] else "falling"
        rvol = raw["relative_volume"]
        result["indicators"]["volume"] = {
            "relative_volume": round(rvol, 2),
            "obv_trend": obv_trend,
        }
        if raw.get("roc") is not None:
            result["indicators"]["volume"]["roc_12"] = round(raw["roc"], 2)
        if rvol > 1.5:
            result["indicators"]["volume"]["interpretation"] = "High volume confirms move"
        elif rvol < 0.5:
            result["indicators"]["volume"]["interpretation"] = (
                "Low volume — move may lack conviction"
            )

    # --- Support/Resistance ---
    if "sr" in indicators and len(df) >= 11:
        sr = {}

        # Pivot points from previous day
        if len(df) >= 2:
            prev = df.iloc[-2]
            h, lo, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
            pivot = (h + lo + c) / 3
            sr["pivot"] = {
                "pivot": round(pivot, 2),
                "r1": round(2 * pivot - lo, 2),
                "r2": round(pivot + (h - lo), 2),
                "s1": round(2 * pivot - h, 2),
                "s2": round(pivot - (h - lo), 2),
            }

        # Swing highs/lows
        swing = _find_swing_levels(df)
        sr["swing_highs"] = swing["swing_highs"]
        sr["swing_lows"] = swing["swing_lows"]

        # Nearest levels
        all_supports = swing["swing_lows"]
        all_resistances = swing["swing_highs"]
        if "pivot" in sr:
            all_supports += [sr["pivot"]["s1"], sr["pivot"]["s2"]]
            all_resistances += [sr["pivot"]["r1"], sr["pivot"]["r2"]]

        below = [lvl for lvl in all_supports if lvl < current_price]
        above = [lvl for lvl in all_resistances if lvl > current_price]
        sr["nearest_support"] = max(below) if below else None
        sr["nearest_resistance"] = min(above) if above else None

        result["indicators"]["support_resistance"] = sr

    # --- Risk Metrics ---
    returns, daily_vol, annual_vol = annualized_volatility(df["Close"])
    if len(returns) > 0:
        annual_volatility = annual_vol * 100
        annual_mean_return = returns.mean() * 252 * 100
        if daily_vol > 0:
            sharpe_ratio = (returns.mean() * 252) / annual_vol
        else:
            sharpe_ratio = 0.0

        result["risk_metrics"] = {
            "volatility_annualized_pct": round(annual_volatility, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "mean_return_annualized_pct": round(annual_mean_return, 2),
        }

        # Max drawdown
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        result["risk_metrics"]["max_drawdown_pct"] = round(float(drawdown.min()) * 100, 2)

        # Sortino ratio (penalizes downside only)
        downside = returns[returns < 0]
        if len(downside) > 0:
            downside_vol = downside.std() * math.sqrt(252)
            sortino = (returns.mean() * 252) / downside_vol if downside_vol > 0 else 0.0
        else:
            sortino = 0.0
        result["risk_metrics"]["sortino_ratio"] = round(sortino, 2)

        # Beta vs SPY (optional — requires extra network call)
        if include_beta:
            try:
                spy_hist = yf.Ticker("SPY").history(period=period)
                spy_returns = spy_hist["Close"].pct_change().dropna()
                common_idx = returns.index.intersection(spy_returns.index)
                if len(common_idx) > 20:
                    stock_ret = returns.loc[common_idx]
                    spy_ret = spy_returns.loc[common_idx]
                    covariance = np.cov(stock_ret, spy_ret)[0, 1]
                    spy_variance = np.var(spy_ret)
                    beta = covariance / spy_variance if spy_variance > 0 else None
                    if beta is not None:
                        result["risk_metrics"]["beta"] = round(float(beta), 3)
            except Exception:
                pass

    # --- Trend Classification ---
    result["trend"] = _classify_trend(raw, current_price)

    # --- Confluence ---
    result["confluence"] = _compute_confluence(result["signals"])

    if include_earnings:
        result["earnings"] = get_earnings_data(symbol)

    return result


def compute_multi_symbol(
    symbols: list[str],
    period: str = "3mo",
    indicators: list[str] | None = None,
    include_earnings: bool = False,
    include_beta: bool = False,
) -> dict:
    """Compute indicators for multiple symbols."""
    results = []
    for symbol in symbols:
        result = compute_indicators(symbol, period, indicators, include_earnings, include_beta)
        results.append(result)

    return {"results": results}
