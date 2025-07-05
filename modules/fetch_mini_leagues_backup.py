from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

FPL_API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SPECIAL_FLAGS = {
    "en": "gb-eng",         # England
    "s1": "gb-sct",         # Scotland
    "wa": "gb-wls",         # Wales
    "nn": "gb-nir",         # Northern Ireland
}


def get_league_name(league_id):
    """Return the league’s display name from the FPL API."""
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    # top‐level "league" key holds the meta info
    return data.get("league", {}).get("name", f"League {league_id}")

# Get the data for the teams


def get_team_ids_from_league(league_id, max_show):
    # 1) get the standings
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    standings = resp.json().get("standings", {}).get("results", [])[:max_show]
    # I want to also get name of the league which is at the same url, but not in standings, but rather in "league": {"name": }

    # 2) fetch each manager’s details in parallel
    managers = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_entry = {
            executor.submit(requests.get, f"{FPL_API}/entry/{m['entry']}/", HEADERS): m
            for m in standings
        }
        for fut in as_completed(future_to_entry):
            m = future_to_entry[fut]

            country_code = ""
            overall_rank = None

            try:
                detail = fut.result().json()
                print(f"detail: {detail}")  # print
                raw = detail.get(
                    "player_region_iso_code_short", "").strip().lower()
                overall_rank = detail.get("summary_overall_rank", None)
                last_deadline_value = detail.get("last_deadline_value", None)
                country_code = SPECIAL_FLAGS.get(raw, raw)
            except Exception:
                pass
            managers.append({
                "entry":        m["entry"],
                "player_name":  m["player_name"],  # (real name)
                "entry_name":   m["entry_name"],  # (team name)
                "rank":         m["rank"],
                "last_rank":    m["last_rank"],
                "total_points": m["total"],
                "country_code": country_code,
                "overall_rank": overall_rank,
                "last_deadline_value": last_deadline_value,
            })

    return managers


# Current manager if not included in max_
def append_current_manager(managers, team_id, league_id, logger=None):
    """
    If the given team_id isn't already in managers, fetches the manager data
    from the FPL API and appends it to the managers list.

    Args:
        managers (list): List of existing manager dicts.
        team_id (int or str): The FPL entry ID to fetch.
        league_id (int or str): The classic league ID to match.
        logger (logging.Logger, optional): Logger to record debug messages.
    """
    # Only fetch if team_id is provided and not already in the list
    if team_id and not any(m["entry"] == team_id for m in managers):
        resp = requests.get(
            f"{FPL_API}/entry/{team_id}/",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.ok:
            me = resp.json()
            # print(f"me: {mse}")
            raw = me.get("player_region_iso_code_short", "").strip().lower()
            country_code = SPECIAL_FLAGS.get(raw, raw)

            for cl in me.get("leagues", {}).get("classic", []):
                if cl.get("id") == league_id:
                    managers.append({
                        "entry":        team_id,
                        "player_name":  f"{me.get('player_first_name', '')} {me.get('player_last_name', '')}".strip(),
                        "entry_name":   me.get("entry_name", ""),
                        "team_name":    me.get("name", ""),
                        "overall_rank": me.get("summary_overall_rank", 0),
                        "total_points": me.get("summary_overall_points", 0),
                        "last_deadline_value": me.get("last_deadline_value", 0),
                        "rank":         cl.get("entry_rank", 0),
                        "last_rank":    cl.get("entry_last_rank", 0),
                        "country_code": country_code,

                    })
                    if logger:
                        logger.debug(
                            f"[mini] appended me: {team_id} (rank {cl.get('entry_rank')})"
                        )
                    break


def get_team_mini_league_summary(team_id, static_data):
    """
    Fetches only the picked players for each GW, pulls their live stats,
    and returns a dict of summed team‐level numbers.
    """
    FPL_API = "https://fantasy.premierleague.com/api"
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    # 1) figure out current GW
    current_gw = next(e["id"]
                      for e in static_data["events"] if e.get("is_current"))

    # 2) fetch all pick lists in parallel
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/"
        for gw in range(1, current_gw + 1)
    }
    picks_map = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {
            ex.submit(session.get, url): gw
            for gw, url in pick_urls.items()
        }
        for fut in as_completed(future_to_gw):
            gw = future_to_gw[fut]
            try:
                data = fut.result().json()
                # only keep players with multiplier > 0
                picks_map[gw] = {
                    p["element"]: p.get("multiplier", 1)
                    for p in data.get("picks", [])
                    # if p.get("multiplier", 1) > 0
                }
            except Exception:
                picks_map[gw] = {}

    # 3) prepare summary buckets
    summary = {
        "goals_scored_team":            0,
        "expected_goals_team":          0.0,
        "goals_benched_team":           0,
        "assists_team":                 0,
        "clean_sheets_team":            0,
        "expected_assists_team":        0.0,
        "bps_team":                     0,
        "dreamteam_count_team":         0,
        "yellow_cards_team":            0,
        "red_cards_team":               0,
        "own_goals_team":               0,
        "penalties_saved_team":         0,  # not in use
        "penalties_missed_team":        0,  # not in use
        "minutes_team":                 0,
        "total_points_team":            0,
    }

    # 4) fetch all live data in parallel
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/"
        for gw in picks_map
        if picks_map[gw]
    }
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {
            ex.submit(session.get, url): gw
            for gw, url in live_urls.items()
        }
        for fut in as_completed(future_to_gw):
            gw = future_to_gw[fut]
            try:
                elements = fut.result().json().get("elements", [])
            except Exception:
                continue

            # sum up only the picked players
            multipliers = picks_map.get(gw, {})
            for el in elements:
                pid = el.get("id")
                mult = multipliers.get(pid)
                if mult is None:
                    continue

                stats = el.get("stats", {})

                # benched players
                if mult == 0:
                    summary["goals_benched_team"] += stats.get(
                        "goals_scored", 0)
                    continue

                # raw counts
                summary["goals_scored_team"] += stats.get(
                    "goals_scored", 0) * mult
                summary["assists_team"] += stats.get("assists", 0) * mult
                summary["clean_sheets_team"] += stats.get(
                    "clean_sheets", 0) * mult
                summary["bps_team"] += stats.get("bps", 0) * mult
                summary["expected_goals_team"] += float(
                    stats.get("expected_goals", 0)) * mult
                summary["expected_assists_team"] += float(
                    stats.get("expected_assists", 0)) * mult
                summary["yellow_cards_team"] += stats.get(
                    "yellow_cards", 0) * mult
                summary["red_cards_team"] += stats.get("red_cards", 0) * mult
                summary["own_goals_team"] += stats.get("own_goals", 0) * mult
                summary["penalties_saved_team"] += stats.get(
                    "penalties_saved", 0) * mult
                summary["penalties_missed_team"] += stats.get(
                    "penalties_missed", 0) * mult
                summary["minutes_team"] += stats.get("minutes", 0) * mult

                # dream team count
                if el.get("stats", {}).get("in_dreamteam", False):
                    summary["dreamteam_count_team"] += mult

                # total points
                summary["total_points_team"] += stats.get(
                    "total_points", 0) * mult

    return summary

# Get the current manager (if not part top N number of top ranked displayed)
