
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from flask import g, flash, has_request_context
import json
import logging
import pycountry
from markupsafe import Markup
from modules.fetch_all_tables import build_player_info
from modules.fetch_fixtures import ensure_fixtures_for_gw
from modules.fixtures_utils import build_team_fixture_cache
from modules.http_client import HTTP
import requests
import sqlite3

logger = logging.getLogger(__name__)

DATABASE = "page_views.db"


FPL_API_BASE = "https://fantasy.premierleague.com/api"
FPL_STATIC_URL = f"{FPL_API_BASE}/bootstrap-static/"
FPL_EVENT_STATUS_URL = f"{FPL_API_BASE}/event-status/"
_ES_CACHE = {
    "gw": 1, "is_live": False, "last_update": None,
    "sig": None, "at": None, "maintenance": False, "message": None
}
# _ES_CACHE = {"ts": None, "at": None, "live": False}
LIVE_TTL_SECONDS = 30  # advance freshness at most every 30s while live
STATIC_TTL_SECONDS = 60 * 60  # 1 hour is plenty (even 6–12h is fine)

TIMEOUT_SHORT = (3, 6)   # connect, read
TIMEOUT_MED = (3, 8)
TIMEOUT_LONG = (3, 12)


def _maintenance_forced() -> bool:
    return os.getenv("FPL_MAINTENANCE", "0").lower() in ("1", "true", "yes", "on")


def get_json_cached(url, *, timeout=10):
    if not hasattr(g, "http_cache"):
        g.http_cache = {}
    if url in g.http_cache:
        return g.http_cache[url]
    r = HTTP.get(url, timeout=timeout)
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
            manager_response = HTTP.get(manager_url)
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

    # 1) Manual override FIRST
    if _maintenance_forced():
        _ES_CACHE.update({
            "maintenance": True,
            "message": "The game is being updated and will be available soon.",
            "is_live": False,
            "updating": True,
            "at": now,
            # keep prior gw/last_update if present
        })
        return _ES_CACHE

    # 2) Cache early-return (but don't keep stale maintenance)
    if (not force) and _ES_CACHE.get("at"):
        fresh = (now - _ES_CACHE["at"]).total_seconds() < 30
        if fresh and not _ES_CACHE.get("maintenance"):
            return _ES_CACHE
        # if maintenance was cached but override is OFF, fall through and refetch

    # 3) Normal fetch + parse
    try:
        r = HTTP.get(FPL_EVENT_STATUS_URL, timeout=10)
        if r.status_code == 503:
            _ES_CACHE.update({
                "maintenance": True,
                "message": "The game is being updated and will be available soon.",
                "is_live": False,
                "updating": True,
                "at": now,
            })
            return _ES_CACHE

        r.raise_for_status()
        js = r.json()

        # ---- robust parsing ----
        statuses_all = [s for s in js.get(
            "status", []) if isinstance(s.get("event"), int)]
        if not statuses_all:
            raise ValueError("event-status had no usable rows")

        gw = max((s["event"] for s in statuses_all),
                 default=_ES_CACHE.get("gw") or 1)

        # Only consider rows for this GW (FPL returns up to 3 dates for the same GW)
        rows = [s for s in statuses_all if s.get("event") == gw]
        flags = [s.get("points") or "" for s in rows]           # '', 'l', 'r'
        leagues_flag = (js.get("leagues") or "")                # '' or 'u'
        bonus_any = any(bool(s.get("bonus_added")) for s in rows)

        is_live = any(f == "l" for f in flags)
        results_seen = any(f == "r" for f in flags)
        updating = (leagues_flag == "u") or (results_seen and not bonus_any)

        if is_live:
            message = "Live points are updating."
        elif updating:
            message = "The game is being updated and will be available soon."
        else:
            message = "No fixtures live right now."

        # Include leagues flag in sig so message changes trigger last_update
        sig = json.dumps(
            {"status": rows, "leagues": leagues_flag}, sort_keys=True)

        last_update = _ES_CACHE.get("last_update") or now
        if sig != _ES_CACHE.get("sig"):
            last_update = now

        _ES_CACHE.update({
            "gw": gw,
            "is_live": is_live,
            "updating": updating,
            "message": message,
            "last_update": last_update,
            "sig": sig,
            "at": now,
            "maintenance": False,
        })

        logger.debug(
            "[event-status] gw=%s flags=%s leagues=%r live=%s results=%s bonus_any=%s updating=%s",
            gw, flags, leagues_flag, is_live, results_seen, bonus_any, updating
        )
        return _ES_CACHE

    except Exception:
        # network/parse failure → keep whatever we have; if nothing yet, fall back to safe message
        if not _ES_CACHE.get("at"):
            _ES_CACHE.update({
                "maintenance": True,
                "message": "The game is being updated and will be available soon.",
                "is_live": False,
                "updating": True,
                "at": now,
            })
        return _ES_CACHE


# Backwards-compatible shims (no extra network)


def get_current_gw(force: bool = False) -> int:
    return get_event_status(force)["gw"]


def get_event_status_last_update() -> datetime:
    return get_event_status()["last_update"]


def get_event_status_state(force: bool = False):
    """
    Single source of truth for event status used by before_request.
    Returns gw, is_live, last_update, maintenance, message.
    """
    es = get_event_status(
        force=force)  # <-- use the cached/override-aware call
    return {
        "gw": es.get("gw"),
        "is_live": bool(es.get("is_live")),
        "last_update": es.get("last_update"),
        "maintenance": bool(es.get("maintenance")),
        "message": es.get("message"),
    }


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
                SELECT last_fetched FROM mini_league_summary_cache
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


def get_static_data(
    force_refresh: bool = False,
    current_gw: int = -1,
    event_updated_iso: str | None = None,
    include_global_points: bool = True,   # ✅ existing
    hydrate_fixtures: bool = False,       # ✅ NEW: opt-in per request
    fixtures_lookahead: int = 5,          # ✅ NEW: how many legs per team
):
    logger.debug("🔄 [get_static_data] called")

    # Use provided value (from g) if available
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
    static_data = None

    if row and not force_refresh:
        data_str, last_ts = row
        try:
            cached_time = datetime.fromisoformat(last_ts)
        except ValueError:
            cached_time = datetime.min.replace(tzinfo=timezone.utc)
        age = (now_utc - cached_time).total_seconds()
        if age < STATIC_TTL_SECONDS:
            logger.debug(
                "✅ [get_static_data] bootstrap-static within TTL → using cache (no bump)")
            static_data = json.loads(data_str)
            need_fetch_static = False

    if need_fetch_static:
        logger.debug(
            "⚠️ [get_static_data] bootstrap-static TTL expired (or no row/force) → fetching")
        resp = HTTP.get(FPL_STATIC_URL, timeout=TIMEOUT_MED)
        resp.raise_for_status()
        static_data = resp.json()
        cur.execute(
            "REPLACE INTO static_data (key, data, last_fetched) VALUES (?, ?, ?)",
            ("bootstrap", json.dumps(static_data), now_utc.isoformat())
        )

    # 2) Decide key
    gw_key = current_gw if (isinstance(current_gw, int)
                            and current_gw >= 1) else -1

    # 3) Build static blob (derived / denormalised view of bootstrap)
    static_blob = build_player_info(static_data)

    # 4) Populate global points only when season started AND requested
    if include_global_points and current_gw != -1:
        fill_global_points_from_explain(
            static_blob=static_blob,
            current_gw=gw_key,
            event_updated_iso=event_updated_iso,
            conn=conn,
            cur=cur
        )

    # 4.5) Hydrate fixtures per request (optional, event-aware)
    if hydrate_fixtures and has_request_context():
        try:
            from_event = gw_key if gw_key != -1 else None
            ensure_fixtures_for_gw(
                from_event, database=DATABASE, verbose=False)

            # build per-team in-memory cache once for this request
            g.fixtures_cache = build_team_fixture_cache(
                cur, from_event=from_event, lookahead=fixtures_lookahead)

            legs = sum(len(v) for v in g.fixtures_cache.values())
            logger.debug("[fixtures] hydrated on g: teams=%s legs=%s from_event=%s lookahead=%s",
                         len(g.fixtures_cache), legs, from_event, fixtures_lookahead)
        except Exception as e:
            logger.warning("[fixtures] hydrate failed: %s", e)
            g.fixtures_cache = {}

    # 5) Snapshot for routes to read (write only when we fetched fresh or first init)
    should_write_snapshot = bool(need_fetch_static or force_refresh)
    if not should_write_snapshot:
        cur.execute(
            "SELECT 1 FROM static_player_info WHERE gameweek = ?", (gw_key,))
        if not cur.fetchone():
            logger.debug(
                "🆕 [get_static_data] initialising static_player_info row for gw=%s", gw_key)
            should_write_snapshot = True

    if should_write_snapshot:
        snapshot_time = now_utc.isoformat()
        cur.execute("""
            INSERT OR REPLACE INTO static_player_info (gameweek, data, last_fetched)
            VALUES (?, ?, ?)
        """, (gw_key, json.dumps(static_blob), snapshot_time))
        logger.debug(
            "💾 [get_static_data] Wrote static_player_info (last_fetched=%s) gw=%s", snapshot_time, gw_key)
    else:
        logger.debug(
            "🙅 [get_static_data] Skipped writing static_player_info (cache hit; no bump) gw=%s", gw_key)

    conn.commit()
    conn.close()
    logger.debug("🔚 [get_static_data] finished")
    return static_data


def prune_stale_data(conn, event_updated):
    """
    Delete stale rows from key tables and print comparisons for debugging.
    """
    tables = ["team_player_info", "mini_league_breakdown_cache",
              "mini_league_summary_cache" "managers"]

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
    response = HTTP.get(
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


EXPLAIN_TO_FIELD = {
    "assists": "assists_points",
    "bonus": "bonus_points",
    "clean_sheets": "clean_sheets_points",
    "defensive_contribution": "defensive_contribution_points",
    "goals_scored": "goals_scored_points",
    "goals_conceded": "goals_conceded_points",
    "minutes": "minutes_points",
    "own_goals": "own_goals_points",
    "penalties_saved": "penalties_saved_points",
    "penalties_missed": "penalties_missed_points",
    "red_cards": "red_cards_points",
    "saves": "saves_points",
    "yellow_cards": "yellow_cards_points",
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

    # DB handling
    close_after = False
    if conn is None or cur is None:
        if not db_path:
            db_path = DATABASE
        conn = open_conn(db_path)  # applies PRAGMAs
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
        "SELECT data FROM global_points_cache WHERE event_updated = ?",
        (event_updated_iso,),
    )
    row = cur.fetchone()
    if row:
        logger.debug("[global_points] cache hit")
        try:
            payload = json.loads(row[0])
            apply_points_payload(static_blob, payload)
            # Derive counts from points on cache hit
            for base in static_blob.values():
                pts_dc = int(base.get("defensive_contribution_points", 0) or 0)
                base["defensive_contribution_count"] = pts_dc // 2
        finally:
            if close_after:
                conn.commit()
                conn.close()
        return

    logger.debug(
        "[global_points] cache miss → fetching explain for all GWs (1..%d)",
        current_gw,
    )

    urls = {
        gw: f"https://fantasy.premierleague.com/api/event/{gw}/live/"
        for gw in range(1, current_gw + 1)
    }

    # pid -> { field -> points }
    payload: dict[int, dict[str, int]] = {}

    def ensure(pid: int) -> dict[str, int]:
        if pid not in payload:
            payload[pid] = {v: 0 for v in EXPLAIN_TO_FIELD.values()}
        return payload[pid]

    # Use a sensible connect/read timeout; allow caller to tweak read
    timeout_val = (3, request_timeout)

    # Fetch concurrently
    from concurrent.futures import ThreadPoolExecutor, as_completed  # local import ok
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(HTTP.get, url, timeout=timeout_val): gw
            for gw, url in urls.items()
        }

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
            for el in data.get("elements", []) or []:
                pid = el.get("id")
                if not isinstance(pid, int):
                    continue
                tgt = ensure(pid)
                # 'explain' is a list of blocks, each with 'stats'
                for blk in el.get("explain", []) or []:
                    for s in blk.get("stats", []) or []:
                        ident = s.get("identifier")
                        dst = EXPLAIN_TO_FIELD.get(ident)
                        if not dst:
                            continue
                        try:
                            pts = int(s.get("points", 0) or 0)
                        except (TypeError, ValueError):
                            pts = 0
                        tgt[dst] += pts

    # Persist cache
    cur.execute(
        "INSERT OR REPLACE INTO global_points_cache (event_updated, data, last_fetched) VALUES (?, ?, ?)",
        (event_updated_iso, json.dumps(payload),
         datetime.now(timezone.utc).isoformat()),
    )

    if close_after:
        conn.commit()
        conn.close()

    # Apply to in-memory blob for immediate use by the request
    apply_points_payload(static_blob, payload)

    # Derive counts from points on fresh fetch (parity with cache-hit path)
    for base in static_blob.values():
        pts_dc = int(base.get("defensive_contribution_points", 0) or 0)
        base["defensive_contribution_count"] = pts_dc // 2
