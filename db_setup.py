import sqlite3

DB = "page_views.db"

conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()

# Pragmas to make SQLite friendlier for a web app
cur.execute("PRAGMA journal_mode=WAL;")
cur.execute("PRAGMA synchronous=NORMAL;")
cur.execute("PRAGMA busy_timeout=10000;")
cur.execute("PRAGMA foreign_keys=ON;")

# --- Tables ---

cur.execute("""
CREATE TABLE IF NOT EXISTS static_data (
    key          TEXT PRIMARY KEY,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS static_player_info (
    gameweek     INTEGER PRIMARY KEY,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS team_player_info (
    team_id      INTEGER,
    gameweek     INTEGER,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL,
    PRIMARY KEY (team_id, gameweek)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS live_elements_cache (
    gameweek     INTEGER PRIMARY KEY,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS managers (
    team_id      INTEGER PRIMARY KEY,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL
)
""")

# Used by fill_global_points_from_explain()
cur.execute("""
CREATE TABLE IF NOT EXISTS global_points_cache (
    event_updated TEXT PRIMARY KEY,
    data          TEXT NOT NULL,
    last_fetched  TEXT NOT NULL
)
""")

# --- NEW: Global fixtures cache (from /api/fixtures[/?...]) ---
# One row per fixture; minimal columns for fast filtering by team/event.
cur.execute("""
CREATE TABLE IF NOT EXISTS fixtures (
    id                       INTEGER PRIMARY KEY,
    event                    INTEGER,
    kickoff_time_utc         TEXT,         -- ISO8601 string from API; may be NULL/TBC
    finished                 INTEGER NOT NULL DEFAULT 0,  -- 0/1
    provisional_start_time   INTEGER NOT NULL DEFAULT 0,  -- 0/1
    team_h                   INTEGER NOT NULL,            -- FPL team id (1..20)
    team_a                   INTEGER NOT NULL,
    team_h_difficulty        INTEGER,
    team_a_difficulty        INTEGER,
    last_fetched             TEXT NOT NULL                -- when this row was (re)cached
)
""")

# --- Dedicated caches per mini-league table ---

# Summary table cache (lightweight rows for first paint)
cur.execute("""
CREATE TABLE IF NOT EXISTS mini_league_summary_cache (
    league_id    INTEGER NOT NULL,
    gameweek     INTEGER NOT NULL,
    max_show     INTEGER NOT NULL,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL,
    PRIMARY KEY (league_id, gameweek, max_show)
)
""")

# Breakdown table cache (heavy metrics; same cohort as summary via max_show)
cur.execute("""
CREATE TABLE IF NOT EXISTS mini_league_breakdown_cache (
    league_id    INTEGER NOT NULL,
    gameweek     INTEGER NOT NULL,
    max_show     INTEGER NOT NULL,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL,
    PRIMARY KEY (league_id, gameweek, max_show)
)
""")

# --- Indexes helpful for pruning / freshness checks ---
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_static_data_last_fetched             ON static_data(last_fetched)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_static_player_info_last_fetched      ON static_player_info(last_fetched)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_team_player_info_last_fetched        ON team_player_info(last_fetched)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_live_elements_cache_last_fetched     ON live_elements_cache(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_managers_last_fetched                ON managers(last_fetched)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_global_points_cache_last_fetched     ON global_points_cache(last_fetched)")

# New cache indexes
cur.execute("CREATE INDEX IF NOT EXISTS idx_mls_cache_last_fetched               ON mini_league_summary_cache(last_fetched)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_mlb_cache_last_fetched               ON mini_league_breakdown_cache(last_fetched)")

# --- NEW: Fixtures lookup indexes ---
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_fixtures_event                       ON fixtures(event)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_team_h                      ON fixtures(team_h, finished, event, kickoff_time_utc)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_fixtures_team_a                      ON fixtures(team_a, finished, event, kickoff_time_utc)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_fixtures_last_fetched                ON fixtures(last_fetched)")

conn.commit()
conn.close()

print("Database initialized ✅")
