# rfid_listener.py
import socket
import threading
import json
import time
from PyQt5.QtCore import QThread

class RFIDListener(QThread):
    def __init__(self, on_tag_callback=None, config_file="rfid_config.json"):
        super().__init__()
        self.on_tag_callback = on_tag_callback
        self.config_file = config_file
        self.running = True
        self.threads = []

    def run(self):
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                lanes = config.get("lanes", {})
                for lane_id, lane_info in lanes.items():
                    ip = lane_info["ip"]
                    port = lane_info["port"]
                    thread = threading.Thread(
                        target=self.listen_to_lane,
                        args=(lane_id, ip, port),
                        daemon=True
                    )
                    thread.start()
                    self.threads.append(thread)
                    print(f"🟢 Started RFID listener for Lane {lane_id} at {ip}:{port}")
        except Exception as e:
            print(f"❌ Error loading config or starting listeners: {e}")

    def listen_to_lane(self, lane_id, ip, port):
        while self.running:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((ip, port))
                    print(f"✅ Connected to Lane {lane_id} RFID reader at {ip}:{port}")
                    while self.running:
                        data = s.recv(1024)
                        if data:
                            tag = data.decode().strip()
                            print(f"📥 [Lane {lane_id}] Tag received: {tag}")
                            if self.on_tag_callback:
                                self.on_tag_callback(tag, lane_id)
                        else:
                            time.sleep(0.5)
            except Exception as e:
                print(f"🔁 [Lane {lane_id}] Connection failed: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False
        print("🛑 Stopping RFID listeners...")
