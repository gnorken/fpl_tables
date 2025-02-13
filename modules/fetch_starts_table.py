import requests

FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


# And the for starts table


def get_player_data_starts(static_data):

    # Import stuff from static_data function
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Create a dictionary for quick player lookup by id
    player_info = {
        player["id"]: {
            # team-id stats
            "element_type": player["element_type"],

            "photo": player["photo"].replace(".jpg", ".png"),
            "team_code": player["team_code"],
            "team_name": next((team["short_name"] for team in teams if team["code"] == player["team_code"]), "N/A"),
            "web_name": player["web_name"],

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

            "starts": player["starts"],
            "minutes": player["minutes"],
            "clean_sheets": player["clean_sheets"],
            "yellow_cards": player["yellow_cards"],
            "red_cards": player["red_cards"],
            "dreamteam_count": player["dreamteam_count"],
            "own_goals": player["own_goals"],
            "bps": player["bps"],
            "goals_conceded": player["goals_conceded"],
            "penalties_saved": player["penalties_saved"],
            "penalties_missed": player["penalties_missed"],
        }
        for player in players
    }
    return player_info


# Step 2: Get current gameweek. get_live_data(gw) function
def get_live_data_starts(team_id, player_info, static_data):
    # static_data = get_static_data()
    events = static_data["events"]
    current_gw = next((event["id"]
                      for event in events if event["is_current"]), 1)

    # Step 3: Loop through gameweeks
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
                    starts = element["stats"]["starts"]
                    minutes = element["stats"]["minutes"]
                    cs = element["stats"]["clean_sheets"]
                    yc = element["stats"]["yellow_cards"]
                    rc = element["stats"]["red_cards"]
                    dt = element["stats"]["in_dreamteam"]
                    bps = element["stats"]["bps"]
                    og = element["stats"]["own_goals"]
                    ps = element["stats"]["penalties_saved"]
                    pm = element["stats"]["penalties_missed"]
                    gc = element["stats"]["goals_conceded"]

                    # Benched player
                    if multiplier == 0:
                        player_info[player_id]["starts_benched_team"] += 1
                        player_info[player_id]["minutes_benched_team"] += minutes

                    # Playing or playing as captain
                    if multiplier in [1, 2]:
                        player_info[player_id]["starts_team"] += starts
                        player_info[player_id]["minutes_team"] += minutes
                        player_info[player_id]["clean_sheets_team"] += cs
                        player_info[player_id]["yellow_cards_team"] += yc
                        player_info[player_id]["red_cards_team"] += rc
                        player_info[player_id]["bps_team"] += bps
                        player_info[player_id]["own_goals_team"] += og
                        player_info[player_id]["penalties_saved_team"] += ps
                        player_info[player_id]["penalties_missed_team"] += pm
                        player_info[player_id]["goals_conceded_team"] += gc

                    if dt:
                        player_info[player_id]["dreamteam_count_team"] += 1

                    # Playing as captain or triple captain
                    if multiplier in [2, 3]:
                        player_info[player_id]["captained_team"] += 1

                    break  # Stop searching for this player

    return player_info
