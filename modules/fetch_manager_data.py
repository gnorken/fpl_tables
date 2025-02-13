import requests
import sqlite3

FPL_API_BASE = "https://fantasy.premierleague.com/api"

def get_manager_data(team_id):
    # Fetch FPL Manager data
    manager_url = f"{FPL_API_BASE}/entry/{team_id}/"
    manager_response = requests.get(manager_url)
    manager_data = manager_response.json()

    # Extract manager details
    manager = {
        "first_name": manager_data["player_first_name"],
        "last_name": manager_data["player_last_name"],
        "team_name": manager_data["name"],
        "country_code": manager_data["player_region_iso_code_short"]
    }

    # The flagCDN didn't support Scotland, Northern Ireland and Wales....
    if manager["country_code"] in ["S1", "EN", "WA", "NN"]:
        manager["country_code"] = "GB"

    # Connect to the database
    conn = sqlite3.connect("page_views.db")
    cursor = conn.cursor()

    # Check if the manager already exists in the table
    cursor.execute(
        """
        SELECT id FROM managers WHERE first_name = ? AND last_name = ? AND team_name = ?
        """,
        (manager["first_name"], manager["last_name"], manager["team_name"])
    )

    # If the manager doesn't exist, insert the data
    if not cursor.fetchone():
        cursor.execute(
            """
            INSERT INTO managers (first_name, last_name, team_name, team_id, country_code)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                manager["first_name"],
                manager["last_name"],
                manager["team_name"],
                team_id,
                manager["country_code"]
            )
        )
        conn.commit()

    conn.close()

    return manager
