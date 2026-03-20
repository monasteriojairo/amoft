from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QMessageBox
)

from gui.manual_tab import ManualTab
from gui.auto_tab import AutoTab
from gui.diagnostics_tab import DiagnosticsTab
from gui.settings_tab import SettingsTab


class StatusIndicator(QLabel):
    def __init__(self, text="UNKNOWN", color="gray"):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(110)
        self.set_status(text, color)

    def set_status(self, text, color):
        self.setText(text)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                font-weight: bold;
                border-radius: 8px;
                padding: 4px;
            }}
        """)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AMOFT Control Panel")
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top status bar
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("System Status:"))

        self.pi_status = StatusIndicator("APP OK", "green")
        self.clearcore_status = StatusIndicator("CLEARCORE OFF", "red")
        self.arduino_status = StatusIndicator("ARDUINO OFF", "red")
        self.m0_status = StatusIndicator("M0 IDLE", "gray")
        self.m1_status = StatusIndicator("M1 DISABLED", "gray")
        self.estop_status = StatusIndicator("E-STOP OK", "green")

        for widget in [
            self.pi_status,
            self.clearcore_status,
            self.arduino_status,
            self.m0_status,
            self.m1_status,
            self.estop_status,
        ]:
            status_layout.addWidget(widget)

        status_layout.addStretch()
        main_layout.addLayout(status_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.manual_tab = ManualTab()
        self.auto_tab = AutoTab()
        self.diagnostics_tab = DiagnosticsTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.manual_tab, "Manual")
        self.tabs.addTab(self.auto_tab, "Auto")
        self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        self.tabs.addTab(self.settings_tab, "Settings")

        main_layout.addWidget(self.tabs)

        # Bottom safety bar
        bottom_layout = QHBoxLayout()

        self.stop_all_btn = QPushButton("STOP ALL")
        self.stop_all_btn.setFixedHeight(60)
        self.stop_all_btn.setStyleSheet("""
            QPushButton {
                background-color: red;
                color: white;
                font-size: 22px;
                font-weight: bold;
                border-radius: 10px;
            }
            QPushButton:pressed {
                background-color: darkred;
            }
        """)
        self.stop_all_btn.clicked.connect(self.stop_all)

        bottom_layout.addWidget(self.stop_all_btn)
        main_layout.addLayout(bottom_layout)

        # Connect log signals
        self.manual_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.auto_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.settings_tab.log_signal.connect(self.diagnostics_tab.append_log)

    def stop_all(self):
        self.diagnostics_tab.append_log("STOP ALL pressed")
        QMessageBox.warning(self, "Emergency Stop", "STOP ALL command issued.")