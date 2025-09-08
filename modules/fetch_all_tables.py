import logging
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Logger for debugging
logger = logging.getLogger(__name__)

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
            "appearances": 0,  # not implemented yet
            "assists": p["assists"],
            "assists_performance": round(p["assists"] - float(p.get("expected_assists", 0)), 2),
            "bps": p["bps"],
            "bonus": p["bonus"],
            "cbi": p["clearances_blocks_interceptions"],
            "clean_sheets": p["clean_sheets"],
            "clean_sheets_per_90": p["clean_sheets_per_90"],
            "defensive_contribution": p["defensive_contribution"],
            "defensive_contribution_count": 0,
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
            "recoveries": p["recoveries"],
            "saves": p["saves"],
            "starts": p["starts"],
            "tackles": p["tackles"],
            "ppm": round(p["total_points"] / (p["now_cost"] / 10), 1) if p["now_cost"] else 0,
            "penalties_saved": p["penalties_saved"],
            "penalties_missed": p["penalties_missed"],
            "points_per_game": p["points_per_game"],
            "total_points": p["total_points"],
            "yellow_cards": p["yellow_cards"],

            # Global points breakdown (populate later) Need to convert to points
            # 0-59 minutes. 1 point. 60+ 2 points.
            "assists_points": 0,            # 3 points
            "clean_sheets_points": 0,       # 4 points for GK and Def, 1 point for Mid
            "defensive_contribution_points": 0,  # 2 points
            "goals_conceded_points": 0,     # -1 point every other goal conceded within a game
            # 10, 6, 5, 4 points depending on element type
            "goals_scored_points": 0,
            "minutes_points": 0,
            "own_goals_points": 0,          # -2 points
            "penalties_saved_points": 0,    # 5 points
            "penalties_missed_points": 0,   # -2 points
            "red_cards_points": 0,          # -2 points
            "saves_points": 0,               # 2 points for every three saves in a game
            "yellow_cards_points": 0,       # -1 point

            # Team-specific aggregates
            "appearances_team": 0,
            "assists_performance_team": 0,
            "assists_benched_team": 0,
            "assists_captained_team": 0,
            "assists_points_team": 0,
            "assists_team": 0,
            "benched_points_team": 0,
            "bonus_team": 0,
            "bps_team": 0,
            "cbi_team": 0,
            "clean_sheets_team": 0,
            "clean_sheets_per_90_team": 0,
            "clean_sheets_points_team": 0,
            "clean_sheets_rate_team": 0,
            "captain_points_team": 0,
            "captained_team": 0,
            "dreamteam_count_team": 0,
            "defensive_contribution_team": 0,
            "defensive_contribution_count_team": 0,
            "defensive_contribution_points_team": 0,
            "defensive_contribution_per_90_team": 0,
            "expected_assists_team": 0,
            "expected_goals_team": 0,
            "expected_goal_involvements_team": 0,
            "expected_goals_conceded_team": 0,
            "expected_goals_per_90_team": 0,
            "goals_scored_team": 0,
            "goals_scored_points_team": 0,
            "goals_performance_team": 0,
            "goals_benched_team": 0,
            "goals_captained_team": 0,
            "goals_conceded_points_team": 0,
            "goals_assists_team": 0,
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
            "recoveries_team": 0,
            "saves_points_team": 0,
            "starts_benched_team": 0,
            "starts_team": 0,
            "tackles_team": 0,
            "total_points_team": 0,
            "yellow_cards_team": 0,
            "yellow_cards_points_team": 0,
            "red_cards_team": 0,
            "red_cards_points_team": 0,
        }
    return player_info


def add_explain_points(pi: dict, explain_blocks, suffix: str = "", mult: int = 1, pid=None, gw=None, tag=""):
    for block in (explain_blocks or []):
        fixture_id = block.get("fixture")
        for s in block.get("stats", []):
            ident = s.get("identifier")
            pts = s.get("points", 0)
            key = f"{ident}_points{suffix}"

            # Special debug for goals_scored
            if ident == "goals_scored":
                logger.debug(
                    f"[GW {gw}] PID {pid} fixture={fixture_id} {tag} → "
                    f"trying to update {key} by {pts} (mult={mult}), "
                    f"before={pi.get(key)}"
                )

            if key not in pi:
                logger.warning(
                    f"[GW {gw}] PID {pid} fixture={fixture_id} {tag} → "
                    f"missing key={key}, skipping"
                )
                continue

            before = pi[key]
            pi[key] = before + pts * mult
            after = pi[key]

            logger.debug(
                f"[GW {gw}] PID {pid} fixture={fixture_id} {tag} → "
                f"{key}: {before} + {pts}*{mult} = {after}"
            )


def populate_player_info_all_with_live_data(team_id, player_info, static_data):
    logger.debug("[populate_player_info_all_with_live_data] called")

    FPL_API = "https://fantasy.premierleague.com/api"
    session_req = requests.Session()
    session_req.headers.update(
        {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})

    # 1) Current GW
    try:
        current_gw = next(e["id"] for e in static_data.get(
            "events", []) if e.get("is_current"))
    except StopIteration:
        logger.error("No current gameweek found in static_data.events")
        return {}

    # 2) URLs
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/" for gw in range(1, current_gw + 1)}
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/" for gw in range(1, current_gw + 1)}

    # 3) Fetch concurrently
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
                data = fut.result().json()
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

    # 4) IMPORTANT: reset GLOBAL *_points (we're about to re-sum all GWs)
    GLOBAL_POINTS_KEYS = (
        "minutes_points", "defensive_contribution_points", "clean_sheets_points",
        "assists_points", "goals_scored_points", "saves_points", "own_goals_points",
        "goals_conceded_points", "penalties_saved_points", "penalties_missed_points",
        "yellow_cards_points", "red_cards_points",
    )

    for pi in player_info.values():
        for k in GLOBAL_POINTS_KEYS:
            if k in pi:
                pi[k] = 0

    # 5) Only players ever picked
    all_picked_pids = set()
    for picks in picks_data_map.values():
        all_picked_pids.update(picks.keys())

    # 6) Build team_info as copies and ZERO all *_team fields
    team_info = {}
    for pid in all_picked_pids:
        if pid not in player_info:
            continue
        ti = player_info[pid].copy()
        for k in list(ti.keys()):
            if k.endswith("_team"):
                # zero numeric team aggregates/rates
                try:
                    ti[k] = 0 if isinstance(ti[k], int) else 0.0
                except Exception:
                    ti[k] = 0
        team_info[pid] = ti

    # 7) Compute per GW
    for gw in range(1, current_gw + 1):
        live_elements = live_data_map.get(gw, [])
        multipliers = picks_data_map.get(gw, {})

        # de-dup for GLOBAL pass across this GW
        seen_global = set()  # (pid, fixture_id, identifier)

        for element in live_elements:
            pid = element.get('id')
            base = player_info.get(pid)  # global (non-team)
            if not base:
                continue

            stats = element.get('stats', {})
            explain = element.get('explain', [])

            # ---- GLOBAL (non-team): deduplicate per (pid, fixture, ident) ----
            dedup_blocks = []
            for block in (explain or []):
                fx = block.get("fixture")
                kept = []
                for s in block.get("stats", []):
                    ident = s.get("identifier")
                    sig = (pid, fx, ident)
                    if sig in seen_global:
                        continue
                    seen_global.add(sig)
                    kept.append(s)
                if kept:
                    dedup_blocks.append({"fixture": fx, "stats": kept})

            add_explain_points(base, dedup_blocks, suffix="",
                               mult=1, pid=pid, gw=gw, tag="GLOBAL")

            # ---- TEAM (only if picked this GW) ----
            if pid not in multipliers or pid not in team_info:
                continue
            mult = multipliers[pid]
            ti = team_info[pid]

            # bench
            if mult == 0:
                ti['goals_benched_team'] += stats.get('goals_scored', 0)
                ti['assists_benched_team'] += stats.get('assists', 0)
                ti['starts_benched_team'] += stats.get('starts', 0)
                ti['minutes_benched_team'] += stats.get('minutes', 0)
                ti['benched_points_team'] += stats.get('total_points', 0)

            # starter / (triple) captain
            if mult > 0:
                mins = stats.get('minutes', 0)
                if mins > 0:
                    ti['appearances_team'] += 1
                assists = stats.get('assists', 0)
                bonus = stats.get('bonus', 0)
                bps = stats.get('bps', 0)
                cs = stats.get('clean_sheets', 0)
                cbi = stats.get('clearances_blocks_interceptions', 0)
                # total defcons, underlying
                dc = stats.get('defensive_contribution', 0)
                goals = stats.get('goals_scored', 0)
                gc = stats.get('goals_conceded', 0)
                ic = stats.get('in_dreamteam', False)
                mins = stats.get('minutes', 0)
                rc = stats.get('red_cards', 0)
                r = stats.get('recoveries', 0)
                t = stats.get('tackles', 0)
                xg = float(stats.get('expected_goals', 0))
                xgc = float(stats.get('expected_goals_conceded', 0))
                xa = float(stats.get('expected_assists', 0))
                yc = stats.get('yellow_cards', 0)

                ti['assists_team'] += assists
                ti['bonus_team'] += bonus
                ti['bps_team'] += bps
                ti['cbi_team'] += cbi
                ti['clean_sheets_team'] += cs
                ti['defensive_contribution_team'] += dc
                ti['expected_assists_team'] += xa
                ti['expected_goals_team'] += xg
                ti['expected_goals_conceded_team'] += xgc
                ti['expected_goal_involvements_team'] += (xg + xa)
                ti['goals_conceded_team'] += gc
                ti['goals_scored_team'] += goals
                ti['goals_assists_team'] += (goals + assists)
                ti['minutes_team'] += mins
                ti['red_cards_team'] += rc
                ti['recoveries_team'] += r
                ti['starts_team'] += stats.get('starts', 0)
                ti['tackles_team'] += t
                ti['yellow_cards_team'] += yc
                if ic:
                    ti['dreamteam_count_team'] += 1

                ti['goals_performance_team'] = round(
                    ti['goals_scored_team'] - ti['expected_goals_team'], 2)
                ti['assists_performance_team'] = round(
                    ti['assists_team'] - ti['expected_assists_team'], 2)
                ti['goals_assists_performance_team'] = round(
                    ti['goals_assists_team'] -
                    ti['expected_goal_involvements_team'], 2)

                # Handle captain stats for multipliers 2 (captain) or 3 (triple captain)
                if mult in (2, 3):
                    # Increment captain selection count
                    ti['captained_team'] += 1
                    ti['goals_captained_team'] += goals
                    ti['assists_captained_team'] += assists
                    base_points = stats.get('total_points', 0)
                    ti['captain_points_team'] += base_points * \
                        (mult - 1)  # 1x for captain, 2x for triple captain

                # Team points via explain (with multiplier)
                mult = 1 if mult > 0 else 0  # No captain multiplier
                add_explain_points(ti, explain, suffix="_team",
                                   mult=mult, pid=pid, gw=gw, tag="TEAM")

                # Base points without captain multiplier
                ti['total_points_team'] += stats.get('total_points', 0)

                # Calculate points per million (ppm)
                cost = ti.get('now_cost', 0)
                if cost:
                    ti['ppm_team'] = round(
                        ti['total_points_team'] / (cost / 10), 1)

    # 8) Post-process TEAM rates after aggregation
    for ti in team_info.values():
        apps = ti.get("appearances_team", 0)
        ti["points_per_game_team"] = round(
            ti["total_points_team"] / apps, 2) if apps else 0

        # Calculate per 90s
        mins_total = ti.get("minutes_team", 0)
        if mins_total > 0:
            ti["defensive_contribution_per_90_team"] = (
                ti["defensive_contribution_team"] / mins_total) * 90
            ti["clean_sheets_per_90_team"] = (
                ti["clean_sheets_team"] / mins_total) * 90
            rate = (ti["clean_sheets_team"] / mins_total) * 90
            ti["clean_sheets_rate_team"] = min(rate, 1.0)
            ti["expected_goals_per_90_team"] = (
                ti["expected_goals_team"] / mins_total) * 90
        else:
            ti["defensive_contribution_per_90_team"] = 0.0
            ti["clean_sheets_per_90_team"] = 0.0
            ti["clean_sheets_rate_team"] = 0.0
            ti["expected_goals_per_90_team"] = 0.0

    return team_info
