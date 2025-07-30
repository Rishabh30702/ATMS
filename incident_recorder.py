# incident_recorder.py

import cv2
import os
from datetime import datetime

def record_incident_clip(camera_index, duration_sec=5, save_folder="clips", fps=20):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print("❌ Incident camera could not be opened.")
        return

    os.makedirs(save_folder, exist_ok=True)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    
    filename = datetime.now().strftime("incident_%Y%m%d_%H%M%S.avi")
    filepath = os.path.join(save_folder, filename)
    out = cv2.VideoWriter(filepath, fourcc, fps, (width, height))

    frame_count = int(duration_sec * fps)
    for _ in range(frame_count):
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)

    cap.release()
    out.release()
    print(f"📹 Incident clip saved to {filepath}")
