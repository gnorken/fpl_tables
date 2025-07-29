import sqlite3
from pathlib import Path

DB_PATH = Path("page_views.db")  # change to your DB filename


def estimate_table_size(cur, table):
    """Estimate table size by summing row lengths (bytes)."""
    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        size = 0
        for row in rows:
            size += sum(len(str(col).encode('utf-8'))
                        for col in row if col is not None)
        return round(size / (1024 * 1024), 3)
    except Exception as e:
        return "n/a"


def get_table_stats(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all tables
    cur.execute("SELECT name FROM sqlite_schema WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]

    stats = []
    for table in tables:
        # Row count
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        row_count = cur.fetchone()[0]

        # Try dbstat first
        size_mb = "n/a"
        try:
            cur.execute(f"SELECT SUM(pgsize) FROM dbstat WHERE name='{table}'")
            size_bytes = cur.fetchone()[0] or 0
            size_mb = round(size_bytes / (1024*1024), 3)
        except sqlite3.OperationalError:
            # Fallback: estimate by row lengths
            size_mb = estimate_table_size(cur, table)

        stats.append({
            "table": table,
            "rows": row_count,
            "size_mb": size_mb
        })

    # Total DB size
    cur.execute("PRAGMA page_count")
    page_count = cur.fetchone()[0]
    cur.execute("PRAGMA page_size")
    page_size = cur.fetchone()[0]
    total_db_size_mb = round((page_count * page_size) / (1024 * 1024), 3)

    conn.close()
    return stats, total_db_size_mb


if __name__ == "__main__":
    stats, total_size = get_table_stats(DB_PATH)
    print(f"\nTable stats for: {DB_PATH}")
    print(f"Total DB size: {total_size} MB\n")
    print(f"{'Table':30} {'Rows':10} {'Size (MB)':10}")
    print("-" * 55)
    for s in stats:
        print(f"{s['table']:30} {s['rows']:10} {s['size_mb']}")
