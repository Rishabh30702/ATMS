import threading
import serial
import serial.tools.list_ports
import time
import platform

# If running on Raspberry Pi with GPIO support
try:
    import RPi.GPIO as GPIO
    RPI = True
except ImportError:
    RPI = False


class LoopListener:
    def __init__(self, callback):
        self.callback = callback
        self.running = False
        self.serial_port = None
        self.gpio_pin = 17  # Default GPIO pin
        self.thread = None

    def find_serial_loop_device(self):
        ports = serial.tools.list_ports.comports()
        for port in ports:
            try:
                print(f"🔍 Checking {port.device}...")
                ser = serial.Serial(port.device, 9600, timeout=1)
                time.sleep(2)
                ser.flushInput()
                print(f"✅ Loop device found on {port.device}")
                return ser
            except Exception as e:
                print(f"⚠️ {port.device} failed: {e}")
        return None

    def gpio_loop_listener(self):
        print(f"📡 Listening for loop on GPIO {self.gpio_pin}")
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        try:
            while self.running:
                if GPIO.input(self.gpio_pin) == GPIO.HIGH:
                    print("🚗 Loop triggered via GPIO!")
                    self.callback()
                    time.sleep(1)
        finally:
            GPIO.cleanup()

    def serial_loop_listener(self, ser):
        print(f"📡 Listening for loop on {ser.port}")
        try:
            while self.running:
                if ser.in_waiting:
                    line = ser.readline().decode(errors='ignore').strip()
                    if line:
                        print(f"🔁 Loop Data Received: {line}")
                        self.callback()
                time.sleep(0.1)
        except Exception as e:
            print(f"❌ Serial listener error: {e}")
        finally:
            ser.close()

    def start(self):
        self.running = True
        if RPI:
            self.thread = threading.Thread(target=self.gpio_loop_listener, daemon=True)
            self.thread.start()
        else:
            self.serial_port = self.find_serial_loop_device()
            if self.serial_port:
                self.thread = threading.Thread(target=self.serial_loop_listener, args=(self.serial_port,), daemon=True)
                self.thread.start()
            else:
                print("❌ No loop sensor found on any serial port.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
