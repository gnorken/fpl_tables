# modules/fetch_fixtures.py
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import argparse
import requests

# Default DB path: one level up from /modules
DEFAULT_DB = str((Path(__file__).resolve().parents[1] / "page_views.db"))

FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fixtures (
    id                       INTEGER PRIMARY KEY,
    event                    INTEGER,
    kickoff_time_utc         TEXT,
    finished                 INTEGER NOT NULL DEFAULT 0,
    provisional_start_time   INTEGER NOT NULL DEFAULT 0,
    team_h                   INTEGER NOT NULL,
    team_a                   INTEGER NOT NULL,
    team_h_difficulty        INTEGER,
    team_a_difficulty        INTEGER,
    last_fetched             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fixtures_event         ON fixtures(event);
CREATE INDEX IF NOT EXISTS idx_fixtures_team_h        ON fixtures(team_h, finished, event, kickoff_time_utc);
CREATE INDEX IF NOT EXISTS idx_fixtures_team_a        ON fixtures(team_a, finished, event, kickoff_time_utc);
CREATE INDEX IF NOT EXISTS idx_fixtures_last_fetched  ON fixtures(last_fetched);
"""


def ensure_schema(cur):
    cur.executescript(SCHEMA_SQL)


def fetch_and_cache_fixtures(*, future=True, event=None, database=DEFAULT_DB, verbose=True):
    params = {}
    if event is not None:
        params["event"] = int(event)
    elif future:
        params["future"] = 1

    if verbose:
        print(f"[fixtures] DB: {database}")
        print(f"[fixtures] GET {FIXTURES_URL} params={params}")

    r = requests.get(FIXTURES_URL, params=params, timeout=15)
    r.raise_for_status()
    fixtures = r.json()

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = sqlite3.connect(database, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout=10000")

    # Ensure table/indexes exist
    ensure_schema(cur)

    # For nicer logging
    fetched_ids = [f["id"] for f in fixtures]
    existing = set()
    if fetched_ids:
        placeholders = ",".join("?" * len(fetched_ids))
        cur.execute(
            f"SELECT id FROM fixtures WHERE id IN ({placeholders})", fetched_ids)
        existing = {row[0] for row in cur.fetchall()}

    new, updated = 0, 0

    cur.execute("BEGIN")
    try:
        for f in fixtures:
            was_existing = f["id"] in existing
            cur.execute(
                """
                INSERT OR REPLACE INTO fixtures
                (id, event, kickoff_time_utc, finished, provisional_start_time,
                 team_h, team_a, team_h_difficulty, team_a_difficulty, last_fetched)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f["id"],
                    f.get("event"),
                    f.get("kickoff_time"),
                    1 if f.get("finished") else 0,
                    1 if f.get("provisional_start_time") else 0,
                    f["team_h"],
                    f["team_a"],
                    f.get("team_h_difficulty"),
                    f.get("team_a_difficulty"),
                    now_utc,
                ),
            )
            new += 0 if was_existing else 1
            updated += 1 if was_existing else 0

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Quick sanity print: how many rows total?
        try:
            cur.execute("SELECT COUNT(*) FROM fixtures")
            total = cur.fetchone()[0]
        except Exception:
            total = "?"
        conn.close()

    if verbose:
        print(
            f"[fixtures] fetched={len(fixtures)} new={new} updated={updated} total_rows={total} at {now_utc}")

    return {"fetched": len(fixtures), "new": new, "updated": updated, "total": total, "timestamp": now_utc}


def ensure_fixtures_for_gw(from_event: int | None, *, database=DEFAULT_DB, verbose=True):
    """
    Ensure we have unfinished fixtures for the current (or next) gameweeks.
    No TTL. We fetch only if DB lacks any row with finished=0 AND (event>=from_event OR event IS NULL).

    If from_event is None or <1 (pre-season), we just require any unfinished row.
    """
    conn = sqlite3.connect(database, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout=10000")
    ensure_schema(cur)

    if from_event and from_event >= 1:
        cur.execute("""
            SELECT 1
            FROM fixtures
            WHERE finished = 0 AND (event IS NULL OR event >= ?)
            LIMIT 1
        """, (from_event,))
    else:
        cur.execute("""
            SELECT 1
            FROM fixtures
            WHERE finished = 0
            LIMIT 1
        """)

    have_upcoming = cur.fetchone() is not None
    conn.close()

    if have_upcoming:
        if verbose:
            print(
                f"[fixtures] coverage OK for from_event={from_event}; no fetch needed")
        return {"skipped": True, "from_event": from_event}

    # Missing coverage → fetch all upcoming in one go
    return fetch_and_cache_fixtures(future=True, database=database, verbose=verbose)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch and cache FPL fixtures")
    ap.add_argument("gw", nargs="?", type=int,
                    help="Gameweek number (omit to fetch future fixtures)")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="Path to SQLite DB (default: project/page_views.db)")
    args = ap.parse_args()

    res = fetch_and_cache_fixtures(
        future=(args.gw is None),
        event=args.gw,
        database=args.db,
        verbose=True,
    )
    print(res)
