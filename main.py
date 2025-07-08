# 🔒 Full working Toll Booth ANPR App with styled login and custom layout
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QComboBox, QGridLayout
)
from PyQt5.QtCore import QTimer, Qt, QSize
from PyQt5.QtGui import QImage, QPixmap, QIcon
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
                if ocr_conf > 0.7 and 6 <= len(clean) <= 12 and is_valid_plate(clean):
                    return clean, (x1, y1, x2, y2)
    return None, None

# --------------------- TollApp Main UI ---------------------
class TollApp(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lane = get_user_lane(user['username'])
        self.setWindowTitle(f"Toll Booth - Lane {self.lane}")
        self.setGeometry(100, 100, 1300, 780)

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
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 6px;
                font-size: 16px;
            }
            QPushButton {
                background-color: #34495e;
                color: white;
                padding: 10px;
                font-size: 16px;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #2c3e50;
            }
        """)

        vehicle_types = ["icons/car.png", "icons/bus.png", "icons/truck.png", "icons/auto.png", "icons/bike.png", "icons/tractor.png"]
        self.vehicle_buttons = QHBoxLayout()
        self.vehicle_buttons.setSpacing(10)
        for vtype in vehicle_types:
            btn = QPushButton()
            btn.setIcon(QIcon(vtype))
            btn.setIconSize(QSize(60, 60))
            btn.setFixedSize(70, 70)
            btn.setStyleSheet("background: white; border: 2px solid #ccc; border-radius: 10px;")
            self.vehicle_buttons.addWidget(btn)

        self.video_label = QLabel("CAMERA")
        self.video_label.setFixedSize(480, 360)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("margin-top: 20px; border: 3px solid #ccc; border-radius: 12px;")

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("Auto detected vehicle number")

        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems(["Car", "Truck", "Bus", "Auto", "Bike", "Tractor"])
        self.vehicle_type.setDisabled(True)

        self.price_display = QLineEdit()
        self.price_display.setPlaceholderText("Calculated price")
        self.price_display.setReadOnly(True)

        self.info_table = QLabel()
        self.info_table.setText("""
            <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
                <tr style='background:#ffd700;'>
                    <th>Vehicle no</th><th>Tagno.</th><th>TagStatus</th><th>vehicle chassis</th><th>Status</th>
                </tr>
                <tr>
                    <td colspan='5'>Waiting for detection...</td>
                </tr>
            </table>
        """)
        self.info_table.setTextFormat(Qt.RichText)

        grid = QGridLayout()
        grid.addLayout(self.vehicle_buttons, 0, 0, 1, 3)
        grid.addWidget(self.video_label, 1, 0, 1, 1)
        grid.addWidget(self.plate_input, 1, 1, 1, 2)
        grid.addWidget(self.vehicle_type, 2, 1, 1, 2)
        grid.addWidget(self.price_display, 3, 1, 1, 2)
        grid.addWidget(self.info_table, 4, 0, 1, 3)

        self.setLayout(grid)

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
                html = f"""
                <table border='1' cellpadding='6' cellspacing='0' style='background:#d4f542'>
                    <tr style='background:#ffd700;'>
                        <th>Vehicle no</th><th>Tagno.</th><th>TagStatus</th><th>vehicle chassis</th><th>Status</th>
                    </tr>
                    <tr>
                        <td>{plate}</td>
                        <td>{tag_info.get('tag_id', 'N/A')}</td>
                        <td>{status}</td>
                        <td>{tag_info.get('vehicle_class', 'N/A')}</td>
                        <td>₹{tag_info.get('balance', 0.0):.2f}</td>
                    </tr>
                </table>
                """
                self.info_table.setText(html)
                log_entry(plate, "Auto", status, self.user["username"], self.lane)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb_image, rgb_image.shape[1], rgb_image.shape[0], QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(image))

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
