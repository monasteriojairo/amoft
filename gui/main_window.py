from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QLabel
)

from gui.auto_tab import AutoTab
from gui.diagnostics_tab import DiagnosticsTab
from gui.manual_tab import ManualTab
from gui.settings_tab import SettingsTab


class StatusIndicator(QLabel):
    def __init__(self, text="UNKNOWN"):
        super().__init__(text)
        self.set_status(text, "red")

    def set_status(self, text, color):
        self.setText(text)
        self.setStyleSheet(
            f"background-color: {color}; color: white; padding: 6px; font-weight: bold;"
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("AMOFT Control")

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.manual_tab = ManualTab()
        self.auto_tab = AutoTab()
        self.diagnostics_tab = DiagnosticsTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.manual_tab, "Manual")
        self.tabs.addTab(self.auto_tab, "Auto")
        self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.pi_status = StatusIndicator("PI LINK OFF")
        self.clearcore_status = StatusIndicator("CLEARCORE OFF")
        self.m0_status = StatusIndicator("M0 OFF")
        self.m1_status = StatusIndicator("M1 OFF")
        self.statusBar().addPermanentWidget(self.pi_status)
        self.statusBar().addPermanentWidget(self.clearcore_status)
        self.statusBar().addPermanentWidget(self.m0_status)
        self.statusBar().addPermanentWidget(self.m1_status)

        self.manual_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.auto_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.auto_tab.command_signal.connect(self.manual_tab.send_command)
        self.auto_tab.reconnect_signal.connect(self.reconnect_from_auto)
        self.settings_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.manual_tab.pi_connection_signal.connect(self.update_pi_status)
        self.manual_tab.clearcore_connection_signal.connect(self.update_clearcore_status)
        self.manual_tab.m0_status_signal.connect(self.update_m0_status)
        self.manual_tab.m1_status_signal.connect(self.update_m1_status)

    def reconnect_from_auto(self):
        self.manual_tab.disconnect_all()
        self.manual_tab.connect_selected_mode()

    def update_pi_status(self, connected: bool):
        if connected:
            self.pi_status.set_status("PI LINK OK", "green")
        else:
            self.pi_status.set_status("PI LINK OFF", "red")

    def update_clearcore_status(self, connected: bool):
        if connected:
            self.clearcore_status.set_status("CLEARCORE OK", "green")
        else:
            self.clearcore_status.set_status("CLEARCORE OFF", "red")

    def update_motor_indicator(self, indicator: StatusIndicator, name: str, status: str):
        if status == "enabled":
            indicator.set_status(f"{name} ENABLED", "#1f7a1f")
        elif status == "disabled":
            indicator.set_status(f"{name} DISABLED", "#b8860b")
        elif status == "transition":
            indicator.set_status(f"{name} TRANSITION", "#1e6aa8")
        elif status == "fault":
            indicator.set_status(f"{name} FAULT", "#8b0000")
        else:
            indicator.set_status(f"{name} OFF", "red")

    def update_m0_status(self, status: str):
        self.update_motor_indicator(self.m0_status, "M0", status)

    def update_m1_status(self, status: str):
        self.update_motor_indicator(self.m1_status, "M1", status)
