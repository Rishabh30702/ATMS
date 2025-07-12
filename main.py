import sys
import os
import cv2
import re
import winsound
import threading
import serial  # Requires pyserial
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QComboBox,
    QFileDialog,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon, QKeyEvent
from ultralytics import YOLO
import easyocr
from db import authenticate_user, get_user_lane, log_entry
from fastag_api import check_fastag, deduct_fastag_amount
import serial.tools.list_ports

BEEP_PATH = os.path.join(os.path.dirname(__file__), "beep.wav")
CAPTURE_FOLDER = "captured"
os.makedirs(CAPTURE_FOLDER, exist_ok=True)
model = YOLO("best2.pt")

PRICING = {"Car": 60, "Bus": 120, "Truck": 150, "Auto": 40, "Bike": 30, "Tractor": 80}


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


def find_rfid_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        print(f"Detected: {port.device} - {port.description}")
        # You can adjust based on your device's description
        if "USB" in port.description or "Serial" in port.description:
            return port.device  # e.g., "COM3"
    return None


def start_rfid_listener(self, port):
    def listen():
        try:
            ser = serial.Serial(port, 9600, timeout=1)
            while True:
                tag = ser.readline().decode().strip()
                if tag:
                    print(f"📶 RFID Tag Read: {tag}")
                    self.handle_rfid_tag(tag)
        except Exception as e:
            print("RFID Error:", e)

    threading.Thread(target=listen, daemon=True).start()


class TollApp(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lane = get_user_lane(user["username"])
        self.relay_mode = None  # 'gpio', 'serial', or None
        self.setup_boom_control()
        self.setWindowTitle(f"Toll Booth - Lane {self.lane}")
        self.setGeometry(100, 100, 1000, 600)
        self.anpr_status = QLabel("ANPR: Detecting...")
        self.rfid_status = QLabel("RFID: Listening...")
        self.anpr_status.setStyleSheet("color: green; font-weight: bold;")
        self.rfid_status.setStyleSheet("color: blue; font-weight: bold;")

        self.boom_status = QLabel("🔴 Boom: Closed")
        self.boom_status.setStyleSheet("color: red; font-weight: bold;")

        self.setup_ui()  # Now it's safe to use these labels
        self.setup_boom_control()

        self.reader = easyocr.Reader(["en"], gpu=True)
        self.cap = cv2.VideoCapture(0)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)
        self.frame_count = 0
        self.last_detected_plate = ""
        self.current_frame = None

        rfid_port = find_rfid_port()
        if rfid_port:
            self.start_rfid_listener(rfid_port)
        else:
            print("⚠️ No RFID COM port found.")

    def setup_ui(self):
        vehicle_types = [
            ("Car", "icons/car.jpg", "F1"),
            ("Bus", "icons/bus.jpg", "F2"),
            ("Truck", "icons/truck.png", "F3"),
            ("Auto", "icons/auto.jpg", "F4"),
            ("Bike", "icons/bike.jpg", "F5"),
            ("Tractor", "icons/tractor.jpg", "F6"),
        ]
        self.vehicle_buttons = QHBoxLayout()
        self.vehicle_btns = {}
        for label, path, key in vehicle_types:
            btn = QPushButton(f"{label}\\n[{key}]")
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(80, 80))
            btn.setFixedSize(140, 100)
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

        self.info_table = QLabel("Waiting for detection...")
        self.info_table.setTextFormat(Qt.RichText)

        self.transactions_table = QTableWidget(5, 5)
        self.transactions_table.setHorizontalHeaderLabels(
            ["Plate", "Vehicle", "FASTag", "Operator", "Time"]
        )
        self.transactions_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        self.confirm_button = QPushButton("Confirm Transaction")
        self.confirm_button.clicked.connect(self.handle_transaction)

        self.export_button = QPushButton("Export Logs")
        self.export_button.clicked.connect(self.export_logs)

        self.test_boom_button = QPushButton("Test Boom")
        self.test_boom_button.clicked.connect(lambda: self.toggle_boom(True))

        form = QVBoxLayout()
        form.addWidget(self.plate_input)
        form.addWidget(self.vehicle_type)
        form.addWidget(self.amount_input)
        form.addWidget(self.no_fastag_checkbox)
        form.addWidget(self.info_table)
        form.addWidget(self.confirm_button)
        form.addWidget(self.export_button)
        form.addWidget(self.test_boom_button)

        right = QVBoxLayout()
        right.addWidget(self.transactions_table)
        right.addLayout(form)

        # -------- Header Layout --------
        header_layout = QHBoxLayout()
        
        company_label = QLabel("🚗 <b>Valliento Tech</b>")
        company_label.setStyleSheet("font-size: 20px; color: #273c75; font-weight: bold;")
        
        vendor_label = QLabel("🔧 Powered by XYZ Solutions")
        vendor_label.setStyleSheet("font-size: 13px; color: #7f8c8d; margin left: 10px;")
        
        lane_label = QLabel(f"🛣️ Lane: {self.lane}")
        lane_label.setStyleSheet("font-size: 13px; color: #2d3436;")
        
        header_info = QVBoxLayout()
        header_info.addWidget(company_label)
        header_info.addWidget(vendor_label)
        header_info.addWidget(lane_label)
        
        header_layout.addLayout(header_info)
        header_layout.addStretch()
    

        main = QVBoxLayout()
        main.addLayout(header_layout)
        main.addLayout(self.vehicle_buttons)
        row = QHBoxLayout()
        row.addWidget(self.video_label)
        row.addLayout(right)

        status_layout = QHBoxLayout()
        status_layout.addWidget(self.anpr_status)
        status_layout.addWidget(self.rfid_status)

        status_layout.addWidget(self.boom_status)

        main.addLayout(status_layout)

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

        if tag_info["status"] == "Valid":
            amount = PRICING.get(tag_info.get("vehicle_class", "Car"), 60)
            if tag_info["balance"] >= amount:
                deduct_fastag_amount(plate, amount)
                self.capture_image(plate)
                log_entry(
                    plate,
                    tag_info.get("vehicle_class", "Car"),
                    tag_info["status"],
                    self.user["username"],
                    self.lane,
                )
                self.update_transactions(
                    plate, tag_info.get("vehicle_class", "Car"), tag_info["status"]
                )

        self.info_table.setText(
            f"<b>Plate:</b> {plate} | <b>Status:</b> {tag_info['status']} | <b>Balance:</b> ₹{tag_info.get('balance', 0)}"
        )

    def toggle_boom(self, open_boom=True):
        if open_boom:
            self.boom_status.setText("🟢 Boom: Open")
            self.boom_status.setStyleSheet("color: green; font-weight: bold;")
            print("🚧 Boom barrier opened!")

            if hasattr(self, "gpio_mode") and self.gpio_mode:
                self.GPIO.output(self.BOOM_PIN, self.GPIO.HIGH)
            elif hasattr(self, "relay_serial") and self.relay_serial:
                self.relay_serial.write(b"O")  # Open command
        else:
            self.boom_status.setText("🔴 Boom: Closed")
            self.boom_status.setStyleSheet("color: red; font-weight: bold;")
            print("🚧 Boom barrier closed!")

            if hasattr(self, "gpio_mode") and self.gpio_mode:
                self.GPIO.output(self.BOOM_PIN, self.GPIO.LOW)
            elif hasattr(self, "relay_serial") and self.relay_serial:
                self.relay_serial.write(b"C")  # Close command

        # Auto-close after 3 seconds
        QTimer.singleShot(3000, lambda: self.toggle_boom(False))

    def handle_rfid_tag(self, tag):
        self.plate_input.setText(tag.upper())
        tag_info = check_fastag(tag)

        winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)

        now = datetime.now().strftime("%H:%M:%S")

        if tag_info["status"] == "Valid":
            amount = PRICING.get(tag_info.get("vehicle_class", "Car"), 60)
            if tag_info["balance"] >= amount:
                deduct_fastag_amount(tag, amount)
                self.capture_image(tag)
                log_entry(
                    tag,
                    tag_info.get("vehicle_class", "Car"),
                    tag_info["status"],
                    self.user["username"],
                    self.lane,
                )
                self.update_transactions(
                    tag, tag_info.get("vehicle_class", "Car"), tag_info["status"]
                )

        self.info_table.setText(
            f"<b>Plate:</b> {tag} | <b>Status:</b> {tag_info['status']} | "
            f"<b>Balance:</b> ₹{tag_info.get('balance', 0)} | "
            f"<b>Class:</b> {tag_info.get('vehicle_class', 'Unknown')} | "
            f"<b>Tag ID:</b> {tag_info.get('tag_id', 'N/A')}"
        )

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
        winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
        now = datetime.now().strftime("%H:%M:%S")

        if tag_info["status"] != "Valid" and not self.no_fastag_checkbox.isChecked():
            QMessageBox.warning(
                self, "FASTag Error", "FASTag invalid. Select 'Proceed without FASTag'."
            )
            return

        if tag_info["status"] == "Valid":
            if tag_info["balance"] >= amount:
                deduct_fastag_amount(plate, amount)
                self.capture_image(plate)
                log_entry(
                    plate, vehicle, tag_info["status"], self.user["username"], self.lane
                )
                self.update_transactions(plate, vehicle, tag_info["status"])

                # ✅ Show success message
                QMessageBox.information(
                    self,
                    "FASTag Deducted",
                    f"₹{amount} deducted from {tag_info['tag_id']}.\nNew Balance: ₹{tag_info['balance']:.2f}",
                )

                # ✅ Simulate Boom Gate Opening
                print("🚦 Boom gate OPEN (manual confirm)")

                # ✅ Optional: Voice feedback
                if hasattr(self, "tts"):
                    self.tts.say(f"{amount} rupees deducted from FASTag.")
                    self.tts.runAndWait()

            else:
                QMessageBox.warning(
                    self,
                    "Insufficient Balance",
                    f"Balance ₹{tag_info['balance']} is less than required ₹{amount}.",
                )
                return

        else:
            # Manual override transaction
            self.capture_image(plate)
            log_entry(plate, vehicle, "Manual", self.user["username"], self.lane)
            self.update_transactions(plate, vehicle, "Manual")
            QMessageBox.information(
                self, "Manual Transaction", f"Manual transaction logged for {plate}."
            )

            # ✅ Optional: Simulate boom for manual override
            print("🚦 Boom gate OPEN (manual override)")

    def setup_boom_control(self):
        # Try Raspberry Pi GPIO first
        try:
            import RPi.GPIO as GPIO

            self.GPIO = GPIO
            self.gpio_mode = True
            GPIO.setmode(GPIO.BCM)
            self.BOOM_PIN = 18
            GPIO.setup(self.BOOM_PIN, GPIO.OUT)
            GPIO.output(self.BOOM_PIN, GPIO.LOW)
            print("✅ GPIO Boom setup complete.")
        except ImportError:
            self.gpio_mode = False
            print("❌ GPIO not available, trying serial relay...")

            try:
                self.relay_serial = serial.Serial(
                    "COM4", 9600, timeout=1
                )  # Change COM4 if needed
                print("✅ Serial relay connected.")
            except Exception as e:
                print(f"❌ Serial relay not available: {e}")
                self.relay_serial = None

    def capture_image(self, plate):
        if self.current_frame is not None:
            filename = os.path.join(
                CAPTURE_FOLDER,
                f"{plate}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
            )
            cv2.imwrite(filename, self.current_frame)

    def update_transactions(self, plate, vehicle, status):
        row = [
            plate,
            vehicle,
            status,
            self.user["username"],
            datetime.now().strftime("%H:%M:%S"),
        ]
        self.transactions_table.insertRow(0)
        for col, val in enumerate(row):
            self.transactions_table.setItem(0, col, QTableWidgetItem(str(val)))
        if self.transactions_table.rowCount() > 5:
            self.transactions_table.removeRow(5)

    def export_logs(self):
        QMessageBox.information(self, "Info", "All logs are stored in logs.db")

    def keyPressEvent(self, event: QKeyEvent):
        keys = {
            Qt.Key_F1: "Car",
            Qt.Key_F2: "Bus",
            Qt.Key_F3: "Truck",
            Qt.Key_F4: "Auto",
            Qt.Key_F5: "Bike",
            Qt.Key_F6: "Tractor",
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
        self.setStyleSheet(
            """
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
        """
        )
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
