#!/usr/bin/env python3
# ABOUTME: Analyzes existing short option positions for rolling/closing decisions.
# ABOUTME: Classifies positions (CC/CSP), applies decision engine with Greeks,
# ABOUTME: theta preservation, and earnings guards, finds optimal roll targets
# ABOUTME: with net credit/debit from Tradier chain data.

import argparse
import json
import os
import sys
from datetime import datetime
from statistics import mean

# ── Tunable thresholds ────────────────────────────────────────────────────────
PROFIT_TARGET_PCT = 50.0        # Default profit capture threshold
THETA_EXIT_PCT = 0.10           # Let expire if remaining value < 10% of original
THETA_EXIT_MAX_DTE = 10         # Only apply theta exit when DTE <= this
MAX_ROLL_DEBIT = 0.50           # Max acceptable net debit per contract for roll
EARNINGS_BLOCK_DAYS = 14        # Hard-block roll targets within this many days
ATM_THRESHOLD_PCT = 1.0         # Within 1% of strike = ATM
SAFE_OTM_PCT = 3.0              # >3% OTM = safe to let expire
LOW_EXTRINSIC_THRESHOLD = 0.25  # CC ITM extrinsic below this -> roll
HIGH_DELTA_THRESHOLD = 0.70     # Delta above this -> high assignment risk
PREMIUM_EROSION_PCT = 0.005     # cost_basis/(strike*100) below this -> exit flag
CLOSE_REOPEN_SPREAD_PCT = 10.0  # Roll spread above this -> close + reopen
MIN_NET_CREDIT = 0.10           # Below this, close+reopen is likely better

# ── Reuse shared utilities from portfolio-income-plan ─────────────────────────
_skills_dir = os.path.join(
    os.path.dirname(__file__), "..", "..", "portfolio-income-plan", "scripts"
)
sys.path.insert(0, _skills_dir)
from extract_strikes import DELTA_RANGES  # noqa: E402, I001
from shared_utils import classify_earnings_risk  # noqa: E402, I001


# ═══════════════════════════════════════════════════════════════════════════════
# Function 1: Position Classification
# ═══════════════════════════════════════════════════════════════════════════════


def classify_position(
    option: dict,
    current_price: float,
    stock_positions: list[dict],
) -> dict:
    """Classify a short option position by type, moneyness, and risk level.

    Args:
        option: Single option position from portfolio JSON.
        current_price: Current stock price for the underlying.
        stock_positions: All stock positions (for CC eligibility check).

    Returns:
        dict with strategy, moneyness, risk_level, etc.
    """
    symbol = option.get("underlying", "")
    option_type = option.get("option_type", "")
    strike = option.get("strike", 0)
    expiry_str = option.get("expiry", "")
    contracts = abs(option.get("quantity", 0))

    # DTE calculation
    today = datetime.now().date()
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        dte = (expiry - today).days
    except (ValueError, TypeError):
        dte = 0

    # CC vs CSP: check if underlying has enough shares
    shares_held = 0
    for sp in stock_positions:
        if sp.get("symbol", "").upper() == symbol.upper():
            shares_held = sp.get("quantity", 0)
            break
    is_covered = shares_held >= 100 * contracts
    strategy = "CC" if option_type == "call" and is_covered else "CSP"

    # Moneyness
    if current_price <= 0 or strike <= 0:
        moneyness = "OTM"
        moneyness_pct = 0.0
        itm_amount = 0.0
    elif option_type == "call":
        # Call: OTM when price < strike
        moneyness_pct = (strike - current_price) / strike * 100
        itm_amount = max(0.0, current_price - strike)
    else:
        # Put: OTM when price > strike
        moneyness_pct = (current_price - strike) / strike * 100
        itm_amount = max(0.0, strike - current_price)

    if abs(moneyness_pct) <= ATM_THRESHOLD_PCT:
        moneyness = "ATM"
    elif moneyness_pct > 0:
        moneyness = "OTM"
    else:
        moneyness = "ITM"
        moneyness_pct = abs(moneyness_pct)  # report as positive distance

    # Delta-based risk level (uses greeks if available)
    greeks = option.get("greeks") or {}
    delta = abs(greeks.get("delta", 0) or 0)
    if delta >= 0.60:
        risk_level = "very_high"
    elif delta >= 0.40:
        risk_level = "high"
    elif delta >= 0.20:
        risk_level = "moderate"
    else:
        risk_level = "low"

    return {
        "symbol": symbol,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry_str,
        "dte": dte,
        "contracts": contracts,
        "strategy": strategy,
        "moneyness": moneyness,
        "moneyness_pct": round(moneyness_pct, 2),
        "itm_amount": round(itm_amount, 2),
        "is_covered": is_covered,
        "risk_level": risk_level,
        "delta": round(delta, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Function 2: Decision Engine
# ═══════════════════════════════════════════════════════════════════════════════


def decide_action(
    classification: dict,
    option: dict,
    current_price: float,
    close_cost: float | None = None,
    trend: str = "neutral",
    assignment_mode: str = "neutral",
    profit_target: float = PROFIT_TARGET_PCT,
) -> dict:
    """Apply decision engine rules to determine recommended action.

    Args:
        classification: Output from classify_position().
        option: Raw option position dict.
        current_price: Current underlying price.
        close_cost: Estimated cost to buy-to-close (option mid/ask).
        trend: Per-stock trend class for CC upside guard.
        assignment_mode: "avoid" / "neutral" / "wheel".
        profit_target: Profit capture threshold %.

    Returns:
        dict with action, reason, why_now, urgency, etc.
    """
    dte = classification["dte"]
    moneyness = classification["moneyness"]
    moneyness_pct = classification["moneyness_pct"]
    strategy = classification["strategy"]
    contracts = classification["contracts"]
    delta = classification["delta"]
    strike = classification["strike"]

    action = "HOLD"
    reason = ""
    why_now = ""
    urgency = 0
    needs_roll = False
    profit_captured_pct = None
    extrinsic_value = None
    assignment_risk = None
    hold_for_upside = False
    consider_exit = False
    exit_reason = None

    # ── Pre-check: Premium erosion detection ──────────────────────────────
    cost_basis = abs(option.get("cost_basis", 0))
    capital_at_risk = strike * 100 * contracts
    # cost_basis is per-share from parse_etrade; total = cost_basis * 100 * contracts
    total_premium = cost_basis * 100 * contracts
    if total_premium > 0 and capital_at_risk > 0:
        premium_ratio = total_premium / capital_at_risk
        if premium_ratio < PREMIUM_EROSION_PCT:
            consider_exit = True
            exit_reason = (
                f"Premium received ({premium_ratio:.3%} of capital) suggests "
                "position has been rolled repeatedly. Consider closing entirely."
            )

    # ── Profit calculation ────────────────────────────────────────────────
    # cost_basis from parse_etrade is cost_basis_total = per_share_premium * contracts
    # (e.g. sold 2 contracts at $0.63/share → cost_basis = 1.26, not 0.63)
    # current_value from parse_etrade is total position value in dollars
    current_value = abs(option.get("current_value", 0))
    if cost_basis > 0 and current_value > 0:
        per_sold = cost_basis / contracts              # total → per-share per-contract
        per_now = current_value / contracts / 100      # total → per-share
        if per_sold > 0:
            profit_captured_pct = round(
                (per_sold - per_now) / per_sold * 100, 1
            )

    # ── Extrinsic value (for ITM positions) ───────────────────────────────
    if moneyness == "ITM" and close_cost is not None:
        intrinsic = classification["itm_amount"]
        extrinsic_value = round(max(0, close_cost - intrinsic), 2)

    # ── Delta-based assignment risk ───────────────────────────────────────
    if delta >= HIGH_DELTA_THRESHOLD:
        assignment_risk = "high"
    elif delta >= 0.40:
        assignment_risk = "moderate"
    else:
        assignment_risk = "low"

    # ═══════════════════════════════════════════════════════════════════════
    # DECISION RULES (priority order — first match wins)
    # ═══════════════════════════════════════════════════════════════════════

    # Rule 1: Profit capture with theta guard
    if profit_captured_pct is not None and profit_captured_pct >= profit_target:
        # V3 theta guard: if option is nearly worthless, just let it expire
        # cost_basis is already per-share from parse_etrade output
        cost_basis_per = cost_basis
        if (
            close_cost is not None
            and cost_basis_per > 0
            and (close_cost / cost_basis_per) < THETA_EXIT_PCT
            and dte <= THETA_EXIT_MAX_DTE
        ):
            remaining_pct = close_cost / cost_basis_per
            action = "LET_EXPIRE"
            reason = (
                f"Profit {profit_captured_pct:.0f}% captured, "
                f"option worth ${close_cost:.2f} "
                f"({remaining_pct:.0%} of original). Let theta finish."
            )
            why_now = (
                f"theta nearly exhausted — only "
                f"{remaining_pct:.0%} of premium remains"
            )
            urgency = 0
        else:
            action = "CLOSE_EARLY"
            reason = (
                f"Profit {profit_captured_pct:.0f}% >= {profit_target:.0f}% "
                f"target. Buy to close ~${close_cost or per_now:.2f}."
            )
            why_now = f"profit target reached ({profit_captured_pct:.0f}%)"
            urgency = 1

    # Rule 2: DTE <= 5, safe OTM
    elif dte <= 5 and moneyness == "OTM" and moneyness_pct > SAFE_OTM_PCT:
        action = "LET_EXPIRE"
        reason = (
            f"{dte} DTE, {moneyness_pct:.1f}% OTM — safe to let expire."
        )
        why_now = f"expiration in {dte} days, safely OTM"
        urgency = 0

    # Rule 3: DTE <= 5, threatened (near strike)
    elif dte <= 5 and moneyness in ("ATM", "OTM") and moneyness_pct <= SAFE_OTM_PCT:
        action = "ROLL_OUT"
        reason = (
            f"{dte} DTE, only {moneyness_pct:.1f}% from strike — "
            "roll to avoid last-minute assignment risk."
        )
        why_now = f"expiration in {dte} days, dangerously close to strike"
        urgency = 2
        needs_roll = True

    # Rule 4: ITM CC — check extrinsic
    elif moneyness == "ITM" and strategy == "CC":
        if (
            trend in ("strong_bull",)
            and classification["itm_amount"] > 0
            and classification["itm_amount"] / strike * 100 < 3.0
        ):
            # Strong bull, barely ITM — flag for manual decision
            hold_for_upside = True
            action = "HOLD"
            reason = (
                f"ITM by ${classification['itm_amount']:.2f} but strong "
                "uptrend. Consider holding for upside vs rolling."
            )
            why_now = "strong momentum — rolling may cap gains"
            urgency = 1
        elif (
            extrinsic_value is not None
            and extrinsic_value < LOW_EXTRINSIC_THRESHOLD
        ) or delta > HIGH_DELTA_THRESHOLD:
            action = "ROLL_OUT_AND_UP"
            ext_str = (
                f"${extrinsic_value:.2f}" if extrinsic_value is not None
                else "unknown"
            )
            reason = (
                f"ITM CC, extrinsic {ext_str}, delta {delta:.2f}. "
                "Roll out and up to avoid assignment."
            )
            why_now = "low extrinsic — assignment likely"
            urgency = 2
            needs_roll = True
        else:
            # Rule 5: ITM CC with good extrinsic
            action = "HOLD"
            reason = (
                f"ITM CC but extrinsic ${extrinsic_value:.2f} still "
                "provides buffer. Monitor."
            )
            why_now = "extrinsic value provides time buffer"
            urgency = 0

    # Rule 6/6b/7: ITM CSP
    elif moneyness == "ITM" and strategy == "CSP":
        if assignment_mode == "wheel" and trend in ("strong_bull", "bull"):
            action = "LET_EXPIRE"
            reason = (
                f"ITM CSP, wheel mode + {trend} trend. "
                "Accept assignment at ${:.2f} cost basis.".format(strike)
            )
            why_now = "wheel entry — bullish stock at good strike"
            urgency = 1
        elif assignment_mode == "avoid":
            action = "ROLL_OUT_AND_DOWN"
            reason = (
                "ITM CSP, avoid-assignment mode. "
                "Roll down and out to reduce assignment risk."
            )
            why_now = "ITM with avoid-assignment preference"
            urgency = 2
            needs_roll = True
        else:
            # neutral mode + bearish/neutral trend
            action = "ROLL_OUT_AND_DOWN"
            reason = (
                f"ITM CSP, {trend} trend. "
                "Roll down and out to defend position."
            )
            why_now = f"ITM with {trend} outlook — assignment undesirable"
            urgency = 2
            needs_roll = True

    # Rule 8: High delta warning
    elif delta > 0.60 and dte <= 14:
        action = "HOLD"
        reason = (
            f"Delta {delta:.2f} (>{HIGH_DELTA_THRESHOLD}) with "
            f"{dte} DTE. Monitor closely for assignment risk."
        )
        why_now = "elevated delta approaching expiration"
        urgency = 1

    # Rule 9: Default
    else:
        action = "HOLD"
        reason = (
            f"{moneyness} {strategy}, {dte} DTE, "
            f"delta {delta:.2f}. No action needed."
        )
        why_now = ""
        urgency = 0

    return {
        "action": action,
        "reason": reason,
        "why_now": why_now,
        "urgency": urgency,
        "needs_roll_targets": needs_roll,
        "profit_captured_pct": profit_captured_pct,
        "extrinsic_value": extrinsic_value,
        "assignment_risk": assignment_risk,
        "hold_for_upside": hold_for_upside,
        "consider_exit": consider_exit,
        "exit_reason": exit_reason,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Function 3: Roll Target Finder
# ═══════════════════════════════════════════════════════════════════════════════


def find_roll_targets(
    option: dict,
    action: str,
    classification: dict,
    chains: dict[str, list[dict]],
    current_price: float,
    trend: str = "neutral",
    max_debit: float = MAX_ROLL_DEBIT,
    earnings_dates: dict | None = None,
    assignment_mode: str = "neutral",
) -> dict:
    """Find optimal roll targets from available chain data.

    Args:
        option: Current position dict.
        action: The decided action (ROLL_OUT, ROLL_OUT_AND_UP, etc.).
        classification: Position classification from classify_position().
        chains: Dict mapping expiry -> list of raw Tradier option entries.
        current_price: Current stock price.
        trend: Per-stock trend class for delta targeting.
        max_debit: Maximum acceptable net debit per contract.
        earnings_dates: Optional {symbol: {date: str, days_away: int}}.
        assignment_mode: For earnings hard-block exception.

    Returns:
        dict with roll_targets list, execution_note, fallback_options.
    """
    option_type = classification["option_type"]
    old_strike = classification["strike"]
    old_delta = classification["delta"]
    contracts = classification["contracts"]
    symbol = classification["symbol"]

    # Determine target delta range
    trend_key = trend if trend in DELTA_RANGES else "neutral"
    ot_key = "call" if option_type == "call" else "put"
    d_min, d_max = DELTA_RANGES[trend_key][ot_key]
    d_center = (d_min + d_max) / 2

    # Estimate close cost from option data
    close_cost_ask = None
    current_value = abs(option.get("current_value", 0))
    if current_value > 0 and contracts > 0:
        close_cost_ask = round(current_value / contracts / 100, 2)

    targets = []

    for expiry, chain_options in sorted(chains.items()):
        # Calculate new DTE
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            new_dte = (exp_date - datetime.now().date()).days
        except (ValueError, TypeError):
            continue
        if new_dte <= 0:
            continue

        # Earnings hard-block check
        earnings_warning = None
        earnings_disqualified = False
        if earnings_dates and symbol in earnings_dates:
            earn_info = earnings_dates[symbol]
            earn_date_str = earn_info.get("date", "")
            earn_days = earn_info.get("days_away")
            if earn_days is not None and earn_date_str:
                # Days from new expiry to earnings
                try:
                    earn_date = datetime.strptime(
                        earn_date_str, "%Y-%m-%d"
                    ).date()
                    days_before_earnings = (earn_date - exp_date).days
                    # If expiry is within BLOCK window of earnings
                    if abs(days_before_earnings) <= EARNINGS_BLOCK_DAYS:
                        earnings_risk = classify_earnings_risk(
                            abs(days_before_earnings)
                        )
                        if (
                            earnings_risk == "BLOCK"
                            and assignment_mode != "wheel"
                        ):
                            earnings_disqualified = True
                            earnings_warning = (
                                f"⚠️ BLOCKED — expiry within "
                                f"{EARNINGS_BLOCK_DAYS}d of earnings "
                                f"({earn_date_str})"
                            )
                        elif earnings_risk in ("BLOCK", "SHORT_DTE_ONLY"):
                            earnings_warning = (
                                f"⚠️ Expiry near earnings ({earn_date_str})"
                            )
                except (ValueError, TypeError):
                    pass

        # Compute chain average IV for iv_relative
        iv_values = []
        for o in chain_options:
            if o.get("option_type") != option_type:
                continue
            g = o.get("greeks") or {}
            iv = g.get("mid_iv")
            if iv and iv > 0:
                iv_values.append(iv * 100)
        chain_avg_iv = mean(iv_values) if iv_values else None

        # Filter candidates based on action type
        for o in chain_options:
            if o.get("option_type") != option_type:
                continue
            g = o.get("greeks") or {}
            new_delta = abs(g.get("delta", 0) or 0)
            new_strike = o.get("strike", 0)
            bid = o.get("bid", 0) or 0
            ask = o.get("ask", 0) or 0
            mid = round((bid + ask) / 2, 2) if (bid or ask) else 0
            theta = g.get("theta", 0) or 0
            oi = o.get("open_interest", 0) or 0
            vol = o.get("volume", 0) or 0
            iv_raw = g.get("mid_iv")
            target_iv = round(iv_raw * 100, 1) if iv_raw else None

            if bid <= 0:
                continue

            # Strike direction filter
            if action == "ROLL_OUT" and new_strike != old_strike:
                continue
            elif action == "ROLL_OUT_AND_UP" and new_strike <= old_strike:
                continue
            elif action == "ROLL_OUT_AND_DOWN" and new_strike >= old_strike:
                continue

            # Delta range filter (for non-ROLL_OUT actions)
            if action != "ROLL_OUT":
                if not (d_min <= new_delta <= d_max):
                    continue

            # Net credit calculation
            if close_cost_ask is not None:
                net_credit = round(bid - close_cost_ask, 2)
            else:
                net_credit = round(bid, 2)  # unknown close cost
            net_credit_total = round(net_credit * 100 * contracts, 2)

            # Annualized yield
            ann_yield = round(
                (bid / new_strike) * (365 / max(new_dte, 1)) * 100, 1
            ) if new_strike > 0 else 0.0

            # IV relative
            iv_relative = None
            if target_iv and chain_avg_iv and chain_avg_iv > 0:
                iv_relative = round(target_iv / chain_avg_iv, 2)

            # Spread
            spread_pct = (
                round((ask - bid) / mid * 100, 1) if mid > 0 else 999.0
            )

            # ── Roll quality score (0-10) ─────────────────────────────
            score = 0.0

            # Net credit (0-4)
            if net_credit >= 1.0:
                score += 4.0
            elif net_credit >= 0:
                score += 2.0 + (net_credit / 1.0) * 2.0
            elif net_credit >= -0.50:
                score += max(0, 2.0 + (net_credit / 0.50) * 2.0)

            # Delta improvement (0-2)
            if old_delta > 0 and new_delta > 0:
                old_dist = abs(old_delta - d_center)
                new_dist = abs(new_delta - d_center)
                if old_dist > 0:
                    improvement = (old_dist - new_dist) / old_dist
                    score += max(0, min(2.0, improvement * 2.0))

            # Theta pickup (0-1.5)
            if theta < 0:
                # More negative theta = better (more daily income)
                theta_score = min(1.5, abs(theta) / 0.10 * 1.5)
                score += theta_score

            # Liquidity (0-1.5)
            if spread_pct < 5:
                score += 0.5
            if oi > 500:
                score += 0.5
            if vol > 0:
                score += 0.5

            # DTE sweet spot (0-1)
            if 21 <= new_dte <= 45:
                score += 1.0
            elif 14 <= new_dte <= 60:
                score += 0.5

            score = round(score, 1)

            # Disqualification check
            disqualified = False
            disqualified_reason = None
            if earnings_disqualified:
                disqualified = True
                disqualified_reason = (
                    f"Expiry within {EARNINGS_BLOCK_DAYS}d of earnings"
                )
            elif net_credit < -max_debit:
                disqualified = True
                disqualified_reason = (
                    f"Net debit ${abs(net_credit):.2f} > "
                    f"max ${max_debit:.2f}"
                )

            # Build rationale
            parts = []
            if net_credit > 0:
                parts.append(f"net credit ${net_credit:.2f}")
            elif net_credit < 0:
                parts.append(f"net debit ${abs(net_credit):.2f}")
            if old_delta > 0:
                parts.append(
                    f"delta {old_delta:.2f} → {new_delta:.2f}"
                )
            parts.append(f"{new_dte} DTE")
            if earnings_warning:
                parts.append(earnings_warning)

            targets.append({
                "new_strike": new_strike,
                "new_expiry": expiry,
                "new_dte": new_dte,
                "new_delta": round(new_delta, 3),
                "new_theta": round(theta, 4),
                "new_premium_bid": bid,
                "close_cost_ask": close_cost_ask,
                "net_credit": net_credit,
                "net_credit_total": net_credit_total,
                "new_ann_yield_pct": ann_yield,
                "iv_relative": iv_relative,
                "earnings_warning": earnings_warning,
                "roll_quality_score": score,
                "roll_rationale": " | ".join(parts),
                "disqualified": disqualified,
                "disqualified_reason": disqualified_reason,
            })

    # Sort: qualified first by score desc, then disqualified by score desc
    qualified = [t for t in targets if not t["disqualified"]]
    disqualified_list = [t for t in targets if t["disqualified"]]
    qualified.sort(key=lambda x: -x["roll_quality_score"])
    disqualified_list.sort(key=lambda x: -x["roll_quality_score"])
    sorted_targets = qualified + disqualified_list

    # ── Close-and-Reopen detection ────────────────────────────────────────
    execution_note = None
    execution_reason = None
    if qualified and close_cost_ask and close_cost_ask > 0:
        best = qualified[0]
        if best["new_premium_bid"] > 0:
            total_spread = close_cost_ask + best["new_premium_bid"]
            if total_spread > 0:
                roll_spread = (
                    (close_cost_ask - best["net_credit"]) / total_spread * 100
                    if total_spread > 0
                    else 0
                )
            else:
                roll_spread = 0
            if (
                roll_spread > CLOSE_REOPEN_SPREAD_PCT
                or best["net_credit"] < MIN_NET_CREDIT
            ):
                execution_note = "CLOSE_AND_REOPEN"
                execution_reason = (
                    "Roll spread is wide. Consider: close current position "
                    "first (limit order at mid), then sell new contract "
                    "separately for better fills."
                )

    # ── Deep ITM fallback ─────────────────────────────────────────────────
    fallback_options = None
    if not qualified and classification["moneyness"] == "ITM":
        fallback_options = []
        # Option A: Accept assignment
        if classification["strategy"] == "CC":
            fallback_options.append({
                "action": "ACCEPT_ASSIGNMENT",
                "description": (
                    f"Let shares be called away at "
                    f"${classification['strike']:.2f}"
                ),
            })
        else:
            fallback_options.append({
                "action": "ACCEPT_ASSIGNMENT",
                "description": (
                    f"Accept shares at "
                    f"${classification['strike']:.2f} (wheel entry)"
                ),
            })
        # Option B: Best debit roll
        if disqualified_list:
            best_debit = min(
                disqualified_list, key=lambda x: abs(x["net_credit"])
            )
            fallback_options.append({
                "action": "ROLL_FOR_DEBIT",
                "description": (
                    f"Roll to ${best_debit['new_strike']:.2f} "
                    f"{best_debit['new_expiry']} for "
                    f"${abs(best_debit['net_credit']):.2f} debit"
                ),
                "total_debit": round(
                    abs(best_debit["net_credit"]) * 100 * contracts, 2
                ),
            })

    return {
        "roll_targets": sorted_targets,
        "execution_note": execution_note,
        "execution_reason": execution_reason,
        "fallback_options": fallback_options,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Function 4: Chain Loading
# ═══════════════════════════════════════════════════════════════════════════════


def load_chains(chains_dir: str) -> dict[str, dict[str, list[dict]]]:
    """Load all Tradier chain JSON files from a directory.

    Expects files named SYMBOL_EXPIRY.json (e.g., NVDA_2026-04-17.json).

    Returns:
        Nested dict: {symbol: {expiry: [option_entries...]}}
    """
    result: dict[str, dict[str, list[dict]]] = {}
    if not os.path.isdir(chains_dir):
        return result

    for filename in sorted(os.listdir(chains_dir)):
        if not filename.endswith(".json"):
            continue
        parts = filename[:-5].rsplit("_", 1)
        if len(parts) != 2:
            continue
        symbol, expiry = parts[0].upper(), parts[1]

        filepath = os.path.join(chains_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            # Handle MCP wrapper format
            if isinstance(data, list) and data and "text" in data[0]:
                data = json.loads(data[0]["text"])
            options = data.get("options", {}).get("option", [])
            if not isinstance(options, list):
                options = [options] if options else []
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

        if symbol not in result:
            result[symbol] = {}
        result[symbol][expiry] = options

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Function 5: Estimate Close Cost
# ═══════════════════════════════════════════════════════════════════════════════


def estimate_close_cost(
    option: dict,
    chains: dict[str, list[dict]],
    contracts: int,
) -> float | None:
    """Estimate buy-to-close cost from chain data or portfolio value.

    Returns per-contract option price (not total).
    """
    symbol = option.get("underlying", "").upper()
    strike = option.get("strike", 0)
    expiry = option.get("expiry", "")
    option_type = option.get("option_type", "")

    # Try to find in loaded chains
    if symbol in chains and expiry in chains[symbol]:
        for o in chains[symbol][expiry]:
            if (
                o.get("strike") == strike
                and o.get("option_type") == option_type
            ):
                ask = o.get("ask", 0) or 0
                bid = o.get("bid", 0) or 0
                if ask > 0:
                    return round(ask, 2)
                elif bid > 0:
                    return round(bid * 1.05, 2)  # estimate ask from bid

    # Fallback to portfolio current_value
    current_value = abs(option.get("current_value", 0))
    if current_value > 0 and contracts > 0:
        return round(current_value / contracts / 100, 2)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Function 6: Main Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


def analyze_rolls(
    portfolio: dict,
    prices: dict[str, float],
    chains_dir: str,
    profit_target: float = PROFIT_TARGET_PCT,
    max_debit: float = MAX_ROLL_DEBIT,
    assignment_mode: str = "neutral",
    trend_overrides: dict[str, str] | None = None,
    earnings_dates: dict | None = None,
) -> dict:
    """Analyze all short option positions for rolling decisions.

    Args:
        portfolio: Parsed portfolio JSON from parse_etrade.py.
        prices: Map of symbol -> current stock price.
        chains_dir: Directory with SYMBOL_EXPIRY.json chain files.
        profit_target: Profit capture threshold %.
        max_debit: Max acceptable roll debit per contract.
        assignment_mode: "avoid" / "neutral" / "wheel".
        trend_overrides: Optional {symbol: trend_class} from preflight.
        earnings_dates: Optional {symbol: {date, days_away}} from preflight.

    Returns:
        Structured result dict with per-position recommendations.
    """
    stock_positions = portfolio.get("stock_positions", [])
    option_positions = portfolio.get("option_positions", [])
    all_chains = load_chains(chains_dir)
    trends = trend_overrides or {}

    results = []
    summary = {"close_early": 0, "roll": 0, "let_expire": 0, "hold": 0}

    for opt in option_positions:
        qty = opt.get("quantity", 0)
        if qty >= 0:
            continue  # Only analyze short positions

        symbol = opt.get("underlying", "").upper()
        current_price = prices.get(symbol, 0)
        if current_price <= 0:
            continue

        # Step 1: Enrich option with greeks from current-expiry chain, then classify
        opt_expiry = opt.get("expiry", "")
        opt_strike = opt.get("strike", 0)
        opt_type = opt.get("option_type", "")
        if symbol in all_chains and opt_expiry in all_chains[symbol]:
            for chain_opt in all_chains[symbol][opt_expiry]:
                if (
                    chain_opt.get("strike") == opt_strike
                    and chain_opt.get("option_type") == opt_type
                ):
                    opt = {**opt, "greeks": chain_opt.get("greeks", {})}
                    break
        classification = classify_position(opt, current_price, stock_positions)

        # Step 2: Estimate close cost
        close_cost = estimate_close_cost(
            opt, all_chains, classification["contracts"]
        )

        # Step 3: Decide action
        trend = trends.get(symbol, "neutral")
        decision = decide_action(
            classification=classification,
            option=opt,
            current_price=current_price,
            close_cost=close_cost,
            trend=trend,
            assignment_mode=assignment_mode,
            profit_target=profit_target,
        )

        # Step 4: Find roll targets if needed
        roll_result = {"roll_targets": [], "execution_note": None,
                       "execution_reason": None, "fallback_options": None}
        if decision["needs_roll_targets"] and symbol in all_chains:
            roll_result = find_roll_targets(
                option=opt,
                action=decision["action"],
                classification=classification,
                chains=all_chains.get(symbol, {}),
                current_price=current_price,
                trend=trend,
                max_debit=max_debit,
                earnings_dates=earnings_dates,
                assignment_mode=assignment_mode,
            )

        # Update summary
        act = decision["action"]
        if act == "CLOSE_EARLY":
            summary["close_early"] += 1
        elif act.startswith("ROLL_"):
            summary["roll"] += 1
        elif act == "LET_EXPIRE":
            summary["let_expire"] += 1
        else:
            summary["hold"] += 1

        # Assemble result
        entry = {
            **{k: classification[k] for k in [
                "symbol", "option_type", "strike", "expiry", "dte",
                "contracts", "strategy", "moneyness", "moneyness_pct",
                "itm_amount", "risk_level", "delta",
            ]},
            **{k: decision[k] for k in [
                "action", "reason", "why_now", "urgency",
                "profit_captured_pct", "extrinsic_value",
                "assignment_risk", "hold_for_upside",
                "consider_exit", "exit_reason",
            ]},
            **roll_result,
        }
        results.append(entry)

    # Sort by urgency descending
    results.sort(key=lambda x: -x["urgency"])

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "assignment_mode": assignment_mode,
        "total_positions": len(results),
        "summary": summary,
        "positions": results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Analyze short option positions for rolling decisions"
    )
    parser.add_argument(
        "--portfolio", required=True,
        help="Path to parse_etrade.py JSON output",
    )
    parser.add_argument(
        "--prices", required=True,
        help="Path to {symbol: price} JSON file",
    )
    parser.add_argument(
        "--chains-dir", required=True,
        help="Directory with SYMBOL_EXPIRY.json chain files",
    )
    parser.add_argument(
        "--profit-target", type=float, default=PROFIT_TARGET_PCT,
        help=f"Profit capture %% threshold (default: {PROFIT_TARGET_PCT})",
    )
    parser.add_argument(
        "--max-debit", type=float, default=MAX_ROLL_DEBIT,
        help=f"Max roll debit per contract (default: {MAX_ROLL_DEBIT})",
    )
    parser.add_argument(
        "--assignment-mode", default="neutral",
        choices=["avoid", "neutral", "wheel"],
        help="Assignment preference (default: neutral)",
    )
    parser.add_argument(
        "--trend-overrides",
        help="Path to {symbol: trend_class} JSON file",
    )
    parser.add_argument(
        "--earnings",
        help="Path to {symbol: {date, days_away}} JSON file",
    )
    args = parser.parse_args()

    # Validation
    if args.profit_target <= 0 or args.profit_target > 100:
        parser.error("--profit-target must be between 0 and 100")
    if args.max_debit < 0:
        parser.error("--max-debit must be non-negative")
    if not os.path.exists(args.portfolio):
        parser.error(f"File not found: {args.portfolio}")
    if not os.path.exists(args.prices):
        parser.error(f"File not found: {args.prices}")
    if not os.path.isdir(args.chains_dir):
        parser.error(f"Directory not found: {args.chains_dir}")

    # Load data
    with open(args.portfolio) as f:
        portfolio = json.load(f)
    with open(args.prices) as f:
        prices = json.load(f)

    trend_overrides = None
    if args.trend_overrides:
        if not os.path.exists(args.trend_overrides):
            parser.error(f"File not found: {args.trend_overrides}")
        with open(args.trend_overrides) as f:
            trend_overrides = json.load(f)

    earnings_dates = None
    if args.earnings:
        if not os.path.exists(args.earnings):
            parser.error(f"File not found: {args.earnings}")
        with open(args.earnings) as f:
            earnings_dates = json.load(f)

    result = analyze_rolls(
        portfolio=portfolio,
        prices=prices,
        chains_dir=args.chains_dir,
        profit_target=args.profit_target,
        max_debit=args.max_debit,
        assignment_mode=args.assignment_mode,
        trend_overrides=trend_overrides,
        earnings_dates=earnings_dates,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
