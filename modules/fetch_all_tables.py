import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Build base player info from static_data (bootstrap-static)


def build_player_info(static_data):
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

            # Season stats (so far)
            "goals_scored": p["goals_scored"],
            "expected_goals": round(float(p.get("expected_goals", 0)), 2),
            "assists": p["assists"],
            "expected_assists": round(float(p.get("expected_assists", 0)), 2),
            "expected_goal_involvements": round(float(p.get("expected_goal_involvements", 0)), 2),
            "goals_assists": p["goals_scored"] + p["assists"],
            "goals_performance": round(p["goals_scored"] - float(p.get("expected_goals", 0)), 2),
            "assists_performance": round(p["assists"] - float(p.get("expected_assists", 0)), 2),
            "goals_assists_performance": round((p["goals_scored"] + p["assists"]) - float(p.get("expected_goal_involvements", 0)), 2),
            "goals_assists_performance_team_vs_total": 0,
            "starts": p["starts"],
            "minutes": p["minutes"],
            "clean_sheets": p["clean_sheets"],
            "yellow_cards": p["yellow_cards"],
            "red_cards": p["red_cards"],
            "bps": p["bps"],
            "own_goals": p["own_goals"],
            "goals_conceded": p["goals_conceded"],
            "penalties_saved": p["penalties_saved"],
            "penalties_missed": p["penalties_missed"],
            "dreamteam_count": p["dreamteam_count"],
            "total_points": p["total_points"],
            "ppm": round(p["total_points"] / (p["now_cost"] / 10), 1) if p["now_cost"] else 0,

            # Global points breakdown (populate later)
            "minutes_points": 0,
            "clean_sheets_points": 0,
            "assists_points": 0,
            "goals_points": 0,
            "bonus_points": 0,
            "save_points": 0,
            "own_goals_points": 0,
            "goals_conceded_points": 0,
            "penalties_saved_points": 0,
            "penalties_missed_points": 0,
            "yellow_cards_points": 0,
            "red_cards_points": 0,

            # Team-specific aggregates (populate later)
            "goals_scored_team": 0,
            "expected_goals_team": 0,
            "goals_performance_team": 0,
            "goals_benched_team": 0,
            "goals_captained_team": 0,
            "assists_team": 0,
            "expected_assists_team": 0,
            "assists_performance_team": 0,
            "assists_benched_team": 0,
            "assists_captained_team": 0,
            "goals_assists_team": 0,
            "expected_goal_involvements_team": 0,
            "goals_assists_performance_team": 0,
            "starts_team": 0,
            "minutes_team": 0,
            "clean_sheets_team": 0,
            "captained_team": 0,
            "yellow_cards_team": 0,
            "red_cards_team": 0,
            "bps_team": 0,
            "dreamteam_count_team": 0,
            "starts_benched_team": 0,
            "minutes_benched_team": 0,
            "own_goals_team": 0,
            "goals_conceded_team": 0,
            "penalties_saved_team": 0,
            "penalties_missed_team": 0,
            "total_points_team": 0,
            "ppm_team": 0,
            "minutes_points_team": 0,
            "clean_sheets_points_team": 0,
            "assists_points_team": 0,
            "goals_points_team": 0,
            "yellow_cards_points_team": 0,
            "red_cards_points_team": 0,
            "bonus_points_team": 0,
            "save_points_team": 0,
            "own_goals_points_team": 0,
            "goals_conceded_points_team": 0,
            "penalties_saved_points_team": 0,
            "penalties_missed_points_team": 0,
            "benched_points_team": 0,
            "captained_points_team": 0
        }
    return player_info


# Logger for debugging
logger = logging.getLogger(__name__)


def populate_player_info_all_with_live_data(team_id, player_info, static_data):
    """
    Populate both global points breakdown and team-specific aggregates
    in one pass per GW, fetching HTTP in parallel to speed up loads.
    This function now clones its input so the original static blob
    remains untouched.
    """
    # 0️⃣ Clone the static blob to avoid mutating original data
    player_info = {pid: info.copy() for pid, info in player_info.items()}

    FPL_API = "https://fantasy.premierleague.com/api"
    session_req = requests.Session()
    session_req.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip"
    })

    # Determine current GW
    try:
        current_gw = next(e["id"] for e in static_data.get(
            "events", []) if e.get("is_current"))
    except StopIteration:
        logger.error("No current gameweek found in static_data.events")
        return player_info

    # Prepare URLs
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/" for gw in range(1, current_gw + 1)}
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/" for gw in range(1, current_gw + 1)}

    # Fetch live + pick data in parallel
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

    # Process each GW
    for gw in range(1, current_gw + 1):
        live_elements = live_data_map.get(gw, [])
        multipliers = picks_data_map.get(gw, {})
        applied = sum(1 for m in multipliers.values() if m > 0)
        logger.debug(
            f"GW {gw}: using {applied} picks; live_elements={len(live_elements)}; multipliers={len(multipliers)}")

        for element in live_elements:
            pid = element.get('id')
            if pid not in player_info:
                continue
            pi = player_info[pid]
            stats = element.get('stats', {})
            mult = multipliers.get(pid)

            # 1) Global points breakdown
            for block in element.get('explain', []):
                for s in block.get('stats', []):
                    key = f"{s['identifier']}_points"
                    if key in pi:
                        pi[key] += s.get('points', 0)

            # Skip team-specific logic if not in picks
            if mult is None:
                continue

            # 2) Bench stats
            if mult == 0:
                pi['goals_benched_team'] += stats.get('goals_scored', 0)
                pi['assists_benched_team'] += stats.get('assists', 0)
                pi['starts_benched_team'] += stats.get('starts', 0)
                pi['minutes_benched_team'] += stats.get('minutes', 0)

            # 3) Starter (and possibly captain) stats
            if mult in (1, 2, 3):
                xg = float(stats.get('expected_goals', 0))
                xa = float(stats.get('expected_assists', 0))
                goals = stats.get('goals_scored', 0)
                assists = stats.get('assists', 0)
                cs = stats.get('clean_sheets', 0)
                bps = stats.get('bps', 0)
                yc = stats.get('yellow_cards', 0)
                rc = stats.get('red_cards', 0)
                ic = stats.get('in_dreamteam', False)

                # accumulate
                pi['expected_goals_team'] += xg
                pi['expected_assists_team'] += xa
                pi['goals_scored_team'] += goals
                pi['assists_team'] += assists
                pi['goals_assists_team'] += (goals + assists)
                pi['expected_goal_involvements_team'] += (xg + xa)
                pi['starts_team'] += stats.get('starts', 0)
                pi['minutes_team'] += stats.get('minutes', 0)
                pi['clean_sheets_team'] += cs
                pi['bps_team'] += bps
                pi['yellow_cards_team'] += yc
                pi['red_cards_team'] += rc
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

            # 4) Captain extra
            if mult in (2, 3):
                pi['goals_captained_team'] += stats.get('goals_scored', 0)
                pi['assists_captained_team'] += stats.get('assists', 0)
                pi['captained_team'] += 1

            # 5) Team points from explain
            for block in element.get('explain', []):
                for s in block.get('stats', []):
                    key = f"{s['identifier']}_points_team"
                    if key in pi and mult > 0:
                        pi[key] += s['points'] * mult

            # 6) Total points & ppm
            if mult and mult > 0:
                total_pts = stats.get('total_points', 0)
                pi['total_points_team'] += total_pts
                cost = pi.get('now_cost', 0)
                if cost:
                    pi['ppm_team'] = round(
                        pi['total_points_team'] / (cost / 10), 1)

    return player_info
