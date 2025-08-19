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
    Filter and sort players. Compute price_range BEFORE applying price filters.
    """
    table = request_args.get("table", "summary")

    if table in ["summary", "defence", "offence", "points"]:
        player_info = merge_team_and_global(global_info, team_info)
    else:
        player_info = global_info

    default_sort_by = {
        "summary": "total_points_team",
        "defence": "starts_team",
        "offence": "goals_scored_team",
        "points": "minutes_points_team",
        "talisman": "total_points",
        "teams": "total_points",
    }.get(table, "goals_scored_team")

    sort_by = request_args.get("sort_by", default_sort_by)
    order = request_args.get("order", "desc")
    selected_positions = request_args.get("selected_positions", "")
    min_cost = request_args.get(
        "min_cost", type=float)  # £ units (may be None)
    max_cost = request_args.get("max_cost", type=float)
    min_minutes = int(request_args.get("min_minutes", 0))
    max_minutes = int(request_args.get("max_minutes", 38 * 90))

    # ---------------- 1) Pre-price filtering (positions + minutes only) ----------------
    pre_price = []
    for p in player_info.values():
        pos_ok = (not selected_positions or str(
            p.get("element_type")) in selected_positions)
        min_ok = (min_minutes <= p.get("minutes", 0) <= max_minutes)
        if pos_ok and min_ok:
            pre_price.append(p)

    # ---------------- 2) price_range from pre_price (in tenths, like now_cost) --------
    all_costs = [p.get("now_cost")
                 for p in pre_price if p.get("now_cost") is not None]
    price_range = {
        "min": min(all_costs) if all_costs else None,
        "max": max(all_costs) if all_costs else None,
    }

    # ---------------- 3) Apply price filter (convert £ to tenths) ----------------------
    players = pre_price
    if min_cost is not None:
        thr = int(min_cost * 10)
        players = [p for p in players if p.get("now_cost", 0) >= thr]
    if max_cost is not None:
        thr = int(max_cost * 10)
        players = [p for p in players if p.get("now_cost", 0) <= thr]

    # ---------------- 4) Column-based inclusion filter -------------------------------
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

    if sort_by in negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0)) < 0]
    elif sort_by in positive_and_negative_columns:
        players = [p for p in players if float(p.get(sort_by, 0))]
    else:
        players = [p for p in players if float(p.get(sort_by, 0)) > 0]

    # ---------------- 5) Sort ----------------------------------------------------------
    reverse_order = (order == "desc")
    if sort_by in negative_columns:
        players = sorted(players, key=lambda x: x.get(
            sort_by, 0), reverse=not reverse_order)
    else:
        players = sorted(players, key=lambda x: float(
            x.get(sort_by, 0)), reverse=reverse_order)

    # ---------------- 6) Truncate & images --------------------------------------------
    is_truncated = False
    if table in ["summary", "defence", "offence", "points"]:
        is_truncated = len(players) > 100
        players = players[:100]

    players_images = [{"photo": p.get("photo"), "team_code": p.get(
        "team_code")} for p in players[:5]]

    return players, players_images, is_truncated, price_range

# Sort for simple tables. I use it for graph/tables combo on manager page


def sort_table_data(data, sort_by, order, allowed_fields):
    if sort_by in allowed_fields:
        reverse = (order.lower() == 'desc')
        return sorted(data, key=lambda row: row.get(sort_by, 0), reverse=reverse)
    return data
