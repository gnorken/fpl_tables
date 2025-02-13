import requests
from flask import flash, request

FPL_API_BASE = "https://fantasy.premierleague.com/api"
FPL_STATIC_URL = f"{FPL_API_BASE}/bootstrap-static/"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


# Helper to validate team ID
def validate_team_id(team_id, max_users):
    try:
        team_id = int(team_id)  # Ensure team_id is an integer
        if 1 <= team_id <= max_users:
            # Test API to check if the game is being updated
            manager_url = f"{FPL_API_BASE}/entry/{team_id}/"
            manager_response = requests.get(manager_url)

            if manager_response.status_code == 503:
                flash(
                    "The game is currently being updated. Please try again later.", "warning")
                return None  # Return None to stop further processing

            manager_response.raise_for_status()  # Raise other HTTP errors
            return team_id  # Return valid team_id if no issues

        else:
            flash(f"Team ID must be between 1 and {max_users}", "error")
    except ValueError:
        flash("Invalid Team ID. Please enter a valid number.", "error")
    except requests.exceptions.RequestException as e:
        flash(f"An error occurred while validating the Team ID: {e}", "error")

    return None


# Helper to fetch `MAX_USERS`
def get_max_users():
    try:
        response = requests.get(FPL_STATIC_URL, headers=headers)
        response.raise_for_status()
        static_data = response.json()
        return static_data["total_players"]
    except requests.exceptions.RequestException:
        return 10994911  # Fallback value

# Helper to fetch current gameweek


def get_current_gw():
    static_data = get_static_data()
    events = static_data["events"]
    current_gw = next((event["id"]
                      for event in events if event["is_current"]), 1)
    return current_gw

# Fetch static player data


def get_static_data():
    static_url = FPL_STATIC_URL
    response = requests.get(static_url, headers=headers)
    response.raise_for_status()
    static_data = response.json()
    return static_data

# Fetch static Player’s Detailed Data


def get_player_detail_data():
    response = requests.get(
        f"https://fantasy.premierleague.com/api/element-summary/", headers=headers)
    response.raise_for_status()
    player_detail_data = response.json()
    return player_detail_data
