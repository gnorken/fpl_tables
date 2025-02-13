# Filter and sort top_scorers table
def filter_and_sort_players(player_info, request_args):
    players_filtered = {}
    # Determine which table is being sorted
    table = request_args.get("table", "goals_scored_team")  # Default to "goals" table IS THIS IN USE?

    # Set default sort_by based on the table
    default_sort_by = {
        "goals_scorers": "goals_scored_team",   # Default for "goals" table
        "starts": "starts_team",                # Default for "starts" table
        "points": "minutes_points_team",        # Default for "points" table
    }.get(table, "goals_scored_team")           # Fallback default if table is unrecognized #?

    # Sort by query parameters
    sort_by = request_args.get("sort_by", default_sort_by)
    order = request_args.get("order", "desc")
    selected_positions = request_args.get("selected_positions", "")
    print("selected_positions:", selected_positions)

    # Columns that need sorting for negative values
    negative_columns = {"points_pm_team",
                        "yellow_cards_points_team",
                        "yellow_cards_points",
                        "red_cards_points_team",
                        "red_cards_points",
                        "penalties_missed_points",
                        "penalties_missed_points_team",
                        "own_goals_points",
                        "own_goals_points_team",
                        "goals_conceded_points",
                        "goals_conceded_points_team",
                        }

    positive_and_negative_columns = {"goals_performance_team",
                                     "assists_performance_team",
                                     "goals_assists_performance_team",
                                     "goals_performance",
                                     "assists_performance",
                                     "goals_assists_performance",
                                     "goals_assists_performance_team_vs_total",
                                    "total_points",
                                    "starts_team",
                                    "total_points_team"}


    # Filter players dynamically based on the selected column
    if sort_by in negative_columns:
        players = [p for p in player_info.values() if float(p.get(sort_by, 0)) < 0 and str(p['element_type']) in selected_positions]
    elif sort_by in positive_and_negative_columns:
        players = [p for p in player_info.values() if float(p.get(sort_by)) and str(p['element_type']) in selected_positions]
    else:
        players = [p for p in player_info.values() if float(p.get(sort_by, 0)) > 0 and str(p['element_type']) in selected_positions]


    # Apply sorting to the filtered lists based on the sort_by and order parameters
    if sort_by in negative_columns: # For negativ columns. Most negative first for desc
        if order == "asc":
            players = sorted(players, key=lambda x: x[sort_by], reverse=True)
        else:
            players = sorted(players, key=lambda x: x[sort_by])
    else:
        if order == "asc":          # For positive, regular columns
            players = sorted(players, key=lambda x: float(x[sort_by]))
        else:
            players = sorted(players, key=lambda x: float(x[sort_by]), reverse=True)

    # Get the top 5 images by slicing and extract only the 'photo' values
    players_images = [{"photo": player["photo"]} for player in players[:5]]

    return players, players_images
