import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.resize(1100, 650)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

    
import serial
import time

arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(2)  # let Arduino reset

arduino.write(b'EXTEND\n')
response = arduino.readline().decode().strip()
print(response)

arduino.write(b'RETRACT\n')
response = arduino.readline().decode().strip()
print(response)

arduino.close()