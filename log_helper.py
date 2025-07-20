# log_helper.py
import sqlite3
from datetime import datetime

def insert_rfid_log(tag, lane):
    try:
        conn = sqlite3.connect("logs.db")
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS rfid_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT,
                lane TEXT,
                timestamp TEXT
            )
        """)
        c.execute("INSERT INTO rfid_logs (tag, lane, timestamp) VALUES (?, ?, ?)", 
                  (tag, lane, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        print(f"✅ Saved tag {tag} from lane {lane} to logs.db")
    except Exception as e:
        print(f"❌ Failed to insert RFID log: {e}")

def insert_log(lane, tag):
    try:
        conn = sqlite3.connect("logs.db")
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS vehicle_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT,
                lane TEXT,
                timestamp TEXT
            )
        """)
        c.execute("INSERT INTO vehicle_logs (tag, lane, timestamp) VALUES (?, ?, ?)",
                  (tag, lane, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        print(f"✅ Saved vehicle log for tag {tag} in lane {lane}")
    except Exception as e:
        print(f"❌ Failed to insert vehicle log: {e}")
