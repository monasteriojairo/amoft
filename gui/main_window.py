from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QLabel
)

from gui.auto_tab import AutoTab
from gui.diagnostics_tab import DiagnosticsTab
from gui.manual_tab import ManualTab
from gui.settings_tab import SettingsTab
from gui.validation_tab import ValidationTab


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
        self.validation_tab = ValidationTab()
        self.diagnostics_tab = DiagnosticsTab()
        self.settings_tab = SettingsTab()

        self.tabs.addTab(self.manual_tab, "Manual")
        self.tabs.addTab(self.auto_tab, "Auto")
        self.tabs.addTab(self.validation_tab, "Validation")
        self.tabs.addTab(self.diagnostics_tab, "Diagnostics")
        self.tabs.addTab(self.settings_tab, "Settings")

        self.pi_status = StatusIndicator("PI LINK OFF")
        self.clearcore_status = StatusIndicator("CLEARCORE OFF")
        self.arduino_status = StatusIndicator("ARDUINO OFF")
        self.m0_status = StatusIndicator("M0 OFF")
        self.m1_status = StatusIndicator("M1 OFF")
        self.statusBar().addPermanentWidget(self.pi_status)
        self.statusBar().addPermanentWidget(self.clearcore_status)
        self.statusBar().addPermanentWidget(self.arduino_status)
        self.statusBar().addPermanentWidget(self.m0_status)
        self.statusBar().addPermanentWidget(self.m1_status)

        self.manual_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.auto_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.validation_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.auto_tab.command_signal.connect(self.manual_tab.send_command)
        self.manual_tab.command_failed_signal.connect(self.auto_tab.handle_command_failure)
        self.auto_tab.reconnect_signal.connect(self.reconnect_from_auto)
        self.auto_tab.cycle_state_signal.connect(self.manual_tab.on_cycle_state_changed)
        self.auto_tab.cycle_state_signal.connect(self.validation_tab.on_auto_cycle_state_changed)
        self.validation_tab.validation_mode_signal.connect(self.set_validation_mode)
        self.validation_tab.start_sequence_signal.connect(self.start_validation_sequence)
        self.validation_tab.abort_signal.connect(self.auto_tab.abort_from_hardware)
        self.validation_tab.sensor_poll_signal.connect(self.update_validation_sensors)
        self.validation_tab.sensor_config_signal.connect(self.configure_validation_sensors)
        self.settings_tab.log_signal.connect(self.diagnostics_tab.append_log)
        self.manual_tab.pi_connection_signal.connect(self.update_pi_status)
        self.manual_tab.clearcore_connection_signal.connect(self.update_clearcore_status)
        self.manual_tab.arduino_connection_signal.connect(self.update_arduino_status)
        self.manual_tab.m0_status_signal.connect(self.update_m0_status)
        self.manual_tab.m1_status_signal.connect(self.update_m1_status)
        self.manual_tab.hardware_start_requested.connect(self.auto_tab.start_from_hardware)
        self.manual_tab.hardware_stop_requested.connect(self.auto_tab.abort_from_hardware)
        self.manual_tab.home_switch_stop_signal.connect(self.auto_tab.handle_home_switch_stop)

    def set_validation_mode(self, enabled: bool):
        self.auto_tab.set_external_lock(enabled, "Validation mode" if enabled else "")

    def start_validation_sequence(self, steps: list, label: str):
        started = self.auto_tab.start_external_sequence(steps, label)
        self.validation_tab.on_validation_start_result(started)

    def update_validation_sensors(self):
        digital_response = self.manual_tab.read_validation_sensor_inputs()
        analog_response = self.manual_tab.read_analog_sensor_inputs()
        self.validation_tab.update_sensor_inputs(digital_response)
        self.validation_tab.update_analog_sensor_inputs(analog_response)
        self.validation_tab.record_sensor_snapshot()

    def configure_validation_sensors(self, settings: dict):
        response = self.manual_tab.configure_validation_sensor_inputs(settings)
        self.validation_tab.on_sensor_calibration_saved(response)

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

    def update_arduino_status(self, connected: bool):
        if connected:
            self.arduino_status.set_status("ARDUINO OK", "green")
        else:
            self.arduino_status.set_status("ARDUINO OFF", "red")

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
