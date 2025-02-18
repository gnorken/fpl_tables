import sqlite3

# Create a connection to the database
conn = sqlite3.connect("page_views.db", check_same_thread=False)
cursor = conn.cursor()

# Create the managers table if it doesn't exist
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS managers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT,
        last_name TEXT,
        team_name TEXT,
        team_id TEXT,
        country_code TEXT
    )
    """
)

# Create table for player info dictionary for goals table
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS player_info_goals (
        team_id INTEGER PRIMARY KEY,
        data TEXT,
        gameweek INTEGER
    )
    """
)

# Create table for player info dictionary for starts table
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS player_info_starts (
        team_id INTEGER PRIMARY KEY,
        data TEXT,
        gameweek INTEGER
    )
    """
)

# Create table for player info dictionary for points table
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS player_info_points (
        team_id INTEGER PRIMARY KEY,
        data TEXT,
        gameweek INTEGER
    )
    """
)

# Commit the changes and close the connection
conn.commit()
conn.close()

print("Database and tables created successfully.")
