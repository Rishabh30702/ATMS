# rfid_simulator.py
import socket
import time
import random

def simulate_reader(ip='0.0.0.0', port=4001):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((ip, port))
    s.listen(1)
    print(f"🚦 Simulated RFID reader running on {ip}:{port}")
    conn, addr = s.accept()
    print(f"📶 Client connected: {addr}")
    tags = ['FAST1234', 'FAST5678', 'FAST9999']
    while True:
        tag = random.choice(tags) + "\n"
        conn.sendall(tag.encode())
        print(f"📤 Sent tag: {tag.strip()}")
        time.sleep(5)

simulate_reader()
