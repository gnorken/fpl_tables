import requests
from datetime import datetime


def days_since_joined(date_str):
    date_joined = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = datetime.today().date()
    return (today - date_joined).days


FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


# Get player data and create a lookup dict for the keys I want.
def get_player_data_am(static_data):

    # Import stuff from static_data function
    teams = static_data.get("teams", [])
    players = static_data.get("elements", [])

    # Create a dictionary for quick player lookup by id
    player_info = {
        player["id"]: {
            # team-id stats
            "element_type": player["element_type"],
            "photo": player["opta_code"] + ".png",
            "team_code": player["team_code"],
            "team_name": next((team["short_name"] for team in teams if team["code"] == player["team_code"]), "N/A"),
            "web_name": player["web_name"],
            "now_cost": player["now_cost"],

            # Player totals
            "selected_by_percent": player["selected_by_percent"],
            "form": player["form"],
            "total_points": player["total_points"],
            "mng_win": player["mng_win"],
            "mng_draw": player["mng_draw"],
            "mng_loss": player["mng_loss"],
            "mng_underdog_win": player["mng_underdog_win"],
            "mng_underdog_draw": player["mng_underdog_draw"],
            "mng_clean_sheets": player["mng_clean_sheets"],
            "mng_goals_scored": player["mng_goals_scored"],
            "code": player["code"],
            "ep_next": player["ep_next"],
            "ep_this": player["ep_this"],
            "event_points": player["event_points"],
            "transfers_in": player["transfers_in"],
            "transfers_in_event": player["transfers_in_event"],
            "transfers_out": player["transfers_out"],
            "transfers_out_event": player["transfers_out_event"],
            "value_form": player["value_form"],
            "team_join_date": days_since_joined(player["team_join_date"]),
            "birth_date": player["birth_date"],
            "opta_code": player["opta_code"],
        }
        for player in players if player["element_type"] == 5
    }
    print("---start---")
    print(f"player_info: {player_info}")
    print("---slutt---")
    return player_info
