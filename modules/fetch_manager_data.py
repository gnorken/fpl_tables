from flask import session, url_for
import json
from datetime import datetime, timezone
from modules.utils import get_event_status_last_update, territory_icon, SESSION, get_json_cached
from modules.utils import (territory_icon)
import logging
import sqlite3
import time


logger = logging.getLogger(__name__)

TIMEOUT_SHORT = (3, 6)   # connect, read
TIMEOUT_MED = (3, 8)
TIMEOUT_LONG = (3, 12)


TOTAL_MANAGERS_BY_SEASON = {
    "2002/03": 76_284,
    "2003/04": 312_026,
    "2004/05": 472_251,
    "2005/06": 810_000,
    "2006/07": 1_270_000,
    "2007/08": 1_700_000,
    "2008/09": 1_950_000,
    "2009/10": 2_100_000,
    "2010/11": 2_350_000,
    "2011/12": 2_785_573,
    "2012/13": 2_610_000,
    "2013/14": 3_220_000,
    "2014/15": 3_500_000,
    "2015/16": 3_730_000,
    "2016/17": 4_500_000,
    "2017/18": 5_190_000,
    "2018/19": 6_320_000,
    "2019/20": 7_630_000,
    "2020/21": 8_150_000,
    "2021/22": 9_170_000,
    "2022/23": 11_450_000,
    "2023/24": 10_910_000,
    "2024/25": 11_431_930,
}


FPL_API_BASE = "https://fantasy.premierleague.com/api"

DB_PATH = "page_views.db"


def get_manager_data(team_id):
    """
    Fetch manager data and cache it as a single JSON blob in SQLite.
    Returns the cached data if it's already up-to-date based on event-status.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS managers (
            team_id      INTEGER PRIMARY KEY,
            data         TEXT    NOT NULL,
            last_fetched TEXT    NOT NULL
        )
    """)
    conn.commit()

    # 1️⃣ Check cache
    cursor.execute(
        "SELECT data, last_fetched FROM managers WHERE team_id = ?", (team_id,))
    row = cursor.fetchone()
    if row:
        data_json, last_fetched = row
        cached_time = datetime.fromisoformat(last_fetched)
        event_updated = get_event_status_last_update()
        if cached_time >= event_updated:
            conn.close()
            return json.loads(data_json)

    # 2️⃣ Cache miss or stale → fetch from API
    def try_fetch(url):
        resp = SESSION.get(url, timeout=10)
        logger.debug("REQUEST %s HEADERS: %s", url, resp.request.headers)
        logger.debug("RESPONSE STATUS: %s", resp.status_code)
        logger.debug("RESPONSE CONTENT-TYPE: %s",
                     resp.headers.get("Content-Type"))
        snippet = resp.text[:200].replace("\n", "\\n")
        logger.debug("BODY PREVIEW: %r", snippet)
        return resp

    base_url = f"{FPL_API_BASE}/entry/{team_id}/"
    api_data = get_json_cached(base_url)  # dedup within the request
    resp = try_fetch(base_url)

    # detect HTML or parse errors
    def is_html(r):
        ct = r.headers.get("Content-Type", "")
        return "text/html" in ct or r.text.lstrip().startswith("<!DOCTYPE html>")

    if is_html(resp):
        # retry once with cache-bust
        bust_url = f"{base_url}?_={int(time.time())}"
        logger.warning(
            "Got HTML back for %s, retrying with cache-bust → %s", team_id, bust_url)
        resp = try_fetch(bust_url)

    # final check
    try:
        api_data = resp.json()
    except ValueError:
        logger.error("Still not JSON for team_id=%s, giving up", team_id)
        conn.close()
        return None

    # extract the bits we care about
    manager = {
        "first_name":   api_data.get("player_first_name"),
        "last_name":    api_data.get("player_last_name"),
        "team_name":    api_data.get("name"),
        "country_code": api_data.get("player_region_iso_code_short", "").lower(),
        "classic_leagues": api_data.get("leagues", {}).get("classic", []),
        "flag_html":    territory_icon(api_data.get("player_region_iso_code_short", "")),
    }

    # build national league URL
    country_name = api_data.get("player_region_name", "")
    for league in manager["classic_leagues"]:
        if league.get("name", "").lower() == country_name.lower():
            manager["national_league_url"] = url_for(
                'mini_leagues', league_id=league['id'])
            break
    else:
        manager["national_league_url"] = None

    # 3️⃣ Upsert into DB
    cursor.execute("""
        INSERT INTO managers (team_id, data, last_fetched)
        VALUES (?, ?, ?)
        ON CONFLICT(team_id) DO UPDATE SET
            data = excluded.data,
            last_fetched = excluded.last_fetched
    """, (
        team_id,
        json.dumps(manager),
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

    return manager


DEFAULT_PHOTO = "placeholder"


def _add_past_percentiles(history_data: dict) -> None:
    """Mutates history_data['past'] to include total_managers and percentile."""
    for season in history_data.get("past", []):
        tm = TOTAL_MANAGERS_BY_SEASON.get(season.get('season_name'))
        if tm:
            season['total_managers'] = tm
            raw_percentile = 100 * (season.get('rank', 0) / tm)
            if raw_percentile < 0.1:
                season['percentile'] = 0.1
            elif raw_percentile < 1:
                season['percentile'] = round(raw_percentile, 2)
            else:
                season['percentile'] = round(raw_percentile)
        else:
            season['total_managers'] = None
            season['percentile'] = None


def build_current_rows_from_history(history_data: dict) -> list[dict]:
    """
    Turn history['current'] list into the rows your charts/table expect:
    gw, or, rank_change, op, gwr, gwp, pb, tm, tc, £
    """
    rows = []
    cur = history_data.get("current", []) or []

    prev_or = None
    for entry in cur:
        gw = entry.get("event")
        # Keys observed on this endpoint:
        #  points, total_points, overall_rank, rank (GW rank), value, bank,
        #  event_transfers, event_transfers_cost, points_on_bench, ...
        orank = entry.get("overall_rank")
        gwr = entry.get("rank") or entry.get(
            "event_rank")  # FPL sometimes uses 'rank'
        gwp = entry.get("points")
        op = entry.get("total_points")
        pb = entry.get("points_on_bench")
        tm = entry.get("event_transfers")
        tc = entry.get("event_transfers_cost")
        value_tenths = entry.get("value")  # team value in tenths of £m

        # rank_change: positive = improved (moved up), negative = dropped
        rank_change = None
        if prev_or is not None and orank is not None:
            rank_change = prev_or - orank  # e.g. 120k -> 100k = +20k improvement
        prev_or = orank if orank is not None else prev_or

        rows.append({
            "gw": gw,
            "or": orank,
            "rank_change": rank_change,
            "op": op,
            "gwr": gwr,
            "gwp": gwp,
            "pb": pb,
            "tm": tm,
            "tc": tc,
            "£": round(value_tenths / 10, 1) if isinstance(value_tenths, (int, float)) else None,
        })

    return rows


def get_manager_history(team_id):
    """
    Single fetch of /entry/{team_id}/history/ powering:
      • history['past'] (with total_managers + percentile)
      • chips_state (enriched with photos/points where relevant)
      • current_rows (for charts/tables on the current season)
    """
    history_url = f"{FPL_API_BASE}/entry/{team_id}/history/"
    history_response = SESSION.get(history_url, timeout=TIMEOUT_MED)
    history_data = history_response.json()

    # 1) Past seasons → add percentile context
    _add_past_percentiles(history_data)

    # 2) Build current season rows from the SAME payload (no extra HTTP)
    current_rows = build_current_rows_from_history(history_data)

    # 3) Chip usage state (and later, enrich some with picks/live)
    chips_state = {
        "wildcard_1": {"used": False, "gw": None},
        "wildcard_2": {"used": False, "gw": None},
        "freehit_1": {"used": False, "gw": None},
        "freehit_2": {"used": False, "gw": None},
        "bboost_1": {
            "used": False,
            "gw": None,
            "total_points": 0,
            "players": [
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
            ],
        },
        "bboost_2": {
            "used": False,
            "gw": None,
            "total_points": 0,
            "players": [
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
            ],
        },
        "3xc_1": {"used": False, "gw": None, "total_points": 0, "photo": DEFAULT_PHOTO, "web_name": None, "team_code": None},
        "3xc_2": {"used": False, "gw": None, "total_points": 0, "photo": DEFAULT_PHOTO, "web_name": None, "team_code": None},
    }

    # Correct chip parsing (no stray elifs)
    for chip in history_data.get("chips", []):
        chip_name = chip.get("name")
        event = chip.get("event", 0) or 0

        if chip_name == "bboost":
            if event <= 19:
                chips_state["bboost_1"]["used"] = True
                chips_state["bboost_1"]["gw"] = event
            elif event >= 20:
                chips_state["bboost_2"]["used"] = True
                chips_state["bboost_2"]["gw"] = event

        elif chip_name == "3xc":
            if event <= 19:
                chips_state["3xc_1"]["used"] = True
                chips_state["3xc_1"]["gw"] = event
            elif event >= 20:
                chips_state["3xc_2"]["used"] = True
                chips_state["3xc_2"]["gw"] = event

        elif chip_name == "freehit":
            if event <= 19:
                chips_state["freehit_1"]["used"] = True
                chips_state["freehit_1"]["gw"] = event
            elif event >= 20:
                chips_state["freehit_2"]["used"] = True
                chips_state["freehit_2"]["gw"] = event

        elif chip_name == "wildcard":
            if event <= 19:
                chips_state["wildcard_1"]["used"] = True
                chips_state["wildcard_1"]["gw"] = event
            elif event >= 20:
                chips_state["wildcard_2"]["used"] = True
                chips_state["wildcard_2"]["gw"] = event

    # Fetch bootstrap static data once for use in photo/name lookups
    bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    bootstrap_response = SESSION.get(bootstrap_url, timeout=TIMEOUT_MED)
    bootstrap_data = bootstrap_response.json()

    # -----------------------------
    # Enrich Triple Captain chips
    # -----------------------------
    for suffix in ["_1", "_2"]:
        chip_key = f"3xc{suffix}"
        if chips_state[chip_key]["used"] and chips_state[chip_key]["gw"]:
            event_number = chips_state[chip_key]["gw"]

            # Fetch picks for the event.
            picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
            picks_response = SESSION.get(picks_url, timeout=TIMEOUT_SHORT)
            picks_data = picks_response.json()

            # Find the captain's pick.
            captain_element = None
            for pick in picks_data.get("picks", []):
                if pick.get("is_captain"):
                    captain_element = pick.get("element")
                    break

            if captain_element is not None:
                # Fetch live data for the event.
                live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
                live_response = SESSION.get(live_url, timeout=TIMEOUT_SHORT)
                live_data = live_response.json()

                for element in live_data.get("elements", []):
                    if element.get("id") == captain_element:
                        stats = element.get("stats", {})
                        chips_state[chip_key]["total_points"] = stats.get(
                            "total_points", 0)
                        # Retrieve the captain's photo/name from bootstrap data.
                        for player in bootstrap_data.get("elements", []):
                            if player.get("id") == captain_element:
                                chips_state[chip_key]['web_name'] = player.get(
                                    "web_name")
                                chips_state[chip_key]["team_code"] = player.get(
                                    "team_code")
                                photo = player.get("photo", "")
                                if photo:
                                    # if not photo.startswith("p"):
                                    #     photo = "p" + photo
                                    chips_state[chip_key]["photo"] = photo.replace(
                                        ".jpg", "")
                                else:
                                    chips_state[chip_key]["photo"] = DEFAULT_PHOTO
                                break
                        break

    # -----------------------------
    # Enrich Bench Boost chips
    # -----------------------------
    for suffix in ["_1", "_2"]:
        chip_key = f"bboost{suffix}"
        if chips_state[chip_key]["used"] and chips_state[chip_key]["gw"]:
            event_number = chips_state[chip_key]["gw"]

            # Fetch picks for the bench boost event.
            picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
            picks_response = SESSION.get(picks_url, timeout=TIMEOUT_MED)
            picks_data = picks_response.json()

            # Get the four bench players based on their positions (12, 13, 14, 15).
            bench_players = [
                pick for pick in picks_data.get("picks", [])
                if pick.get("position") in [12, 13, 14, 15]
            ]
            bench_players = sorted(
                bench_players, key=lambda p: p.get("position"))

            # Fetch live data for the event.
            live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
            live_response = SESSION.get(live_url, timeout=TIMEOUT_MED)
            live_data = live_response.json()

            # Create a mapping of element IDs to their total points.
            live_points = {
                element.get("id"): element.get("stats", {}).get("total_points", 0)
                for element in live_data.get("elements", [])
            }

            # Update bench boost players info.
            for idx, bench_pick in enumerate(bench_players[:4]):
                element_id = bench_pick.get("element")
                points = live_points.get(element_id, 0)
                photo = DEFAULT_PHOTO
                web_name = ""
                team_code = None

                for player in bootstrap_data.get("elements", []):
                    if player.get("id") == element_id:
                        candidate = player.get("photo", "")
                        if candidate:
                            # if not candidate.startswith("p"):
                            #     candidate = "p" + candidate
                            photo = candidate.replace(".jpg", "")
                        web_name = player.get("web_name", "")
                        team_code = player.get("team_code", "")
                        break

                chips_state[chip_key]["players"][idx]["total_points"] = points
                chips_state[chip_key]["players"][idx]["photo"] = photo
                chips_state[chip_key]["players"][idx]["web_name"] = web_name
                chips_state[chip_key]["players"][idx]["team_code"] = team_code
                chips_state[chip_key]["total_points"] += points

    return {
        "chips_state": chips_state,
        "history": history_data,
        "current_rows": current_rows,  # 👈 use this in /api/current-season
    }
