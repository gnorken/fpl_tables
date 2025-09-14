import requests
import json

FPL_API_BASE = "https://fantasy.premierleague.com/api"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.11; rv:40.0) Gecko/20100101 Firefox/40.0",
    "Accept-Encoding": "gzip"
}


def aggregate_team_stats(player_info):
    teams_data = {}
    for player in player_info.values():
        team_code = player.get("team_code")
        team_name = player.get("team_name", "N/A")

        # Initialize the team's stats if not already present
        if team_code not in teams_data:
            teams_data[team_code] = {
                "photo": "p438098.png",
                "team_code": team_code,
                "team_name": team_name,
                "starts_team": 0,
                "minutes_team": 0,
                "clean_sheets_team": 0,
                "assists_team": 0,
                "expected_assists_team": 0,
                "goals_scored_team": 0,
                "expected_goals_team": 0,

                "captained_team": 0,
                "yellow_cards_team": 0,
                "red_cards_team": 0,
                "bps_team": 0,
                "bonus_team": 0,
                "dreamteam_count_team": 0,
                "starts_benched_team": 0,
                "minutes_benched_team": 0,
                "own_goals_team": 0,
                "goals_conceded_team": 0,
                "penalties_saved_team": 0,
                "penalties_missed_team": 0,

                "starts": 0,
                "minutes": 0,
                "clean_sheets": 0,
                "assists": 0,
                "expected_assists": 0,
                "goals_scored": 0,
                "expected_goals": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "bps": 0,
                "bonus": 0,
                "dreamteam_count": 0,
                "starts_benched": 0,
                "minutes_benched": 0,
                "own_goals": 0,
                "goals_conceded": 0,
                "penalties_saved": 0,
                "penalties_missed": 0,
            }

        # Aggregate each player's stats into the team's totals
        # Fantasy teams
        teams_data[team_code]["starts_team"] += player.get("starts_team", 0)
        teams_data[team_code]["minutes_team"] += player.get("minutes_team", 0)
        teams_data[team_code]["clean_sheets_team"] += player.get(
            "clean_sheets_team", 0)
        teams_data[team_code]["assists_team"] += player.get(
            "assists_team", 0)
        teams_data[team_code]["expected_assists_team"] += player.get(
            "expected_assists_team", 0)
        teams_data[team_code]["goals_scored_team"] += player.get(
            "goals_scored_team", 0)
        teams_data[team_code]["expected_goals_team"] += player.get(
            "expected_goals_team", 0)
        teams_data[team_code]["captained_team"] += player.get(
            "captained_team", 0)
        teams_data[team_code]["yellow_cards_team"] += player.get(
            "yellow_cards_team", 0)
        teams_data[team_code]["red_cards_team"] += player.get(
            "red_cards_team", 0)
        teams_data[team_code]["bps_team"] += player.get("bps_team", 0)
        teams_data[team_code]["bonus"] += player.get("bonus_team", 0)
        teams_data[team_code]["dreamteam_count_team"] += player.get(
            "dreamteam_count_team", 0)
        teams_data[team_code]["starts_benched_team"] += player.get(
            "starts_benched_team", 0)
        teams_data[team_code]["minutes_benched_team"] += player.get(
            "minutes_benched_team", 0)
        teams_data[team_code]["own_goals_team"] += player.get(
            "own_goals_team", 0)
        teams_data[team_code]["goals_conceded_team"] += player.get(
            "goals_conceded_team", 0)
        teams_data[team_code]["penalties_saved_team"] += player.get(
            "penalties_saved_team", 0)
        teams_data[team_code]["penalties_missed_team"] += player.get(
            "penalties_missed_team", 0)

        # Totals
        teams_data[team_code]["starts"] += player.get("starts", 0)
        teams_data[team_code]["minutes"] += player.get("minutes", 0)
        teams_data[team_code]["clean_sheets"] += player.get("clean_sheets", 0)
        teams_data[team_code]["assists"] += player.get("assists", 0)
        teams_data[team_code]["expected_assists"] += float(
            player.get("expected_assists", 0) or 0.0)

        teams_data[team_code]["goals_scored"] += player.get("goals_scored", 0)
        teams_data[team_code]["expected_goals"] += float(
            player.get("expected_goals", 0) or 0.0)

        teams_data[team_code]["yellow_cards"] += player.get("yellow_cards", 0)
        teams_data[team_code]["red_cards"] += player.get("red_cards", 0)
        teams_data[team_code]["bps"] += player.get("bps", 0)
        teams_data[team_code]["bonus"] += player.get("bonus", 0)
        teams_data[team_code]["dreamteam_count"] += player.get(
            "dreamteam_count", 0)
        teams_data[team_code]["own_goals"] += player.get("own_goals", 0)
        teams_data[team_code]["goals_conceded"] += player.get(
            "goals_conceded", 0)
        teams_data[team_code]["penalties_saved"] += player.get(
            "penalties_saved", 0)
        teams_data[team_code]["penalties_missed"] += player.get(
            "penalties_missed", 0)

    return teams_data
