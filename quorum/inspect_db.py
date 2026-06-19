import sqlite3

conn = sqlite3.connect("quorum_app.db")
cur = conn.cursor()

cur.execute("""
SELECT
    id,
    display_name,
    kind,
    connection_meta
FROM data_sources
ORDER BY id DESC
LIMIT 10
""")

for row in cur.fetchall():
    print(row)