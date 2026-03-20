from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QCheckBox
)


class SettingsTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        box = QGroupBox("System Settings")
        grid = QGridLayout(box)

        self.clearcore_port = QLineEdit("/dev/ttyACM0")
        self.arduino_port = QLineEdit("/dev/ttyUSB0")

        self.baud_box = QComboBox()
        self.baud_box.addItems(["9600", "115200", "230400"])

        self.m1_enabled = QCheckBox("Enable M1 Axis")
        self.sim_mode = QCheckBox("Simulation Mode")

        self.save_btn = QPushButton("Save Settings")

        grid.addWidget(QLabel("ClearCore Port:"), 0, 0)
        grid.addWidget(self.clearcore_port, 0, 1)

        grid.addWidget(QLabel("Arduino Port:"), 1, 0)
        grid.addWidget(self.arduino_port, 1, 1)

        grid.addWidget(QLabel("Baud Rate:"), 2, 0)
        grid.addWidget(self.baud_box, 2, 1)

        grid.addWidget(self.m1_enabled, 3, 0, 1, 2)
        grid.addWidget(self.sim_mode, 4, 0, 1, 2)
        grid.addWidget(self.save_btn, 5, 0, 1, 2)

        layout.addWidget(box)
        layout.addStretch()

        self.save_btn.clicked.connect(self.save_settings)

    def save_settings(self):
        self.log_signal.emit(
            f"Settings saved | ClearCore={self.clearcore_port.text()} | "
            f"Arduino={self.arduino_port.text()} | Baud={self.baud_box.currentText()} | "
            f"M1 enabled={self.m1_enabled.isChecked()} | Sim mode={self.sim_mode.isChecked()}"
        )