import sqlite3
import json

conn = sqlite3.connect("quorum_app.db")
cur = conn.cursor()

cur.execute("""
UPDATE data_sources
SET connection_meta = ?
WHERE display_name = 'Northwind (sample)'
""", [json.dumps({
    "path": r"D:\Quorum_analyzer\quorum\data\samples\northwind.db"
})])

cur.execute("""
UPDATE data_sources
SET connection_meta = ?
WHERE display_name = 'Chinook (sample)'
""", [json.dumps({
    "path": r"D:\Quorum_analyzer\quorum\data\samples\chinook.db"
})])

conn.commit()
conn.close()

print("Fixed datasource paths")