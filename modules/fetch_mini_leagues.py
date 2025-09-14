# fetch_mini_league.py
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import url_for
from modules.utils import ordinalformat, get_static_data

logger = logging.getLogger(__name__)

FPL_API = "https://fantasy.premierleague.com/api"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

SPECIAL_FLAGS = {
    "en": "gb-eng",  # England
    "s1": "gb-sct",  # Scotland
    "wa": "gb-wls",  # Wales
    "nn": "gb-nir",  # Northern Ireland
}

static_data = get_static_data()
current_gw = next((e["id"] for e in static_data["events"]
                  if e.get("is_current")), None)
gw_finished = next(
    (e["finished"] for e in static_data["events"] if e["id"] == current_gw), False)
# optionally: data_checked = next((e["data_checked"] ...), False)

# Maps from your cached bootstrap-static structure
player_data_by_id = {e["id"]: e for e in static_data["elements"]}
team_id_to_name = {t["id"]: t["name"] for t in static_data["teams"]}


def get_entry_history(entry_id: int) -> dict:
    url = f"{FPL_API}/entry/{entry_id}/history/"
    resp = SESSION.get(url)
    if not resp.ok:
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


def get_current_gameweek():
    url = f"{FPL_API}/bootstrap-static/"
    resp = SESSION.get(url)
    if not resp.ok:
        logger.error("Failed to fetch bootstrap-static for current gameweek")
        return None
    data = resp.json()
    for event in data.get("events", []):
        if event.get("is_current"):
            return event.get("id")
    return None


def get_player_data():
    url = f"{FPL_API}/bootstrap-static/"
    resp = SESSION.get(url)
    if not resp.ok:
        logger.error("Failed to fetch bootstrap-static for player data")
        return {}
    return {p["id"]: p for p in resp.json().get("elements", [])}


def get_live_points(event_id: int):
    url = f"{FPL_API}/event/{event_id}/live/"
    resp = SESSION.get(url)
    if not resp.ok:
        logger.error("Failed to fetch live points for event %s", event_id)
        return {}
    return {p["id"]: p["stats"] for p in resp.json().get("elements", [])}


def get_picks(entry_id: int, event_id: int):
    url = f"{FPL_API}/entry/{entry_id}/event/{event_id}/picks/"
    resp = SESSION.get(url)
    if not resp.ok:
        logger.warning(
            "Failed to fetch picks for entry %s, event %s", entry_id, event_id)
        return []
    return resp.json().get("picks", [])


def get_overall_league_leader_total():
    """
    Fetch the classic‐league standings for `league_id` and return
    the `total` points held by the manager in 1st place.

    Returns None if there’s no data or no rank==1 entry.
    """
    url = f"{FPL_API}/leagues-classic/314/standings/"
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


def enrich_points_behind(managers: list[dict]) -> list[dict]:
    if not managers:
        return managers

    league_leader_pts = max((m.get("total_points", 0)
                            for m in managers), default=0)
    leader_pts = get_overall_league_leader_total()

    for m in managers:
        # negative = "behind"
        m["pts_behind_league_leader"] = m.get(
            "total_points", 0) - league_leader_pts
        m["pts_behind_overall"] = m.get("total_points", 0) - (leader_pts or 0)
        m["years_active_label"] = ordinalformat(m.get("years_active", 0))

    return managers


def build_manager(me: dict, league_entry: dict | None = None) -> dict:
    raw = (me.get("player_region_iso_code_short") or "").strip().lower()
    country_code = SPECIAL_FLAGS.get(raw, raw)

    years_active_val = (me.get("years_active") or 0) + 1

    base = {
        "entry": me.get("id", me.get("entry")),
        "entry_name": me.get("entry_name", ""),
        "country_code": country_code,
        "player_region_iso_code_long": me.get("player_region_iso_code_long", "N/A"),
        "team_name": me.get("name", ""),
        "last_deadline_bank": me.get("last_deadline_bank") or 0,
        "last_deadline_total_transfers": me.get("last_deadline_total_transfers") or 0,
        "last_deadline_value": me.get("last_deadline_value") or 0,
        "player_name": f"{me.get('player_first_name', '')} {me.get('player_last_name', '')}".strip(),
        "total_points": me.get("summary_overall_points", 0),
        "years_active": years_active_val,
        "years_active_label": years_active_val,
    }

    if league_entry:
        base.update({
            "rank": league_entry.get("entry_rank", league_entry.get("rank", 0)),
            "last_rank": league_entry.get("entry_last_rank", league_entry.get("last_rank", 0)),
        })

    # National league URL
    country_name = (me.get("player_region_name") or "").strip().lower()
    classic_leagues = me.get("leagues", {}).get("classic", [])
    base["national_league_url"] = None
    if country_name and classic_leagues:
        for league in classic_leagues:
            league_name = (league.get("name") or "").strip().lower()
            if league_name == country_name:
                try:
                    base["national_league_url"] = url_for(
                        'mini_leagues', league_id=league['id'])
                except Exception as e:
                    logger.warning(
                        f"Failed to generate URL for league {league.get('id')}: {e}")
                    base["national_league_url"] = None

    # ---------- Static data (from DB) ----------
    from modules.utils import get_static_data
    static_data = get_static_data() or {}
    elements = static_data.get("elements", [])
    teams = static_data.get("teams", [])
    events = static_data.get("events", [])

    player_data_by_id = {e["id"]: e for e in elements}
    team_id_to_name = {t["id"]: t["name"] for t in teams}

    current_gw = next((e["id"] for e in events if e.get("is_current")), None)
    gw_finished = next((e["finished"]
                       for e in events if e.get("id") == current_gw), False)

    # ---------- Live + picks ----------
    live_points = get_live_points(current_gw) if current_gw else {}
    picks = get_picks(base["entry"], current_gw) if current_gw else []

    # ---------- Entry history (CHIPS, ranks, etc.) ----------
    history = get_entry_history(base["entry"])
    chips = history.get("chips", []) or []

    # Active chip (label for UI + numeric for backend sort alias)
    chip_name_map = {
        "bboost": "Bench Boost",
        "freehit": "Free Hit",
        "3xc": "Triple Captain",
        "wildcard": "Wildcard",
    }
    chip_order = {"bboost": 1, "freehit": 2, "3xc": 3, "wildcard": 4}

    active_chip_code = next(
        (c.get("name") for c in chips
         if c.get("event") == current_gw and c.get("name") in chip_name_map),
        None
    )
    base["active_chip"] = chip_name_map.get(active_chip_code, "")
    base["active_chip_sort"] = chip_order.get(
        active_chip_code, 99)  # empties last

    # ---------- Captain snapshot ----------
    base["captain_current_name"] = "N/A"
    base["captain_current_team"] = "N/A"
    base["captain_current_team_id"] = 0
    base["captain_current_team_code"] = 0
    base["captain_current_multiplier"] = 0
    base["captain_current_points"] = 0
    base["captain_current_pending"] = False

    if picks and current_gw:
        # Pick armband by multiplier (>1 covers C/TC; VC will only move after GW ends)
        armband = next((p for p in picks if int(
            p.get("multiplier", 1) or 1) > 1), None)
        if armband is None:
            armband = next((p for p in picks if p.get("is_captain")), None)

        if armband:
            element_id = armband.get("element")
            player = player_data_by_id.get(element_id, {}) or {}
            stats = live_points.get(element_id, {}) or {}
            mult = int(armband.get("multiplier", 1) or 1)

            team_id = player.get("team")
            team_code = player.get("team_code", 0)

            base["captain_current_name"] = player.get("web_name", "N/A")
            base["captain_current_team"] = team_id_to_name.get(team_id, "N/A")
            base["captain_current_team_id"] = team_id or 0
            base["captain_current_team_code"] = team_code or 0
            base["captain_current_multiplier"] = mult

            minutes = int(stats.get("minutes") or 0)
            total_points = int(stats.get("total_points") or 0)

            if not gw_finished and minutes == 0:
                base["captain_current_points"] = None  # UI shows ⏳ for None
                base["captain_current_pending"] = True
            else:
                base["captain_current_points"] = total_points * mult
                base["captain_current_pending"] = False

    # ---------- Copy history metrics ----------
    base["chips"] = chips
    base["bench_points"] = history.get("bench_points", 0)
    base["transfer_cost"] = history.get("transfer_cost", 0)
    base["overall_rank"] = history.get("overall_rank") or 0
    base["overall_last_rank"] = history.get("overall_last_rank") or 0

    # Per-chip first-use GWs (for your columns)
    chip_events: dict[str, list[int]] = {}
    for c in chips:
        chip_events.setdefault(c.get("name"), []).append(c.get("event"))

    wcs = chip_events.get("wildcard", []) or []
    base["wildcard1_gw"] = wcs[0] if len(wcs) > 0 else 0
    base["wildcard2_gw"] = wcs[1] if len(wcs) > 1 else 0

    for chip_name in ("3xc", "bboost", "freehit", "manager"):
        events_used = chip_events.get(chip_name, []) or []
        base[f"{chip_name}_gw"] = events_used[0] if events_used else 0

    return base


def get_league_name(league_id: int) -> str:
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = SESSION.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("league", {}).get("name", f"League {league_id}")


def get_team_ids_from_league(league_id: int, max_show: int) -> list[dict]:
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = SESSION.get(url)
    resp.raise_for_status()
    standings = resp.json().get("standings", {}).get("results", [])[:max_show]

    managers = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_entry = {
            executor.submit(SESSION.get, f"{FPL_API}/entry/{m['entry']}/"): m
            for m in standings
        }
        for fut in as_completed(future_to_entry):
            m = future_to_entry[fut]
            try:
                me = fut.result().json()
            except Exception:
                continue
            managers.append(build_manager(me, league_entry=m))

    return managers


def append_current_manager(managers: list[dict], team_id: int, league_id: int, logger=None) -> None:
    if team_id and not any(m["entry"] == team_id for m in managers):
        resp = SESSION.get(f"{FPL_API}/entry/{team_id}/")
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


def get_team_mini_league_summary(team_id: int, static_data: dict, live_data_map: dict) -> dict:
    SESSION = requests.Session()
    SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

    current_gw = next(
        (e["id"] for e in static_data["events"] if e.get("is_current")),
        None
    )

    if current_gw is None:
        logger.warning("No current gameweek found in the data.")
        return {}

    # Fetch all picks for this manager (still per manager)
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/"
        for gw in range(1, current_gw + 1)
    }
    picks_map = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {ex.submit(SESSION.get, url)                        : gw for gw, url in pick_urls.items()}
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
        "bps_team": 0,  # Change to bonus_points_team
        "bonus_team": 0,
        "captain_points_team": 0,
        "clean_sheets_team": 0,
        "defensive_contribution_team": 0,
        "dreamteam_count_team": 0,
        "expected_assists_team": 0.0,
        "expected_goals_team": 0.0,
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
            stats = el.get("stats", {})

            if mult == 0:
                summary["goals_benched_team"] += stats.get("goals_scored", 0)
                continue

            base_points = stats.get("total_points", 0)
            if mult == 2:
                summary["captain_points_team"] += base_points
            elif mult == 3:
                summary["captain_points_team"] += base_points * 2

            if mult in (1, 2, 3):
                summary["goals_scored_team"] += stats.get("goals_scored", 0)
                summary["assists_team"] += stats.get("assists", 0)
                summary["clean_sheets_team"] += stats.get("clean_sheets", 0)

                # ✅ Override: use points from explain instead of value for DC
                dc_points = 0
                for block in el.get("explain", []):
                    for s in block.get("stats", []):
                        if s.get("identifier") == "defensive_contribution":
                            dc_points += s.get("points", 0)
                summary["defensive_contribution_team"] += dc_points

                summary["bonus_team"] += stats.get("bonus", 0)
                summary["yellow_cards_team"] += stats.get("yellow_cards", 0)
                summary["red_cards_team"] += stats.get("red_cards", 0)
                summary["minutes_team"] += stats.get("minutes", 0)
                if stats.get("in_dreamteam", False):
                    summary["dreamteam_count_team"] += 1
                summary["total_points_team"] += base_points

    return summary
