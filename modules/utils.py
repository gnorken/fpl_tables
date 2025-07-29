from datetime import datetime, timedelta, timezone
from flask import flash, request
import json
import pycountry
from markupsafe import Markup
from modules.fetch_all_tables import build_player_info
import requests
import sqlite3

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
            print(f"FPL API status code: {manager_response.status_code}")
            print(f"max_users: {max_users}")

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
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cursor = conn.cursor()

    # If we already have bootstrap-static cached, read it
    cursor.execute("SELECT data FROM static_data WHERE key='bootstrap'")
    row = cursor.fetchone()
    conn.close()

    if row:
        data = json.loads(row[0])
    else:
        # Fetch fresh bootstrap-static directly
        resp = requests.get(FPL_STATIC_URL)
        resp.raise_for_status()
        data = resp.json()

    # Determine current GW
    for event in data.get("events", []):
        if event.get("is_current"):
            return event["id"]

    # Fallback pre-season
    return None


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

    print(f"✅ Initialized _last_event_updated={_last_event_updated}")


def get_static_data(force_refresh=False, current_gw=-1):
    """Fetch bootstrap-static data and sync static_player_info, pruning stale data."""
    print("🔄 [get_static_data] called")

    # Trigger event-status check + pruning
    event_updated = get_event_status_last_update()
    print(f"🕒 [get_static_data] event_updated: {event_updated}")

    static_url = FPL_STATIC_URL
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cursor = conn.cursor()

    # 1️⃣ Check cache
    cursor.execute(
        "SELECT data, last_fetched FROM static_data WHERE key = 'bootstrap'")
    row = cursor.fetchone()

    if row:
        data_str, timestamp = row
        cached_time = datetime.fromisoformat(timestamp)
        print(f"📦 [get_static_data] cached_time: {cached_time}")

        # Use event-status freshness check only
        if not force_refresh and cached_time >= event_updated:
            print("✅ [get_static_data] Cache is fresh, returning cached data")
            conn.close()
            return json.loads(data_str)
        else:
            print("⚠️ [get_static_data] Cache is stale, fetching fresh data")

    else:
        print("❌ [get_static_data] No cache row found, fetching fresh data")

    # 2️⃣ Fetch fresh data from FPL API
    print("🌐 [get_static_data] Fetching bootstrap-static from API...")
    response = requests.get(static_url, headers=headers)
    response.raise_for_status()
    static_data = response.json()

    timestamp = datetime.now(timezone.utc).isoformat()

    # 3️⃣ Update static_data table
    cursor.execute(
        "REPLACE INTO static_data (key, data, last_fetched) VALUES (?, ?, ?)",
        ("bootstrap", json.dumps(static_data), timestamp)
    )
    print("💾 [get_static_data] Updated static_data table")

    # 4️⃣ Rebuild static_player_info (keep only 1 row)
    static_blob = build_player_info(static_data)
    cursor.execute("""
        INSERT OR REPLACE INTO static_player_info (gameweek, data, last_fetched)
        VALUES (?, ?, ?)
    """, (current_gw, json.dumps(static_blob), timestamp))
    print("💾 [get_static_data] Updated static_player_info table")

    conn.commit()
    conn.close()

    print("🔚 [get_static_data] finished")
    return static_data

# Check if I have the latest data


def get_event_status_last_update():
    """Fetch the last event update timestamp and prune stale data if needed."""
    global _last_event_updated
    if _last_event_updated is None:
        init_last_event_updated()  # Initialize from DB

    print("🔄 get_event_status_last_update called")

    response = requests.get(FPL_EVENT_STATUS_URL)
    response.raise_for_status()
    status_data = response.json()

    timestamps = []
    for event in status_data.get("status", []):
        for key in ["points", "bonus_added"]:
            if event.get(key):
                timestamps.append(
                    datetime.fromisoformat(event[key].replace("Z", "+00:00"))
                )

    if timestamps:
        _last_event_updated = max(timestamps)

    # print(f"⏩ Faking new event_updated: {_last_event_updated}")
    # _last_event_updated = datetime.now(timezone.utc) + timedelta(minutes=5)

    print(f"🧹 Pruning with event_updated={_last_event_updated}")

    with sqlite3.connect(DATABASE, check_same_thread=False) as conn:
        prune_stale_data(conn, _last_event_updated)
        print(f"🗑️ Deleting stale rows older than {_last_event_updated}")

    return _last_event_updated


# Delete old rows in db when new data available on server


# def prune_stale_data(conn, event_updated):
#     """Delete all stale rows from user-generated tables."""
#     tables = ["team_player_info", "mini_league_cache", "managers"]
#     for table in tables:
#         conn.execute(
#             f"DELETE FROM {table} WHERE last_fetched < ?", (event_updated.isoformat(),))
#     conn.commit()

# Prune with backend logs
def prune_stale_data(conn, event_updated):
    """
    Delete stale rows from key tables and print comparisons for debugging.
    """
    tables = ["team_player_info", "mini_league_cache", "managers"]

    for table in tables:
        print(f"🧹 [prune_stale_data] Checking table: {table}")

        # Show all rows with their timestamps before pruning
        rows = conn.execute(f"SELECT rowid, * FROM {table}").fetchall()
        for row in rows:
            # assuming last_fetched is always last column
            last_fetched = row[-1]
            print(
                f"   ➡️ Row {row[0]}: last_fetched={last_fetched} vs event_updated={event_updated}")

            # Show whether this row will be deleted
            if datetime.fromisoformat(last_fetched) < event_updated:
                print("      ❌ Will be deleted (older than event_updated)")
            else:
                print("      ✅ Will be kept (fresh enough)")

        # Perform actual deletion
        deleted = conn.execute(
            f"DELETE FROM {table} WHERE last_fetched < ?", (event_updated.isoformat(
            ),)
        ).rowcount
        print(
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
