import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import url_for

# use the pooled session from http_client
from modules.utils import ordinalformat, get_static_data
from modules.live_cache import get_live_points_map
from modules.http_client import HTTP

logger = logging.getLogger(__name__)

FPL_API = "https://fantasy.premierleague.com/api"

SPECIAL_FLAGS = {
    "en": "gb-eng",  # England
    "s1": "gb-sct",  # Scotland
    "wa": "gb-wls",  # Wales
    "nn": "gb-nir",  # Northern Ireland
}

DATABASE = "page_views.db"  # adjust path as needed


def get_live_points(event_id: int, cur: sqlite3.Cursor | None = None) -> dict[int, dict]:
    """
    Return id->stats for a GW via the shared live cache.
    If 'cur' is None, open a short-lived connection so legacy callers still work.
    """
    local_conn = None
    try:
        if cur is None:
            local_conn = sqlite3.connect(DATABASE, check_same_thread=False)
            cur = local_conn.cursor()
        return get_live_points_map(cur, event_id, FPL_API)
    finally:
        if local_conn is not None:
            local_conn.close()


def get_entry_history(entry_id: int) -> dict:
    url = f"{FPL_API}/entry/{entry_id}/history/"
    try:
        resp = HTTP.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return {
            "chips": [],
            "bench_points": 0,
            "transfer_cost": 0,
            "overall_rank": None,
            "overall_last_rank": None,
        }

    data = resp.json()
    chips = [{"name": c.get("name"), "event": c.get("event")}
             for c in data.get("chips", [])]

    bench_points = sum(ev.get("points_on_bench", 0)
                       for ev in data.get("current", []))
    transfer_cost = sum(ev.get("event_transfers_cost", 0)
                        for ev in data.get("current", []))

    current = data.get("current", [])
    overall_rank = current[-1]["overall_rank"] if current else None
    overall_last_rank = current[-2]["overall_rank"] if len(
        current) > 1 else None

    return {
        "chips": chips,
        "bench_points": bench_points,
        "transfer_cost": transfer_cost,
        "overall_rank": overall_rank,
        "overall_last_rank": overall_last_rank,
    }


def get_overall_league_leader_total(league_id: int = 314) -> int | None:
    """
    Fetch the classic‐league standings and return the `total` points for rank==1.
    """
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    try:
        resp = HTTP.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch overall league leader total: %s", e)
        return None

    data = resp.json()
    results = data.get("standings", {}).get("results", [])
    if not results:
        return None

    leader = next((r for r in results if r.get("rank") == 1), results[0])
    return leader.get("total")


def enrich_points_behind(managers: list[dict], overall_league_id: int = 314) -> list[dict]:
    if not managers:
        return managers

    league_leader_pts = max((m.get("total_points", 0)
                            for m in managers), default=0)
    overall_leader_pts = get_overall_league_leader_total(
        overall_league_id) or 0

    for m in managers:
        m["pts_behind_league_leader"] = m.get(
            "total_points", 0) - league_leader_pts  # negative = behind
        m["pts_behind_overall"] = m.get("total_points", 0) - overall_leader_pts
        m["years_active_label"] = ordinalformat(m.get("years_active", 0))

    return managers


def build_manager(
    me: dict,
    league_entry: dict | None = None,
    cur: sqlite3.Cursor | None = None,
    *,
    static_data: dict | None = None,
    live_points_by_element: dict[int, dict] | None = None,
    skip_history: bool = False,
) -> dict:
    # --- country + base fields (unchanged) ---
    raw = (me.get("player_region_iso_code_short") or "").strip().lower()
    country_code = SPECIAL_FLAGS.get(raw, raw)
    years_active_val = (me.get("years_active") or 0) + 1
    base = {
        "entry": me.get("id", me.get("entry")),
        "entry_name": me.get("entry_name", ""),
        "country_code": country_code,
        "last_deadline_bank": me.get("last_deadline_bank") or 0,
        "last_deadline_total_transfers": me.get("last_deadline_total_transfers") or 0,
        "last_deadline_value": me.get("last_deadline_value") or 0,
        "player_name": f"{me.get('player_first_name', '')} {me.get('player_last_name', '')}".strip(),
        "player_region_iso_code_long": me.get("player_region_iso_code_long", "N/A"),
        "summary_event_points": me.get("summary_event_points", 0),
        "team_name": me.get("name", ""),
        "total_points": me.get("summary_overall_points", 0),
        "years_active": years_active_val,
        "years_active_label": years_active_val,  # overwritten later
    }
    if league_entry:
        base.update({
            "rank": league_entry.get("entry_rank", league_entry.get("rank", 0)),
            "last_rank": league_entry.get("entry_last_rank", league_entry.get("last_rank", 0)),
        })

    # --- National league URL (reinstated) ---
    base["national_league_url"] = None
    country_name = (me.get("player_region_name") or "").strip().casefold()
    classic_leagues = (me.get("leagues") or {}).get("classic") or []

    for league in classic_leagues:
        if (league.get("name") or "").strip().casefold() == country_name:
            base["national_league_url"] = url_for(
                "mini_leagues", league_id=league["id"])
            break

    # --- static data (reuse if passed) ---
    if static_data is None:
        static_data = get_static_data(
            current_gw=-1, include_global_points=False) or {}
    elements = static_data.get("elements", [])
    teams = static_data.get("teams", [])
    events = static_data.get("events", [])
    player_data_by_id = {e["id"]: e for e in elements}
    team_id_to_name = {t["id"]: t["name"] for t in teams}
    current_gw = next((e["id"] for e in events if e.get("is_current")), None)
    gw_finished = next((e.get("finished")
                       for e in events if e.get("id") == current_gw), False)

    # --- current GW points UX nicety ---
    current_SEP = int(me.get("summary_event_points") or 0)
    if not gw_finished and current_SEP == 0:
        base["summary_event_points"] = None
        base["summary_event_points_pending"] = True
    else:
        base["summary_event_points"] = current_SEP
        base["summary_event_points_pending"] = False

    # --- live points cache (reuse if passed) ---
    if live_points_by_element is None and current_gw:
        live_points_by_element = get_live_points(current_gw, cur)

    # --- captain snapshot (current GW only, 1 picks call) ---
    base.update({
        "captain_current_name": "N/A",
        "captain_current_team": "N/A",
        "captain_current_team_id": 0,
        "captain_current_team_code": 0,
        "captain_current_multiplier": 0,
        "captain_current_points": 0,
        "captain_current_pending": False,
    })
    if current_gw:
        picks = get_picks(base["entry"], current_gw)
        armband = next((p for p in picks if int(
            p.get("multiplier", 1) or 1) > 1), None)
        if armband is None:
            armband = next((p for p in picks if p.get("is_captain")), None)
        if armband:
            el_id = armband.get("element")
            player = player_data_by_id.get(el_id, {}) or {}
            stats = (live_points_by_element or {}).get(el_id, {}) or {}
            mult = int(armband.get("multiplier", 1) or 1)
            base["captain_current_name"] = player.get("web_name", "N/A")
            base["captain_current_team_id"] = player.get("team") or 0
            base["captain_current_team"] = team_id_to_name.get(
                player.get("team"), "N/A")
            base["captain_current_team_code"] = player.get("team_code", 0) or 0
            base["captain_current_multiplier"] = mult
            minutes = int(stats.get("minutes") or 0)
            total_points = int(stats.get("total_points") or 0)
            if not gw_finished and minutes == 0:
                base["captain_current_points"] = None
                base["captain_current_pending"] = True
            else:
                base["captain_current_points"] = total_points * mult

    # --- entry history only if you need those columns ---
    if not skip_history:
        history = get_entry_history(base["entry"])
        chips = history.get("chips", []) or []
        base["chips"] = chips
        base["bench_points"] = history.get("bench_points", 0)
        base["transfer_cost"] = history.get("transfer_cost", 0)
        base["overall_rank"] = history.get("overall_rank") or 0
        base["overall_last_rank"] = history.get("overall_last_rank") or 0

        chip_name_map = {"bboost": "Bench Boost", "freehit": "Free Hit",
                         "3xc": "Triple Captain", "wildcard": "Wildcard"}
        chip_order = {"bboost": 1, "freehit": 2, "3xc": 3, "wildcard": 4}
        active_chip_code = next((c.get("name") for c in chips if c.get(
            "event") == current_gw and c.get("name") in chip_name_map), None)
        base["active_chip"] = chip_name_map.get(active_chip_code, "")
        base["active_chip_sort"] = chip_order.get(active_chip_code, 99)

        chip_events: dict[str, list[int]] = {}
        for c in chips:
            chip_events.setdefault(c.get("name"), []).append(c.get("event"))
        wcs = chip_events.get("wildcard", []) or []
        base["wildcard1_gw"] = wcs[0] if len(wcs) > 0 else 0
        base["wildcard2_gw"] = wcs[1] if len(wcs) > 1 else 0
        for chip_name in ("3xc", "bboost", "freehit"):
            used = chip_events.get(chip_name, []) or []
            base[f"{chip_name}_gw"] = used[0] if used else 0
    else:
        base.update({
            "chips": [],
            "bench_points": 0,
            "transfer_cost": 0,
            "overall_rank": 0,
            "overall_last_rank": 0,
            "active_chip": "",
            "active_chip_sort": 99,
            "wildcard1_gw": 0,
            "wildcard2_gw": 0,
            "3xc_gw": 0,
            "bboost_gw": 0,
            "freehit_gw": 0,
        })
    return base


def get_league_name(league_id: int) -> str:
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = HTTP.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("league", {}).get("name", f"League {league_id}")


def get_team_ids_from_league(
    league_id: int,
    max_show: int,
    *,
    static_data: dict | None = None,
    current_gw: int | None = None,
    live_points_by_element: dict[int, dict] | None = None,
    cur: sqlite3.Cursor | None = None,
    skip_history: bool = True,
) -> list[dict]:
    # 1) One-time static + gw
    if static_data is None:
        static_data = get_static_data(
            current_gw=-1, include_global_points=False) or {}
    if current_gw is None:
        current_gw = next((e["id"] for e in static_data.get(
            "events", []) if e.get("is_current")), None)

    # 2) One-time live map (current GW only)
    local_conn = None
    if cur is None:
        local_conn = sqlite3.connect(DATABASE, check_same_thread=False)
        cur = local_conn.cursor()
    if live_points_by_element is None and current_gw:
        live_points_by_element = get_live_points(current_gw, cur)

    # 3) Fetch league + entries (unchanged), but reuse the data above
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = HTTP.get(url, timeout=10)
    resp.raise_for_status()
    standings = resp.json().get("standings", {}).get("results", [])[:max_show]

    managers: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(standings))) as executor:
            future_to_entry = {
                executor.submit(HTTP.get, f"{FPL_API}/entry/{m['entry']}/", timeout=10): m
                for m in standings
            }
            for fut in as_completed(future_to_entry):
                m = future_to_entry[fut]
                try:
                    r = fut.result()
                    r.raise_for_status()
                    me = r.json()
                except Exception as e:
                    logger.warning(
                        "Entry fetch failed for %s: %s", m.get("entry"), e)
                    continue
                managers.append(
                    build_manager(
                        me,
                        league_entry=m,
                        cur=cur,
                        static_data=static_data,
                        live_points_by_element=live_points_by_element,
                        skip_history=skip_history,  # True for summary table if you don’t show those cols
                    )
                )
    finally:
        if local_conn is not None:
            local_conn.close()

    return managers


def append_current_manager(managers: list[dict], team_id: int, league_id: int, logger=None) -> None:
    if team_id and not any(m["entry"] == team_id for m in managers):
        resp = HTTP.get(f"{FPL_API}/entry/{team_id}/", timeout=10)
        if not resp.ok:
            return
        me = resp.json()
        for cl in me.get("leagues", {}).get("classic", []):
            if cl.get("id") == league_id:
                managers.append(build_manager(me, league_entry=cl))
                if logger:
                    logger.debug(
                        f"[mini] appended manager {team_id} (rank {cl.get('entry_rank')})")
                break


def get_picks(entry_id: int, event_id: int) -> list[dict]:
    url = f"{FPL_API}/entry/{entry_id}/event/{event_id}/picks/"
    try:
        resp = HTTP.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        logger.warning(
            "Failed to fetch picks for entry %s, event %s", entry_id, event_id)
        return []
    return resp.json().get("picks", [])


def get_team_mini_league_breakdown(team_id: int, static_data: dict, live_data_map: dict) -> dict:
    current_gw = next((e["id"] for e in static_data.get(
        "events", []) if e.get("is_current")), None)
    if current_gw is None:
        logger.warning("No current gameweek found in the data.")
        return {}

    # Fetch all picks for this manager (still per manager)
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/"
        for gw in range(1, current_gw + 1)
    }

    picks_map: dict[int, dict[int, int]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {
            ex.submit(HTTP.get, url, timeout=10): gw for gw, url in pick_urls.items()}
        for fut in as_completed(future_to_gw):
            gw = future_to_gw[fut]
            try:
                data = fut.result().json()
                picks_map[gw] = {p["element"]: p.get(
                    "multiplier", 1) for p in data.get("picks", [])}
            except Exception:
                picks_map[gw] = {}

    summary = {
        "assists_team": 0,
        "bonus_team": 0,
        "captain_points_team": 0,
        "clean_sheets_team": 0,
        "defensive_contribution_team": 0,
        "dreamteam_count_team": 0,
        "expected_goals_team": 0,
        "goals_scored_team": 0,
        "goals_benched_team": 0,
        "minutes_team": 0,
        "total_points_team": 0,
        "red_cards_team": 0,
        "yellow_cards_team": 0,
    }

    # Use pre-fetched live_data_map instead of fetching again
    for gw, multipliers in picks_map.items():
        elements = live_data_map.get(gw, [])
        for el in elements:
            pid = el.get("id")
            mult = multipliers.get(pid)
            if mult is None:
                continue
            stats = el.get("stats", {}) or {}

            if mult == 0:
                summary["goals_benched_team"] += stats.get("goals_scored", 0)
                continue

            base_points = stats.get("total_points", 0)
            if mult == 2:
                summary["captain_points_team"] += base_points
            elif mult == 3:
                summary["captain_points_team"] += base_points * 2

            # Starters / captains
            if mult in (1, 2, 3):
                summary["goals_scored_team"] += stats.get("goals_scored", 0)
                summary["assists_team"] += stats.get("assists", 0)
                summary["clean_sheets_team"] += stats.get("clean_sheets", 0)
                # summary["expected_goals_team"] += stats.get(
                #     "expected_goals", 0)

                # Use points from explain for defensive contribution
                dc_points = 0
                for block in el.get("explain", []) or []:
                    for s in block.get("stats", []) or []:
                        if s.get("identifier") == "defensive_contribution":
                            dc_points += s.get("points", 0)
                summary["defensive_contribution_team"] += dc_points

                summary["bonus_team"] += stats.get("bonus", 0)
                summary["yellow_cards_team"] += stats.get("yellow_cards", 0)
                summary["red_cards_team"] += stats.get("red_cards", 0)
                summary["minutes_team"] += stats.get("minutes", 0)
                if stats.get("in_dreamteam"):
                    summary["dreamteam_count_team"] += 1
                summary["total_points_team"] += base_points

    return summary
