from datetime import datetime, timedelta
from flask import flash, request
import json
import pycountry
from markupsafe import Markup
import requests
import sqlite3

DB_PATH = "page_views.db"


FPL_API_BASE = "https://fantasy.premierleague.com/api"
FPL_STATIC_URL = f"{FPL_API_BASE}/bootstrap-static/"

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
    static_data = get_static_data()
    events = static_data["events"]
    current_gw = next((event["id"]
                      for event in events if event["is_current"]), None)
    return current_gw

# Fetch static player data


def get_static_data(force_refresh=False, max_age_hours=6):
    static_url = FPL_STATIC_URL

    # Connect to the database
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Try to fetch cached static data
    cursor.execute(
        "SELECT data, timestamp FROM static_data WHERE key = 'bootstrap'")
    row = cursor.fetchone()

    if row:
        data_str, timestamp = row
        cached_time = datetime.fromisoformat(timestamp)
        if not force_refresh and datetime.now() - cached_time < timedelta(hours=max_age_hours):
            conn.close()
            return json.loads(data_str)

    # Fetch new data from FPL
    response = requests.get(static_url, headers=headers)
    response.raise_for_status()
    static_data = response.json()

    # Store the new data in the database
    cursor.execute(
        "REPLACE INTO static_data (key, data, timestamp) VALUES (?, ?, ?)",
        ("bootstrap", json.dumps(static_data), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    return static_data

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
    "top 10% 24/25 league": "Need an emoji here",
    "top 1% 24/25 league": "Need an even more exclusive emoji here",
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

# Get OR leader


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
