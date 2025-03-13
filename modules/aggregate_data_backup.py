# Filter and sort top_scorers table
def filter_and_sort_players(player_info, request_args):
    players_filtered = {}

    # Determine which table is being sorted
    table = request_args.get("table", "goals_scored_team")

    # Set default sort_by based on the table
    default_sort_by = {
        "goals_scorers": "goals_scored_team",
        "starts": "starts_team",
        "points": "minutes_points_team",
    }.get(table, "goals_scored_team")

    # Sort by query parameters
    sort_by = request_args.get("sort_by", default_sort_by)
    order = request_args.get("order", "desc")
    selected_positions = request_args.get("selected_positions", "")

    # Get min/max cost from request, convert to API format (multiply by 10)
    min_cost = float(request_args.get("min_cost", 0)) * 10
    max_cost = float(request_args.get("max_cost", 20)) * 10

    print(f"Filtering by cost range: {min_cost} - {max_cost}")

    # Columns that need sorting for negative values
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

    # Filter players based on position, cost, and selected column
    players = [
        p for p in player_info.values()
        if (min_cost <= p["now_cost"] <= max_cost)  # Cost filter
        and str(p['element_type']) in selected_positions  # Position filter
    ]

    # Additional filtering based on the selected column
    if sort_by in negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0)) < 0]
    elif sort_by in positive_and_negative_columns:
        players = [p for p in players if float(p.get(sort_by))]
    else:
        players = [p for p in players if float(p.get(sort_by, 0)) > 0]

    # Apply sorting
    reverse_order = order == "desc"
    if sort_by in negative_columns:
        players = sorted(
            players, key=lambda x: x[sort_by], reverse=not reverse_order)
    else:
        players = sorted(players, key=lambda x: float(
            x[sort_by]), reverse=reverse_order)

    # Get the top 5 images by slicing and extract only the 'photo' values
    players_images = [{"photo": player["photo"]} for player in players[:5]]

    return players, players_images
