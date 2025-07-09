import sqlite3

conn = sqlite3.connect("logs.db")  # Ensure path is correct
cursor = conn.cursor()

cursor.execute("SELECT * FROM vehicle_logs ORDER BY timestamp DESC")
rows = cursor.fetchall()

print("Stored Logs:")
for row in rows:
    print(row)

conn.close()
