import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QComboBox
)
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QImage, QPixmap
import cv2
import easyocr
from db import authenticate_user, log_entry, get_user_lane
from anpr import detect_plate
from fastag_api import check_fastag


class LoginScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Operator Login")
        self.setGeometry(100, 100, 300, 200)
        self.init_ui()

    def init_ui(self):
        self.username_input = QLineEdit(self)
        self.username_input.setPlaceholderText("Username")

        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.login)

        layout = QVBoxLayout()
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
            QLabel {
                font-weight: 500;
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

        self.user_info = QLabel(f"👤 {self.user['username']} | Lane {self.lane}")
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
        if ret:
            self.frame_count += 1
            if self.frame_count % 15 == 0:
                plate = detect_plate(self.reader, frame)
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
