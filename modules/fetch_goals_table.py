import requests

FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


# Get player data and create a lookup dict for the keys I want.
def get_player_data_goals(static_data):

    # Import stuff from static_data function
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Create a dictionary for quick player lookup by id
    player_info = {
        player["id"]: {
            # team-id stats
            "photo": "p" + player["photo"].replace(".jpg", ".png"),

            "team_code": player["team_code"],
            "team_name": next((team["short_name"] for team in teams if team["code"] == player["team_code"]), "N/A"),
            "web_name": player["web_name"],

            # Team stats
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
            "goals_assists_performance_team_vs_total": 0,

            # Player totals
            "goals_scored": player["goals_scored"],
            "expected_goals": round(float(player["expected_goals"]), 2),
            "goals_performance": round(float(player["goals_scored"]) - float(player["expected_goals"]), 2),
            "assists": player["assists"],
            "expected_assists": round(float(player["expected_assists"]), 2),
            "assists_performance": round(float(player["assists"] - float(player["expected_assists"])), 1),
            "goals_assists": int(player["goals_scored"]) + int(player["assists"]),
            "expected_goal_involvements": round(float(player["expected_goal_involvements"]), 2),
            "goals_assists_performance": round(float(player["goals_scored"]) + float(player["assists"]) - float(player["expected_goal_involvements"]), 2),

            "element_type": player["element_type"],
            "now_cost": player["now_cost"],
        }

        for player in players
    }
    return player_info

# Get current gameweek. get_live_data(gw) function


def get_live_data_goals(team_id, player_info, static_data):
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
                    assists = element["stats"]["assists"]
                    expected_goals = element["stats"]["expected_goals"]
                    expected_assists = element["stats"]["expected_assists"]
                    goals_scored = element["stats"]["goals_scored"]

                    # Benched
                    if multiplier == 0:
                        player_info[player_id]["assists_benched_team"] += assists
                        player_info[player_id]["goals_benched_team"] += goals_scored

                    # Playing
                    if multiplier in [1, 2, 3]:
                        player_info[player_id]["expected_assists_team"] += float(
                            expected_assists)
                        player_info[player_id]["expected_assists_team"] = round(
                            # Round to one decimals
                            player_info[player_id]["expected_assists_team"], 2)
                        player_info[player_id]["expected_goals_team"] += float(
                            expected_goals)
                        player_info[player_id]["expected_goals_team"] = round(
                            # Round to one decimals
                            player_info[player_id]["expected_goals_team"], 2)
                        player_info[player_id]["goals_scored_team"] += goals_scored
                        player_info[player_id]["goals_assists_team"] += goals_scored
                        player_info[player_id]["assists_team"] += assists
                        player_info[player_id]["goals_assists_team"] += assists
                        player_info[player_id]["goals_performance_team"] = round(float(
                            player_info[player_id]["goals_scored_team"]) - float(player_info[player_id]["expected_goals_team"]), 2)
                        player_info[player_id]["assists_performance_team"] = round(float(
                            player_info[player_id]["assists_team"]) - float(player_info[player_id]["expected_assists_team"]), 2)
                        player_info[player_id]["expected_goal_involvements_team"] = round(
                            player_info[player_id]["expected_goals_team"] + player_info[player_id]["expected_assists_team"], 2)
                        player_info[player_id]["goals_assists_performance_team"] = round(float(
                            player_info[player_id]["goals_assists_team"]) - float(player_info[player_id]["expected_goal_involvements_team"]), 2)
                        player_info[player_id]["goals_assists_performance_team_vs_total"] = player_info[player_id][
                            "goals_assists_performance_team"] - player_info[player_id]["goals_assists_performance"]

                    # Playing as captain or triple captain
                    if multiplier in [2, 3]:
                        player_info[player_id]["assists_captained_team"] += assists
                        player_info[player_id]["goals_captained_team"] += goals_scored

                        break  # Stop searching for this player
    return player_info
