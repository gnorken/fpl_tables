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
_EVENT_STATUS_CACHE = {"ts": None, "at": None, "live": False}
LIVE_TTL_SECONDS = 30  # advance freshness at most every 30s while live
STATIC_TTL_SECONDS = 60 * 60  # 1 hour is plenty (even 6–12h is fine)

headers = {
    # This header identifies the client making the request. By setting it to a typical browser string, you're making your server-side request appear as though it's coming from a regular browser. Some APIs might behave differently or restrict requests that don't look like they're coming from a browser.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    # This tells the server that the client can handle gzip-compressed responses. If the server supports gzip, it can send compressed data back, which often results in faster transfers and lower bandwidth usage.
    "Accept-Encoding": "gzip"
}


def open_conn(path):
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    # Make SQLite friendlier under parallel requests
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")  # ms
    return conn


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


def get_static_data(force_refresh: bool = False, current_gw: int = -1):
    logger.debug("🔄 [get_static_data] called")

    # 0) Event status (for live/global points freshness)
    event_updated = get_event_status_last_update()
    event_updated_iso = event_updated.isoformat()
    logger.debug(f"🕒 [get_static_data] event_updated: {event_updated}")
    now_utc = datetime.now(timezone.utc)

    conn = open_conn(DATABASE)
    cur = conn.cursor()

    # 1) Load bootstrap-static (TTL-based, not event-status-based)
    cur.execute(
        "SELECT data, last_fetched FROM static_data WHERE key='bootstrap'")
    row = cur.fetchone()

    need_fetch_static = True
    if row and not force_refresh:
        data_str, last_ts = row
        try:
            cached_time = datetime.fromisoformat(last_ts)
        except ValueError:
            cached_time = datetime.min.replace(tzinfo=timezone.utc)
        age = (now_utc - cached_time).total_seconds()
        if age < STATIC_TTL_SECONDS:
            logger.debug(
                "✅ [get_static_data] bootstrap-static within TTL → using cache")
            static_data = json.loads(data_str)
            need_fetch_static = False

    if need_fetch_static:
        logger.debug(
            "⚠️ [get_static_data] bootstrap-static TTL expired (or no row) → fetching")
        resp = requests.get(FPL_STATIC_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        static_data = resp.json()
        cur.execute(
            "REPLACE INTO static_data (key, data, last_fetched) VALUES (?, ?, ?)",
            ("bootstrap", json.dumps(static_data), now_utc.isoformat())
        )

    # 2) Decide key
    gw_key = current_gw if (isinstance(current_gw, int)
                            and current_gw >= 1) else -1

    # 3) Build static blob
    static_blob = build_player_info(static_data)

    # 4) Populate global points only when season started (driven by event_status freshness)
    if current_gw != -1:
        fill_global_points_from_explain(
            static_blob=static_blob,
            current_gw=gw_key,
            event_updated_iso=event_updated_iso,
            conn=conn,   # reuse same connection
            cur=cur
        )
    else:
        logger.info("Preseason (gw=-1) → skipping team_player_info population")

    # 5) Snapshot for routes to read (use *now* as snapshot time)
    snapshot_time = now_utc.isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO static_player_info (gameweek, data, last_fetched)
        VALUES (?, ?, ?)
    """, (gw_key, json.dumps(static_blob), snapshot_time))
    logger.debug("💾 [get_static_data] Updated static_player_info table")

    conn.commit()
    conn.close()
    logger.debug("🔚 [get_static_data] finished")
    return static_data

# Check if I have the latest data


def _floor_to_bucket(dt: datetime, seconds: int) -> datetime:
    bucket = int(dt.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(bucket, tz=timezone.utc)


def get_event_status_last_update() -> datetime:
    global _last_event_updated, _EVENT_STATUS_CACHE
    now = datetime.now(timezone.utc)

    # 1) Small network memoization to avoid hammering the endpoint
    if _EVENT_STATUS_CACHE["at"] and (now - _EVENT_STATUS_CACHE["at"]) < timedelta(seconds=10):
        return _EVENT_STATUS_CACHE["ts"] or _last_event_updated or now

    # 2) Fetch and parse
    resp = requests.get(
        "https://fantasy.premierleague.com/api/event-status/", headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("status", [])

    def parse_day(s: str) -> datetime:
        y, m, d = map(int, s.split("-"))
        return datetime(y, m, d, 0, 0, tzinfo=timezone.utc)

    latest_row = max(rows, key=lambda r: r.get("date", ""), default=None)
    latest_dt = parse_day(
        latest_row["date"]) if latest_row and latest_row.get("date") else now

    is_live = any(r.get("points") == "l" for r in rows)

    if is_live:
        # Advance only on a 30s bucket to avoid “always stale” spam
        candidate = max(_last_event_updated or latest_dt,
                        _floor_to_bucket(now, LIVE_TTL_SECONDS))
    elif latest_row and latest_row.get("points") == "r" and not latest_row.get("bonus_added", False):
        candidate = latest_dt.replace(
            hour=23, minute=59, second=59, microsecond=0)
    else:
        candidate = latest_dt

    # Monotonic
    if _last_event_updated is None or candidate > _last_event_updated:
        _last_event_updated = candidate

    _EVENT_STATUS_CACHE.update(
        {"ts": _last_event_updated, "at": now, "live": is_live})
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


def fill_global_points_from_explain(
    *,
    static_blob: dict,
    current_gw: int,
    event_updated_iso: str,
    conn=None,
    cur=None,
    db_path: str | None = None,
    max_workers: int = 8,
    request_timeout: int = 10,
) -> None:
    """
    Populate per-player cumulative points by aggregating the 'explain' blocks
    from /api/event/{gw}/live/ for gw = 1..current_gw.

    If `conn`/`cur` are provided, uses them (no commit/close here).
    Otherwise opens its own connection (requires db_path), and commits/closes.

    Caches the aggregated payload in global_points_cache keyed by event_updated_iso.
    """
    if not current_gw or current_gw < 1:
        logger.debug("[global_points] no current_gw yet → skip")
        return

    # Decide DB handling mode
    close_after = False
    if conn is None or cur is None:
        if not db_path:
            raise ValueError("db_path required if conn/cur not provided")
        # Use your shared open_conn helper if you created one; fall back to plain connect otherwise
        try:
            from modules.db import open_conn  # your helper with WAL/busy_timeout
            conn = open_conn(db_path)
        except Exception:
            conn = sqlite3.connect(db_path, timeout=30,
                                   check_same_thread=False)
            # Make life easier even without helper
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=10000;")
        cur = conn.cursor()
        close_after = True

    # Ensure cache table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_points_cache (
            event_updated TEXT PRIMARY KEY,
            data         TEXT NOT NULL,
            last_fetched TEXT NOT NULL
        )
    """)

    # Cache hit?
    cur.execute(
        "SELECT data FROM global_points_cache WHERE event_updated = ?", (event_updated_iso,))
    row = cur.fetchone()
    if row:
        logger.debug("[global_points] cache hit")
        try:
            payload = json.loads(row[0])
            apply_points_payload(static_blob, payload)
        finally:
            if close_after:
                conn.commit()
                conn.close()
        return

    logger.debug(
        "[global_points] cache miss → fetching explain for all GWs (1..%d)", current_gw)

    # Build requests session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Connection": "keep-alive",
    })

    urls = {
        gw: f"https://fantasy.premierleague.com/api/event/{gw}/live/" for gw in range(1, current_gw + 1)}

    # pid -> { field -> points }
    payload: dict[int, dict[str, int]] = {}

    def ensure(pid: int) -> dict[str, int]:
        if pid not in payload:
            payload[pid] = {v: 0 for v in EXPLAIN_TO_FIELD.values()}
        return payload[pid]

    # Fetch concurrently with a sensible cap
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(session.get, url, timeout=request_timeout)                : gw for gw, url in urls.items()}
        for fut in as_completed(futs):
            gw = futs[fut]
            try:
                resp = fut.result()
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning("[global_points] GW %s fetch failed: %s", gw, e)
                continue

            # Aggregate per element
            for el in data.get("elements", []):
                pid = el.get("id")
                if not isinstance(pid, int):
                    continue
                tgt = ensure(pid)
                # 'explain' is a list of blocks, each with 'stats'
                for blk in el.get("explain", []):
                    for s in blk.get("stats", []):
                        ident = s.get("identifier")
                        dst = EXPLAIN_TO_FIELD.get(ident)
                        if not dst:
                            continue
                        try:
                            pts = int(s.get("points", 0))
                        except (TypeError, ValueError):
                            pts = 0
                        tgt[dst] += pts

    # Persist cache
    cur.execute(
        "INSERT OR REPLACE INTO global_points_cache (event_updated, data, last_fetched) VALUES (?, ?, ?)",
        (event_updated_iso, json.dumps(payload),
         datetime.now(timezone.utc).isoformat()),
    )

    # IMPORTANT: only commit/close here if we opened the connection ourselves.
    if close_after:
        conn.commit()
        conn.close()

    # Apply to your in-memory blob for immediate use by the request
    apply_points_payload(static_blob, payload)
