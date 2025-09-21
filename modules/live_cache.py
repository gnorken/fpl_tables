# modules/live_cache.py
import json
import requests
from datetime import datetime, timezone, timedelta

USER_AGENT = {"User-Agent": "Mozilla/5.0"}
LIVE_TTL = timedelta(seconds=60)  # or your existing LIVE_TTL


def get_live_elements(cur, gw: int, fpl_api_base: str) -> list[dict]:
    """Return list of elements for GW, cached in SQLite."""
    cur.execute(
        "SELECT data, last_fetched FROM live_elements_cache WHERE gameweek=?", (gw,))
    row = cur.fetchone()
    now = datetime.now(timezone.utc)
    if row:
        data, last_iso = row
        try:
            if now - datetime.fromisoformat(last_iso) < LIVE_TTL:
                return json.loads(data)
        except Exception:
            pass

    url = f"{fpl_api_base}/event/{gw}/live/"
    resp = requests.get(url, headers=USER_AGENT, timeout=10)
    resp.raise_for_status()
    elements = resp.json().get("elements", [])
    cur.execute(
        "INSERT OR REPLACE INTO live_elements_cache (gameweek, data, last_fetched) VALUES (?, ?, ?)",
        (gw, json.dumps(elements), now.isoformat()),
    )
    return elements


def get_live_points_map(cur, gw: int, fpl_api_base: str) -> dict[int, dict]:
    """id -> stats map for the GW, from the same cache."""
    els = get_live_elements(cur, gw, fpl_api_base)
    return {e["id"]: e.get("stats", {}) for e in els}
