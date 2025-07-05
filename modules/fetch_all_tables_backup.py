import requests


def build_player_info(static_data):
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Build lookup maps once
    code_to_name = {team["code"]: team["name"] for team in teams}
    code_to_short_name = {team["code"]: team["short_name"] for team in teams}

    player_info = {}

    for player in players:
        team_code = player["team_code"]
        team_name = code_to_name.get(team_code, "UNK")
        team_short = code_to_short_name.get(team_code, "UNK")

        player_info[player["id"]] = {
            # Basic info
            "photo": "p" + player["photo"].replace(".jpg", ".png"),
            "team_code": team_code,
            "team_name": team_name,          # Full name
            "team_short_name": team_short,   # 3-letter code
            "web_name": player["web_name"],
            "element_type": player["element_type"],
            "now_cost": player["now_cost"],

            # ✅ (everything else unchanged)
            "goals_scored": player["goals_scored"],
            "expected_goals": round(float(player["expected_goals"]), 2),
            "assists": player["assists"],
            "expected_assists": round(float(player["expected_assists"]), 2),
            "expected_goal_involvements": round(float(player["expected_goal_involvements"]), 2),
            "goals_assists": int(player["goals_scored"]) + int(player["assists"]),
            "goals_performance": round(player["goals_scored"] - float(player["expected_goals"]), 2),
            "assists_performance": round(player["assists"] - float(player["expected_assists"]), 2),
            "goals_assists_performance": round(
                (player["goals_scored"] + player["assists"]) - float(player["expected_goal_involvements"]), 2),
            "goals_assists_performance_team_vs_total": 0,
            "starts": player["starts"],
            "minutes": player["minutes"],
            "clean_sheets": player["clean_sheets"],
            "yellow_cards": player["yellow_cards"],
            "red_cards": player["red_cards"],
            "bps": player["bps"],
            "own_goals": player["own_goals"],
            "goals_conceded": player["goals_conceded"],
            "penalties_saved": player["penalties_saved"],
            "penalties_missed": player["penalties_missed"],
            "dreamteam_count": player["dreamteam_count"],
            "total_points": player["total_points"],
            "ppm": round(player["total_points"] / (player["now_cost"] / 10), 1) if player["now_cost"] else 0,

            # Team-related metrics (unchanged)
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
            "captained_points_team": 0,
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
            "red_cards_points": 0
        }

    return player_info


def populate_player_info_all_with_live_data(team_id, player_info, static_data):
    """
    Populate both global points breakdown and team-specific aggregates
    in one pass per GW, fetching HTTP in parallel to speed up loads.
    """
    FPL_API = "https://fantasy.premierleague.com/api"
    session_req = requests.Session()
    session_req.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Encoding": "gzip"
    })

    # Determine current GW
    current_gw = next(e["id"] for e in static_data.get(
        "events", []) if e.get("is_current"))

    # Prepare URLs
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/" for gw in range(1, current_gw + 1)}
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/" for gw in range(1, current_gw + 1)}

    # Fetch live + pick data in parallel
    live_data_map = {}
    picks_data_map = {}
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
            except Exception:
                continue
            if kind == 'live':
                live_data_map[gw] = data.get('elements', [])
            else:
                picks_data_map[gw] = {
                    p['element']: p.get('multiplier', 1)
                    for p in data.get('picks', [])
                }

    # DEBUG #1: which GWs did we fetch?
    print(f"[populate] live_data_map keys: {sorted(live_data_map.keys())}")
    print(f"[populate] picks_data_map keys: {sorted(picks_data_map.keys())}")

    # Process each GW
    for gw in range(1, current_gw + 1):
        live_elements = live_data_map.get(gw, [])
        multipliers = picks_data_map.get(gw, {})

        # DEBUG #2: summary counts for this GW
        applied = sum(1 for m in multipliers.values() if m)
        print(f"[GW {gw}] will apply {applied} picked players; "
              f"#live_elements={len(live_elements)}, #multipliers={len(multipliers)}")

        for element in live_elements:
            pid = element.get('id')
            if pid not in player_info:
                continue
            pi = player_info[pid]
            stats = element.get('stats', {})
            mult = multipliers.get(pid)

            # 1) Global points from explain
            for block in element.get('explain', []):
                for s in block.get('stats', []):
                    key = f"{s['identifier']}_points"
                    if key in pi:
                        pi[key] += s.get('points', 0)

            # Skip team logic if not picked
            if mult is None:
                continue

            # 2) Bench stats
            if mult == 0:
                pi['goals_benched_team'] += stats.get('goals_scored', 0)
                pi['assists_benched_team'] += stats.get('assists', 0)
                pi['starts_benched_team'] += stats.get('starts', 0)
                pi['minutes_benched_team'] += stats.get('minutes', 0)

            # 3) Starter & captain stats
            if mult in (1, 2, 3):
                # DEBUG #3: ensure this block is hit and inspect stats
                # print(f"[GW {gw} STARTER] pid={pid}, mult={mult}")
                # print(f"    stats.keys(): {list(stats.keys())}")
                # print(
                #   f"    starts={stats.get('starts')}, goals_scored={stats.get('goals_scored')}")

                xg = float(stats.get('expected_goals', 0))
                xa = float(stats.get('expected_assists', 0))
                goals = stats.get('goals_scored', 0)
                assists = stats.get('assists', 0)
                starts = stats.get('starts', 0)
                mins = stats.get('minutes', 0)
                cs = stats.get('clean_sheets', 0)
                bps = stats.get('bps', 0)
                yc = stats.get('yellow_cards', 0)
                rc = stats.get('red_cards', 0)
                ic = stats.get('in_dreamteam', False)

                # Raw aggregates
                pi['expected_goals_team'] += xg
                pi['expected_assists_team'] += xa
                pi['goals_scored_team'] += goals
                pi['assists_team'] += assists
                pi['goals_assists_team'] += (goals + assists)
                pi['expected_goal_involvements_team'] += (xg + xa)
                pi['starts_team'] += starts
                pi['minutes_team'] += mins
                pi['clean_sheets_team'] += cs
                pi['bps_team'] += bps
                pi['yellow_cards_team'] += yc
                pi['red_cards_team'] += rc
                if ic:
                    pi['dreamteam_count_team'] += 1

                # Performance deltas
                pi['goals_performance_team'] = round(
                    pi['goals_scored_team'] - pi['expected_goals_team'], 2)
                pi['assists_performance_team'] = round(
                    pi['assists_team'] - pi['expected_assists_team'], 2)
                pi['goals_assists_performance_team'] = round(
                    pi['goals_assists_team'] - pi['expected_goal_involvements_team'], 2)

            # 4) Captain extra logic
            if mult in (2, 3):
                pi['goals_captained_team'] += stats.get('goals_scored', 0)
                pi['assists_captained_team'] += stats.get('assists', 0)
                pi['captained_team'] += 1

            # 5) Team points from explain
            for block in element.get('explain', []):
                for s in block.get('stats', []):
                    key = f"{s['identifier']}_points_team"
                    if key in pi and mult > 0:
                        pi[key] += s.get('points', 0) * mult

            # 6) Total points & ppm
            total_pts = stats.get('total_points', 0)
            if mult > 0:
                pi['total_points_team'] += total_pts
                cost = pi.get('now_cost', 0)
                if cost:
                    pi['ppm_team'] = round(
                        pi['total_points_team'] / (cost / 10), 1)

    # DEBUG SUMMARY
   # total_started = sum(1 for pi in player_info.values()
    #                    if pi.get("starts_team", 0) > 0)
    # total_scorers = sum(1 for pi in player_info.values()
     #                   if pi.get("goals_scored_team", 0) > 0)
    # print(f"[populate] players with starts_team>0:   {total_started}")
    # print(f"[populate] players with goals_scored_team>0: {total_scorers}")

    return player_info
