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
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

    def send_command(self, cmd: str) -> str:
        self.connect()
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        deadline = time.time() + max(self.timeout, 1.0)

        while time.time() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue

            # Some wrong-port/wrong-device cases return long runs of NUL bytes.
            if raw.strip(b"\x00\r\n") == b"":
                continue

            response = raw.replace(b"\x00", b"").decode(errors="ignore").strip()
            if response:
                return response

        raise RuntimeError(f"No valid response from ClearCore on {self.port}")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None
