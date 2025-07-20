import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# fetch_mini_leagues.py

FPL_API = "https://fantasy.premierleague.com/api"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


SPECIAL_FLAGS = {
    "en": "gb-eng",         # England
    "s1": "gb-sct",         # Scotland
    "wa": "gb-wls",         # Wales
    "nn": "gb-nir",         # Northern Ireland
}


# Get the current team, why is the benched points are not implementet yet
def get_entry_history(entry_id: int) -> list[dict]:
    url = f"{FPL_API}/entry/{entry_id}/history/"
    resp = SESSION.get(url)
    if not resp.ok:
        return {"chips": [], "bench_points": 0, "transfer_cost": 0}

    data = resp.json()
    # 1) raw chip list
    chips = [
        {"name": c.get("name"), "event": c.get("event")}
        for c in data.get("chips", [])
    ]

    # 2) sum the two per-GW fields
    bench_points = sum(ev.get("points_on_bench", 0)
                       for ev in data.get("current", []))
    transfer_cost = sum(ev.get("event_transfers_cost", 0)
                        for ev in data.get("current", []))

    return {
        "chips":           chips,
        "bench_points":    bench_points,
        "transfer_cost":   transfer_cost,
    }

# Create the dict which will be sent as JSON to frontend


def build_manager(me: dict, league_entry: dict | None = None) -> dict:
    """
    Map raw `/entry/{id}/` JSON + optional classic-league slice to our fields.
    """
    raw = me.get("player_region_iso_code_short", "").strip().lower()
    country_code = SPECIAL_FLAGS.get(raw, raw)

    base = {
        "entry":               me.get("id", me.get("entry")),
        "entry_name":          me.get("entry_name", ""),
        "country_code":        country_code,
        "player_region_iso_code_long": me.get("player_region_iso_code_long", "N/A"),
        "team_name":           me.get("name", ""),
        "last_deadline_bank":  me.get("last_deadline_bank") or 0,
        "last_deadline_total_transfers": me.get("last_deadline_total_transfers") or 0,
        "last_deadline_value": me.get("last_deadline_value") or 0,
        "overall_rank":        me.get("summary_overall_rank", 0),
        "player_name":         f"{me.get('player_first_name', '')} {me.get('player_last_name', '')}".strip(),
        "total_points":        me.get("summary_overall_points", 0),
        "years_active":        me.get("years_active") or 0,
    }

    if league_entry:
        base.update({
            "rank":      league_entry.get("entry_rank",
                                          league_entry.get("rank", 0)),
            "last_rank": league_entry.get("entry_last_rank",
                                          league_entry.get("last_rank", 0)),
        })

    # now fetch the chip history; this will be [] if none were played
    history = get_entry_history(base["entry"])
    base["chips"] = history["chips"]
    base["bench_points"] = history["bench_points"]
    base["transfer_cost"] = history["transfer_cost"]

    # ─── Flatten the chips array into individual GW fields ───
    # collect all events for each chip type
    chip_events: dict[str, list[int]] = {}
    for c in base["chips"]:
        chip_events.setdefault(c["name"], []).append(c["event"])

    # wildcard1_gw and wildcard2_gw
    wcs = chip_events.get("wildcard", [])
    base["wildcard1_gw"] = wcs[0] if len(wcs) > 0 else 0
    base["wildcard2_gw"] = wcs[1] if len(wcs) > 1 else 0

    # for the single‐use chips, just take the first (or None)
    for chip_name in ("3xc", "bboost", "freehit", "manager"):
        events = chip_events.get(chip_name, [])
        base[f"{chip_name}_gw"] = events[0] if events else 0

    return base

# Get the league name. (Suprised I needed a separate call for this)


def get_league_name(league_id: int) -> str:
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = SESSION.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("league", {}).get("name", f"League {league_id}")

# Get all the team ids and uses build_manager() to create dicts


def get_team_ids_from_league(league_id: int, max_show: int) -> list[dict]:
    """Fetch standings and return list of manager dicts."""
    url = f"{FPL_API}/leagues-classic/{league_id}/standings/"
    resp = SESSION.get(url)
    resp.raise_for_status()
    standings = resp.json().get("standings", {}).get("results", [])[:max_show]

    managers = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_entry = {
            executor.submit(SESSION.get, f"{FPL_API}/entry/{m['entry']}/"): m
            for m in standings
        }
        for fut in as_completed(future_to_entry):
            m = future_to_entry[fut]
            try:
                me = fut.result().json()
            except Exception:
                continue
            managers.append(build_manager(me, league_entry=m))

    return managers

# If the current manager is not wihtin maxShow, go get it and append to list of managers


def append_current_manager(managers: list[dict], team_id: int, league_id: int, logger=None) -> None:
    """
    If `team_id` not in managers, fetch and append.
    """
    if team_id and not any(m["entry"] == team_id for m in managers):
        resp = SESSION.get(f"{FPL_API}/entry/{team_id}/")
        if not resp.ok:
            return
        me = resp.json()
        for cl in me.get("leagues", {}).get("classic", []):
            if cl.get("id") == league_id:
                managers.append(build_manager(me, league_entry=cl))
                if logger:
                    logger.debug(
                        f"[mini] appended manager {team_id} (rank {cl.get('entry_rank')})")
                break

# Go thru all the gameweeks with all the teams


def get_team_mini_league_summary(team_id: int, static_data: dict) -> dict:
    """
    Fetch picked players for each GW, sum live stats, and return team‐level numbers.
    """
    SESSION = requests.Session()
    SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

    # 1) figure out current GW
    current_gw = next(e["id"]
                      for e in static_data["events"] if e.get("is_current"))

    # 2) fetch all pick lists in parallel
    pick_urls = {
        gw: f"{FPL_API}/entry/{team_id}/event/{gw}/picks/"
        for gw in range(1, current_gw + 1)
    }
    picks_map = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {ex.submit(SESSION.get, url)                        : gw for gw, url in pick_urls.items()}
        for fut in as_completed(future_to_gw):
            gw = future_to_gw[fut]
            try:
                data = fut.result().json()
                picks_map[gw] = {p["element"]: p.get(
                    "multiplier", 1) for p in data.get("picks", [])}
            except Exception:
                picks_map[gw] = {}

    # 3) prepare summary buckets
    summary = {
        "goals_scored_team":      0,
        "expected_goals_team":    0.0,
        "goals_benched_team":     0,
        "assists_team":           0,
        "clean_sheets_team":      0,
        "expected_assists_team":  0.0,
        "bps_team":               0,
        "dreamteam_count_team":   0,
        "yellow_cards_team":      0,
        "red_cards_team":         0,
        # "own_goals_team":         0,
        # "penalties_saved_team":   0,
        # "penalties_missed_team":  0,
        "minutes_team":           0,
        "total_points_team":      0,
    }

    # 4) fetch all live data in parallel
    live_urls = {
        gw: f"{FPL_API}/event/{gw}/live/" for gw in picks_map if picks_map[gw]}
    with ThreadPoolExecutor(max_workers=8) as ex:
        future_to_gw = {ex.submit(SESSION.get, url)                        : gw for gw, url in live_urls.items()}
        for fut in as_completed(future_to_gw):
            gw = future_to_gw[fut]
            try:
                elements = fut.result().json().get("elements", [])
            except Exception:
                continue

            multipliers = picks_map.get(gw, {})
            for el in elements:
                pid = el.get("id")
                mult = multipliers.get(pid)
                if mult is None:
                    continue
                stats = el.get("stats", {})

                # benched players
                if mult == 0:
                    summary["goals_benched_team"] += stats.get(
                        "goals_scored", 0)
                    continue

                # aggregate stats
                summary["goals_scored_team"] += stats.get(
                    "goals_scored", 0) * mult
                summary["assists_team"] += stats.get("assists", 0) * mult
                summary["clean_sheets_team"] += stats.get(
                    "clean_sheets", 0) * mult
                summary["bps_team"] += stats.get("bps", 0) * mult
                # summary["expected_goals_team"] += float(
                #     stats.get("expected_goals", 0)) * mult
                # summary["expected_assists_team"] += float(
                #     stats.get("expected_assists", 0)) * mult
                summary["yellow_cards_team"] += stats.get(
                    "yellow_cards", 0) * mult
                summary["red_cards_team"] += stats.get("red_cards", 0) * mult
                # summary["own_goals_team"] += stats.get("own_goals", 0) * mult
                # summary["penalties_saved_team"] += stats.get(
                #     "penalties_saved", 0) * mult
                # summary["penalties_missed_team"] += stats.get(
                #     "penalties_missed", 0) * mult
                summary["minutes_team"] += stats.get("minutes", 0) * mult
                if stats.get("in_dreamteam", False):
                    summary["dreamteam_count_team"] += mult
                summary["total_points_team"] += stats.get(
                    "total_points", 0) * mult

    return summary
