import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Build base player info from static_data (bootstrap-static)


def build_player_info(static_data):
    logger.debug("[build_player_info] called")
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Build lookup maps
    code_to_name = {team["code"]: team["name"] for team in teams}
    code_to_short = {team["code"]: team["short_name"] for team in teams}

    player_info = {}
    for p in players:
        team_code = p["team_code"]
        player_info[p["id"]] = {
            # Basic info
            "photo": "p" + p["photo"].replace(".jpg", ".png"),
            "team_code": team_code,
            "team_name": code_to_name.get(team_code, "UNK"),
            "team_short_name": code_to_short.get(team_code, "UNK"),
            "web_name": p["web_name"],
            "element_type": p["element_type"],
            "now_cost": p["now_cost"],
            "selected_by_percent": p["selected_by_percent"],

            # Season stats (so far)
            "assists": p["assists"],
            "assists_performance": round(p["assists"] - float(p.get("expected_assists", 0)), 2),
            "bonus": p["bonus"],
            "bps": p["bps"],
            "clean_sheets": p["clean_sheets"],
            "clean_sheets_per_90": p["clean_sheets_per_90"],
            "defensive_contribution": p["defensive_contribution"],
            "defensive_contribution_per_90": p["defensive_contribution_per_90"],
            "dreamteam_count": p["dreamteam_count"],
            "expected_assists": round(float(p.get("expected_assists", 0)), 2),
            "expected_goal_involvements": round(float(p.get("expected_goal_involvements", 0)), 2),
            "expected_goals": round(float(p.get("expected_goals", 0)), 2),
            "expected_goals_conceded": p["expected_goals_conceded"],
            "expected_goals_per_90": p["expected_goals_per_90"],
            "goals_assists_performance": round((p["goals_scored"] + p["assists"]) - float(p.get("expected_goal_involvements", 0)), 2),
            "goals_assists_performance_team_vs_total": 0,
            "goals_scored": p["goals_scored"],
            "goals_assists": p["goals_scored"] + p["assists"],
            "goals_conceded": p["goals_conceded"],
            "goals_performance": round(p["goals_scored"] - float(p.get("expected_goals", 0)), 2),
            "minutes": p["minutes"],
            "own_goals": p["own_goals"],
            "red_cards": p["red_cards"],
            "starts": p["starts"],
            "ppm": round(p["total_points"] / (p["now_cost"] / 10), 1) if p["now_cost"] else 0,
            "penalties_saved": p["penalties_saved"],
            "penalties_missed": p["penalties_missed"],
            "points_per_game": p["points_per_game"],
            "total_points": p["total_points"],
            "yellow_cards": p["yellow_cards"],

            # Global points breakdown (populate later) Need to convert to points
            # 0-59 minutes. 1 point. 60+ 2 points.
            "minutes_points": 0,
            "defensive_contribution_points": 0,  # 2 points
            "clean_sheets_points": 0,       # 4 points for GK and Def, 1 point for Mid
            "assists_points": 0,            # 3 points
            "goals_points": 0,              # 10, 6, 5, 4 points depending on element type
            "save_points": 0,               # 2 points for every three saves in a game
            "own_goals_points": 0,          # -2 points
            "goals_conceded_points": 0,     # -1 point every other goal conceded within a game
            "penalties_saved_points": 0,    # 5 points
            "penalties_missed_points": 0,   # -2 points
            "yellow_cards_points": 0,       # -1 point
            "red_cards_points": 0,          # -2 points

            # Team-specific aggregates (populate later)
            "assists_performance_team": 0,
            "assists_benched_team": 0,
            "assists_captained_team": 0,
            "assists_points_team": 0,
            "assists_team": 0,
            "benched_points_team": 0,
            "bonus_team": 0,
            "bps_team": 0,
            "clean_sheets_team": 0,
            "clean_sheets_per_90_team": 0,
            "clean_sheets_points_team": 0,
            "captained_points_team": 0,
            "captained_team": 0,
            "dreamteam_count_team": 0,
            # Need to wire up in get all player data function
            "defensive_contribution_team": 0,
            "defensive_contribution_per_90_team": 0,
            "expected_assists_team": 0,
            "expected_goals_team": 0,
            "expected_goal_involvements_team": 0,
            "expected_goals_conceded_team": 0,
            "expected_goals_per_90_team": 0,
            "goals_scored_team": 0,
            "goals_performance_team": 0,
            "goals_benched_team": 0,
            "goals_captained_team": 0,
            "goals_conceded_points_team": 0,
            "goals_assists_team": 0,
            "goals_points_team": 0,
            "goals_conceded_team": 0,
            "goals_assists_performance_team": 0,
            "minutes_team": 0,
            "minutes_benched_team": 0,
            "minutes_points_team": 0,
            "own_goals_team": 0,
            "own_goals_points_team": 0,
            "penalties_saved_team": 0,
            "penalties_missed_team": 0,
            "points_per_game_team": 0,
            "ppm_team": 0,
            "penalties_saved_points_team": 0,
            "penalties_missed_points_team": 0,
            "save_points_team": 0,
            "starts_benched_team": 0,
            "starts_team": 0,
            "total_points_team": 0,
            "yellow_cards_team": 0,
            "yellow_cards_points_team": 0,
            "red_cards_team": 0,
            "red_cards_points_team": 0,
        }
    return player_info


# Logger for debugging
logger = logging.getLogger(__name__)


def populate_player_info_all_with_live_data(team_id, player_info, static_data):
    logger.debug("[populate_player_info_all_with_live_data] called")
    """
    Build team_player_info for a specific team_id:
    - Only players that were in the user's picks at least once.
    - Aggregate team-specific stats across all GWs up to current GW.
    """

    FPL_API = "https://fantasy.premierleague.com/api"
    session_req = requests.Session()
    session_req.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip"
    })

    # 1️⃣ Determine current GW
    try:
        current_gw = next(e["id"] for e in static_data.get(
            "events", []) if e.get("is_current"))
    except StopIteration:
        logger.error("No current gameweek found in static_data.events")
        return {}

    # 2️⃣ Prepare URLs for live data and picks (1..current_gw)
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/" for gw in range(1, current_gw + 1)
    }
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/" for gw in range(1, current_gw + 1)
    }

    # 3️⃣ Fetch all live data and picks concurrently
    live_data_map, picks_data_map = {}, {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_info = {}
        for gw, url in live_urls.items():
            future_to_info[executor.submit(
                session_req.get, url)] = ('live', gw)
        for gw, url in pick_urls.items():
            future_to_info[executor.submit(
                session_req.get, url)] = ('picks', gw)

        for fut in as_completed(future_to_info):
            kind, gw = future_to_info[fut]
            try:
                resp = fut.result()
                data = resp.json()
            except Exception as e:
                logger.warning(f"Failed fetch {kind} for GW {gw}: {e}")
                continue

            if kind == 'live':
                live_data_map[gw] = data.get('elements', [])
            else:
                picks = data.get('picks', [])
                picks_data_map[gw] = {p['element']: p.get(
                    'multiplier', 1) for p in picks}

    logger.debug(f"Fetched live_data for GWs: {sorted(live_data_map.keys())}")
    logger.debug(f"Fetched pick_data for GWs: {sorted(picks_data_map.keys())}")

    # 4️⃣ Find all players ever picked across GWs
    all_picked_pids = set()
    for picks in picks_data_map.values():
        all_picked_pids.update(picks.keys())

    # 5️⃣ Initialize ONLY those players from player_info (static snapshot)
    team_info = {
        pid: player_info[pid].copy()
        for pid in all_picked_pids
        if pid in player_info  # skip if missing in static_data
    }

    # 6️⃣ Process each GW for team-specific stats
    for gw in range(1, current_gw + 1):
        live_elements = live_data_map.get(gw, [])
        multipliers = picks_data_map.get(gw, {})

        logger.debug(
            f"GW {gw}: picks={len(multipliers)}, live_elements={len(live_elements)}")

        for element in live_elements:
            pid = element.get('id')
            if pid not in multipliers or pid not in team_info:
                continue  # skip players not picked

            pi = team_info[pid]
            stats = element.get('stats', {})
            mult = multipliers[pid]

            # Bench stats
            if mult == 0:
                pi['goals_benched_team'] += stats.get('goals_scored', 0)
                pi['assists_benched_team'] += stats.get('assists', 0)
                pi['starts_benched_team'] += stats.get('starts', 0)
                # pi['minutes_benched_team'] += stats.get('minutes', 0)

            # Starter (or captain/triple) stats
            if mult > 0:
                assists = stats.get('assists', 0)
                bonus = stats.get('bonus', 0)
                bps = stats.get('bps', 0)
                cs = stats.get('clean_sheets', 0)
                cs90 = stats.get('clean_sheets_per_90', 0)
                goals = stats.get('goals_scored', 0)
                ic = stats.get('in_dreamteam', False)
                ppg = stats.get('points_per_game', 0)
                rc = stats.get('red_cards', 0)
                xg = float(stats.get('expected_goals', 0))
                xgc = float(stats.get('expected_goals_conceded', 0))
                xg90 = float(stats.get('expected_goals_per_90', 0))
                xa = float(stats.get('expected_assists', 0))
                yc = stats.get('yellow_cards', 0)

                pi['assists_team'] += assists
                pi['bonus_team'] += bonus
                pi['bps_team'] += bps
                pi['clean_sheets_team'] += cs
                pi['clean_sheets_per_90_team'] += cs90
                pi['expected_assists_team'] += xa
                pi['expected_goals_team'] += xg
                pi['expected_goals_conceded_team'] += xgc
                pi['expected_goal_involvements_team'] += xg + xa
                pi['expected_goals_per_90_team'] += xg90
                pi['goals_scored_team'] += goals
                pi['goals_assists_team'] += goals + assists
                pi['minutes_team'] += stats.get('minutes', 0)
                pi['points_per_game'] = ppg  # Get the latest one. No summing
                pi['red_cards_team'] += rc
                pi['starts_team'] += stats.get('starts', 0)
                pi['yellow_cards_team'] += yc

                if ic:
                    pi['dreamteam_count_team'] += 1

                # performance deltas
                pi['goals_performance_team'] = round(
                    pi['goals_scored_team'] - pi['expected_goals_team'], 2)
                pi['assists_performance_team'] = round(
                    pi['assists_team'] - pi['expected_assists_team'], 2)
                pi['goals_assists_performance_team'] = round(
                    pi['goals_assists_team'] -
                    pi['expected_goal_involvements_team'], 2
                )

                # Captain extra
                if mult in (2, 3):
                    pi['goals_captained_team'] += stats.get('goals_scored', 0)
                    pi['assists_captained_team'] += stats.get('assists', 0)
                    pi['captained_team'] += 1

                # Points from explain
                for block in element.get('explain', []):
                    for s in block.get('stats', []):
                        key = f"{s['identifier']}_points_team"
                        if key in pi:
                            pi[key] += s['points'] * mult

                # Total points & ppm
                total_pts = stats.get('total_points', 0)
                pi['total_points_team'] += total_pts
                cost = pi.get('now_cost', 0)
                if cost:
                    pi['ppm_team'] = round(
                        pi['total_points_team'] / (cost / 10), 1)

    # 7️⃣ Return ONLY picked players
    return team_info
