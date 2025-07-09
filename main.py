# ✅ Full Toll Booth ANPR App with GUI beep integration + CSV log export
import sys
import os
import csv
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QComboBox, QFileDialog
)
from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon
import cv2
import easyocr
import re
import winsound  # For playing beep
from ultralytics import YOLO

from db import authenticate_user, get_user_lane
from fastag_api import check_fastag

# Load beep file path
BEEP_PATH = os.path.join(os.path.dirname(__file__), "beep.wav")

# Load YOLOv8 model
model = YOLO("best2.pt")

LOG_FILE = "logs.csv"

# Ensure CSV exists with headers
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Plate", "Mode", "Status", "User", "Lane"])


def log_entry(plate, mode, status, username, lane):
    with open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), plate, mode, status, username, lane])


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
                if ocr_conf > 0.7 and 6 <= len(clean) <= 12 and is_valid_plate(clean):
                    return clean, (x1, y1, x2, y2)
    return None, None


class TollApp(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lane = get_user_lane(user['username'])
        self.setWindowTitle(f"Toll Booth - Lane {self.lane}")
        self.setGeometry(100, 100, 800, 500)

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
            QWidget { font-family: 'Segoe UI'; font-size: 15px; }
            QLineEdit, QComboBox {
                padding: 10px;
                border: 1px solid #bbb;
                border-radius: 6px;
                font-size: 15px;
            }
            QPushButton {
                background-color: #34495e;
                color: white;
                padding: 10px;
                font-size: 15px;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #2c3e50; }
        """)

        vehicle_types = [
            ("Car", "icons/car.jpg"),
            ("Bus", "icons/bus.jpg"),
            ("Truck", "icons/truck.png"),
            ("Auto", "icons/auto.jpg"),
            ("Bike", "icons/bike.jpg"),
            ("Tractor", "icons/tractor.jpg")
        ]

        self.vehicle_buttons = QHBoxLayout()
        for label, path in vehicle_types:
            btn = QPushButton()
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(90, 90))
            btn.setFixedSize(100, 100)
            btn.setToolTip(label)
            btn.setStyleSheet("background: white; border: 2px solid #ddd; border-radius: 12px;")
            self.vehicle_buttons.addWidget(btn)

        self.video_label = QLabel()
        self.video_label.setFixedSize(480, 360)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("margin-top: 30px; border: 3px solid #ccc; border-radius: 12px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Auto detected vehicle number")

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems([v[0] for v in vehicle_types])
        self.vehicle_type.setDisabled(True)

        self.price_display = QLineEdit()
        self.price_display.setPlaceholderText("Calculated price")
        self.price_display.setReadOnly(True)

        self.info_table = QLabel("""
            <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
                <tr style='background:#ffd700;'>
                    <th>Vehicle no</th><th>Tagno.</th><th>TagStatus</th><th>vehicle chassis</th><th>Status</th>
                </tr>
                <tr><td colspan='5'>Waiting for detection...</td></tr>
            </table>
        """)
        self.info_table.setTextFormat(Qt.RichText)

        self.export_button = QPushButton("\U0001F4E4 Export Logs")
        self.export_button.clicked.connect(self.export_logs)

        form_layout = QVBoxLayout()
        form_layout.addWidget(self.plate_input)
        form_layout.addWidget(self.vehicle_type)
        form_layout.addWidget(self.price_display)
        form_layout.addWidget(self.info_table)
        form_layout.addWidget(self.export_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(self.vehicle_buttons)
        row_layout = QHBoxLayout()
        row_layout.addWidget(self.video_label)
        row_layout.addSpacing(20)
        row_layout.addLayout(form_layout)
        main_layout.addLayout(row_layout)

        self.setLayout(main_layout)

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Logs", "", "CSV Files (*.csv)")
        if path:
            import pandas as pd
            df = pd.read_csv(LOG_FILE)
            df.to_csv(path, index=False)
            QMessageBox.information(self, "Export Complete", f"Logs exported to:\n{path}")

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
                winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
                html = f"""
                <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
                    <tr style='background:#ffd700;'>
                        <th>Vehicle no</th><th>Tagno.</th><th>TagStatus</th><th>vehicle chassis</th><th>Status</th>
                    </tr>
                    <tr>
                        <td>{plate}</td>
                        <td>{tag_info.get('tag_id', 'N/A')}</td>
                        <td>{tag_info['status']}</td>
                        <td>{tag_info.get('vehicle_class', 'N/A')}</td>
                        <td>₹{tag_info.get('balance', 0.0):.2f}</td>
                    </tr>
                </table>
                """
                self.info_table.setText(html)
                log_entry(plate, "Auto", tag_info["status"], self.user["username"], self.lane)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb_image, rgb_image.shape[1], rgb_image.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def closeEvent(self, event):
        self.cap.release()


class LoginScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Toll Booth Login")
        self.setGeometry(600, 300, 400, 300)
        self.setStyleSheet("""
            QWidget { background-color: #ecf0f1; font-family: 'Segoe UI'; }
            QLabel { font-size: 20px; color: #2c3e50; font-weight: bold; }
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
            QPushButton:hover { background-color: #1f618d; }
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
