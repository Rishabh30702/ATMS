import random
import sys
import os
import cv2
import re
from sync_worker import start_sync_thread
import winsound
import threading
import time
import json
from loop_listener import LoopListener
from rfid_listener import RFIDListener
from log_helper import insert_log, insert_rfid_log
import glob
from log_helper import insert_log
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
    QTextEdit,
    QFormLayout,
    QGroupBox
)
import numpy as np
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem
from rfid_listener import RFIDListener

from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon, QKeyEvent
from ultralytics import YOLO
import easyocr
from db import authenticate_user, get_user_lane, log_entry
from fastag_api import check_fastag, deduct_fastag_amount,FASTAG_DATABASE
import serial.tools.list_ports
from incident_recorder import record_incident_clip
from camera_manager import MultiCameraManager

BEEP_PATH = os.path.join(os.path.dirname(__file__), "beep.wav")
CAPTURE_FOLDER = "captured"
os.makedirs(CAPTURE_FOLDER, exist_ok=True)
model = YOLO("best2.pt")

def clean_old_images(folder, days=15):
    """Deletes .jpg images older than the given number of days in the specified folder."""
    cutoff = time.time() - (days * 86400)
    for filepath in glob.glob(os.path.join(folder, "*.jpg")):
        if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff:
            try:
                os.remove(filepath)
                print(f"🗑️ Deleted old image: {filepath}")
            except Exception as e:
                print(f"⚠️ Failed to delete {filepath}: {e}")

PRICING = {"Car": 60, "Bus": 120, "Truck": 150, "Auto": 40, "Bike": 30, "Tractor": 80}

def find_relay_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = port.description.lower()
        if "relay" in desc or "usb" in desc or "serial" in desc:
            print(f"🔌 Potential Relay Port Detected: {port.device} - {port.description}")
            return port.device
    return None


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
        self.last_cleanup = None
        self.user = user
        self.cam_index = None
        self.camera_manager = MultiCameraManager()
        self.cap = None  # For vehicle camera
        self.incident_cap = None  # ✅ For incident camera
        self.loop_listener = LoopListener(callback=self.on_loop_detected)
        self.loop_listener.start()
        self.lane = get_user_lane(user["username"])
        self.relay_mode = None  # 'gpio', 'serial', or None
        self.setup_boom_control()
        self.setWindowTitle(f"Toll Booth - Lane {self.lane}")
        self.setGeometry(100, 100, 1000, 600)
        self.anpr_status = QLabel("ANPR: Detecting...")
        self.rfid_status = QLabel("RFID: Listening...")
        self.anpr_status.setStyleSheet("color: green; font-weight: bold;")
        self.rfid_status.setStyleSheet("color: blue; font-weight: bold;")
        self.last_rfid_time = time.time()
        self.rfid_status.setText("RFID: Not Connected")
        self.rfid_status.setStyleSheet("color: red; font-weight: bold;")

        self.rfid_timer = QTimer()
        self.rfid_timer.timeout.connect(self.check_rfid_status)
        self.rfid_timer.start(2000)  # every 2 seconds
        
        # Start RFID listener
        self.rfid_thread = RFIDListener(on_tag_callback=self.handle_rfid_tag)
        self.rfid_thread.start()


        self.boom_status = QLabel("🔴 Boom: Closed")
        self.boom_status.setStyleSheet("color: red; font-weight: bold;")

        self.setup_ui()  # Now it's safe to use these labels

        self.reader = easyocr.Reader(["en"], gpu=True)
        self.cap = self.camera_manager.get_camera()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)
        self.frame_count = 0
        self.last_detected_plate = ""
        self.current_frame = None

        self.incident_timer = QTimer()
        self.incident_timer.timeout.connect(self.update_incident_frame)
        self.incident_timer.start(100)

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
            btn = QPushButton(f"{key}")
            btn.setIcon(QIcon(path))
            btn.setIconSize(QSize(80, 80))
            btn.setFixedSize(140, 100)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _, t=label: self.select_vehicle(t))
            self.vehicle_buttons.addWidget(btn)
            self.vehicle_btns[key] = label

        self.video_label = QLabel()
        self.video_label.setFixedSize(460, 220)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("border: 3px solid #FFD700; margin-top: 0px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Auto detected vehicle number")

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems(PRICING.keys())
        self.vehicle_type.currentTextChanged.connect(self.set_amount_by_vehicle)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Enter Toll Amount")
        self.set_amount_by_vehicle()

                       # Non-editable backend-driven fields
        self.pass_type_input = QLineEdit("Single Pass")
        self.pass_type_input.setReadOnly(True)
        
        self.payment_method_input = QLineEdit("ETC")
        self.payment_method_input.setReadOnly(True)
        
        self.exemption_type_input = QLineEdit("")
        self.exemption_type_input.setReadOnly(True)
        
        self.base_weight_input = QLineEdit("19432")
        self.base_weight_input.setReadOnly(True)
        
        self.wim_weight_input = QLineEdit("0")
        self.wim_weight_input.setReadOnly(True)
        
        self.axle_count_input = QLineEdit("0")
        self.axle_count_input.setReadOnly(True)
        
        self.fare_input = QLineEdit("0")
        self.fare_input.setReadOnly(True)
        
        self.penalty_input = QLineEdit("0")
        self.penalty_input.setReadOnly(True)
        
        self.total_amount_input = QLineEdit("Rs. 0")
        self.total_amount_input.setReadOnly(True)
        self.total_amount_input.setStyleSheet("font-weight: bold; font-size: 16px; color: #FFD700;")
        
       # --- Structured form layout moved to right panel ---
        form_layout = QFormLayout()
        form_layout.addRow("Pass Type", self.pass_type_input)
        form_layout.addRow("Payment Method", self.payment_method_input)
        form_layout.addRow("Exemption Type", self.exemption_type_input)
        form_layout.addRow("Base Weight", self.base_weight_input)
        form_layout.addRow("WIM Weight", self.wim_weight_input)
        form_layout.addRow("Axle Count", self.axle_count_input)
        form_layout.addRow("Fare", self.fare_input)
        form_layout.addRow("Penalty", self.penalty_input)
        form_layout.addRow("Total Amount", self.total_amount_input)
        
        # --- Main Form (center section as before) ---
        self.info_table = QLabel("Waiting for detection...")
        self.info_table.setTextFormat(Qt.RichText)
        self.no_fastag_checkbox = QCheckBox("Proceed without FASTag") 
        self.confirm_button = QPushButton("FINISH")
        self.confirm_button.clicked.connect(self.cancel_transaction)

        self.export_button = QPushButton("RESTART")
        self.export_button.clicked.connect(self.restart_form)

        self.test_boom_button = QPushButton("SIMULATE")
        form = QVBoxLayout()
        form.addWidget(self.plate_input)
        form.addWidget(self.vehicle_type)
        form.addWidget(self.amount_input)
        form.addWidget(self.no_fastag_checkbox)
        form.addWidget(self.info_table)
        form.addWidget(self.confirm_button)
        form.addWidget(self.export_button)
        form.addWidget(self.test_boom_button)
        
        self.plate_input.setFixedHeight(40)
        self.amount_input.setFixedHeight(40)
        self.vehicle_type.setFixedHeight(40)
        
        # --- Center Block (transactions + form) ---
        # Transactions Table (add this before right.addWidget)
        self.transactions_table = QTableWidget()
        self.transactions_table.setColumnCount(5)
        self.transactions_table.setHorizontalHeaderLabels(["Time", "Plate", "Type", "Amount", "FASTag"])
        self.transactions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.transactions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.transactions_table.setMaximumHeight(150)
        right = QVBoxLayout()
        right.addWidget(self.transactions_table)
        right.addLayout(form)
        
        # --- Right Panel: Detailed Info Fields ---
        info_right = QVBoxLayout()
        vehicle_info_group = QGroupBox("Vehicle Info")
        vehicle_info_group.setLayout(form_layout)
        vehicle_info_group.setStyleSheet("border: 2px solid #FFD700; padding: 6px;")  # Golden border
        info_right.addWidget(vehicle_info_group)
        
        # --- Top Header Row (Company & Vendor) ---
        header_layout = QHBoxLayout()

        logo_label = QLabel()
        logo_pixmap = QPixmap("icons/vallenlogo.jpg")
        logo_pixmap = logo_pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(logo_pixmap)
        
        company_name = QLabel("Valliento Tech")
        company_name.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        
        company_layout = QHBoxLayout()
        company_layout.addWidget(logo_label)
        company_layout.addWidget(company_name)
        company_layout.setAlignment(Qt.AlignLeft)
        
        company_label = QLabel("")
        company_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50; border: 1px solid #2c3e50; padding: 4px;")
        vendor_label = QLabel("🔧 XYZ Solutions")
        vendor_label.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        
        header_layout.addLayout(company_layout)
        header_layout.addStretch()
        header_layout.addWidget(vendor_label)
        header_layout.addWidget(company_label)
        header_layout.addStretch()
        header_layout.addWidget(vendor_label)
        
        # --- Main Layout Assembly ---
        main = QVBoxLayout()
        main.addLayout(header_layout)
        
        lane_title = QLabel(f"🚧 Toll Booth - Lane {self.lane}")
        lane_title.setAlignment(Qt.AlignCenter)
        lane_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #273c75;")
        main.addWidget(lane_title)
        main.addLayout(self.vehicle_buttons)
        
        # --- Horizontal Layout: Left (video), Middle (form+logs), Right (detailed info) ---
        # Incident camera label and view
        self.incident_camera_title = QLabel("Incident Camera")
        self.incident_camera_title.setStyleSheet("font-weight: bold; font-size: 14px; margin-top: 8px;")
        
        self.incident_camera_view = QLabel("Incident Camera")
        self.incident_camera_view.setFixedSize(460, 160)
        self.incident_camera_view.setAlignment(Qt.AlignCenter)
        self.incident_camera_view.setStyleSheet("border: 2px solid red;")

        vehicle_camera_label = QLabel("Vehicle Camera")
        vehicle_camera_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 5px;")


        left_camera_column = QVBoxLayout()
        left_camera_column.addWidget(vehicle_camera_label)
        left_camera_column.addWidget(self.video_label)
        left_camera_column.addWidget(self.incident_camera_title)
        left_camera_column.addWidget(self.incident_camera_view)

        row = QHBoxLayout()
        row.addLayout(left_camera_column)
        row.addLayout(right)
        row.addLayout(info_right)
        main.addLayout(row)
        
        # --- Status Row ---
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.anpr_status)
        status_layout.addWidget(self.rfid_status)
        status_layout.addWidget(self.boom_status)
        main.addLayout(status_layout)
        
       # --- Bottom Icons: Right-Aligned Status Icons ---
        bottom_icon_container = QHBoxLayout()
        bottom_icon_container.addStretch()  # Push icons to the right

        # Boom icon
        self.boom_icon = QLabel()
        self.boom_icon.setPixmap(QPixmap("icons/boomclose.jpg").scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.boom_icon.setToolTip("Boom Barrier")
        bottom_icon_container.addWidget(self.boom_icon)

        # Indicator icon
        self.indicator_icon = QLabel()
        self.indicator_icon.setPixmap(QPixmap("icons/indicatorOff.jpg").scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.indicator_icon.setToolTip("Indicator Lights")
        bottom_icon_container.addWidget(self.indicator_icon)

        # Camera icon
        self.camera_icon = QLabel()
        self.camera_icon.setPixmap(QPixmap("icons/camOff.jpg").scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.camera_icon.setToolTip("Camera Active")
        bottom_icon_container.addWidget(self.camera_icon)

        # Add bottom_icon_container at the very bottom of the main layout
        main.addLayout(bottom_icon_container)

        
        # --- Set Layout + Resize Window ---
        self.setLayout(main)
        main.setContentsMargins(10, 10, 10, 50) # (left, top, right, bottom)
        self.showMaximized()
         # 🔲 DARK THEME
        self.setStyleSheet("""
        QWidget {
            background-color: #2e2e2e;
            color: white;
            font-size: 14px;
        }
        QLineEdit, QComboBox, QTableWidget, QCheckBox {
            background-color: #1E1E1E;
            border: 1px solid #444;
            padding: 4px;
        }
        QPushButton {
            background-color: #2E2E2E;
            border: 1px solid #666;
            padding: 6px 12px;
            border-radius: 5px;
        }
        QPushButton:hover {
            background-color: #3C3C3C;
        }
        QTableWidget QHeaderView::section {
            background-color: #2A2A2A;
            color: white;
            padding: 4px;
            border: 1px solid #444;
        }
    """)

    def restart_form(self):
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def record_incident_clip(self, duration=5, fps=20):
        incident_index = self.camera_manager.cameras.get("incident_camera")
        if incident_index is None:
            print("⚠️ Incident camera not found in config.")
            return
    
        cap = cv2.VideoCapture(incident_index)
        if not cap.isOpened():
            print("❌ Incident camera could not be opened.")
            return
    
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
    
        os.makedirs("clips", exist_ok=True)
        filename = datetime.now().strftime("incident_%Y%m%d_%H%M%S.avi")
        filepath = os.path.join("clips", filename)
    
        out = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
        frame_count = int(duration * fps)
    
        print(f"📹 Recording incident clip to {filepath}...")
    
        try:
            for _ in range(frame_count):
                ret, frame = cap.read()
                if not ret:
                    print("⚠️ Failed to read frame from incident camera.")
                    break
                
                # Optional: overlay timestamp
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cv2.putText(frame, timestamp, (10, height - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
                out.write(frame)
                time.sleep(1.0 / fps)  # optional: pacing for stability
        finally:
            cap.release()
            out.release()
    
        print(f"✅ Incident clip saved: {filepath}")




    def cancel_transaction(self):
     # Clear input fields
     self.plate_input.clear()
     self.amount_input.clear()
     self.base_weight_input.clear()
     self.wim_weight_input.clear()
     self.axle_count_input.clear()
     self.fare_input.clear()
     self.penalty_input.clear()
     self.total_amount_input.clear()

     # Uncheck checkboxes safely
     if hasattr(self, "fastag_checkbox") and self.fastag_checkbox:
         self.fastag_checkbox.setChecked(False)
     if hasattr(self, "no_fastag_checkbox") and self.no_fastag_checkbox:
         self.no_fastag_checkbox.setChecked(False)

     # Optionally update in-app info label
     if hasattr(self, "info_label"):
         self.info_label.setText("❌ Transaction cancelled.")
     else:
         # Fallback: show message box
         QMessageBox.information(
             self,
             "Transaction Cancelled",
             "❌ The current transaction has been cancelled.",
             QMessageBox.Ok
         )




    def populate_vehicle_fields(self, identifier):
        data = check_fastag(identifier)
    
        if isinstance(data, dict):
            if data.get("plate"):
                self.plate_input.setText(data.get("plate"))
    
            self.pass_type_input.setText(data.get("pass_type", ""))
            self.payment_method_input.setText(data.get("payment_method", ""))
            self.exemption_type_input.setText(data.get("exemption_type", ""))
            self.base_weight_input.setText(data.get("base_weight", ""))
            self.wim_weight_input.setText(data.get("wim_weight", ""))
            self.axle_count_input.setText(data.get("axle_count", ""))
            self.fare_input.setText(data.get("fare", ""))
            self.penalty_input.setText(data.get("penalty", ""))
            self.total_amount_input.setText("Rs. " + data.get("total_amount", "0"))
    
        else:
            # If data is just a plate string, at least show it
            self.plate_input.setText(str(data))
            self.info_table.setText("<font color='red'>No detailed FASTag data found.</font>")


    def verify_fastag(self, plate_number=None, tag_id=None):
        # If plate is available, prefer it
        if plate_number:
            fastag_info = check_fastag(plate_number)
            if fastag_info["status"] == "Valid":
                return fastag_info
        # Else fallback to RFID tag
        elif tag_id:
            # Simulate checking via tag_id (you can add reverse mapping logic here if needed)
            for number, info in FASTAG_DATABASE.items():
                if info["tag_id"] == tag_id:
                    if info["status"] == "Valid":
                        return info
        return None


    def log_event(self, event, tag_id=None, image_path=None, plate_number=None, vehicle_class=None, balance=None):
        print(f"[LOG] Event: {event}")
        print(f"      Plate: {plate_number}, Tag ID: {tag_id}, Class: {vehicle_class}, Balance: {balance}")

        # Determine FASTag status
        if balance is None:
            fastag_status = "unknown"
        elif balance >= 100:
            fastag_status = "valid"
        elif 0 < balance < 100:
            fastag_status = "low balance"
        else:
            fastag_status = "invalid"

        # Fallback values
        plate = plate_number or "Unknown"
        v_type = vehicle_class or "Unknown"
        operator = self.logged_in_user.get("username", "unknown")
        lane_id = self.logged_in_user.get("lane_id", "0")

        try:
            # Log into SQLite
            log_entry(plate, v_type, fastag_status, operator, lane_id)
            print("✅ Event logged to SQLite using db.py")

            # Update GUI table
            self.update_transactions(plate, v_type, fastag_status)

            # Emit signal to update any listeners
            self.vehicleLogged.emit({
                "plate": plate,
                "vehicle_type": v_type,
                "fastag_status": fastag_status,
                "operator": operator,
                "lane_id": lane_id
            })

        except Exception as e:
             print("❌ Failed to log event:", e)


    
    def on_loop_detected(self):
        print("🚗 Vehicle on loop — detected inside MainWindow")

        image_path = self.capture_image("from_loop")

        plate_number = getattr(self, 'last_plate_number', None)
        tag_id = getattr(self, 'last_fastag_id', None)

        fastag_info = self.verify_fastag(plate_number=plate_number, tag_id=tag_id)

        if fastag_info:
            toll_amount = 50  # Or fetch from some config based on vehicle_class

            success = deduct_fastag_amount(plate_number or tag_id, toll_amount)
            if success:
                print("✅ Toll deducted and barrier opened")
                self.open_barrier()
                self.log_event(
                    f"FASTag OK - ₹{toll_amount} deducted",
                    fastag_info["tag_id"],
                    image_path,
                    plate_number,
                    fastag_info["vehicle_class"],
                    fastag_info["balance"]
                )
            else:
                print("❌ FASTag balance too low")
                self.log_event(
                    "FASTag valid but insufficient balance",
                    fastag_info["tag_id"],
                    image_path,
                    plate_number,
                    fastag_info["vehicle_class"],
                    fastag_info["balance"]
                )
        else:
            print("🚫 No valid FASTag found")
            self.log_event(
                "No valid FASTag",
                tag_id,
                image_path,
                plate_number
            )

    

    def check_rfid_status(self):
        now = time.time()
        if now - self.last_rfid_time < 5:
            self.rfid_status.setText("RFID: Active")
            self.rfid_status.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.rfid_status.setText("RFID: Not Connected")
            self.rfid_status.setStyleSheet("color: red; font-weight: bold;")
    
    
    def capture_image(self, plate=None):
        if self.current_frame is None:
            print("⚠️ No frame to capture.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{timestamp}"
        if plate:
            filename = f"{plate}_{timestamp}"
        path = os.path.join("captures", f"{filename}.jpg")

        os.makedirs("captures", exist_ok=True)
        cv2.imwrite(path, self.current_frame)
        print(f"📸 Image saved to {path}")
         # 🔁 Automatically start incident recording
        threading.Thread(target=self.record_incident_clip).start()


    def update_frame(self):
        if self.cap is None or not self.cap.isOpened():
            self.cap = self.camera_manager.get_camera("vehicle_camera")  # explicitly specify

        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.current_frame = frame.copy()
            else:
                print("⚠️ Failed to read from camera. Showing blank.")
                self.current_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            print("⚠️ No camera found. Showing blank.")
            self.current_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        self.frame_count += 1

        if self.frame_count % 10 == 0:
            plate, box = detect_plate(self.reader, self.current_frame)

            if plate:
                if plate != self.last_detected_plate or time.time() - getattr(self, 'last_plate_time', 0) > 3:
                    self.last_detected_plate = plate
                    self.last_plate_time = time.time()

                    self.plate_input.setText(plate)

                    tag_info = check_fastag(plate)
                    vehicle_class = tag_info.get("vehicle_class", "Car")

                    if vehicle_class in PRICING:
                        index = self.vehicle_type.findText(vehicle_class)
                        if index != -1:
                            self.vehicle_type.setCurrentIndex(index)

                    self.handle_auto_deduction_with_taginfo(plate, tag_info)

        rgb = cv2.cvtColor(self.current_frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb, rgb.shape[1], rgb.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def update_incident_frame(self):
        if self.incident_cap is None or not self.incident_cap.isOpened():
            self.incident_cap = self.camera_manager.get_camera("incident_camera")
            if not self.incident_cap or not self.incident_cap.isOpened():
                self.incident_camera_view.setText("❌ Incident Camera not available")
                return
    
        ret, frame = self.incident_cap.read()
        if not ret or frame is None:
            return
    
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb, rgb.shape[1], rgb.shape[0], QImage.Format_RGB888)
        self.incident_camera_view.setPixmap(QPixmap.fromImage(image))


    def set_amount_by_vehicle(self):
        vehicle = self.vehicle_type.currentText()
        if vehicle in PRICING:
            self.amount_input.setText(str(PRICING[vehicle]))

    def select_vehicle(self, vehicle):
        index = self.vehicle_type.findText(vehicle)
        if index >= 0:
            self.vehicle_type.setCurrentIndex(index)

    def handle_auto_deduction_with_taginfo(self, plate, tag_info):
        winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)

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

                # ✅ Populate vehicle details in UI
            self.populate_vehicle_fields(plate)

        # Always update info panel
        self.info_table.setText(
            f"<b>Plate:</b> {plate} | <b>Status:</b> {tag_info['status']} | "
            f"<b>Balance:</b> ₹{tag_info.get('balance', 0)} | "
            f"<b>Class:</b> {tag_info.get('vehicle_class', 'Unknown')} | "
            f"<b>Tag ID:</b> {tag_info.get('tag_id', 'N/A')}"
        )

        self.toggle_boom(True)



    def toggle_boom(self, open_boom=True):
        if open_boom:
            self.boom_status.setText("🟢 Boom: Open")
            self.boom_status.setStyleSheet("color: green; font-weight: bold;")
            self.boom_icon.setPixmap(QPixmap("icons/boomopen.jpg").scaled(70, 70))
            print("🚧 Boom barrier opened!")
            self.cap = self.camera_manager.get_camera()

            if hasattr(self, "gpio_mode") and self.gpio_mode:
                self.GPIO.output(self.BOOM_PIN, self.GPIO.HIGH)
            elif hasattr(self, "relay_serial") and self.relay_serial:
                self.relay_serial.write(b"O")  # Open command
        else:
            self.boom_status.setText("🔴 Boom: Closed")
            self.boom_status.setStyleSheet("color: red; font-weight: bold;")
            self.boom_icon.setPixmap(QPixmap("icons/boomclose.jpg").scaled(70, 70))
            print("🚧 Boom barrier closed!")

            if hasattr(self, "gpio_mode") and self.gpio_mode:
                self.GPIO.output(self.BOOM_PIN, self.GPIO.LOW)
            elif hasattr(self, "relay_serial") and self.relay_serial:
                self.relay_serial.write(b"C")  # Close command

        # Auto-close after 3 seconds
        QTimer.singleShot(3000, lambda: self.toggle_boom(False))

    def handle_rfid_tag(self, tag, lane_id):
     insert_rfid_log(tag, lane_id)
     print(f"📶 Tag from Lane {lane_id}: {tag}")
     tag = tag.upper()
     self.plate_input.setText(tag)
    
     tag_info = check_fastag(tag)
     vehicle_class = tag_info.get("vehicle_class")
     if not vehicle_class:
        QMessageBox.warning(self, "Missing Data", "No vehicle class found for this FASTag.")
        return  # Stop further processing
    
     # Auto-select vehicle class
     if vehicle_class in PRICING:
         index = self.vehicle_type.findText(vehicle_class)
         if index != -1:
             self.vehicle_type.setCurrentIndex(index)
     amount = PRICING.get(vehicle_class, 60)
     # Update UI fields
     self.populate_vehicle_fields(tag)     
    
     winsound.PlaySound(BEEP_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
    
     now = datetime.now().strftime("%H:%M:%S")
    
     status = tag_info["status"]
     balance = tag_info.get("balance", 0)
    
     # Decide on deduction
     if status == "Valid" and balance >= amount:
         deduct_fastag_amount(tag, amount)
         self.capture_image(tag)
    
         log_entry(
             tag,
             vehicle_class,
             status,
             self.user["username"],
             lane_id
         )
         insert_log(lane_id, tag)
    
     # ✅ Always update the table regardless of status
     self.update_transactions(tag, vehicle_class, status)
    
     self.info_table.setText(
         f"<b>Plate:</b> {tag} | <b>Status:</b> {status} | "
         f"<b>Balance:</b> ₹{balance} | "
         f"<b>Class:</b> {vehicle_class} | "
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
        amount = float(amount) if isinstance(amount, str) else amount
        self.populate_fastag_fields(tag_info, amount)
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
            self.toggle_boom(True)
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
            return
        except ImportError:
            self.gpio_mode = False
            print("❌ GPIO not available, trying serial relay...")

        # Try to auto-detect relay port
        try:
            relay_port = find_relay_port()  # 👈 Now this will work!
            if relay_port:
                self.relay_serial = serial.Serial(relay_port, 9600, timeout=1)
                print(f"✅ Serial relay connected on {relay_port}.")
            else:
                print("❌ No serial relay port detected.")
                self.relay_serial = None
        except Exception as e:
            print(f"❌ Serial relay setup failed: {e}")
            self.relay_serial = None

   
    def update_transactions(self, plate, vehicle_type, fastag_status):
       row_position = self.transactions_table.rowCount()
       self.transactions_table.insertRow(row_position)

       self.transactions_table.setItem(row_position, 0, QTableWidgetItem(plate))
       self.transactions_table.setItem(row_position, 1, QTableWidgetItem(vehicle_type))
       self.transactions_table.setItem(row_position, 2, QTableWidgetItem(fastag_status))
       self.transactions_table.setItem(row_position, 3, QTableWidgetItem(self.user["username"]))
       self.transactions_table.setItem(row_position, 4, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))

       # Optional: Scroll to the latest row
       self.transactions_table.scrollToBottom()

       # Optional: Limit to last N rows (e.g., 50)
       if self.transactions_table.rowCount() > 50:
           self.transactions_table.removeRow(0)


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
        try:
            if hasattr(self, 'rfid_listener'):
                self.rfid_listener.stop()
            if hasattr(self, 'toll_window'):
                self.toll_window.close()
                self.camera_manager.release()
        except Exception as e:
            print("Error during close:", e)
        event.accept()




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
    
    def handle_rfid_tag(self, lane_id, tag):
        print(f"✅ [Lane {lane_id}] Received FASTag: {tag}")
        self.vehicle_input.setText(tag)  # ✅ update GUI with tag
        # You can also play sound or update database/logs here

    def save_entry(self):
        vehicle = self.vehicle_input.text()
        vtype = self.type_dropdown.currentText()
        if not vehicle:
            QMessageBox.warning(self, "Missing", "Vehicle number is empty!")
            return
        print(f"🚗 Entry Saved: {vehicle}, Type: {vtype}")
        winsound.Beep(1000, 200)  # ✅ feedback


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
     # ✅ Start background sync thread
    start_sync_thread()
    sys.exit(app.exec_())