import sqlite3
import hashlib

def init_db():
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            lane_id TEXT
        )
    ''')

    # Create vehicle logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vehicle_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT,
            vehicle_type TEXT,
            fastag_status TEXT,
            operator TEXT,
            lane_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def add_default_user():
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()

    # Add default admin user if not exists
    cursor.execute("INSERT OR IGNORE INTO users (username, password, lane_id) VALUES (?, ?, ?)",
                   ("admin", hash_password("admin123"), "1"))

    conn.commit()
    conn.close()

def authenticate_user(username, password):
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()
    hashed = hash_password(password)
    cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (username, hashed))
    row = cursor.fetchone()
    conn.close()
    return {"username": row[1], "lane_id": row[3]} if row else None

def get_user_lane(username):
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT lane_id FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Unknown"

def log_entry(plate, vehicle_type, fastag_status, operator, lane_id):
    conn = sqlite3.connect("logs.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO vehicle_logs (plate, vehicle_type, fastag_status, operator, lane_id) VALUES (?, ?, ?, ?, ?)",
                   (plate, vehicle_type, fastag_status, operator, lane_id))
    conn.commit()
    conn.close()

# Run this when script loads
init_db()
add_default_user()
