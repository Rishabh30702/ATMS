import sqlite3
import mysql.connector
import time
import os
from datetime import datetime
import threading

# --- CONFIG ---
SQLITE_DB = "logs.db"
LAST_SYNC_FILE = "last_sync.txt"
SYNC_INTERVAL = 10  # its 10 second for now later we can change it to 15 min (900 seconds)

MYSQL_CONFIG = {
    "host": "sql12.freesqldatabase.com",
    "user": "sql12768414",             # ✅ Corrected user
    "password": "2ecIyTVvIh",
    "database": "sql12768414"
}

def get_last_sync_time():
    if not os.path.exists(LAST_SYNC_FILE):
        return "2000-01-01 00:00:00"
    with open(LAST_SYNC_FILE, "r") as f:
        return f.read().strip()

def set_last_sync_time(ts):
    with open(LAST_SYNC_FILE, "w") as f:
        f.write(ts)

def fetch_unsynced_logs(last_sync):
    conn = sqlite3.connect(SQLITE_DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT plate, vehicle_type, fastag_status, operator, lane_id, timestamp, created_at
        FROM vehicle_logs
        WHERE datetime(created_at) > datetime(?)
        ORDER BY datetime(created_at)
    """, (last_sync,))
    rows = cur.fetchall()
    conn.close()
    return rows

def push_to_mysql(rows):
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cur = conn.cursor()

    for row in rows:
        cur.execute("""
            INSERT INTO vehicle_logs (plate, vehicle_type, fastag_status, operator, lane_id, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, row[:6])  # Only first 6 items (omit created_at)

    conn.commit()
    conn.close()

def sync_task():
    while True:
        try:
            print("🔄 Starting sync...")
            last_sync = get_last_sync_time()
            logs = fetch_unsynced_logs(last_sync)

            if logs:
                print(f"📤 Syncing {len(logs)} new logs...")
                attempts = 3
                for attempt in range(attempts):
                    try:
                        push_to_mysql(logs)
                        set_last_sync_time(logs[-1][-1])  # Update with last created_at
                        print("✅ Sync successful.")
                        break
                    except Exception as e:
                        print(f"❌ Attempt {attempt + 1} failed: {e}")
                        time.sleep(5)
            else:
                print("✅ No new logs to sync.")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
        time.sleep(SYNC_INTERVAL)

def start_sync_thread():
    t = threading.Thread(target=sync_task, daemon=True)
    t.start()
