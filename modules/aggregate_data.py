# Merging static totals from player_info with team-specific data from team_player_info SQL table
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
    Merge global and team-specific player info, then filter and sort players.
    """
    # 1️⃣ Merge team_info with global_info (ensures missing players get zeros)
    player_info = merge_team_and_global(global_info, team_info)

    # 2️⃣ Determine which table is being sorted
    table = request_args.get("table", "goals_scored_team")

    # 3️⃣ Set default sort_by based on the table
    default_sort_by = {
        "defence": "starts_team",
        "offence": "goals_scored_team",
        "points": "minutes_points_team",
        "am": "total_points",
        "talisman": "total_points",
    }.get(table, "goals_scored_team")

    # 4️⃣ Get sorting and filter parameters
    sort_by = request_args.get("sort_by", default_sort_by)
    order = request_args.get("order", "desc")
    selected_positions = request_args.get("selected_positions", "")

    # Cost filter (convert from UI cost to API cost format)
    min_cost = float(request_args.get("min_cost", 0)) * 10
    max_cost = float(request_args.get("max_cost", 20)) * 10

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

    # 5️⃣ Apply filters
    players = [
        p for p in player_info.values()
        if (not min_cost or not max_cost or min_cost <= p["now_cost"] <= max_cost)
        and (not selected_positions or str(p['element_type']) in selected_positions)
    ]

    if sort_by in negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0)) < 0]
    elif sort_by in positive_and_negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0))]
    else:
        players = [p for p in players if float(p.get(sort_by, 0)) > 0]

    # 6️⃣ Sort
    reverse_order = order == "desc"
    if sort_by in negative_columns:
        players = sorted(
            players, key=lambda x: x[sort_by], reverse=not reverse_order)
    else:
        players = sorted(players, key=lambda x: float(
            x[sort_by]), reverse=reverse_order)

    # 7️⃣ Return players and top 5 images
    players_images = [{"photo": player["photo"], "team_code": player["team_code"]}
                      for player in players[:5]]

    return players, players_images


# Sort for simple tables. I use it for graph/tabls combo on manager page
def sort_table_data(data, sort_by, order, allowed_fields):
    if sort_by in allowed_fields:
        reverse = (order.lower() == 'desc')
        return sorted(data, key=lambda row: row.get(sort_by, 0), reverse=reverse)
    return data
