
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from flask import g, flash, request
import json
import logging
import pycountry
from markupsafe import Markup
from modules.fetch_all_tables import build_player_info
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import sqlite3

logger = logging.getLogger(__name__)

DATABASE = "page_views.db"


FPL_API_BASE = "https://fantasy.premierleague.com/api"
FPL_STATIC_URL = f"{FPL_API_BASE}/bootstrap-static/"
FPL_EVENT_STATUS_URL = "https://fantasy.premierleague.com/api/event-status/"
_ES_CACHE = {
    "gw": 1, "is_live": False, "last_update": None,
    "sig": None, "at": None
}
# _ES_CACHE = {"ts": None, "at": None, "live": False}
LIVE_TTL_SECONDS = 30  # advance freshness at most every 30s while live
STATIC_TTL_SECONDS = 60 * 60  # 1 hour is plenty (even 6–12h is fine)

TIMEOUT_SHORT = (3, 6)   # connect, read
TIMEOUT_MED = (3, 8)
TIMEOUT_LONG = (3, 12)


SESSION = requests.Session()
adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=20,
    max_retries=Retry(total=3, backoff_factor=0.3,
                      status_forcelist=[502, 503, 504]),
)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Connection": "keep-alive",
})


def get_json_cached(url, *, timeout=10):
    if not hasattr(g, "http_cache"):
        g.http_cache = {}
    if url in g.http_cache:
        return g.http_cache[url]
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    js = r.json()
    g.http_cache[url] = js
    return js


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
            manager_response = SESSION.get(manager_url)
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
    # 1) try DB cache
    try:
        conn = open_conn(DATABASE)
        row = conn.execute(
            "SELECT data FROM static_data WHERE key='bootstrap'").fetchone()
        if row:
            return json.loads(row[0]).get("total_players") or 11_000_000
    except Exception:
        pass
    # 2) fallback network (cached by get_json_cached per-request)
    js = get_json_cached(FPL_STATIC_URL)
    return js.get("total_players", 11_000_000)

# Helper to fetch current gameweek


def get_event_status(force: bool = False):
    now = datetime.now(timezone.utc)
    if (not force) and _ES_CACHE["at"] and (now - _ES_CACHE["at"]).total_seconds() < 30:
        return _ES_CACHE

    r = SESSION.get(FPL_EVENT_STATUS_URL, timeout=10)
    r.raise_for_status()
    js = r.json()
    statuses = js.get("status", [])

    gw = max((s.get("event")
             for s in statuses if isinstance(s.get("event"), int)), default=1)
    is_live = any(s.get("points") == "l" for s in statuses)
    sig = json.dumps(statuses, sort_keys=True)

    # bump last_update only when content changes (monotonic)
    last_update = _ES_CACHE["last_update"] or datetime.now(timezone.utc)
    if sig != _ES_CACHE["sig"]:
        last_update = now

    _ES_CACHE.update({"gw": gw, "is_live": is_live,
                      "last_update": last_update, "sig": sig, "at": now})
    return _ES_CACHE

# Backwards-compatible shims (no extra network)


def get_current_gw(force: bool = False) -> int:
    return get_event_status(force)["gw"]


def get_event_status_last_update() -> datetime:
    return get_event_status()["last_update"]


def get_event_status_state(force: bool = False):
    gw = get_current_gw(force=force)
    last = get_event_status_last_update()
    return {"gw": gw, "is_live": bool(_ES_CACHE.get("is_live")), "last_update": last}


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


def get_static_data(force_refresh: bool = False, current_gw: int = -1, event_updated_iso: str | None = None):
    logger.debug("🔄 [get_static_data] called")

    # use provided value (from g) if available
    if event_updated_iso is None:
        event_updated = get_event_status_last_update()
        event_updated_iso = event_updated.isoformat()
    else:
        event_updated = datetime.fromisoformat(event_updated_iso)
    logger.debug("🕒 [get_static_data] event_updated: %s", event_updated)
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
        resp = SESSION.get(FPL_STATIC_URL, timeout=TIMEOUT_MED)
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
    response = SESSION.get(
        "https://fantasy.premierleague.com/api/element-summary/", timeout=10)
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
    resp = SESSION.get(url, timeout=10)
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
    "defensive_contribution": "defensive_contribution_points",
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
    request_timeout: int = 6,
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

    # new fallback
    if conn is None or cur is None:
        if not db_path:
            db_path = DATABASE  # or raise, your call
        conn = open_conn(db_path)  # this applies all PRAGMAs
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
            # ✅ derive counts from points (global)
            for base in static_blob.values():
                pts_dc = int(base.get("defensive_contribution_points", 0) or 0)
                base["defensive_contribution_count"] = pts_dc // 2
        finally:
            if close_after:
                conn.commit()
                conn.close()
        return

    logger.debug(
        "[global_points] cache miss → fetching explain for all GWs (1..%d)", current_gw)

    # Build requests session
    session = SESSION
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
        # when submitting futures
        futs = {ex.submit(session.get, url, timeout=TIMEOUT_SHORT): gw for gw, url in urls.items()}

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
