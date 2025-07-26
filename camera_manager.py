# camera_manager.py

import cv2
import json
import os

CONFIG_FILE = "camera_config.json"

class CameraManager:
    def __init__(self):
        self.index = None
        self.camera = None
        self.load_camera_config()

    def detect_and_save_camera(self, max_index=5):
        for i in range(max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                cap.release()
                self.index = i
                print(f"✅ Camera detected at index {i}")
                self.save_camera_config(i)
                return i
            cap.release()
        print("❌ No working camera found.")
        self.index = None
        return None

    def load_camera_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                self.index = config.get("camera_index")
                print(f"📂 Loaded camera index from config: {self.index}")
        else:
            print("📂 No camera config found. Detecting camera...")
            self.detect_and_save_camera()

    def save_camera_config(self, index):
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"camera_index": index}, f)
            print(f"💾 Saved camera index {index} to config")

    def get_camera(self):
        if self.index is None:
            self.detect_and_save_camera()
        self.camera = cv2.VideoCapture(self.index)
        return self.camera

    def release(self):
        if self.camera and self.camera.isOpened():
            self.camera.release()
            print("🔒 Camera released.")
