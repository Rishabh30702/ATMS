# multi_camera_manager.py

import cv2
import json
import os

CONFIG_FILE = "camera_config.json"

class MultiCameraManager:
    def __init__(self, max_index=5):
        self.max_index = max_index
        self.cameras = {}  # {label: index}
        self.load_or_create_config()

    def detect_all_cameras(self):
        found = []
        for i in range(self.max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                found.append(i)
                cap.release()
        return found

    def save_camera_config(self, config):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
            print(f"💾 Saved camera config: {config}")

    def load_or_create_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.cameras = json.load(f)
                    print(f"📂 Loaded camera config: {self.cameras}")
            except Exception as e:
                print(f"❌ Failed to load config, re-detecting cameras: {e}")
                self.auto_assign_cameras()
        else:
            print("📂 No camera config found. Detecting cameras...")
            self.auto_assign_cameras()

    def auto_assign_cameras(self):
        detected = self.detect_all_cameras()
        if not detected:
            print("❌ No cameras detected.")
            return

        # Assign cameras
        config = {
            "vehicle_camera": detected[0]
        }
        if len(detected) > 1:
            config["incident_camera"] = detected[1]
        else:
            config["incident_camera"] = detected[0]  # Fallback to same

        self.cameras = config
        self.save_camera_config(config)

    def get_camera(self, label="vehicle_camera"):
        if label in self.cameras:
            index = self.cameras[label]
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                print(f"✅ {label} opened successfully at index {index}")
                return cap
            else:
                print(f"⚠️ {label} at index {index} could not be opened.")
        else:
            print(f"❌ {label} not found in camera config.")
        return None


    def release_all(self):
        for label, index in self.cameras.items():
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                cap.release()
                print(f"🔒 Released camera '{label}'")
