# modules/fixtures_utils.py
from datetime import datetime
from pathlib import Path
import sqlite3

DEFAULT_DB = str((Path(__file__).resolve().parents[1] / "page_views.db"))


def build_team_fixture_cache(cur, from_event: int | None, lookahead: int = 5):
    """
    Returns {team_id: [fixtures...]} where each fixture dict is:
    {
      'event': int|None,
      'is_home': bool,
      'opp_team_id': int,
      'difficulty': int|None,
      'kickoff_time_utc': str|None,
      'tbc': bool,
    }
    Only includes unfinished fixtures, ordered by (kickoff_time_utc NULLS LAST, event).
    """
    rows = cur.execute(
        """
        SELECT id, event, kickoff_time_utc, finished, provisional_start_time,
               team_h, team_a, team_h_difficulty, team_a_difficulty
        FROM fixtures
        WHERE finished = 0
          AND (event IS NULL OR ? IS NULL OR event >= ?)
        ORDER BY CASE WHEN kickoff_time_utc IS NULL THEN 1 ELSE 0 END,
                 COALESCE(kickoff_time_utc, '9999-12-31T00:00:00Z'),
                 COALESCE(event, 999)
        """,
        (from_event, from_event),
    ).fetchall()

    cache: dict[int, list] = {}
    for (_fid, ev, ko, _fin, provisional, h, a, hd, ad) in rows:
        # home perspective
        cache.setdefault(h, [])
        if len(cache[h]) < lookahead:
            cache[h].append({
                "event": ev,
                "is_home": True,
                "opp_team_id": a,
                "difficulty": hd,
                "kickoff_time_utc": ko,
                "tbc": bool(provisional or ko is None),
            })
        # away perspective
        cache.setdefault(a, [])
        if len(cache[a]) < lookahead:
            cache[a].append({
                "event": ev,
                "is_home": False,
                "opp_team_id": h,
                "difficulty": ad,
                "kickoff_time_utc": ko,
                "tbc": bool(provisional or ko is None),
            })
    return cache


def get_team_upcoming(cache: dict[int, list], team_id: int, n: int = 3):
    """Convenience: slice up to n fixtures for a given team_id."""
    return (cache.get(team_id) or [])[:n]


def attach_upcoming_to_rows(rows, fixtures_cache, static_data, lookahead=5):
    """
    Mutates rows in-place, adding:
      - upcoming_fixtures (list[dict])
      - next3_fixtures / next5_fixtures (strings)
      - next3_fdr_sum/avg, next5_fdr_sum/avg
      - next_ko_ts_utc (for sorting)
    'rows' can be a list[dict] or dict[id]->dict.
    Requires each row to have either 'team_code' or 'team_id'.
    """
    teams = static_data.get("teams", [])
    code_to_id = {t["code"]: t["id"] for t in teams}
    short_by_id = {t["id"]:  t["short_name"] for t in teams}

    def fmt_leg(l):
        opp = short_by_id.get(l["opp_team_id"], "UNK")
        ha = "H" if l["is_home"] else "A"
        fdr = l["difficulty"] if l["difficulty"] is not None else "?"
        return f"{opp}({ha})-{fdr}{'*' if l.get('tbc') else ''}"

    def fdr_agg(legs, n):
        diffs = [l["difficulty"]
                 for l in legs[:n] if l["difficulty"] is not None]
        if not diffs:
            return None, None
        s = sum(diffs)
        return s, round(s/len(diffs), 2)

    iterable = rows.values() if isinstance(rows, dict) else rows
    for row in iterable:
        team_id = row.get("team_id")
        if team_id is None:
            tc = row.get("team_code")
            if tc is not None:
                team_id = code_to_id.get(tc)

        if team_id is None:
            # Can't attach without a team id; skip quietly
            continue

        legs = (fixtures_cache.get(team_id) or [])[:lookahead]

        up_list = []
        for l in legs:
            ko = l.get("kickoff_time_utc")
            ts = None
            if ko:
                try:
                    ts = datetime.fromisoformat(
                        ko.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = None
            up_list.append({
                "event": l.get("event"),
                "is_home": l.get("is_home"),
                "opp_team_id": l.get("opp_team_id"),
                "opp_short": short_by_id.get(l.get("opp_team_id"), "UNK"),
                "difficulty": l.get("difficulty"),
                "kickoff_time_utc": ko,
                "kickoff_ts_utc": ts,
                "tbc": bool(l.get("tbc")),
            })

        s3, a3 = fdr_agg(legs, 3)
        s5, a5 = fdr_agg(legs, 5)

        row.update({
            "upcoming_fixtures": up_list,
            "next3_fixtures": ", ".join(fmt_leg(l) for l in legs[:3]) or None,
            "next5_fixtures": ", ".join(fmt_leg(l) for l in legs[:5]) or None,
            "next3_fdr_sum": s3,
            "next3_fdr_avg": a3,
            "next5_fdr_sum": s5,
            "next5_fdr_avg": a5,
            "next_ko_ts_utc": (up_list[0]["kickoff_ts_utc"] if up_list else None),
        })


def add_fixture_metrics_to_blob(static_blob: dict, static_data: dict, fixtures_cache: dict, lookahead: int = 5):
    """Add next3/next5 FDR sums/avgs to every player row in static_blob."""
    teams = static_data.get("teams", [])
    code_to_id = {t["code"]: t["id"] for t in teams}

    def agg(legs, n):
        diffs = [l.get("difficulty")
                 for l in legs[:n] if l.get("difficulty") is not None]
        if not diffs:
            return None, None
        s = sum(diffs)
        return s, round(s / len(diffs), 2)

    for row in static_blob.values():
        team_code = row.get("team_code")
        team_id = code_to_id.get(team_code)
        legs = (fixtures_cache.get(team_id) or [])[
            :lookahead] if team_id else []

        s3, a3 = agg(legs, 3)
        s5, a5 = agg(legs, 5)

        row["next3_fdr_sum"] = s3
        row["next3_fdr_avg"] = a3
        row["next5_fdr_sum"] = s5
        row["next5_fdr_avg"] = a5
