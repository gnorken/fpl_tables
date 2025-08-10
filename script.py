#!/usr/bin/env python3
import csv
import sys
import argparse
from typing import List, Dict
import requests

API_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

POSITION_MAP = {
    1: "GK",
    2: "DEF",
    3: "MID",
    4: "FWD",
}


def fetch_elements() -> List[Dict]:
    resp = requests.get(API_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    elements = data.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError("Unexpected API shape: 'elements' not a list")
    return elements


def parse_players(elements: List[Dict]) -> List[Dict]:
    rows = []
    for e in elements:
        web_name = e.get("web_name", "")
        now_cost = e.get("now_cost", None)
        element_type = e.get("element_type", None)

        if now_cost is None or element_type not in POSITION_MAP:
            # Skip malformed entries
            continue

        price_m = now_cost / 10.0  # e.g. 55 -> 5.5
        position = POSITION_MAP[element_type]

        rows.append({
            "web_name": web_name,
            "price_m": f"{price_m:.1f}",
            "element_type": element_type,
            "position": position,
        })
    return rows


def write_csv(rows: List[Dict], out_path: str) -> None:
    fieldnames = ["web_name", "price_m", "position", "element_type"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch FPL player names, prices and positions from bootstrap-static."
    )
    parser.add_argument(
        "-o", "--output",
        default="fpl_players_prices.csv",
        help="CSV output filepath (default: fpl_players_prices.csv)"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Show a preview of the first N rows in the terminal (default: 20)"
    )
    args = parser.parse_args()

    try:
        elements = fetch_elements()
        rows = parse_players(elements)
        # Sort by position then price then name for readability
        rows.sort(key=lambda r: (r["position"], -
                  float(r["price_m"]), r["web_name"].lower()))
        write_csv(rows, args.output)

        # Terminal preview
        preview = rows[:args.top]
        print(f"\nFetched {len(rows)} players. Saved CSV -> {args.output}\n")
        print(f"{'Name':<20} {'Price(£m)':<10} {'Pos':<4}")
        print("-" * 40)
        for r in preview:
            print(f"{r['web_name']:<20} {r['price_m']:<10} {r['position']:<4}")
        print("\nTip: open the CSV in a spreadsheet, or paste selections back here.")
    except requests.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
