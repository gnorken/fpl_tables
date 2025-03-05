import requests
import sqlite3

FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


def get_manager_data(team_id):
    # Fetch FPL Manager data
    manager_url = f"{FPL_API_BASE}/entry/{team_id}/"
    manager_response = requests.get(manager_url, headers=headers)
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


DEFAULT_PHOTO = "Photo-Missing"


def get_manager_history(team_id):
    history_url = f"{FPL_API_BASE}/entry/{team_id}/history/"
    history_response = requests.get(history_url, headers=headers)
    history_data = history_response.json()

    # Expanded chip usage state with the simplified assistant manager ("am")
    chips_state = {
        "wildcard_1": {"used": False, "gw": None},
        "wildcard_2": {"used": False, "gw": None},
        "freehit": {"used": False, "gw": None},
        "bboost": {
            "used": False,
            "gw": None,
            "total_points": 0,
            "players": [
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None}
            ]
        },
        "3xc": {"used": False, "gw": None, "total_points": 0, "photo": DEFAULT_PHOTO, "web_name": None, "team_code": None},
        "am": {
            "used": False,
            "gw": None,
            "total_points": 0,
            "events": [],
            "managers": [
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None},
                {"photo": DEFAULT_PHOTO, "total_points": 0,
                    "web_name": None, "team_code": None}
            ]
        },
    }

    chips_list = history_data.get("chips", [])
    for chip in chips_list:
        chip_name = chip.get("name")
        event = chip.get("event", 0)
        if chip_name == "wildcard":
            if 2 <= event <= 19:
                chips_state["wildcard_1"]["used"] = True
                chips_state["wildcard_1"]["gw"] = event
            elif 20 <= event <= 38:
                chips_state["wildcard_2"]["used"] = True
                chips_state["wildcard_2"]["gw"] = event
        elif chip_name == "3xc":
            chips_state["3xc"]["used"] = True
            chips_state["3xc"]["gw"] = event
        elif chip_name == "bboost":
            chips_state["bboost"]["used"] = True
            chips_state["bboost"]["gw"] = event
        # This chip now corresponds to the assistant manager ("am")
        elif chip_name == "manager":
            chips_state["am"]["used"] = True
            chips_state["am"]["gw"] = event

    # Fetch bootstrap static data once for use in all lookups.
    bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    bootstrap_response = requests.get(bootstrap_url, headers=headers)
    bootstrap_data = bootstrap_response.json()

    # -----------------------------
    # Process Triple Captain (3xc)
    # -----------------------------
    if chips_state["3xc"]["used"] and chips_state["3xc"]["gw"]:
        event_number = chips_state["3xc"]["gw"]

        # Fetch picks for the event.
        picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
        picks_response = requests.get(picks_url, headers=headers)
        picks_data = picks_response.json()

        # Find the captain's pick.
        captain_element = None
        for pick in picks_data.get("picks", []):
            if pick.get("is_captain"):
                captain_element = pick.get("element")
                break

        if captain_element is not None:
            # Fetch live data for the event.
            live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
            live_response = requests.get(live_url, headers=headers)
            live_data = live_response.json()

            for element in live_data.get("elements", []):
                if element.get("id") == captain_element:
                    stats = element.get("stats", {})
                    chips_state["3xc"]["total_points"] = stats.get(
                        "total_points", 0)
                    # Retrieve the captain's photo from bootstrap data and convert extension.
                    for player in bootstrap_data.get("elements", []):
                        if player.get("id") == captain_element:
                            chips_state["3xc"]['web_name'] = player.get(
                                "web_name")
                            chips_state["3xc"]["team_code"] = player.get(
                                "team_code")
                            photo = player.get("photo", "")
                            if photo:
                                # Ensure the photo string has a "p" prefix, then convert the extension.
                                if not photo.startswith("p"):
                                    photo = "p" + photo
                                chips_state["3xc"]["photo"] = photo.replace(
                                    ".jpg", "")
                            else:
                                chips_state["3xc"]["photo"] = DEFAULT_PHOTO
                            break
                    break

    # -----------------------------
    # Process Bench Boost (bboost)
    # -----------------------------
    if chips_state["bboost"]["used"] and chips_state["bboost"]["gw"]:
        event_number = chips_state["bboost"]["gw"]

        # Fetch picks for the bench boost event.
        picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
        picks_response = requests.get(picks_url, headers=headers)
        picks_data = picks_response.json()

        # Get the four bench players based on their positions (12, 13, 14, 15).
        bench_players = [pick for pick in picks_data.get(
            "picks", []) if pick.get("position") in [12, 13, 14, 15]]
        bench_players = sorted(bench_players, key=lambda p: p.get("position"))

        # Fetch live data for the event.
        live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
        live_response = requests.get(live_url, headers=headers)
        live_data = live_response.json()

        # Create a mapping of element IDs to their total points.
        live_points = {
            element.get("id"): element.get("stats", {}).get("total_points", 0)
            for element in live_data.get("elements", [])
        }

        # Update bench boost players info.
        for idx, bench_pick in enumerate(bench_players):
            element_id = bench_pick.get("element")
            points = live_points.get(element_id, 0)
            photo = DEFAULT_PHOTO
            web_name = ""  # Initialize web_name
            for player in bootstrap_data.get("elements", []):
                if player.get("id") == element_id:
                    # Update photo
                    candidate = player.get("photo", "")
                    if candidate:
                        if not candidate.startswith("p"):
                            candidate = "p" + candidate
                        photo = candidate.replace(".jpg", "")
                    # Get web_name from the player data
                    web_name = player.get("web_name", "")
                    team_code = player.get("team_code", "")
                    break
            if idx < 4:  # Only update the four expected players.
                chips_state["bboost"]["players"][idx]["total_points"] = points
                chips_state["bboost"]["players"][idx]["photo"] = photo
                chips_state["bboost"]["players"][idx]["web_name"] = web_name
                chips_state["bboost"]["players"][idx]["team_code"] = team_code
                chips_state["bboost"]["total_points"] += points

    # -----------------------------
    # Process Assistant Manager (am)
    # -----------------------------
    # The assistant manager is identified by picks with element_type == 5 and spans three consecutive gameweeks.
    if chips_state["am"]["used"] and chips_state["am"]["gw"]:
        start_event = chips_state["am"]["gw"]
        am_total = 0
        events_list = []
        managers_list = []
        # Process three consecutive gameweeks.
        for event_number in range(start_event, start_event + 3):
            picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
            picks_response = requests.get(picks_url, headers=headers)
            picks_data = picks_response.json()

            assistant_element = None
            # Find the assistant manager by element_type == 5.
            for pick in picks_data.get("picks", []):
                if pick.get("element_type") == 5:
                    assistant_element = pick.get("element")
                    break

            points = 0
            photo = DEFAULT_PHOTO
            web_name = None
            team_code = None

            if assistant_element is not None:
                # Fetch live data for this event.
                live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
                live_response = requests.get(live_url, headers=headers)
                live_data = live_response.json()

                for element in live_data.get("elements", []):
                    if element.get("id") == assistant_element:
                        points = element.get("stats", {}).get(
                            "total_points", 0)
                        break

                # Get photo and web_name from bootstrap data.
                for player in bootstrap_data.get("elements", []):
                    if player.get("id") == assistant_element:
                        team_code = player.get("team_code")
                        candidate = player.get("opta_code", "")
                        if candidate:
                            photo = candidate.replace(".jpg", ".png")
                        web_name = player.get("web_name")
                        break

            events_list.append(event_number)
            am_total += points
            managers_list.append(
                {"photo": photo, "total_points": points, "web_name": web_name, "team_code": team_code})

        chips_state["am"]["events"] = events_list
        chips_state["am"]["managers"] = managers_list
        chips_state["am"]["total_points"] = am_total

    return chips_state
