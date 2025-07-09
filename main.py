# ✅ Enhanced Toll Booth GUI with ANPR + RFID + FASTag + Auto Deduction + Logs

import sys
import os
import cv2
import re
import winsound
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QComboBox, QFileDialog, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon, QKeyEvent
from ultralytics import YOLO
import easyocr
from db import authenticate_user, get_user_lane, log_entry
from fastag_api import check_fastag, deduct_fastag_amount

BEEP_PATH = os.path.join(os.path.dirname(__file__), "beep.wav")
model = YOLO("best2.pt")
CAPTURE_FOLDER = "captured"
os.makedirs(CAPTURE_FOLDER, exist_ok=True)

PRICING = {
    "Car": 60,
    "Bus": 120,
    "Truck": 150,
    "Auto": 40,
    "Bike": 30,
    "Tractor": 80
}

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
        self.setGeometry(100, 100, 1000, 600)
        self.setup_ui()
        self.reader = easyocr.Reader(['en'])
        self.cap = cv2.VideoCapture(0)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)
        self.frame_count = 0
        self.last_detected_plate = ""
        self.current_frame = None

    def setup_ui(self):
        vehicle_types = [
            ("Car", "icons/car.jpg", "F1"),
            ("Bus", "icons/bus.jpg", "F2"),
            ("Truck", "icons/truck.png", "F3"),
            ("Auto", "icons/auto.jpg", "F4"),
            ("Bike", "icons/bike.jpg", "F5"),
            ("Tractor", "icons/tractor.jpg", "F6")
        ]

        self.vehicle_buttons = QHBoxLayout()
        self.vehicle_btns = {}
        for label, path, key in vehicle_types:
            btn = QPushButton(f"{label}\n[{key}]")
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(80, 80))
            btn.setFixedSize(100, 100)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, t=label: self.select_vehicle(t))
            self.vehicle_buttons.addWidget(btn)
            self.vehicle_btns[key] = label

        self.video_label = QLabel()
        self.video_label.setFixedSize(480, 360)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("border: 3px solid #ccc; border-radius: 12px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Auto detected vehicle number")

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems(PRICING.keys())
        self.vehicle_type.currentTextChanged.connect(self.set_amount_by_vehicle)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Enter Toll Amount")

        self.no_fastag_checkbox = QCheckBox("Proceed without FASTag")

        self.info_table = QLabel("""
            <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
                <tr style='background:#ffd700;'>
                    <th>Vehicle no</th><th>Tagno.</th><th>Status</th><th>Class</th><th>Time</th>
                </tr><tr><td colspan='5'>Waiting for detection...</td></tr></table>
        """)
        self.info_table.setTextFormat(Qt.RichText)

        self.transactions_table = QTableWidget(5, 5)
        self.transactions_table.setHorizontalHeaderLabels(["Plate", "Vehicle", "FASTag", "Operator", "Time"])
        self.transactions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.confirm_button = QPushButton("Confirm Transaction")
        self.confirm_button.clicked.connect(self.handle_transaction)

        self.export_button = QPushButton("Export Logs")
        self.export_button.clicked.connect(self.export_logs)

        form = QVBoxLayout()
        form.addWidget(self.plate_input)
        form.addWidget(self.vehicle_type)
        form.addWidget(self.amount_input)
        form.addWidget(self.no_fastag_checkbox)
        form.addWidget(self.info_table)
        form.addWidget(self.confirm_button)
        form.addWidget(self.export_button)

        right = QVBoxLayout()
        right.addWidget(self.transactions_table)
        right.addLayout(form)

        main = QVBoxLayout()
        main.addLayout(self.vehicle_buttons)
        row = QHBoxLayout()
        row.addWidget(self.video_label)
        row.addLayout(right)
        main.addLayout(row)

        self.setLayout(main)

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return
        self.current_frame = frame.copy()
        self.frame_count += 1
        if self.frame_count % 10 == 0:
            plate, box = detect_plate(self.reader, frame)
            if plate and plate != self.last_detected_plate:
                self.last_detected_plate = plate
                self.plate_input.setText(plate)
                self.handle_auto_deduction(plate)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb, rgb.shape[1], rgb.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def set_amount_by_vehicle(self):
        vehicle = self.vehicle_type.currentText()
        if vehicle in PRICING:
            self.amount_input.setText(str(PRICING[vehicle]))

    def select_vehicle(self, vehicle):
        index = self.vehicle_type.findText(vehicle)
        if index >= 0:
            self.vehicle_type.setCurrentIndex(index)

    def handle_auto_deduction(self, plate):
        tag_info = check_fastag(plate)
        winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
        now = datetime.now().strftime("%H:%M:%S")

        html = f"""
        <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
            <tr style='background:#ffd700;'>
                <th>Vehicle no</th><th>Tagno.</th><th>Status</th><th>Class</th><th>Time</th>
            </tr>
            <tr>
                <td>{plate}</td>
                <td>{tag_info.get('tag_id', 'N/A')}</td>
                <td>{tag_info['status']}</td>
                <td>{tag_info.get('vehicle_class', 'N/A')}</td>
                <td>{now}</td>
            </tr>
        </table>"""
        self.info_table.setText(html)

        if tag_info['status'] == 'Valid':
            amount = PRICING.get(tag_info.get('vehicle_class', 'Car'), 60)
            if tag_info['balance'] >= amount:
                deduct_fastag_amount(plate, amount)
                self.capture_image(plate)
                log_entry(plate, tag_info.get('vehicle_class', 'Car'), tag_info['status'], self.user['username'], self.lane)
                self.update_transactions(plate, tag_info.get('vehicle_class', 'Car'), tag_info['status'])

    def handle_transaction(self):
        plate = self.plate_input.text().strip().upper()
        amount = self.amount_input.text().strip()
        vehicle = self.vehicle_type.currentText()
        if not plate or not amount:
            QMessageBox.warning(self, "Missing Info", "Enter plate and amount.")
            return
        try:
            amount = float(amount)
        except:
            QMessageBox.warning(self, "Invalid Amount", "Amount must be a number.")
            return

        tag_info = check_fastag(plate)
        if tag_info['status'] != 'Valid' and not self.no_fastag_checkbox.isChecked():
            QMessageBox.warning(self, "FASTag Error", "FASTag invalid. Select 'Proceed without FASTag'.")
            return

        if tag_info['status'] == 'Valid' and tag_info['balance'] >= amount:
            deduct_fastag_amount(plate, amount)
        self.capture_image(plate)
        log_entry(plate, vehicle, tag_info['status'], self.user['username'], self.lane)
        self.update_transactions(plate, vehicle, tag_info['status'])

    def capture_image(self, plate):
        if self.current_frame is not None:
            filename = os.path.join(CAPTURE_FOLDER, f"{plate}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg")
            cv2.imwrite(filename, self.current_frame)

    def update_transactions(self, plate, vehicle, status):
        row = [plate, vehicle, status, self.user['username'], datetime.now().strftime("%H:%M:%S")]
        self.transactions_table.insertRow(0)
        for col, val in enumerate(row):
            self.transactions_table.setItem(0, col, QTableWidgetItem(str(val)))
        if self.transactions_table.rowCount() > 5:
            self.transactions_table.removeRow(5)

    def export_logs(self):
        QMessageBox.information(self, "Info", "All logs stored in local SQLite logs.db")

    def keyPressEvent(self, event: QKeyEvent):
        keys = {
            Qt.Key_F1: "Car",
            Qt.Key_F2: "Bus",
            Qt.Key_F3: "Truck",
            Qt.Key_F4: "Auto",
            Qt.Key_F5: "Bike",
            Qt.Key_F6: "Tractor"
        }
        if event.key() in keys:
            self.select_vehicle(keys[event.key()])

    def closeEvent(self, event):
        self.cap.release()

class LoginScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🚧 Toll Booth Login")
        self.setFixedSize(400, 350)
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f6fa;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel#title {
                font-size: 24px;
                color: #2c3e50;
                font-weight: bold;
            }
            QLineEdit {
                padding: 12px;
                border: 2px solid #dcdde1;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton {
                padding: 12px;
                background-color: #273c75;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #192a56;
            }
        """)
        self.init_ui()

    def init_ui(self):
        self.title = QLabel("🚧 Toll Booth Login")
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignCenter)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter Username")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter Password")
        self.password_input.setEchoMode(QLineEdit.Password)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.login)

        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        layout.addWidget(self.title)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(self.login_button)

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

if __name__ == '__main__':
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
