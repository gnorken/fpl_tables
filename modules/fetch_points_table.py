import requests

FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/102.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://fantasy.premierleague.com/",
}

# And the for points table


def get_player_data_points(static_data):

    # Import stuff from static_data function
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Create a dictionary for quick player lookup by id
    player_info = {
        player["id"]: {
            "element_type": player["element_type"],
            "photo": player["photo"].replace(".jpg", ".png"),
            "team_code": player["team_code"],
            "team_name": next((team["short_name"] for team in teams if team["code"] == player["team_code"]), "N/A"),
            "web_name": player["web_name"],
            "now_cost": player["now_cost"],

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

            "total_points": player["total_points"],
            "ppm": round(float(player["total_points"]) / float(player["now_cost"] / 10)),
            "minutes_points": 0,
            "clean_sheets_points": 0,
            "assists_points": 0,
            "goals_points": 0,
            "yellow_cards_points": 0,
            "red_cards_points": 0,
            "bonus_points": 0,
            "save_points": 0,
            "own_goals_points": 0,
            "goals_conceded_points": 0,
            "penalties_saved_points": 0,
            "penalties_missed_points": 0,
        }
        for player in players
    }
    return player_info


# Find stats by looping thru gameweeks in live data and looping thru player history
def get_live_data_points(team_id, player_info, static_data):
    # Start of live data
    # static_data = get_static_data()
    events = static_data["events"]
    current_gw = next((event["id"]
                      for event in events if event["is_current"]), 1)

    # Loop through gameweeks
    for gw in range(1, current_gw + 1):
        # Fetch live gameweek stats
        live_url = f"{FPL_API_BASE}/event/{gw}/live/"
        live_response = requests.get(live_url, headers=headers)
        live_response.raise_for_status()
        live_data = live_response.json()
        live_elements = live_data.get("elements", [])

        # Fetch picks for the team
        picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{gw}/picks/"
        picks_response = requests.get(picks_url, headers=headers)
        picks_response.raise_for_status()
        picks_data = picks_response.json()

        # Extract player IDs and multipliers from picks
        picks = picks_data.get("picks", [])

        for pick in picks:
            player_id = pick["element"]
            multiplier = pick.get("multiplier", 0)

            # Find the player's gameweek stats in the live data
            for element in live_elements:
                if element["id"] == player_id:
                    # No. of...
                    points = element["stats"]["total_points"]
                    minutes = 0
                    clean_sheets = 0
                    assists = 0
                    goals_scored = 0
                    bonus = 0
                    yc = 0
                    rc = 0
                    og = 0
                    saves = 0
                    ps = 0
                    pm = 0
                    gc = 0
                    captained_points = 0

                    for explanation in element.get("explain", []):
                        for stat in explanation.get("stats", []):
                            if stat.get("identifier") == "minutes":
                                minutes = stat.get("points", 0)
                            if stat.get("identifier") == "clean_sheets":
                                clean_sheets = stat.get("points", 0)
                            if stat.get("identifier") == "assists":
                                assists = stat.get("points", 0)
                            if stat.get("identifier") == "goals_scored":
                                goals_scored = stat.get("points", 0)
                            if stat.get("identifier") == "own_goals":
                                og = stat.get("points", 0)
                            if stat.get("identifier") == "goals_conceded":
                                gc = stat.get("points", 0)
                            if stat.get("identifier") == "bonus":
                                bonus = stat.get("points", 0)
                            if stat.get("identifier") == "saves":
                                saves = stat.get("points", 0)
                            if stat.get("identifier") == "penalties_saved":
                                ps = stat.get("points", 0)
                            if stat.get("identifier") == "penalties_missed":
                                pm = stat.get("points", 0)
                            if stat.get("identifier") == "yellow_cards":
                                yc = stat.get("points", 0)
                            if stat.get("identifier") == "red_cards":
                                rc = stat.get("points", 0)

                    # Benched player
                    if multiplier == 0:
                        benched_points = (minutes + clean_sheets + assists +
                                          goals_scored + bonus + saves + ps + pm + gc + yc + rc)
                        player_info[player_id]["benched_points_team"] += benched_points

                    # Captained points
                    if multiplier in [2, 3]:  # Captain or triple captain
                        captained_points = (
                            minutes + clean_sheets + assists + goals_scored + bonus + saves + ps + pm + gc + yc + rc)
                        player_info[player_id]["captained_points_team"] += captained_points

                    # Playing or playing as captain
                    if multiplier in [1, 2]:
                        player_info[player_id]["total_points_team"] += points
                        # Where can put this?
                        player_info[player_id]["ppm_team"] = round(float(
                            player_info[player_id]["total_points_team"]) / float(player_info[player_id]["now_cost"] / 10))
                        # "ppm": round(float(player["total_points"]) / float(player["now_cost"] / 10)),
                        player_info[player_id]["minutes_points_team"] += minutes
                        player_info[player_id]["clean_sheets_points_team"] += clean_sheets
                        player_info[player_id]["assists_points_team"] += assists
                        player_info[player_id]["goals_points_team"] += goals_scored
                        player_info[player_id]["bonus_points_team"] += bonus
                        player_info[player_id]["yellow_cards_points_team"] += yc
                        player_info[player_id]["red_cards_points_team"] += rc
                        player_info[player_id]["own_goals_points_team"] += og
                        player_info[player_id]["save_points_team"] += saves
                        player_info[player_id]["penalties_saved_points_team"] += ps
                        player_info[player_id]["penalties_missed_points_team"] += pm
                        player_info[player_id]["goals_conceded_points_team"] += gc
                    break  # Stop searching for this player

        # Add logic for all players
        for element in live_elements:
            player_id = element["id"]

            # Stats initialization
            minutes = 0
            clean_sheets = 0
            assists = 0
            goals_scored = 0
            bonus = 0
            yc = 0
            rc = 0
            og = 0
            saves = 0
            ps = 0
            pm = 0
            gc = 0

            # Extract stats for all players
            for explanation in element.get("explain", []):
                for stat in explanation.get("stats", []):
                    if stat.get("identifier") == "minutes":
                        minutes = stat.get("points", 0)
                    if stat.get("identifier") == "clean_sheets":
                        clean_sheets = stat.get("points", 0)
                    if stat.get("identifier") == "assists":
                        assists = stat.get("points", 0)
                    if stat.get("identifier") == "goals_scored":
                        goals_scored = stat.get("points", 0)
                    if stat.get("identifier") == "own_goals":
                        og = stat.get("points", 0)
                    if stat.get("identifier") == "goals_conceded":
                        gc = stat.get("points", 0)
                    if stat.get("identifier") == "bonus":
                        bonus = stat.get("points", 0)
                    if stat.get("identifier") == "saves":
                        saves = stat.get("points", 0)
                    if stat.get("identifier") == "penalties_saved":
                        ps = stat.get("points", 0)
                    if stat.get("identifier") == "penalties_missed":
                        pm = stat.get("points", 0)
                    if stat.get("identifier") == "yellow_cards":
                        yc = stat.get("points", 0)
                    if stat.get("identifier") == "red_cards":
                        rc = stat.get("points", 0)

            # Add stats to player_info
            player_info[player_id]["minutes_points"] += minutes
            player_info[player_id]["clean_sheets_points"] += clean_sheets
            player_info[player_id]["assists_points"] += assists
            player_info[player_id]["goals_points"] += goals_scored
            player_info[player_id]["bonus_points"] += bonus
            player_info[player_id]["yellow_cards_points"] += yc
            player_info[player_id]["red_cards_points"] += rc
            player_info[player_id]["own_goals_points"] += og
            player_info[player_id]["save_points"] += saves
            player_info[player_id]["penalties_saved_points"] += ps
            player_info[player_id]["penalties_missed_points"] += pm
            player_info[player_id]["goals_conceded_points"] += gc

    return player_info
