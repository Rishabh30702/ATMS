# ✅ Full Toll Booth ANPR App with GUI + Auto Deduction + Manual + FASTag + Icons + Function Keys
import sys
import os
import csv
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QComboBox, QFileDialog, QCheckBox
)
from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon, QKeySequence
import cv2
import easyocr
import re
import winsound
from ultralytics import YOLO

from db import authenticate_user, get_user_lane
from fastag_api import check_fastag, deduct_fastag_amount

BEEP_PATH = os.path.join(os.path.dirname(__file__), "beep.wav")
model = YOLO("best2.pt")
LOG_FILE = "logs.csv"
CAPTURE_FOLDER = "captured"
os.makedirs(CAPTURE_FOLDER, exist_ok=True)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Plate", "Mode", "Status", "User", "Lane"])

def log_entry(plate, mode, status, username, lane):
    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
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
        self.reader = easyocr.Reader(['en'])
        self.cap = cv2.VideoCapture(0)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)
        self.frame_count = 0
        self.last_detected_plate = ""
        self.current_frame = None
        self.vehicle_buttons_map = {}
        self.setup_ui()

    def setup_ui(self):
        vehicle_types = [
            ("Car", "icons/car.jpg", Qt.Key_F1),
            ("Bus", "icons/bus.jpg", Qt.Key_F2),
            ("Truck", "icons/truck.png", Qt.Key_F3),
            ("Auto", "icons/auto.jpg", Qt.Key_F4),
            ("Bike", "icons/bike.jpg", Qt.Key_F5),
            ("Tractor", "icons/tractor.jpg", Qt.Key_F6)
        ]

        self.vehicle_buttons = QHBoxLayout()
        self.vehicle_type = QComboBox()

        for i, (label, path, key) in enumerate(vehicle_types):
            btn = QPushButton(f"{label}\n(F{i+1})")
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(50, 50))
            btn.setFixedSize(90, 90)
            btn.setToolTip(label)
            btn.setStyleSheet("background: white; border: 2px solid #ddd; border-radius: 12px;")
            btn.clicked.connect(lambda _, l=label: self.vehicle_type.setCurrentText(l))
            self.vehicle_buttons.addWidget(btn)
            self.vehicle_buttons_map[key] = label
            self.vehicle_type.addItem(label)

        self.video_label = QLabel()
        self.video_label.setFixedSize(480, 360)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("margin-top: 30px; border: 3px solid #ccc; border-radius: 12px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Auto detected vehicle number")

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Enter Amount")

        self.price_display = QLineEdit()
        self.price_display.setPlaceholderText("Calculated price")
        self.price_display.setReadOnly(True)

        self.no_fastag_checkbox = QCheckBox("Proceed without FASTag (Cash/Invalid Tag)")

        self.info_table = QLabel("""<table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
            <tr style='background:#ffd700;'>
                <th>Vehicle no</th><th>Tagno.</th><th>TagStatus</th><th>vehicle chassis</th><th>Status</th>
            </tr><tr><td colspan='5'>Waiting for detection...</td></tr></table>""")
        self.info_table.setTextFormat(Qt.RichText)

        self.confirm_button = QPushButton("Confirm Transaction")
        self.confirm_button.clicked.connect(self.handle_manual_deduction)

        self.export_button = QPushButton("\U0001F4E4 Export Logs")
        self.export_button.clicked.connect(self.export_logs)

        form_layout = QVBoxLayout()
        form_layout.addWidget(self.plate_input)
        form_layout.addWidget(self.vehicle_type)
        form_layout.addWidget(self.amount_input)
        form_layout.addWidget(self.price_display)
        form_layout.addWidget(self.no_fastag_checkbox)
        form_layout.addWidget(self.info_table)
        form_layout.addWidget(self.confirm_button)
        form_layout.addWidget(self.export_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(self.vehicle_buttons)
        row_layout = QHBoxLayout()
        row_layout.addWidget(self.video_label)
        row_layout.addSpacing(20)
        row_layout.addLayout(form_layout)
        main_layout.addLayout(row_layout)
        self.setLayout(main_layout)

    def keyPressEvent(self, event):
        if event.key() in self.vehicle_buttons_map:
            self.vehicle_type.setCurrentText(self.vehicle_buttons_map[event.key()])

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
        self.current_frame = frame.copy()
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

                toll_amount = 60.0
                if tag_info["status"] == "Valid" and tag_info["balance"] >= toll_amount:
                    success = deduct_fastag_amount(plate, toll_amount)
                    if success:
                        QMessageBox.information(self, "Auto Deduction", f"₹{toll_amount:.2f} deducted from {plate}")
                        if self.current_frame is not None:
                            filename = os.path.join(CAPTURE_FOLDER, f"{plate}_{datetime.now().strftime('%Y%m%d%H%M%S')}_auto.jpg")
                            cv2.imwrite(filename, self.current_frame)
                        log_entry(plate, "Auto", f"Deducted ₹{toll_amount:.2f}", self.user["username"], self.lane)
                    else:
                        QMessageBox.warning(self, "Auto Deduction Failed", "FASTag deduction failed.")
                else:
                    log_entry(plate, "Auto", tag_info["status"], self.user["username"], self.lane)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb_image, rgb_image.shape[1], rgb_image.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def handle_manual_deduction(self):
        plate = self.plate_input.text().strip().upper()
        amount = self.amount_input.text().strip()
        vehicle = self.vehicle_type.currentText()

        if not plate or not amount:
            QMessageBox.warning(self, "Input Error", "Please enter vehicle number and amount.")
            return

        try:
            amount = float(amount)
        except ValueError:
            QMessageBox.warning(self, "Amount Error", "Amount must be a number.")
            return

        tag_info = check_fastag(plate)
        if tag_info['status'] != 'Valid':
            if not self.no_fastag_checkbox.isChecked():
                QMessageBox.warning(self, "FASTag Error",
                    f"FASTag is {tag_info['status']}. Check 'Proceed without FASTag' to allow manual processing.")
                return
            else:
                if self.current_frame is not None:
                    filename = os.path.join(CAPTURE_FOLDER, f"{plate}_{datetime.now().strftime('%Y%m%d%H%M%S')}_manual.jpg")
                    cv2.imwrite(filename, self.current_frame)
                QMessageBox.information(self, "Processed", "Entry logged manually without FASTag.")
                log_entry(plate, "Manual (No Tag)", f"₹{amount:.2f} Cash", self.user['username'], self.lane)
                self.last_detected_plate = ""
                self.frame_count = 0
                return

        if tag_info['balance'] < amount:
            QMessageBox.warning(self, "Balance Error", "Insufficient balance in FASTag.")
            return

        success = deduct_fastag_amount(plate, amount)
        if success:
            QMessageBox.information(self, "Success", f"₹{amount:.2f} deducted successfully from {plate}")
            if self.current_frame is not None:
                filename = os.path.join(CAPTURE_FOLDER, f"{plate}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
                cv2.imwrite(filename, self.current_frame)
            log_entry(plate, "Manual", "Deducted", self.user['username'], self.lane)
            self.last_detected_plate = ""
            self.frame_count = 0
        else:
            QMessageBox.warning(self, "Transaction Failed", "Deduction failed due to unknown error.")

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
        self.title = QLabel("⚧ Toll Booth Login")
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
