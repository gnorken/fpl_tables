from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from flask import flash, request
import json
import logging
import pycountry
from markupsafe import Markup
from modules.fetch_all_tables import build_player_info
import requests
import sqlite3

logger = logging.getLogger(__name__)

DATABASE = "page_views.db"


FPL_API_BASE = "https://fantasy.premierleague.com/api"
FPL_STATIC_URL = f"{FPL_API_BASE}/bootstrap-static/"
FPL_EVENT_STATUS_URL = "https://fantasy.premierleague.com/api/event-status/"

headers = {
    # This header identifies the client making the request. By setting it to a typical browser string, you're making your server-side request appear as though it's coming from a regular browser. Some APIs might behave differently or restrict requests that don't look like they're coming from a browser.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    # This tells the server that the client can handle gzip-compressed responses. If the server supports gzip, it can send compressed data back, which often results in faster transfers and lower bandwidth usage.
    "Accept-Encoding": "gzip"
}


# Helper to validate team ID
def validate_team_id(team_id, max_users):
    try:
        team_id = int(team_id)  # Ensure team_id is an integer
        if 1 <= team_id <= max_users:
            # Test API to check if the game is being updated
            manager_url = f"{FPL_API_BASE}/entry/{team_id}/"
            manager_response = requests.get(manager_url)
            logger.debug(
                f"FPL API status code: {manager_response.status_code}")
            logger.debug(f"max_users: {max_users}")

            if manager_response.status_code == 503:
                flash(
                    "The game is currently being updated. Please try again later.", "warning")
                return None  # Return None to stop further processing

            manager_response.raise_for_status()  # Raise other HTTP errors
            return team_id  # Return valid team_id if no issues

        else:
            flash(f"Team ID must be between 1 and {max_users}", "error")
    except ValueError:
        flash("Invalid Team ID. Please enter a valid number.", "error")
    except requests.exceptions.RequestException as e:
        flash(f"An error occurred while validating the Team ID: {e}", "error")

    return None


# Helper to fetch `MAX_USERS`
def get_max_users():
    try:
        response = requests.get(FPL_STATIC_URL, headers=headers)
        response.raise_for_status()
        static_data = response.json()
        return static_data["total_players"]
    except requests.exceptions.RequestException:
        return 10994911  # Fallback value

# Helper to fetch current gameweek


def get_current_gw():
    logger.debug("[get_current_gw] opening DB %r", DATABASE)
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT data FROM static_data WHERE key='bootstrap'")
    row = cursor.fetchone()
    conn.close()

    if row:
        logger.debug(
            "[get_current_gw] cache hit, loading bootstrap-static from DB")
        data = json.loads(row[0])
    else:
        logger.debug("[get_current_gw] cache miss, fetching %s",
                     FPL_STATIC_URL)
        resp = requests.get(FPL_STATIC_URL)
        resp.raise_for_status()
        data = resp.json()

    # Determine current gameweek
    for event in data.get("events", []):
        if event.get("is_current"):
            gw = event["id"]
            logger.debug("[get_current_gw] found is_current event → gw %r", gw)
            return gw

    # pre-season or between seasons
    logger.debug(
        "[get_current_gw] no 'is_current' event found, returning None (pre-season or post-season)")
    return None

# def get_current_gw():
#     return 8


# Check latest entry in database
_last_event_updated = None


def init_last_event_updated():
    """Initialize _last_event_updated from the DB on startup."""
    global _last_event_updated
    with sqlite3.connect(DATABASE, check_same_thread=False) as conn:
        cursor = conn.cursor()
        # Look for the newest last_fetched across all tables
        cursor.execute("""
            SELECT MAX(last_fetched) FROM (
                SELECT last_fetched FROM static_data
                UNION ALL
                SELECT last_fetched FROM static_player_info
                UNION ALL
                SELECT last_fetched FROM team_player_info
                UNION ALL
                SELECT last_fetched FROM mini_league_cache
                UNION ALL
                SELECT last_fetched FROM managers
            )
        """)
        row = cursor.fetchone()
        if row and row[0]:
            _last_event_updated = datetime.fromisoformat(row[0])
        else:
            _last_event_updated = datetime.now(timezone.utc)

    logger.debug(f"✅ Initialized _last_event_updated={_last_event_updated}")


def get_static_data(force_refresh=False, current_gw=-1):
    logger.debug("🔄 [get_static_data] called")

    # 0) Event status (also prunes)
    event_updated = get_event_status_last_update()
    event_updated_iso = event_updated.isoformat()
    logger.debug(f"🕒 [get_static_data] event_updated: {event_updated}")

    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cur = conn.cursor()

    # 1) Load bootstrap-static (cache vs API)
    cur.execute(
        "SELECT data, last_fetched FROM static_data WHERE key='bootstrap'")
    row = cur.fetchone()

    if row:
        data_str, timestamp = row
        cached_time = datetime.fromisoformat(timestamp)
        if not force_refresh and cached_time >= event_updated:
            logger.debug(
                "✅ [get_static_data] Cache is fresh — using cached bootstrap-static")
            static_data = json.loads(data_str)
        else:
            logger.debug(
                "⚠️ [get_static_data] Cache stale — fetching bootstrap-static")
            resp = requests.get(FPL_STATIC_URL, headers=headers)
            resp.raise_for_status()
            static_data = resp.json()
            timestamp = datetime.now(timezone.utc).isoformat()
            cur.execute(
                "REPLACE INTO static_data (key, data, last_fetched) VALUES (?, ?, ?)",
                ("bootstrap", json.dumps(static_data), timestamp)
            )
    else:
        logger.debug(
            "❌ [get_static_data] No cache row — fetching bootstrap-static")
        resp = requests.get(FPL_STATIC_URL, headers=headers)
        resp.raise_for_status()
        static_data = resp.json()
        timestamp = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "REPLACE INTO static_data (key, data, last_fetched) VALUES (?, ?, ?)",
            ("bootstrap", json.dumps(static_data), timestamp)
        )

    # 2) Decide the single key we’ll use (-1 in preseason)
    gw_key = current_gw if (isinstance(current_gw, int)
                            and current_gw >= 1) else -1

    # 3) Build static_blob
    static_blob = build_player_info(static_data)

    # 4) Only aggregate global points once the season starts
    if current_gw == -1:
        logger.info("Preseason (gw=-1) → skipping team_player_info population")
        team_blob = {}
    else:
        fill_global_points_from_explain(
            static_blob=static_blob,
            current_gw=gw_key,
            event_updated_iso=event_updated_iso,
            db_path=DATABASE
        )

    # 5) Snapshot for routes to read
    cur.execute("""
        INSERT OR REPLACE INTO static_player_info (gameweek, data, last_fetched)
        VALUES (?, ?, ?)
    """, (gw_key, json.dumps(static_blob), timestamp))
    logger.debug("💾 [get_static_data] Updated static_player_info table")

    conn.commit()
    conn.close()
    logger.debug("🔚 [get_static_data] finished")
    return static_data


# Check if I have the latest data


def get_event_status_last_update() -> datetime:
    global _last_event_updated

    data = requests.get(FPL_EVENT_STATUS_URL,
                        headers=headers, timeout=10).json()
    rows = data.get("status", [])

    # Parse dates safely (YYYY-MM-DD) → aware UTC datetimes at 00:00
    def parse_day(dstr: str) -> datetime:
        y, m, d = map(int, dstr.split("-"))
        return datetime(y, m, d, 0, 0, tzinfo=timezone.utc)

    # Nothing? fall back
    if not rows:
        return _last_event_updated or datetime.now(timezone.utc)

    # Find the latest calendar day in this GW
    latest = max(rows, key=lambda r: r.get("date", ""))
    latest_dt = parse_day(latest["date"])

    # Freshness rules:
    # - If any day is live ("l"), treat as "updating now" → return now to force refreshes.
    # - Else if the latest day has results ("r") but no bonus yet, keep it warm (same-day evening).
    # - Else use the start of the latest matchday.
    if any(r.get("points") == "l" for r in rows):
        event_updated = datetime.now(timezone.utc)
    elif latest.get("points") == "r" and not latest.get("bonus_added", False):
        event_updated = latest_dt.replace(hour=23, minute=59, second=59)
    else:
        event_updated = latest_dt

    # Keep a monotonic, aware cache
    if _last_event_updated is None or event_updated > _last_event_updated:
        _last_event_updated = event_updated
    return _last_event_updated


def prune_stale_data(conn, event_updated):
    """
    Delete stale rows from key tables and print comparisons for debugging.
    """
    tables = ["team_player_info", "mini_league_cache", "managers"]

    for table in tables:
        logger.debug(f"🧹 [prune_stale_data] Checking table: {table}")

        # Show all rows with their timestamps before pruning
        rows = conn.execute(f"SELECT rowid, * FROM {table}").fetchall()
        for row in rows:
            # assuming last_fetched is always last column
            last_fetched = row[-1]
            logger.debug(
                f"   ➡️ Row {row[0]}: last_fetched={last_fetched} vs event_updated={event_updated}")

            # Show whether this row will be deleted
            if datetime.fromisoformat(last_fetched) < event_updated:
                logger.debug(
                    "      ❌ Will be deleted (older than event_updated)")
            else:
                logger.debug("      ✅ Will be kept (fresh enough)")

        # Perform actual deletion
        deleted = conn.execute(
            f"DELETE FROM {table} WHERE last_fetched < ?", (event_updated.isoformat(
            ),)
        ).rowcount
        logger.debug(
            f"🗑️ [prune_stale_data] Deleted {deleted} stale rows from {table}")


# Fetch static Player’s Detailed Data


def get_player_detail_data():
    response = requests.get(
        f"https://fantasy.premierleague.com/api/element-summary/", headers=headers)
    response.raise_for_status()
    player_detail_data = response.json()
    return player_detail_data

# formatting for mini league drop down menu


def ordinalformat(n):
    """
    Convert an integer to a string with:
      • apostrophe thousands separators (e.g. 1'234)
      • appropriate English ordinal suffix (st, nd, rd, th)
    """
    n = int(n)
    # thousands separator
    formatted = "{:,}".format(n).replace(",", "'")
    # ordinal suffix
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{formatted}{suffix}"


# Formatting numbers in dropdown menu
def thousands(n):
    if n is None:
        return "-"
    # Convert an integer to a string with apostrophe thousands separators.
    return "{:,}".format(int(n)).replace(",", "'")

# Formatting to millions


def millions(value):
    if value is None:
        return "-"
    return f"{value / 1_000_000:.2f}M"


# Creative mapping of club names or codes to a pair of color emojis + team symbol
TEAM_EMOJIS = {
    "arsenal":                  "🔴⚪️🏹",    # Red & White, cannon
    "aston villa":              "🟣🔵🦁",    # Claret & Blue, lion
    "bournemouth":              "🟥⚫️🍒",   # Red & Black, cherry
    "brentford":                "⚪️🟥🐝",    # White & Red, bee
    "brighton":                 "🔵⚪️🕊️",  # Blue & White, dove
    "chelsea":                  "🔵⚪️👑",    # Blue & White, crown
    "crystal palace":           "🔴🔵🦅",    # Red & Blue, eagle
    "everton":                  "🔵⚪️⚓",    # Blue & White, anchor
    "fulham":                   "⚪️⚫️🐏",   # White & Black, ram
    "ipswich":                  "🔵⚪️🚜",    # Blue & White, tractor
    "leicester":                "🔵⚪️🦊",    # Blue & White, fox
    "liverpool":                "🔴⚪️🐔",    # Red & White, liver bird
    "manc city":                "🔵⚪️☁️",    # Sky Blue & White, cloud
    "man utd":                  "🔴⚫️😈",    # Red & Black, devil
    "newcastle":                "⚫️⬜️🦅",    # Black & White, eagle
    "nott'm forest":            "🔴⚪️🌳",    # Red & White, tree
    "southampton":              "🔴⚪️🛥️",  # Red & White, ship
    "spurs":                    "⚪️🔵🐓",    # White & Navy, cockerel
    "west ham":                 "🟣🟫🛠️",   # Claret & Blue, crossed hammers
    "wolves":                   "🟡⚫️🐺",   # Gold & Black, wolf
    # Next season promotions (2025-2026)
    "burnley":                   "🟣🔵🏰",    # Claret & Blue, castle
    "leeds":                     "⚪️🟡🌸",    # White & Yellow, flower
    "sunderland":                "🔴⚪️🐈"     # Red & White, cat
}

LEAGUE_EMOJIS = {
    "top 10% 24/25 league": "🏆",
    "top 1% 24/25 league": "🏆👏",
    ".com": "🧑‍💻",
    "ai": "🤖",
    "algorithm": "🤖",
    "analytics": "📊",
    "astro sport league": "📺",
    "betting": "🤑",
    "bein sports league": "📺",
    "blackbox": "✈🟧",
    "broadcast": "📺",
    "cash": "🤑",
    # "fpl": "⚽️",
    "fml fpl": "🐑",
    "gameweek 1": "🐣",
    "gameweek 2": "🐥",
    "general": "⭐️⭐️⭐️⭐️",
    "global": "🌍",
    "korea": "🇰🇷",
    "invite": "✉️",
    "invitational": "✉️",
    "money": "🤑",
    "nbc sports league": "📺",
    "overall": "🌍",
    "patreon": "🧡",
    "planet": "🌍",
    "podcast": "🎧",
    "second chance": "🤞",
    "sky sports league": "📺",
    "trophy": "🏆",
    "viaplay league": "🔴▶️",
    "world": "🌍",
    "youtube": "📺"
}

# Flags

SPECIAL_FLAGS = {
    "en": "gb-eng",         # England
    "england": "gb-eng",
    "s1": "gb-sct",         # Scotland
    "scotland": "gb-sct",
    "wa": "gb-wls",         # Wales
    "wales": "gb-wls",
    "nn": "gb-nir",         # Northern Ireland
    "northern ireland": "gb-nir"
}


def territory_icon(key: str) -> Markup:
    k = key.strip().lower()
    # Custom team emojis
    league_emojis = ''
    for substr, emoji in LEAGUE_EMOJIS.items():
        if substr in k:
            league_emojis += emoji
    if league_emojis:
        return Markup(league_emojis)

    # League emojis
    if k in TEAM_EMOJIS:
        return Markup(TEAM_EMOJIS[k])
    # Home-nation overrides
    if k in SPECIAL_FLAGS:
        code = SPECIAL_FLAGS[k]
    # ISO alpha-2
    elif len(k) == 2 and k.isalpha():
        code = k
    # Full name lookup
    else:
        try:
            country = pycountry.countries.lookup(key)
            code = country.alpha_2.lower()
        except LookupError:
            return Markup("")

    # Emit the Lipis v7.3.2 classes
    return Markup(f"<span class='fi fi-{code}' aria-hidden='true'></span>")

# Get OR leader (to have the trailing behind leader col)


def get_overall_league_leader_total():
    """
    Fetch the classic‐league standings for `league_id` and return
    the `total` points held by the manager in 1st place.

    Returns None if there’s no data or no rank==1 entry.
    """
    url = f"{FPL_API_BASE}/leagues-classic/314/standings/"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("standings", {}).get("results", [])
    if not results:
        return None

    # Try to find the entry whose 'rank' is 1
    leader = next((r for r in results if r.get("rank") == 1), None)
    if leader is None:
        # Fallback to the first element in case the API guarantees sorted order
        leader = results[0]

    return leader.get("total")

# emojis for manager history performance


def performance_emoji(percentile):
    if percentile is None:
        return "–"
    if percentile > 70:
        return "💩"
    elif percentile > 60:
        return "😭"
    elif percentile > 50:
        return "😢"
    elif percentile > 40:
        return "☹️"
    elif percentile > 30:
        return "🙁"
    elif percentile > 20:
        return "😐"
    elif percentile > 15:
        return "😌"
    elif percentile > 10:
        return "🙂"
    elif percentile > 5:
        return "😁"
    elif percentile > 1:
        return "😎"
    elif percentile == 1:
        return "🥰"
    elif percentile > 0.5:
        return "😍"
    elif percentile > 0.1:
        return "🤩"
    else:
        return "🤯"


EXPLAIN_TO_FIELD = {
    "minutes": "minutes_points",
    "goals_scored": "goals_points",
    "assists": "assists_points",
    "clean_sheets": "clean_sheets_points",
    "saves": "save_points",
    "own_goals": "own_goals_points",
    "goals_conceded": "goals_conceded_points",
    "penalties_saved": "penalties_saved_points",
    "penalties_missed": "penalties_missed_points",
    "yellow_cards": "yellow_cards_points",
    "red_cards": "red_cards_points",
}


def apply_points_payload(static_blob: dict, payload: dict) -> None:
    # zero first (defensive)
    for pi in static_blob.values():
        for fld in EXPLAIN_TO_FIELD.values():
            pi[fld] = 0
    for pid_str, pts in payload.items():
        pid = int(pid_str)
        if pid in static_blob:
            for fld, val in pts.items():
                static_blob[pid][fld] = int(val)

# New function to add points per category for points table for player_info_static


def fill_global_points_from_explain(static_blob: dict, current_gw: int, event_updated_iso: str, db_path: str) -> None:
    if not current_gw or current_gw < 1:
        logger.debug("[global_points] no current_gw yet → skip")
        # leaves *_points = 0; fine in preseason
        return

    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_points_cache (
            event_updated TEXT PRIMARY KEY,
            data         TEXT NOT NULL,
            last_fetched TEXT NOT NULL
        )
    """)
    cur.execute(
        "SELECT data FROM global_points_cache WHERE event_updated = ?", (event_updated_iso,))
    row = cur.fetchone()
    if row:
        logger.debug("[global_points] cache hit")
        apply_points_payload(static_blob, json.loads(row[0]))
        conn.close()
        return

    logger.debug("[global_points] cache miss → fetching explain for all GWs")
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})

    urls = {
        gw: f"https://fantasy.premierleague.com/api/event/{gw}/live/" for gw in range(1, current_gw + 1)}
    payload = {}  # pid -> { field -> points }

    def ensure(pid: int):
        if pid not in payload:
            payload[pid] = {v: 0 for v in EXPLAIN_TO_FIELD.values()}
        return payload[pid]

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(session.get, url): gw for gw, url in urls.items()}
        for fut in as_completed(futs):
            gw = futs[fut]
            try:
                resp = fut.result()
                data = resp.json()
            except Exception as e:
                logger.warning(f"[global_points] GW {gw} fetch failed: {e}")
                continue

            for el in data.get("elements", []):
                pid = el.get("id")
                if pid is None:
                    continue
                tgt = ensure(pid)
                for blk in el.get("explain", []):
                    for s in blk.get("stats", []):
                        dst = EXPLAIN_TO_FIELD.get(s.get("identifier"))
                        if dst:
                            tgt[dst] += int(s.get("points", 0))

    cur.execute(
        "INSERT OR REPLACE INTO global_points_cache (event_updated, data, last_fetched) VALUES (?, ?, ?)",
        (event_updated_iso, json.dumps(payload),
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

    apply_points_payload(static_blob, payload)
