#!/usr/bin/env python3
# ABOUTME: Parses the latest E*Trade portfolio CSV from the Etrade Files folder.
# ABOUTME: Returns structured JSON with stock positions, option positions, and cash.

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Folder where E*Trade CSVs are saved ──────────────────────────────────────
ETRADE_FOLDER = Path(__file__).parents[4] / "Etrade Files"


def find_latest_csv(folder: Path) -> Path:
    """Return the most recently modified CSV in the folder."""
    csvs = list(folder.glob("*.csv")) + list(folder.glob("*.CSV"))
    if not csvs:
        raise FileNotFoundError(
            f"No CSV files found in {folder}\n"
            "Please download your E*Trade portfolio CSV and save it to:\n"
            f"  {folder}"
        )
    return max(csvs, key=lambda p: p.stat().st_mtime)


def clean_number(value: str) -> float:
    """Strip $, commas, % and convert to float. Returns 0.0 on failure."""
    if value is None or str(value).strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = re.sub(r"[$,%]", "", str(value).strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_option_description(desc: str) -> dict | None:
    """
    Parse E*Trade option description into components.
    Handles formats like:
      "NVDA Apr 17 2026 $185.00 Call"
      "MSTR Mar 20 2026 $152.50 Put"
      "SOFI 03/27/2026 17.50 Call"
    Returns dict with underlying, option_type, strike, expiry or None if not an option.
    """
    desc = str(desc).strip()

    # Pattern 1: "SYMBOL Mon DD YYYY $STRIKE.XX Call/Put"
    m = re.match(
        r"^([A-Z]{1,5})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\s+\$?([\d.]+)\s+(Call|Put)$",
        desc,
        re.IGNORECASE,
    )
    if m:
        symbol, mon, day, year, strike, opt_type = m.groups()
        try:
            expiry = datetime.strptime(f"{mon} {day} {year}", "%b %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            expiry = f"{year}-{mon}-{day}"
        return {
            "underlying": symbol.upper(),
            "option_type": opt_type.lower(),
            "strike": float(strike),
            "expiry": expiry,
        }

    # Pattern 1b: "SYMBOL Mon DD '26 $STRIKE.XX Call/Put" (E*Trade short year format)
    m = re.match(
        r"^([A-Z]{1,5})\s+([A-Za-z]{3})\s+(\d{1,2})\s+'(\d{2})\s+\$?([\d.]+)\s+(Call|Put)$",
        desc,
        re.IGNORECASE,
    )
    if m:
        symbol, mon, day, short_year, strike, opt_type = m.groups()
        year = f"20{short_year}"
        try:
            expiry = datetime.strptime(f"{mon} {day} {year}", "%b %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            expiry = f"{year}-{mon}-{day}"
        return {
            "underlying": symbol.upper(),
            "option_type": opt_type.lower(),
            "strike": float(strike),
            "expiry": expiry,
        }

    # Pattern 2: "SYMBOL MM/DD/YYYY STRIKE Call/Put"
    m = re.match(
        r"^([A-Z]{1,5})\s+(\d{2}/\d{2}/\d{4})\s+\$?([\d.]+)\s+(Call|Put)$",
        desc,
        re.IGNORECASE,
    )
    if m:
        symbol, date_str, strike, opt_type = m.groups()
        try:
            expiry = datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            expiry = date_str
        return {
            "underlying": symbol.upper(),
            "option_type": opt_type.lower(),
            "strike": float(strike),
            "expiry": expiry,
        }

    # Pattern 3: OCC-style "NVDA260417C00185000"
    m = re.match(r"^([A-Z]{1,5})(\d{6})([CP])(\d{8})$", desc)
    if m:
        symbol, date_str, cp, strike_str = m.groups()
        try:
            expiry = datetime.strptime(date_str, "%y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            expiry = date_str
        return {
            "underlying": symbol.upper(),
            "option_type": "call" if cp == "C" else "put",
            "strike": int(strike_str) / 1000,
            "expiry": expiry,
        }

    return None


def parse_csv(filepath: Path) -> dict:
    """Parse E*Trade portfolio CSV and return structured data."""
    import csv

    stock_positions = []
    option_positions = []
    cash_available = 0.0
    total_value = 0.0

    with open(filepath, encoding="utf-8-sig", newline="") as f:
        content = f.read()

    # E*Trade CSVs often have a header section before the table
    # Find the line with column headers: must contain Symbol AND price/quantity columns
    lines = content.splitlines()
    header_row_idx = None
    for i, line in enumerate(lines):
        # Look for the real data header — must have Symbol plus price/quantity data columns
        if re.search(r"\bSymbol\b", line, re.IGNORECASE) and re.search(
            r"(Last Price|Quantity|Price Paid|Market Value)", line, re.IGNORECASE
        ):
            header_row_idx = i
            break

    if header_row_idx is None:
        raise ValueError(
            "Could not find header row in CSV. "
            "Expected a row containing 'Symbol' or 'Description'."
        )

    # Re-parse from header row
    data_lines = "\n".join(lines[header_row_idx:])
    reader = csv.DictReader(data_lines.splitlines())

    # Normalize column names (strip spaces, newlines, lowercase)
    def norm(col: str) -> str:
        if col is None:
            return ""
        c = col.strip().lower()
        c = c.replace(" ", "_").replace("/", "_")
        return c.replace("\n", "").replace("$", "").rstrip("_")

    for raw_row in reader:
        row = {
            norm(k): v.strip() if v is not None else ""
            for k, v in raw_row.items() if k is not None
        }

        # Get the symbol/description field
        symbol_raw = (
            row.get("symbol") or row.get("description") or ""
        ).strip()

        # Detect cash/money market rows anywhere (E*Trade labels them differently)
        symbol_lower = symbol_raw.lower()
        if any(kw in symbol_lower for kw in ("cash", "money market", "sweep", "free credit")):
            val = clean_number(
                row.get("value") or row.get("current_value")
                or row.get("market_value") or "0"
            )
            cash_available += val
            continue

        if not symbol_raw or symbol_raw.upper().startswith(("ACCOUNT", "TOTAL", "SUBTOTAL")):
            continue

        # Get quantity
        qty_raw = (
            row.get("quantity") or row.get("qty") or row.get("shares") or "0"
        )
        quantity = clean_number(qty_raw)
        if quantity == 0:
            continue

        # Get current value (E*Trade: "Value $\n" → normalized "value")
        value_raw = (
            row.get("value") or row.get("current_value") or row.get("market_value") or "0"
        )
        current_value = clean_number(value_raw)
        total_value += current_value

        # Get cost basis
        # E*Trade CSV: "Price Paid $\n" → normalized "price_paid"
        cost_basis_total_raw = (
            row.get("cost_basis_total") or row.get("total_cost_basis") or
            row.get("cost_basis") or row.get("total_cost") or "0"
        )
        cost_basis_per_share_raw = (
            row.get("cost_basis_per_share") or row.get("price_paid") or
            row.get("avg_cost") or row.get("average_cost") or "0"
        )
        cost_basis_total = clean_number(cost_basis_total_raw)
        cost_basis_per_share = clean_number(cost_basis_per_share_raw)

        # Derive missing cost basis
        if cost_basis_per_share == 0 and cost_basis_total > 0 and quantity != 0:
            cost_basis_per_share = cost_basis_total / abs(quantity)
        if cost_basis_total == 0 and cost_basis_per_share > 0:
            cost_basis_total = cost_basis_per_share * abs(quantity)

        # Get current price (E*Trade: "Last Price $\n" → normalized "last_price")
        price_raw = (
            row.get("last_price") or row.get("price") or row.get("current_price") or "0"
        )
        current_price = clean_number(price_raw)
        if current_price == 0 and current_value > 0 and quantity != 0:
            current_price = current_value / abs(quantity)

        # P&L (E*Trade: "Total Gain $\n" → "total_gain", "Total Gain Loss $" → "total_gain_loss")
        total_pl_raw = (
            row.get("total_gain") or row.get("total_gain_loss") or
            row.get("total_gain_loss_") or row.get("unrealized_gain_loss") or "0"
        )
        total_pl = clean_number(total_pl_raw)
        total_pl_pct = (total_pl / cost_basis_total * 100) if cost_basis_total else 0.0

        # Try to parse as option
        opt_info = parse_option_description(symbol_raw)

        if opt_info:
            # It's an option position
            option_positions.append({
                "description": symbol_raw,
                "underlying": opt_info["underlying"],
                "option_type": opt_info["option_type"],
                "strike": opt_info["strike"],
                "expiry": opt_info["expiry"],
                "quantity": int(quantity),
                "current_value": current_value,
                "cost_basis": cost_basis_total,
            })
        elif re.match(r"^[A-Z]{1,5}$", symbol_raw):
            # It's a stock position (pure ticker)
            stock_positions.append({
                "symbol": symbol_raw,
                "quantity": int(abs(quantity)),
                "cost_basis_per_share": round(cost_basis_per_share, 4),
                "cost_basis_total": round(cost_basis_total, 2),
                "current_price": round(current_price, 4),
                "current_value": round(current_value, 2),
                "total_pl": round(total_pl, 2),
                "total_pl_pct": round(total_pl_pct, 2),
            })
        # else: skip rows that don't match (account totals, blank rows, etc.)

    # Determine which stocks already have covered calls open against them
    covered_symbols = set()
    for opt in option_positions:
        if opt["option_type"] == "call" and opt["quantity"] < 0:
            covered_symbols.add(opt["underlying"])

    stock_symbols = [s["symbol"] for s in stock_positions]
    uncovered = [s for s in stock_symbols if s not in covered_symbols]

    return {
        "file_used": filepath.name,
        "as_of_date": datetime.fromtimestamp(filepath.stat().st_mtime).strftime("%Y-%m-%d"),
        "total_equity": round(total_value, 2),
        "cash_available": round(cash_available, 2),
        "stock_positions": stock_positions,
        "option_positions": option_positions,
        "covered_stocks": sorted(covered_symbols),
        "uncovered_stocks": sorted(uncovered),
        "summary": {
            "total_stocks": len(stock_positions),
            "total_options": len(option_positions),
            "stocks_with_cc": len(covered_symbols),
            "stocks_needing_cc": len(uncovered),
        },
    }


def main():
    folder = ETRADE_FOLDER
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        print(json.dumps({
            "error": f"Folder created but empty: {folder}",
            "action": "Please download your E*Trade portfolio CSV and save it to that folder."
        }, indent=2))
        sys.exit(1)

    try:
        latest_csv = find_latest_csv(folder)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)

    print(f"Reading: {latest_csv}", file=sys.stderr)

    try:
        result = parse_csv(latest_csv)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"Failed to parse CSV: {e}",
                          "file": str(latest_csv)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
