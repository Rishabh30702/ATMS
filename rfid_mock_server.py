# rfid_mock_server.py
import socket
import threading
import time
import random
import json

# Sample mock FASTag IDs
MOCK_TAGS = [
    "ABC12345",
    "XYZ98765",
    "FASTAG111",
    "VEHICLE222",
    "RFID9999",
    "TESTTAG1",
    "MH14BR6899"
]

def handle_client(conn, addr, lane_id):
    print(f"🚗 [Lane {lane_id}] Connected mock client: {addr}")
    try:
        while True:
            tag = random.choice(MOCK_TAGS)
            conn.sendall((tag + "\n").encode())
            print(f"📤 [Lane {lane_id}] Sent mock tag: {tag}")
            time.sleep(random.randint(3, 7))  # Send every 3–7 seconds
    except Exception as e:
        print(f"❌ [Lane {lane_id}] Client disconnected: {e}")
    finally:
        conn.close()

def start_mock_server(ip, port, lane_id):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ip, port))
        server.listen(1)
        print(f"🟢 [Lane {lane_id}] Mock RFID server listening at {ip}:{port}")
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr, lane_id), daemon=True).start()

def load_config_and_start():
    try:
        with open("rfid_config.json", "r") as f:
            config = json.load(f)
        for lane_id, info in config.get("lanes", {}).items():
            ip = "0.0.0.0"  # Bind to all interfaces for local testing
            port = info["port"]
            threading.Thread(target=start_mock_server, args=(ip, port, lane_id), daemon=True).start()
    except Exception as e:
        print(f"❌ Error reading config: {e}")

if __name__ == "__main__":
    load_config_and_start()
    print("🏁 Mock RFID servers running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)
