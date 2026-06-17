# SQLiteというDBの設計図を作るプログラム

import sqlite3

conn = sqlite3.connect("sensor.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS sensor_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    temperature INTEGER,
    humidity INTEGER,
    timestamp REAL
)
""")

conn.commit()
conn.close()

print("DB作成完了")

