from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QPushButton,
    QLabel, QGridLayout, QComboBox
)

from controllers.arduino_controller import ArduinoController
from controllers.clearcore_controller import ClearCoreController
from controllers.pi_client import PiClient
from utils.serial_ports import get_serial_ports


class ManualTab(QWidget):
    log_signal = Signal(str)
    pi_connection_signal = Signal(bool)
    clearcore_connection_signal = Signal(bool)
    arduino_connection_signal = Signal(bool)
    m0_status_signal = Signal(str)
    m1_status_signal = Signal(str)

    def __init__(self):
        super().__init__()

        self.pi_client = PiClient(host="192.168.1.95", port=5000)
        self.clearcore_client = None
        self.arduino_client = None
        self.pi_connected = False
        self.clearcore_connected = False
        self.arduino_connected = False
        self.m0_enabled = False
        self.m1_enabled = False
        self.m0_widgets = []
        self.m1_widgets = []
        self.actuator_widgets = []
        self.arduino_connection_widgets = []
        self.arduino_diagnostic_widgets = []
        self.connection_status = None
        self.m0_state_label = None
        self.m1_state_label = None
        self.arduino_status_label = None
        self.arduino_diag_label = None
        self.actuator_state_label = None
        self.last_motor_status = {"M0": "off", "M1": "off"}

        layout = QHBoxLayout(self)

        left_col = QVBoxLayout()
        left_col.addWidget(self.create_connection_group())
        left_col.addWidget(self.create_m0_group())
        left_col.addWidget(self.create_m1_group())

        right_col = QVBoxLayout()
        right_col.addWidget(self.create_arduino_group())
        right_col.addWidget(self.create_actuator_group())
        right_col.addStretch()

        layout.addLayout(left_col, 2)
        layout.addLayout(right_col, 1)

        self.refresh_ports()
        self.set_pi_connected(False)
        self.set_clearcore_connected(False)
        self.set_motor_status("M0", "off")
        self.set_motor_status("M1", "off")
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1500)
        self.status_timer.timeout.connect(self.refresh_motor_statuses)
        self.auto_retry_timer = QTimer(self)
        self.auto_retry_timer.setInterval(5000)
        self.auto_retry_timer.timeout.connect(self.auto_retry_devices)
        self.update_auto_retry_timer()
        QTimer.singleShot(0, self.auto_connect_startup_devices)

    def connect_selected_mode(self):
        mode = self.mode_combo.currentData()
        if mode == "local":
            self.connect_local_clearcore()
        else:
            self.connect_to_pi()

    def connect_to_pi(self):
        try:
            self.pi_client.connect()
            response = self.pi_client.send("PING")
            self.pi_connected = (response == "PONG")
            self.log_signal.emit(f"Pi connection successful: {response}")
            self.set_pi_connected(self.pi_connected)
            if self.pi_connected:
                self.status_timer.start()
            self.update_connection_label()
        except Exception as e:
            self.pi_connected = False
            self.set_pi_connected(False)
            self.status_timer.stop()
            self.log_signal.emit(f"Pi connection failed: {e}")
            self.update_connection_label()

    def connect_local_clearcore(self, quiet: bool = False):
        port = self.port_combo.currentData()
        if not port:
            if not quiet:
                self.log_signal.emit("Select a serial port before connecting to ClearCore")
            return

        if self.arduino_connected and self.arduino_client is not None and self.arduino_client.port == port:
            if not quiet:
                self.log_signal.emit(
                    f"ClearCore connect blocked: {port} is already assigned to Arduino"
                )
            return

        try:
            if self.clearcore_client is not None:
                self.clearcore_client.close()

            self.clearcore_client = ClearCoreController(port=port)
            self.clearcore_client.connect()
            self.log_signal.emit(f"ClearCore connection successful: {port}")
            self.log_firmware_identity()
            self.set_clearcore_connected(True)
            self.set_motor_status("M0", "disabled")
            self.set_motor_status("M1", "disabled")
            self.status_timer.start()
            self.update_connection_label()
        except Exception as e:
            self.clearcore_client = None
            self.set_clearcore_connected(False)
            self.set_motor_status("M0", "off")
            self.set_motor_status("M1", "off")
            self.status_timer.stop()
            if not quiet:
                self.log_signal.emit(f"ClearCore connection failed: {e}")
            self.update_connection_label()

    def disconnect_all(self):
        try:
            self.pi_client.close()
        except Exception:
            pass

        try:
            if self.clearcore_client is not None:
                self.clearcore_client.close()
        except Exception:
            pass

        try:
            if self.arduino_client is not None:
                self.arduino_client.disconnect()
        except Exception:
            pass

        self.clearcore_client = None
        self.arduino_client = None
        self.set_pi_connected(False)
        self.set_clearcore_connected(False)
        self.set_arduino_connected(False)
        self.set_motor_status("M0", "off")
        self.set_motor_status("M1", "off")
        self.status_timer.stop()
        self.update_connection_label()
        self.log_signal.emit("Disconnected all links")

    def send_command(self, cmd: str):
        try:
            response = self.route_command(cmd)

            if self.response_has_error(response):
                raise RuntimeError(response)

            self.update_motor_status_from_command(cmd)
            self.update_actuator_status_from_command(cmd, response)
            if cmd != "PING":
                self.refresh_motor_statuses()

            self.log_signal.emit(f"{cmd} -> {response}")
        except Exception as e:
            if self.mode_combo.currentData() == "local" and not self.is_actuator_command(cmd):
                self.clearcore_client = None
                self.set_clearcore_connected(False)
                self.set_motor_status("M0", "off")
                self.set_motor_status("M1", "off")
                self.status_timer.stop()
            elif self.mode_combo.currentData() == "local" and self.is_actuator_command(cmd):
                self.arduino_client = None
                self.set_arduino_connected(False)
            elif cmd != "PING":
                self.set_clearcore_connected(False)
                self.set_motor_status("M0", "off")
                self.set_motor_status("M1", "off")
                self.status_timer.stop()

            self.log_signal.emit(f"Command failed ({cmd}): {e}")

            if self.mode_combo.currentData() == "pi" and cmd == "PING":
                self.set_pi_connected(False)

            self.update_connection_label()

    def command_transport_ready(self):
        if self.mode_combo.currentData() == "local":
            return self.clearcore_connected and self.clearcore_client is not None
        return self.pi_connected

    def actuator_transport_ready(self):
        if self.mode_combo.currentData() == "local":
            return self.arduino_connected and self.arduino_client is not None
        return self.pi_connected

    def is_actuator_command(self, cmd: str):
        return cmd in {"EXTEND", "RETRACT", "STOP_ACTUATOR", "STOP"}

    def route_command(self, cmd: str):
        if self.is_actuator_command(cmd):
            if not self.actuator_transport_ready():
                raise RuntimeError("no active actuator transport")

            if self.mode_combo.currentData() == "local":
                return self.send_local_arduino_command(cmd)
            return self.pi_client.send(cmd)

        if not self.command_transport_ready():
            raise RuntimeError("no active transport")

        if self.mode_combo.currentData() == "local":
            return self.clearcore_client.send_command(cmd)
        return self.pi_client.send(cmd)

    def send_local_arduino_command(self, cmd: str):
        translated = "STOP" if cmd == "STOP_ACTUATOR" else cmd
        return self.arduino_client.send_command(translated)

    def is_clearpath_command(self, cmd: str):
        return cmd.endswith("_M0") or cmd.endswith("_M1")

    def response_has_error(self, response: str):
        if response is None:
            return True
        return response.strip().upper().startswith("ERR")

    def set_pi_connected(self, connected: bool):
        self.pi_connected = connected
        self.pi_connection_signal.emit(connected)
        self.update_auto_retry_timer()
        self.update_connection_controls()

    def set_clearcore_connected(self, connected: bool):
        self.clearcore_connected = connected
        self.clearcore_connection_signal.emit(connected)
        self.refresh_port_labels()
        self.update_auto_retry_timer()
        self.update_connection_controls()

    def set_arduino_connected(self, connected: bool):
        self.arduino_connected = connected
        self.arduino_connection_signal.emit(connected)
        if self.arduino_status_label is not None:
            text = "Arduino: CONNECTED" if connected else "Arduino: DISCONNECTED"
            self.arduino_status_label.setText(text)
        self.refresh_port_labels()
        self.update_auto_retry_timer()
        self.update_connection_controls()

    def set_motor_status(self, motor_name: str, status: str):
        enabled = status == "enabled"
        label_text = {
            "enabled": "State: ENABLED",
            "disabled": "State: DISABLED",
            "transition": "State: TRANSITION",
            "fault": "State: FAULT",
            "off": "State: OFF",
        }.get(status, "State: OFF")

        if motor_name == "M0":
            self.m0_enabled = enabled
            if self.m0_state_label is not None:
                self.m0_state_label.setText(label_text)
            self.m0_status_signal.emit(status)
        else:
            self.m1_enabled = enabled
            if self.m1_state_label is not None:
                self.m1_state_label.setText(label_text)
            self.m1_status_signal.emit(status)

    def update_motor_status_from_command(self, cmd: str):
        motor_name = "M0" if cmd.endswith("_M0") else "M1" if cmd.endswith("_M1") else None
        if motor_name is None:
            return

        if cmd.startswith("ENABLE_"):
            self.set_motor_status(motor_name, "enabled")
            self.set_clearcore_connected(True)
            return

        if cmd.startswith("DISABLE_"):
            if self.clearcore_connected:
                self.set_motor_status(motor_name, "disabled")
            else:
                self.set_motor_status(motor_name, "off")
            return

        if cmd.startswith("MOVE_") or cmd.startswith("STOP_"):
            if self.clearcore_connected:
                enabled = self.m0_enabled if motor_name == "M0" else self.m1_enabled
                self.set_motor_status(motor_name, "enabled" if enabled else "disabled")

    def update_actuator_status_from_command(self, cmd: str, response: str):
        if self.actuator_state_label is None or not self.is_actuator_command(cmd):
            return

        normalized = (response or "").strip().upper()
        if cmd == "EXTEND" and normalized in {"STARTED EXTEND", "DONE EXTEND"}:
            self.actuator_state_label.setText("State: EXTENDING")
            if normalized == "DONE EXTEND":
                self.actuator_state_label.setText("State: EXTENDED")
        elif cmd == "RETRACT" and normalized in {"STARTED RETRACT", "DONE RETRACT"}:
            self.actuator_state_label.setText("State: RETRACTING")
            if normalized == "DONE RETRACT":
                self.actuator_state_label.setText("State: RETRACTED")
        elif cmd == "CYCLE" and normalized in {"STARTED CYCLE", "DONE CYCLE"}:
            self.actuator_state_label.setText("State: CYCLING")
            if normalized == "DONE CYCLE":
                self.actuator_state_label.setText("State: IDLE")
        elif cmd in {"STOP_ACTUATOR", "STOP"} and normalized == "STOPPED":
            self.actuator_state_label.setText("State: STOPPED")

    def refresh_motor_statuses(self):
        if not self.command_transport_ready():
            return

        for motor_name in ("M0", "M1"):
            try:
                response = self.send_raw_command(f"STATUS_{motor_name}")
                status = self.parse_status_response(motor_name, response)
                if status is None:
                    continue

                previous = self.last_motor_status[motor_name]
                self.set_motor_status(motor_name, status)
                if status != previous:
                    self.log_signal.emit(f"{motor_name} status -> {status.upper()}")
                self.last_motor_status[motor_name] = status
            except Exception as e:
                self.log_signal.emit(f"{motor_name} status check failed: {e}")
                self.set_motor_status(motor_name, "off")

    def log_firmware_identity(self):
        try:
            version = self.send_raw_command("VERSION")
            self.log_signal.emit(f"ClearCore firmware: {version}")
        except Exception as e:
            self.log_signal.emit(f"ClearCore firmware version check failed: {e}")

        try:
            caps = self.send_raw_command("CAPS")
            self.log_signal.emit(f"ClearCore capabilities: {caps}")
        except Exception as e:
            self.log_signal.emit(f"ClearCore capability check failed: {e}")

    def send_raw_command(self, cmd: str):
        if self.mode_combo.currentData() == "local":
            return self.clearcore_client.send_command(cmd)
        return self.pi_client.send(cmd)

    def parse_status_response(self, motor_name: str, response: str):
        prefix = f"STATUS_{motor_name}:"
        normalized = response.strip().upper()
        if not normalized.startswith(prefix):
            return None

        value = normalized.split(":", 1)[1]
        mapping = {
            "ENABLED": "enabled",
            "DISABLED": "disabled",
            "TRANSITION": "transition",
            "FAULT": "fault",
        }
        return mapping.get(value, "off")

    def update_connection_controls(self):
        clearpath_enabled = self.clearcore_connected if self.mode_combo.currentData() == "local" else self.pi_connected
        actuator_enabled = self.arduino_connected if self.mode_combo.currentData() == "local" else self.pi_connected

        for widget in self.m0_widgets + self.m1_widgets:
            widget.setEnabled(clearpath_enabled)
        for widget in self.actuator_widgets:
            widget.setEnabled(actuator_enabled)
        for widget in self.arduino_connection_widgets:
            widget.setEnabled(self.mode_combo.currentData() == "local")
        for widget in self.arduino_diagnostic_widgets:
            widget.setEnabled(self.mode_combo.currentData() == "local" and self.arduino_connected)

    def update_connection_label(self):
        mode = self.mode_combo.currentData()
        if mode == "local":
            text = "Status: ClearCore connected" if self.clearcore_connected else "Status: Local mode idle"
            button_text = "Connect ClearCore" if not self.clearcore_connected else "Reconnect ClearCore"
        else:
            text = "Status: Pi connected" if self.pi_connected else "Status: Pi mode idle"
            button_text = "Connect to Pi" if not self.pi_connected else "Reconnect to Pi"

        if self.connection_status is not None:
            self.connection_status.setText(text)
        if hasattr(self, "connect_btn"):
            self.connect_btn.setText(button_text)

        self.update_connection_controls()

    def refresh_ports(self, quiet: bool = False):
        self.port_combo.clear()
        self.arduino_port_combo.clear()
        ports = get_serial_ports()
        self.available_ports = ports
        for port in ports:
            role = self.display_role_for_port(port)
            detail = port.get("role_detail") or port["description"]
            label = f"{port['device']} | {role} | {detail}"
            self.port_combo.addItem(label, port["device"])
            self.arduino_port_combo.addItem(label, port["device"])

        if not quiet:
            summary = ", ".join(
                f"{port['device']}={self.display_role_for_port(port)}" for port in ports
            ) or "none"
            self.log_signal.emit(f"Detected {len(ports)} serial port(s): {summary}")

    def refresh_port_labels(self):
        if not hasattr(self, "port_combo") or not hasattr(self, "arduino_port_combo"):
            return

        clearcore_selected = self.port_combo.currentData()
        arduino_selected = self.arduino_port_combo.currentData()

        self.port_combo.blockSignals(True)
        self.arduino_port_combo.blockSignals(True)

        self.port_combo.clear()
        self.arduino_port_combo.clear()

        for port in getattr(self, "available_ports", []):
            role = self.display_role_for_port(port)
            detail = port.get("role_detail") or port["description"]
            label = f"{port['device']} | {role} | {detail}"
            self.port_combo.addItem(label, port["device"])
            self.arduino_port_combo.addItem(label, port["device"])

        if clearcore_selected is not None:
            index = self.port_combo.findData(clearcore_selected)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

        if arduino_selected is not None:
            index = self.arduino_port_combo.findData(arduino_selected)
            if index >= 0:
                self.arduino_port_combo.setCurrentIndex(index)

        self.port_combo.blockSignals(False)
        self.arduino_port_combo.blockSignals(False)

    def auto_connect_startup_devices(self):
        if self.mode_combo.currentData() != "local":
            return

        self.refresh_ports(quiet=True)
        clearcore_port = self.find_preferred_port("ClearCore")
        arduino_port = self.find_preferred_port("Arduino", exclude_devices={clearcore_port} if clearcore_port else None)

        if clearcore_port:
            index = self.port_combo.findData(clearcore_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            self.log_signal.emit(f"Startup auto-connect: trying ClearCore on {clearcore_port}")
            self.connect_local_clearcore()
        else:
            self.log_signal.emit("Startup auto-connect: no ClearCore port detected")

        if arduino_port:
            index = self.arduino_port_combo.findData(arduino_port)
            if index >= 0:
                self.arduino_port_combo.setCurrentIndex(index)
            self.log_signal.emit(f"Startup auto-connect: trying Arduino on {arduino_port}")
            self.connect_arduino()
        else:
            self.log_signal.emit("Startup auto-connect: no Arduino port detected")

    def auto_retry_devices(self):
        if self.mode_combo.currentData() != "local":
            return

        self.refresh_ports(quiet=True)

        if not self.clearcore_connected:
            clearcore_port = self.find_preferred_port("ClearCore")
            if clearcore_port:
                index = self.port_combo.findData(clearcore_port)
                if index >= 0:
                    self.port_combo.setCurrentIndex(index)
                self.connect_local_clearcore(quiet=True)

        if not self.arduino_connected:
            exclude_devices = {self.clearcore_client.port} if self.clearcore_connected and self.clearcore_client is not None else None
            arduino_port = self.find_preferred_port("Arduino", exclude_devices=exclude_devices)
            if arduino_port:
                index = self.arduino_port_combo.findData(arduino_port)
                if index >= 0:
                    self.arduino_port_combo.setCurrentIndex(index)
                self.connect_arduino(quiet=True)

    def update_auto_retry_timer(self):
        if not hasattr(self, "auto_retry_timer"):
            return

        should_retry = (
            self.mode_combo.currentData() == "local"
            and (not self.clearcore_connected or not self.arduino_connected)
        )

        if should_retry and not self.auto_retry_timer.isActive():
            self.auto_retry_timer.start()
        elif not should_retry and self.auto_retry_timer.isActive():
            self.auto_retry_timer.stop()

    def find_preferred_port(self, role: str, exclude_devices=None):
        excluded = exclude_devices or set()
        for port in getattr(self, "available_ports", []):
            if port["device"] in excluded:
                continue
            if port.get("role") == role:
                return port["device"]
        return None

    def display_role_for_port(self, port_info):
        device = port_info["device"]
        if self.clearcore_connected and self.clearcore_client is not None and self.clearcore_client.port == device:
            return "ClearCore"
        if self.arduino_connected and self.arduino_client is not None and self.arduino_client.port == device:
            return "Arduino"
        return port_info.get("role", "Unknown")

    def connect_arduino(self, quiet: bool = False):
        port = self.arduino_port_combo.currentData()
        if not port:
            if not quiet:
                self.log_signal.emit("Select a serial port before connecting to Arduino")
            return

        if self.clearcore_connected and self.clearcore_client is not None and self.clearcore_client.port == port:
            if not quiet:
                self.log_signal.emit(
                    f"Arduino connect blocked: {port} is already assigned to ClearCore"
                )
            return

        try:
            if self.arduino_client is not None:
                self.arduino_client.disconnect()

            self.arduino_client = ArduinoController(port=port)
            if not self.arduino_client.connect():
                raise RuntimeError(f"Unable to open Arduino port {port}")

            self.set_arduino_connected(True)
            self.set_arduino_diag_text("Diagnostics: connected")
            self.log_signal.emit(f"Arduino connection successful: {port}")
        except Exception as e:
            self.arduino_client = None
            self.set_arduino_connected(False)
            self.set_arduino_diag_text("Diagnostics: unavailable")
            if not quiet:
                self.log_signal.emit(f"Arduino connection failed: {e}")

    def disconnect_arduino(self):
        try:
            if self.arduino_client is not None:
                self.arduino_client.disconnect()
        except Exception as e:
            self.log_signal.emit(f"Arduino disconnect warning: {e}")

        self.arduino_client = None
        self.set_arduino_connected(False)
        self.set_arduino_diag_text("Diagnostics: disconnected")
        if self.actuator_state_label is not None:
            self.actuator_state_label.setText("State: IDLE")
        self.log_signal.emit("Arduino disconnected")

    def verify_arduino_connection(self):
        if not self.arduino_connected or self.arduino_client is None:
            self.log_signal.emit("Arduino verify skipped: not connected")
            return

        verified = self.arduino_client.verify_connection()
        self.set_arduino_diag_text(f"Diagnostics: verify={'PASS' if verified else 'FAIL'}")
        self.log_signal.emit(f"Arduino verify_connection -> {verified}")

    def ping_arduino(self):
        if not self.arduino_connected or self.arduino_client is None:
            self.log_signal.emit("Arduino ping skipped: not connected")
            return

        response = self.arduino_client.send_command("PING")
        self.set_arduino_diag_text(f"Diagnostics: ping={response}")
        self.log_signal.emit(f"Arduino PING -> {response}")

    def read_arduino_status(self):
        if not self.arduino_connected or self.arduino_client is None:
            self.log_signal.emit("Arduino status skipped: not connected")
            return

        response = self.arduino_client.status()
        self.set_arduino_diag_text(f"Diagnostics: status={response}")
        self.log_signal.emit(f"Arduino STATUS -> {response}")

    def run_arduino_diagnostics(self):
        if not self.arduino_connected or self.arduino_client is None:
            self.log_signal.emit("Arduino diagnostics skipped: not connected")
            return

        diagnostics = self.arduino_client.get_diagnostics()
        summary = (
            f"Arduino diagnostics -> port={diagnostics['port']}, "
            f"serial_open={diagnostics['serial_open']}, "
            f"ping_ok={diagnostics['ping_ok']}, "
            f"status={diagnostics['status']}"
        )
        self.set_arduino_diag_text(
            f"Diagnostics: ping_ok={diagnostics['ping_ok']} status={diagnostics['status']}"
        )
        self.log_signal.emit(summary)

    def set_arduino_diag_text(self, text: str):
        if self.arduino_diag_label is not None:
            self.arduino_diag_label.setText(text)

    def set_clearcore_port(self):
        port = self.port_combo.currentData()
        if port:
            if self.mode_combo.currentData() == "local":
                self.log_signal.emit(f"Local ClearCore port selected: {port}")
                return

            self.send_command(f"SET_CLEARCORE_PORT:{port}")

    def create_connection_group(self):
        box = QGroupBox("Connection / Ports")
        grid = QGridLayout(box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Local ClearCore", "local")
        self.mode_combo.addItem("Pi Bridge", "pi")
        self.connect_btn = QPushButton("Connect ClearCore")
        disconnect_btn = QPushButton("Disconnect Link")
        self.connection_status = QLabel("Status: Local mode idle")
        self.port_combo = QComboBox()
        refresh_btn = QPushButton("Refresh Ports")
        set_port_btn = QPushButton("Use Selected Port")

        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.connect_btn.clicked.connect(self.connect_selected_mode)
        disconnect_btn.clicked.connect(self.disconnect_all)
        refresh_btn.clicked.connect(self.refresh_ports)
        set_port_btn.clicked.connect(self.set_clearcore_port)

        grid.addWidget(QLabel("Connection Mode:"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1, 1, 2)
        grid.addWidget(self.connect_btn, 1, 0, 1, 2)
        grid.addWidget(disconnect_btn, 1, 2)
        grid.addWidget(self.connection_status, 2, 0, 1, 3)
        grid.addWidget(QLabel("Detected Ports:"), 3, 0)
        grid.addWidget(self.port_combo, 3, 1, 1, 2)
        grid.addWidget(refresh_btn, 4, 0)
        grid.addWidget(set_port_btn, 4, 1)

        return box

    def on_mode_changed(self):
        self.update_connection_label()
        self.log_signal.emit(f"Connection mode set to: {self.mode_combo.currentText()}")

    def create_arduino_group(self):
        box = QGroupBox("Arduino / Diagnostics")
        grid = QGridLayout(box)

        self.arduino_port_combo = QComboBox()
        connect_btn = QPushButton("Connect Arduino")
        disconnect_btn = QPushButton("Disconnect Arduino")
        verify_btn = QPushButton("Verify Link")
        ping_btn = QPushButton("Ping")
        status_btn = QPushButton("Read Status")
        diag_btn = QPushButton("Run Diagnostics")
        self.arduino_status_label = QLabel("Arduino: DISCONNECTED")
        self.arduino_diag_label = QLabel("Diagnostics: unavailable")

        connect_btn.clicked.connect(self.connect_arduino)
        disconnect_btn.clicked.connect(self.disconnect_arduino)
        verify_btn.clicked.connect(self.verify_arduino_connection)
        ping_btn.clicked.connect(self.ping_arduino)
        status_btn.clicked.connect(self.read_arduino_status)
        diag_btn.clicked.connect(self.run_arduino_diagnostics)

        self.arduino_connection_widgets = [
            self.arduino_port_combo, connect_btn, disconnect_btn
        ]
        self.arduino_diagnostic_widgets = [verify_btn, ping_btn, status_btn, diag_btn]

        grid.addWidget(QLabel("Arduino Port:"), 0, 0)
        grid.addWidget(self.arduino_port_combo, 0, 1, 1, 2)
        grid.addWidget(connect_btn, 1, 0)
        grid.addWidget(disconnect_btn, 1, 1, 1, 2)
        grid.addWidget(verify_btn, 2, 0)
        grid.addWidget(ping_btn, 2, 1)
        grid.addWidget(status_btn, 2, 2)
        grid.addWidget(diag_btn, 3, 0, 1, 3)
        grid.addWidget(self.arduino_status_label, 4, 0, 1, 3)
        grid.addWidget(self.arduino_diag_label, 5, 0, 1, 3)

        return box

    def create_m0_group(self):
        box = QGroupBox("M0 | Roll Servo")
        grid = QGridLayout(box)

        ping_btn = QPushButton("Ping")
        enable_btn = QPushButton("Enable")
        pos1_btn = QPushButton("Forward")
        pos2_btn = QPushButton("Reverse")
        stop_btn = QPushButton("Stop")
        disable_btn = QPushButton("Disable")

        self.m0_state_label = QLabel("State: OFF")

        grid.addWidget(ping_btn, 0, 0)
        grid.addWidget(enable_btn, 0, 1)

        grid.addWidget(pos1_btn, 1, 0)
        grid.addWidget(pos2_btn, 1, 1)

        grid.addWidget(stop_btn, 2, 0)
        grid.addWidget(disable_btn, 2, 1)

        grid.addWidget(self.m0_state_label, 3, 0, 1, 2)

        self.m0_widgets = [ping_btn, enable_btn, pos1_btn, pos2_btn, stop_btn, disable_btn]

        ping_btn.clicked.connect(lambda: self.send_command("PING_M0"))
        enable_btn.clicked.connect(lambda: self.send_command("ENABLE_M0"))
        pos1_btn.clicked.connect(lambda: self.send_command("MOVE_POS1_M0"))
        pos2_btn.clicked.connect(lambda: self.send_command("MOVE_POS2_M0"))
        stop_btn.clicked.connect(lambda: self.send_command("STOP_M0"))
        disable_btn.clicked.connect(lambda: self.send_command("DISABLE_M0"))

        return box

    def create_m1_group(self):
        box = QGroupBox("M1 | Tilt Servo")
        grid = QGridLayout(box)

        ping_btn = QPushButton("Ping")
        enable_btn = QPushButton("Enable")
        pos1_btn = QPushButton("Forward")
        pos2_btn = QPushButton("Reverse")
        stop_btn = QPushButton("Stop")
        disable_btn = QPushButton("Disable")

        self.m1_state_label = QLabel("State: OFF")

        grid.addWidget(ping_btn, 0, 0)
        grid.addWidget(enable_btn, 0, 1)
        grid.addWidget(pos1_btn, 1, 0)
        grid.addWidget(pos2_btn, 1, 1)
        grid.addWidget(stop_btn, 2, 0)
        grid.addWidget(disable_btn, 2, 1)
        grid.addWidget(self.m1_state_label, 3, 0, 1, 2)

        self.m1_widgets = [ping_btn, enable_btn, pos1_btn, pos2_btn, stop_btn, disable_btn]

        ping_btn.clicked.connect(lambda: self.send_command("PING_M1"))
        enable_btn.clicked.connect(lambda: self.send_command("ENABLE_M1"))
        pos1_btn.clicked.connect(lambda: self.send_command("MOVE_POS1_M1"))
        pos2_btn.clicked.connect(lambda: self.send_command("MOVE_POS2_M1"))
        stop_btn.clicked.connect(lambda: self.send_command("STOP_M1"))
        disable_btn.clicked.connect(lambda: self.send_command("DISABLE_M1"))

        return box

    def create_actuator_group(self):
        box = QGroupBox("Linear Actuator")
        layout = QVBoxLayout(box)

        extend_btn = QPushButton("Extend")
        retract_btn = QPushButton("Retract")
        stop_btn = QPushButton("Stop")

        self.actuator_state_label = QLabel("State: IDLE")
        limit_label = QLabel("Limits: Unknown")

        self.actuator_widgets = [extend_btn, retract_btn, stop_btn]

        extend_btn.clicked.connect(lambda: self.send_command("EXTEND"))
        retract_btn.clicked.connect(lambda: self.send_command("RETRACT"))
        stop_btn.clicked.connect(lambda: self.send_command("STOP_ACTUATOR"))

        layout.addWidget(extend_btn)
        layout.addWidget(retract_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(self.actuator_state_label)
        layout.addWidget(limit_label)

        return box
