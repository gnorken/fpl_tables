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
CREATE TABLE IF NOT EXISTS live_elements_cache(
    gameweek INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    last_fetched TEXT NOT NULL
)
""")


cur.execute("""
CREATE TABLE IF NOT EXISTS mini_league_cache (
    league_id    INTEGER NOT NULL,
    gameweek     INTEGER NOT NULL,
    team_id      INTEGER,
    max_show     INTEGER NOT NULL,
    data         TEXT NOT NULL,
    last_fetched TEXT NOT NULL,
    PRIMARY KEY (league_id, gameweek, team_id, max_show)
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

# --- Indexes helpful for pruning / freshness checks ---
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_static_data_last_fetched ON static_data(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_static_player_info_last_fetched ON static_player_info(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_team_player_info_last_fetched ON team_player_info(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_mini_league_cache_last_fetched ON mini_league_cache(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_managers_last_fetched ON managers(last_fetched)")
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_global_points_cache_last_fetched ON global_points_cache(last_fetched)")

conn.commit()
conn.close()

print("Database initialized ✅")
