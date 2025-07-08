import cv2
import easyocr
from ultralytics import YOLO
import re

# Load custom-trained YOLO model for Indian number plates
model = YOLO("best2.pt")

# Initialize OCR
reader = easyocr.Reader(['en'], gpu=False)

# Check if text matches Indian number plate format
def is_valid_plate(text):
    pattern = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$"
    return re.match(pattern, text) is not None

# Detect and read plate from a frame
def detect_plate(reader, frame):
    results = model(frame)

    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf < 0.4:
                continue  # Skip low-confidence detections

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cropped = frame[y1:y2, x1:x2]

            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # OCR both grayscale and thresholded versions
            results_gray = reader.readtext(gray)
            results_thresh = reader.readtext(thresh)

            all_results = results_gray + results_thresh

            for _, text, ocr_conf in all_results:
                clean = text.replace(" ", "").upper()
                print(f"[DEBUG] OCR: '{text}' | Clean: '{clean}' | Conf: {ocr_conf:.2f}")
                if ocr_conf > 0.7 and 6 <= len(clean) <= 12 and is_valid_plate(clean):
                    print(f"[INFO] ✅ Valid plate detected: {clean}")
                    return clean, (x1, y1, x2, y2)

    print("[INFO] ❌ No valid plate detected in this frame.")
    return None, None
