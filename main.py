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
        self.setGeometry(100, 100, 900, 700)
        self.setup_ui()
        self.reader = easyocr.Reader(['en'])
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)
        self.frame_count = 0

    def setup_ui(self):
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI';
                font-size: 14px;
            }
            QLabel#Header {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
            }
            QLineEdit, QComboBox {
                padding: 6px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 16px;
            }
            QPushButton {
                background-color: #2980b9;
                color: white;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: #1c5980;
            }
            QLineEdit[readOnly="true"] {
                background-color: #ecf0f1;
                font-size: 20px;
                font-weight: bold;
                color: #e67e22;
            }
            QLabel#FastagStatus {
                font-size: 18px;
                font-weight: bold;
                color: #27ae60;
            }
        """)

        self.user_info_label = QLabel(f"Logged in as: {self.user['username']} | Lane: {self.lane}")
        self.user_info_label.setObjectName("Header")

        self.video_label = QLabel()
        self.video_label.setFixedSize(640, 480)

        self.toggle_button = QPushButton("Switch to Manual Mode")
        self.toggle_button.clicked.connect(self.toggle_mode)
        self.mode = "auto"

        self.plate_label = QLabel("Detected Plate:")
        self.plate_input = QLineEdit()
        self.plate_input.setReadOnly(True)

        self.status_label = QLabel("FASTag:")
        self.status_display = QLabel("")
        self.status_display.setObjectName("FastagStatus")

        self.manual_input = QLineEdit()
        self.vehicle_type = QComboBox()
        self.vehicle_type.addItems(["Car", "Truck", "Bus"])
        self.fastag_status = QComboBox()
        self.fastag_status.addItems(["Valid", "Invalid", "No FASTag"])
        self.manual_submit = QPushButton("Submit Manual Entry")
        self.manual_submit.clicked.connect(self.submit_manual)

        self.manual_input.hide()
        self.vehicle_type.hide()
        self.fastag_status.hide()
        self.manual_submit.hide()

        vbox = QVBoxLayout()
        vbox.addWidget(self.user_info_label)
        vbox.addWidget(self.video_label)
        vbox.addWidget(self.toggle_button)

        hbox = QHBoxLayout()
        hbox.addWidget(self.plate_label)
        hbox.addWidget(self.plate_input)
        hbox.addWidget(self.status_label)
        hbox.addWidget(self.status_display)

        manual_box = QVBoxLayout()
        manual_box.addWidget(QLabel("Manual Plate Entry:"))
        manual_box.addWidget(self.manual_input)
        manual_box.addWidget(QLabel("Vehicle Type:"))
        manual_box.addWidget(self.vehicle_type)
        manual_box.addWidget(QLabel("FASTag Status:"))
        manual_box.addWidget(self.fastag_status)
        manual_box.addWidget(self.manual_submit)

        vbox.addLayout(hbox)
        vbox.addLayout(manual_box)
        self.setLayout(vbox)

    def toggle_mode(self):
        if self.mode == "auto":
            self.mode = "manual"
            self.toggle_button.setText("Switch to Auto Mode")
            self.manual_input.show()
            self.vehicle_type.show()
            self.fastag_status.show()
            self.manual_submit.show()
        else:
            self.mode = "auto"
            self.toggle_button.setText("Switch to Manual Mode")
            self.manual_input.hide()
            self.vehicle_type.hide()
            self.fastag_status.hide()
            self.manual_submit.hide()

    def update_frame(self):
        if self.mode == "auto":
            ret, frame = self.cap.read()
            if ret:
                self.frame_count += 1
                if self.frame_count % 10 == 0:
                    plate = detect_plate(self.reader, frame)
                    if plate:
                        self.plate_input.setText(plate)
                        self.manual_input.setText(plate)

                        tag_info = check_fastag(plate)
                        status = tag_info['status']
                        self.status_display.setText(status)

                        info_message = f"FASTag Status: {status}\n"
                        if status == "Valid":
                            info_message += (
                                f"Tag ID: {tag_info['tag_id']}\n"
                                f"Balance: ₹{tag_info['balance']:.2f}\n"
                                f"Vehicle Class: {tag_info['vehicle_class']}"
                            )
                        elif status == "Invalid":
                            info_message += "This FASTag is invalid. Please ask for alternate payment."
                        else:
                            info_message += "No FASTag associated with this vehicle."

                        QMessageBox.information(self, "FASTag Info", info_message)

                        log_entry(plate, "Auto", status, self.user['username'], self.lane)

                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = QImage(rgb_image, rgb_image.shape[1], rgb_image.shape[0], QImage.Format_RGB888)
                self.video_label.setPixmap(QPixmap.fromImage(image))

    def submit_manual(self):
        plate = self.manual_input.text()
        vehicle = self.vehicle_type.currentText()
        status = self.fastag_status.currentText()
        self.plate_input.setText(plate)
        self.status_display.setText(status)
        log_entry(plate, vehicle, status, self.user['username'], self.lane)

    def closeEvent(self, event):
        self.cap.release()


# --- ENTRY POINT ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginScreen()
    login.show()
    sys.exit(app.exec_())
