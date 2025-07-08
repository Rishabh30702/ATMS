# 🔒 Full working Toll Booth ANPR App with styled login and YOLO+OCR
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QComboBox
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
import cv2
import easyocr
import re
from ultralytics import YOLO

from db import authenticate_user, log_entry, get_user_lane
from fastag_api import check_fastag

# --------------------- YOLOv8 + OCR ---------------------
model = YOLO("best2.pt")
def is_valid_plate(text):
    pattern = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$"
    return re.match(pattern, text) is not None

def detect_plate(reader, frame):
    results = model(frame)
    for r in results:
        for box in r.boxes:
            conf = float(box.conf[0])
            if conf < 0.4:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cropped = frame[y1:y2, x1:x2]
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            ocr_results = reader.readtext(gray) + reader.readtext(thresh)
            for _, text, ocr_conf in ocr_results:
                clean = text.replace(" ", "").upper()
                print(f"[DEBUG] OCR: '{text}' | Clean: '{clean}' | Conf: {ocr_conf:.2f}")
                if ocr_conf > 0.7 and 6 <= len(clean) <= 12 and is_valid_plate(clean):
                    print(f"[INFO] ✅ Valid plate detected: {clean}")
                    return clean, (x1, y1, x2, y2)
    return None, None

# --------------------- TollApp Main UI ---------------------
class TollApp(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lane = get_user_lane(user['username'])
        self.setWindowTitle(f"Toll Booth - Lane {self.lane}")
        self.setGeometry(100, 100, 1100, 600)

        self.setup_ui()
        self.reader = easyocr.Reader(['en'])
        self.cap = cv2.VideoCapture(0)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)
        self.frame_count = 0
        self.last_detected_plate = ""

    def setup_ui(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI';
                font-size: 14px;
            }
            QLabel#Header {
                font-size: 16px;
                font-weight: bold;
                color: #2c3e50;
            }
            QLineEdit, QComboBox {
                padding: 8px;
                border: 1px solid #ccc;
                border-radius: 6px;
                font-size: 16px;
                min-width: 200px;
            }
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 8px;
                font-size: 15px;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1e8449;
            }
        """)

        self.user_info = QLabel(f"\U0001F464 {self.user['username']} | Lane {self.lane}")
        self.user_info.setObjectName("Header")

        self.video_label = QLabel()
        self.video_label.setFixedSize(640, 480)
        self.video_label.setStyleSheet("border: 2px solid #ccc; border-radius: 8px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Vehicle Number")

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems(["Car", "Truck", "Bus"])

        self.fastag_status = QComboBox()
        self.fastag_status.addItems(["Valid", "Invalid", "No FASTag"])

        self.status_display = QLabel("")
        self.status_display.setObjectName("Header")

        self.submit_button = QPushButton("Log Entry")
        self.submit_button.clicked.connect(self.submit_manual)

        video_layout = QVBoxLayout()
        video_layout.addWidget(self.user_info)
        video_layout.addWidget(self.video_label)

        form_layout = QVBoxLayout()
        form_layout.addWidget(QLabel("Plate Number:"))
        form_layout.addWidget(self.plate_input)
        form_layout.addWidget(QLabel("Vehicle Type:"))
        form_layout.addWidget(self.vehicle_type)
        form_layout.addWidget(QLabel("FASTag Status:"))
        form_layout.addWidget(self.fastag_status)
        form_layout.addWidget(QLabel("Detected Info:"))
        form_layout.addWidget(self.status_display)
        form_layout.addStretch()
        form_layout.addWidget(self.submit_button)

        main_layout = QHBoxLayout()
        main_layout.addLayout(video_layout)
        main_layout.addSpacing(30)
        main_layout.addLayout(form_layout)
        self.setLayout(main_layout)

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return
        self.frame_count += 1
        if self.frame_count % 10 == 0:
            plate, box = detect_plate(self.reader, frame)
            if box:
                x1, y1, x2, y2 = box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            if plate and plate != self.last_detected_plate:
                self.last_detected_plate = plate
                self.plate_input.setText(plate)
                tag_info = check_fastag(plate)
                status = tag_info["status"]
                self.fastag_status.setCurrentText(status)
                self.status_display.setText(f"{status} - ₹{tag_info.get('balance', 0.0):.2f}")
                QMessageBox.information(self, "FASTag Info", f"""
FASTag Status: {status}
Tag ID: {tag_info.get('tag_id', 'N/A')}
Balance: ₹{tag_info.get('balance', 0.0):.2f}
Vehicle Class: {tag_info.get('vehicle_class', 'N/A')}
""")
                log_entry(plate, "Auto", status, self.user["username"], self.lane)
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb_image, rgb_image.shape[1], rgb_image.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def submit_manual(self):
        plate = self.plate_input.text()
        vehicle = self.vehicle_type.currentText()
        status = self.fastag_status.currentText()
        log_entry(plate, vehicle, status, self.user["username"], self.lane)
        QMessageBox.information(self, "Manual Entry", "Vehicle logged successfully.")

    def closeEvent(self, event):
        self.cap.release()

# --------------------- Styled Login Screen ---------------------
class LoginScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Toll Booth Login")
        self.setGeometry(600, 300, 400, 300)
        self.setStyleSheet("""
            QWidget {
                background-color: #ecf0f1;
                font-family: 'Segoe UI';
            }
            QLabel {
                font-size: 20px;
                color: #2c3e50;
                font-weight: bold;
            }
            QLineEdit {
                padding: 10px;
                border: 2px solid #bdc3c7;
                border-radius: 10px;
                font-size: 16px;
            }
            QPushButton {
                padding: 10px;
                background-color: #2980b9;
                color: white;
                font-size: 16px;
                border: none;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #1f618d;
            }
        """)
        self.init_ui()

    def init_ui(self):
        self.title = QLabel("\U0001F6A7 Toll Booth Login")
        self.title.setAlignment(Qt.AlignCenter)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter Username")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.login)

        layout = QVBoxLayout()
        layout.addStretch()
        layout.addWidget(self.title)
        layout.addSpacing(20)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(self.login_button)
        layout.addStretch()
        self.setLayout(layout)

    def login(self):
        username = self.username_input.text()
        password = self.password_input.text()
        user = authenticate_user(username, password)
        if user:
            self.close()
            self.main_app = TollApp(user)
            self.main_app.show()
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid username or password")

# --------------------- Main Entry Point ---------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
