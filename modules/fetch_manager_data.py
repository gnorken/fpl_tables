from flask import url_for
from modules.utils import get_event_status_last_update, territory_icon
from datetime import datetime, timezone
import requests
import sqlite3
import json
from flask import session, url_for
from modules.utils import (territory_icon)


TOTAL_MANAGERS_BY_SEASON = {
    "2002/03": 76_284,
    "2003/04": 312_026,
    "2004/05": 472_251,
    "2005/06": 810_000,
    "2006/07": 1_270_000,
    "2007/08": 1_700_000,
    "2008/09": 1_950_000,
    "2009/10": 2_100_000,
    "2010/11": 2_350_000,
    "2011/12": 2_785_573,
    "2012/13": 2_610_000,
    "2013/14": 3_220_000,
    "2014/15": 3_500_000,
    "2015/16": 3_730_000,
    "2016/17": 4_500_000,
    "2017/18": 5_190_000,
    "2018/19": 6_320_000,
    "2019/20": 7_630_000,
    "2020/21": 8_150_000,
    "2021/22": 9_170_000,
    "2022/23": 11_450_000,
    "2023/24": 10_910_000,
    "2024/25": 11_431_930,
}


FPL_API_BASE = "https://fantasy.premierleague.com/api"
HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) "
    "Gecko/20100101 Firefox/40.0",
    "Accept":          "application/json",
    "Accept-Encoding": "gzip",
}


DB_PATH = "page_views.db"


FPL_API_BASE = "https://fantasy.premierleague.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) "
                  "Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip",
    "Accept": "application/json"
}
DB_PATH = "page_views.db"


def get_manager_data(team_id):
    """
    Fetch manager data and cache it as a single JSON blob in SQLite.
    Returns the cached data if it's already up-to-date based on event-status.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Ensure the table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS managers (
            team_id      INTEGER PRIMARY KEY,
            data         TEXT    NOT NULL,
            last_fetched TEXT    NOT NULL
        )
    """)
    conn.commit()

    # 1️⃣ Check cache
    cursor.execute(
        "SELECT data, last_fetched FROM managers WHERE team_id = ?", (team_id,))
    row = cursor.fetchone()
    if row:
        data, last_fetched = row
        cached_time = datetime.fromisoformat(last_fetched)
        event_updated = get_event_status_last_update()
        if cached_time >= event_updated:
            manager = json.loads(data)
            conn.close()
            return manager

    # 2️⃣ Cache miss or stale → fetch from API
    url = f"{FPL_API_BASE}/entry/{team_id}/"

    # **Print out everything that we know is about to go out**
    import platform
    import requests
    print("🔧 HEADERS constant:", HEADERS)
    print("🖥️ Python version:", platform.python_version(),
          "requests version:", requests.__version__)
    print("▶ REQUEST URL:", url)

    response = requests.get(url, headers=HEADERS)

    # **Dump exactly what actually went out**
    print("▶ ACTUAL REQUEST-URL:", response.request.url)
    print("▶ ACTUAL REQUEST-HEADERS:", dict(response.request.headers))

    # **And exactly what came back**
    print("◀ RESPONSE STATUS:", response.status_code)
    print("◀ RESPONSE HEADERS:", dict(response.headers))
    print(f"◀ RESPONSE BODY PREVIEW: {response.text[:200]!r}")

    # 2️⃣bis: Retry if HTML response
    content_type = response.headers.get("Content-Type", "")
    body = response.text.strip()
    if content_type.startswith("text/html") or body.startswith("<!DOCTYPE html>"):
        retry_url = url + "?"
        print(f"⚠️ Got HTML, retrying with URL: {retry_url}")
        response = requests.get(retry_url, headers=HEADERS)
        print("▶ RETRY REQUEST-URL:", response.request.url)
        print("▶ RETRY REQUEST-HEADERS:", dict(response.request.headers))
        print("◀ RETRY RESPONSE STATUS:", response.status_code)
        print("◀ RETRY RESPONSE HEADERS:", dict(response.headers))
        print(f"◀ RETRY RESPONSE BODY PREVIEW: {response.text[:200]!r}")

    # If still HTML, soft-fail
    content_type = response.headers.get("Content-Type", "")
    body = response.text.strip()
    if content_type.startswith("text/html") or body.startswith("<!DOCTYPE html>"):
        print(f"❌ Still HTML for team_id={team_id}, giving up.")
        conn.close()
        return None

    # 3️⃣ Parse JSON and upsert as before
    api_data = response.json()
    manager = {
        "first_name":      api_data.get("player_first_name"),
        "last_name":       api_data.get("player_last_name"),
        "team_name":       api_data.get("name"),
        "country_code":    api_data.get("player_region_iso_code_short", "").lower(),
        "classic_leagues": api_data.get("leagues", {}).get("classic", []),
        "flag_html":       territory_icon(api_data.get("player_region_iso_code_short", "")),
    }
    # build national_league_url…
    # upsert into DB…

    conn.commit()
    conn.close()
    return manager


DEFAULT_PHOTO = "Photo-Missing"


def get_manager_history(team_id):
    history_url = f"{FPL_API_BASE}/entry/{team_id}/history/"
    history_response = requests.get(history_url, headers=HEADERS)
    history_data = history_response.json()

    for season in history_data.get("past", []):
        tm = TOTAL_MANAGERS_BY_SEASON.get(season['season_name'])
        if tm:
            season['total_managers'] = tm
            raw_percentile = 100 * (season['rank'] / tm)

            if raw_percentile < 0.1:
                season['percentile'] = 0.1
            elif raw_percentile < 1:
                season['percentile'] = round(raw_percentile, 2)
            else:
                season['percentile'] = round(raw_percentile)

        else:
            season['total_managers'] = None
            season['percentile'] = None

    # Expanded chip usage state with the simplified assistant manager ("am")
    chips_state = {
        "wildcard_1": {"used": False, "gw": None},
        "wildcard_2": {"used": False, "gw": None},
        "freehit_1": {"used": False, "gw": None},
        "freehit_2": {"used": False, "gw": None},
        "bboost_1": {
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
        "bboost_2": {
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
        "3xc_1": {"used": False, "gw": None, "total_points": 0, "photo": DEFAULT_PHOTO, "web_name": None, "team_code": None},
        "3xc_2": {"used": False, "gw": None, "total_points": 0, "photo": DEFAULT_PHOTO, "web_name": None, "team_code": None},
    }

    chips_list = history_data.get("chips", [])
    for chip in chips_list:
        chip_name = chip.get("name")
        event = chip.get("event", 0)

        if chip_name == "bboost":
            if event <= 19:
                chips_state["bboost_1"]["used"] = True
                chips_state["bboost_1"]["gw"] = event
        elif event >= 20:
            chips_state["bboost_2"]["used"] = True
            chips_state["bboost_2"]["gw"] = event
        elif chip_name == "3xc":
            if event <= 19:
                chips_state["3xc_1"]["used"] = True
                chips_state["3xc_1"]["gw"] = event
            elif event >= 20:
                chips_state["3xc_2"]["used"] = True
                chips_state["3xc_2"]["gw"] = event
        elif chip_name == "freehit":
            if event <= 19:
                chips_state["freehit_1"]["used"] = True
                chips_state["freehit_1"]["gw"] = event
            elif event >= 20:
                chips_state["freehit_2"]["used"] = True
                chips_state["freehit_2"]["gw"] = event
        elif chip_name == "wildcard":
            if event <= 19:
                chips_state["wildcard_1"]["used"] = True
                chips_state["wildcard_1"]["gw"] = event
            elif event >= 20:
                chips_state["wildcard_2"]["used"] = True
                chips_state["wildcard_2"]["gw"] = event

    # Fetch bootstrap static data once for use in all lookups.
    bootstrap_url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    bootstrap_response = requests.get(bootstrap_url, headers=HEADERS)
    bootstrap_data = bootstrap_response.json()

    # -----------------------------
    # Process Triple Captains (3xc)
    # -----------------------------
    # Process 3xc_1 (GW1–19) and 3xc_2 (GW20–38) if used
    for suffix in ["_1", "_2"]:
        chip_key = f"3xc{suffix}"
        if chips_state[chip_key]["used"] and chips_state[chip_key]["gw"]:
            event_number = chips_state[chip_key]["gw"]

            # Fetch picks for the event.
            picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
            picks_response = requests.get(picks_url, headers=HEADERS)
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
                live_response = requests.get(live_url, headers=HEADERS)
                live_data = live_response.json()

                for element in live_data.get("elements", []):
                    if element.get("id") == captain_element:
                        stats = element.get("stats", {})
                        chips_state[chip_key]["total_points"] = stats.get(
                            "total_points", 0)
                        # Retrieve the captain's photo from bootstrap data and convert extension.
                        for player in bootstrap_data.get("elements", []):
                            if player.get("id") == captain_element:
                                chips_state[chip_key]['web_name'] = player.get(
                                    "web_name")
                                chips_state[chip_key]["team_code"] = player.get(
                                    "team_code")
                                photo = player.get("photo", "")
                                if photo:
                                    # Ensure the photo string has a "p" prefix, then convert the extension.
                                    if not photo.startswith("p"):
                                        photo = "p" + photo
                                    chips_state[chip_key]["photo"] = photo.replace(
                                        ".jpg", "")
                                else:
                                    chips_state[chip_key]["photo"] = DEFAULT_PHOTO
                                break
                        break

    # -----------------------------
    # Process Bench Boost (bboost)
    # -----------------------------

    for suffix in ["_1", "_2"]:
        chip_key = f"bboost{suffix}"
        if chips_state[chip_key]["used"] and chips_state[chip_key]["gw"]:
            event_number = chips_state[chip_key]["gw"]

            # Fetch picks for the bench boost event.
            picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
            picks_response = requests.get(picks_url, headers=HEADERS)
            picks_data = picks_response.json()

            # Get the four bench players based on their positions (12, 13, 14, 15).
            bench_players = [
                pick for pick in picks_data.get("picks", [])
                if pick.get("position") in [12, 13, 14, 15]
            ]
            bench_players = sorted(
                bench_players, key=lambda p: p.get("position"))

            # Fetch live data for the event.
            live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
            live_response = requests.get(live_url, headers=HEADERS)
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
                team_code = None

                for player in bootstrap_data.get("elements", []):
                    if player.get("id") == element_id:
                        # Update photo
                        candidate = player.get("photo", "")
                        if candidate:
                            if not candidate.startswith("p"):
                                candidate = "p" + candidate
                            photo = candidate.replace(".jpg", "")
                        # Get web_name and team_code
                        web_name = player.get("web_name", "")
                        team_code = player.get("team_code", "")
                        break

                if idx < 4:  # Only update the four expected players.
                    chips_state[chip_key]["players"][idx]["total_points"] = points
                    chips_state[chip_key]["players"][idx]["photo"] = photo
                    chips_state[chip_key]["players"][idx]["web_name"] = web_name
                    chips_state[chip_key]["players"][idx]["team_code"] = team_code
                    chips_state[chip_key]["total_points"] += points

    # # -----------------------------
    # # Process Assistant Manager (am)
    # # -----------------------------
    # # The assistant manager is identified by picks with element_type == 5 and spans three consecutive gameweeks.
    # if chips_state["am"]["used"] and chips_state["am"]["gw"]:
    #     start_event = chips_state["am"]["gw"]
    #     am_total = 0
    #     events_list = []
    #     managers_list = []
    #     # Process three consecutive gameweeks.
    #     for event_number in range(start_event, start_event + 3):
    #         picks_url = f"{FPL_API_BASE}/entry/{team_id}/event/{event_number}/picks/"
    #         picks_response = requests.get(picks_url, headers=HEADERS)
    #         picks_data = picks_response.json()

    #         assistant_element = None
    #         # Find the assistant manager by element_type == 5.
    #         for pick in picks_data.get("picks", []):
    #             if pick.get("element_type") == 5:
    #                 assistant_element = pick.get("element")
    #                 break

    #         points = 0
    #         photo = DEFAULT_PHOTO
    #         web_name = None
    #         team_code = None

    #         if assistant_element is not None:
    #             # Fetch live data for this event.
    #             live_url = f"{FPL_API_BASE}/event/{event_number}/live/"
    #             live_response = requests.get(live_url, headers=HEADERS)
    #             live_data = live_response.json()

    #             for element in live_data.get("elements", []):
    #                 if element.get("id") == assistant_element:
    #                     points = element.get("stats", {}).get(
    #                         "total_points", 0)
    #                     break

    #             # Get photo and web_name from bootstrap data.
    #             for player in bootstrap_data.get("elements", []):
    #                 if player.get("id") == assistant_element:
    #                     team_code = player.get("team_code")
    #                     candidate = player.get("opta_code", "")
    #                     if candidate:
    #                         photo = candidate.replace(".jpg", ".png")
    #                     web_name = player.get("web_name")
    #                     break

    #         events_list.append(event_number)
    #         am_total += points
    #         managers_list.append(
    #             {"photo": photo, "total_points": points, "web_name": web_name, "team_code": team_code})

    #     chips_state["am"]["events"] = events_list
    #     chips_state["am"]["managers"] = managers_list
    #     chips_state["am"]["total_points"] = am_total

    return {
        "chips_state": chips_state,
        "history": history_data
    }
