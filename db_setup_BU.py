import sqlite3

# Create a connection to the database
conn = sqlite3.connect("page_views.db", check_same_thread=False)
cursor = conn.cursor()

# Create the static data table if it doesn't exist
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS static_data (
        key TEXT PRIMARY KEY,
        data TEXT,
        last_fetched TEXT    NOT NULL
    )
    """
)

cursor.execute("""
    CREATE TABLE IF NOT EXISTS static_player_info(
        gameweek     INTEGER PRIMARY KEY,
        data         TEXT    NOT NULL,
        last_fetched TEXT    NOT NULL
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_player_info(
        team_id    INTEGER,
        gameweek   INTEGER,
        data       TEXT    NOT NULL,
        last_fetched TEXT    NOT NULL,
        PRIMARY KEY(team_id, gameweek)
    )
    """)


cursor.execute("""
    CREATE TABLE mini_league_cache (
        league_id   INTEGER NOT NULL,
        gameweek    INTEGER NOT NULL,
        team_id     INTEGER,
        max_show     INTEGER NOT NULL,
        data        TEXT    NOT NULL,
        last_fetched TEXT    NOT NULL,
        PRIMARY KEY (league_id, gameweek, team_id, max_show)
    );
    """)

# Create the managers table if it doesn't exist
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS managers (
        team_id      INTEGER PRIMARY KEY,
        data         TEXT NOT NULL,
        last_fetched TEXT    NOT NULL
    )
    """
)


# Commit the changes and close the connection
conn.commit()
conn.close()

print("Database and tables created successfully.")
