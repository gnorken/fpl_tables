import logging
from flask import session

logger = logging.getLogger(__name__)

# Merging static totals from player_info with team-specific data from team_player_info SQL tables


def merge_team_and_global(global_info, team_info):
    """
    Merge global player_info (totals) and team_info (team-specific stats).
    Ensures all players have all team_* keys even if never owned.
    """
    merged = {}

    # Collect all possible team-specific keys from team_info (dynamic)
    team_keys = set()
    for p in team_info.values():
        team_keys.update([k for k in p.keys() if k.endswith("_team")])

    for pid, global_player in global_info.items():
        # Start from the global player data
        merged_player = global_player.copy()

        # If player is in team_info, merge values, else default zeros
        if pid in team_info:
            for key in team_keys:
                merged_player[key] = team_info[pid].get(key, 0)
        else:
            # Default all team-specific keys to 0 for players never owned
            for key in team_keys:
                merged_player[key] = 0

        merged[pid] = merged_player

    return merged


# Merge global and team-specific player info, then filter and sort players.


def filter_and_sort_players(global_info, team_info, request_args):
    """
    Filter and sort players, merging global and team-specific info only for tables that need it.
    """
    # Determine table type
    table = request_args.get("table", "summary")

    # Conditionally merge based on table
    if table in ["summary", "defence", "offence", "points"]:
        player_info = merge_team_and_global(global_info, team_info)
    else:
        # For talisman and teams, use global_info directly (no team-specific data needed)
        player_info = global_info

    # Set default sort_by based on the table
    default_sort_by = {
        "summary": "total_points_team",
        "defence": "starts_team",
        "offence": "goals_scored_team",
        "points": "minutes_points_team",
        "talisman": "total_points",
        "teams": "total_points"  # Adjust if teams has a different default
    }.get(table, "goals_scored_team")

    # Get sorting and filter parameters
    sort_by = request_args.get("sort_by", default_sort_by)
    order = request_args.get("order", "desc")
    selected_positions = request_args.get("selected_positions", "")

    # Cost filter (convert from UI cost to API cost format)
    min_cost = float(request_args.get("min_cost", 0)) * 10
    max_cost = float(request_args.get("max_cost", 20)) * 10

    # Minutes filter
    min_minutes = int(request_args.get("min_minutes", 0))
    max_minutes = int(request_args.get("max_minutes", 38 * 90))

    # Columns to treat specially
    negative_columns = {
        "points_pm_team", "yellow_cards_points_team", "yellow_cards_points",
        "red_cards_points_team", "red_cards_points", "penalties_missed_points",
        "penalties_missed_points_team", "own_goals_points", "own_goals_points_team",
        "goals_conceded_points", "goals_conceded_points_team",
    }

    positive_and_negative_columns = {
        "goals_performance_team", "assists_performance_team", "goals_assists_performance_team",
        "goals_performance", "assists_performance", "goals_assists_performance",
        "goals_assists_performance_team_vs_total", "total_points",
        "starts_team", "total_points_team"
    }

    # Apply filters
    kept = []
    for p in player_info.values():
        # Cost, positions, and minutes filters
        cost_ok = (min_cost <= p["now_cost"] <= max_cost)
        pos_ok = (not selected_positions or str(
            p["element_type"]) in selected_positions)
        min_ok = (min_minutes <= p.get("minutes", 0) <= max_minutes)

        if cost_ok and pos_ok and min_ok:
            kept.append(p)

    players = kept

    # Filter based on sort_by column
    if sort_by in negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0)) < 0]
    elif sort_by in positive_and_negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0))]
    else:
        players = [p for p in players if float(p.get(sort_by, 0)) > 0]

    # Sort
    reverse_order = order == "desc"
    if sort_by in negative_columns:
        players = sorted(
            players, key=lambda x: x[sort_by], reverse=not reverse_order)
    else:
        players = sorted(players, key=lambda x: float(
            x[sort_by]), reverse=reverse_order)

    # Cap at 100 and set is_truncated for relevant tables
    is_truncated = False
    if table in ["summary", "defence", "offence", "points"]:
        is_truncated = len(players) > 100
        players = players[:100]

    # Return players and top 5 images
    players_images = [{"photo": player["photo"], "team_code": player["team_code"]}
                      for player in players[:5]]

    return players, players_images, is_truncated

# Sort for simple tables. I use it for graph/tables combo on manager page


def sort_table_data(data, sort_by, order, allowed_fields):
    if sort_by in allowed_fields:
        reverse = (order.lower() == 'desc')
        return sorted(data, key=lambda row: row.get(sort_by, 0), reverse=reverse)
    return data
