import serial
import time


class ClearCoreController:
    def __init__(self, port="/dev/ttyACM1", baudrate=9600, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        if self.ser is None or not self.ser.is_open:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            time.sleep(2)

    def send_command(self, cmd: str) -> str:
        self.connect()
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        response = self.ser.readline().decode(errors="ignore").strip()
        return response

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None
