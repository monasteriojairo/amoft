import time

from PySide6.QtCore import Signal, QTimer, Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QPushButton,
    QLabel, QGridLayout, QComboBox, QCheckBox, QSizePolicy,
    QDialog, QProgressBar
)

from controllers.arduino_controller import ArduinoController
from controllers.clearcore_controller import ClearCoreController
from controllers.pi_client import PiClient
from utils.config_manager import load_config
from utils.pi_gpio import PiGpioManager
from utils.serial_ports import PROBE_BAUDRATES, get_serial_ports


class ManualTab(QWidget):
    log_signal = Signal(str)
    pi_connection_signal = Signal(bool)
    clearcore_connection_signal = Signal(bool)
    arduino_connection_signal = Signal(bool)
    m0_status_signal = Signal(str)
    m1_status_signal = Signal(str)
    hardware_start_requested = Signal()
    hardware_stop_requested = Signal()
    command_failed_signal = Signal(str, str)

    def __init__(self):
        super().__init__()

        self.pi_client = PiClient(host="192.168.1.95", port=5000)
        self.clearcore_client = None
        self.arduino_client = None
        self.local_gpio = PiGpioManager(load_config())
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
        self.m0_diag_label = None
        self.m1_diag_label = None
        self.arduino_status_label = None
        self.arduino_diag_label = None
        self.actuator_state_label = None
        self.actuator_limits_label = None
        self.clearcore_capabilities = ""
        self.machine_state_label = None
        self.machine_inputs_label = None
        self.estop_override_checkbox = None
        self.limit_override_checkbox = None
        self.estop_override_active = False
        self.limit_override_active = False
        self.last_motor_status = {"M0": "off", "M1": "off"}
        self.machine_state = "idle"
        self.system_homed = False
        self.system_faulted = False
        self.estop_active = False
        self.auto_cycle_running = False
        self.motor_motion_direction = {"M0": "STOP", "M1": "STOP"}
        self.home_sequence_active = False
        self.home_step = None
        self.home_motor = None
        self.home_phase_started_at = 0.0
        self.home_release_timeout_s = 5.0
        self.home_seek_timeout_s = 15.0
        self.home_actuator_started_at = 0.0
        self.home_actuator_seen_retracting = False
        self.home_actuator_last_status = None
        self.home_actuator_timeout_s = 12.0
        self.home_poll_attempts = 0
        self.homing_dialog = None
        self.homing_dialog_label = None
        self.homing_dialog_phase = 0
        self.last_led_state = None
        self.last_gpio_inputs_response = None
        self.gpio_pin_map = {"M0_HOME": "23", "M1_HOME": "24"}
        self.last_home_switch_snapshot = {
            "M0_HOME": {"state": None, "raw": None},
            "M1_HOME": {"state": None, "raw": None},
        }
        self.last_home_switch_change = None
        self.last_estop_snapshot = {"state": None, "raw": None, "override": None}

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
        self.supervisor_timer = QTimer(self)
        self.supervisor_timer.setInterval(300)
        self.supervisor_timer.timeout.connect(self.poll_supervisor_state)
        self.home_timer = QTimer(self)
        self.home_timer.setInterval(300)
        self.home_timer.timeout.connect(self.advance_home_sequence)
        self.homing_dialog_timer = QTimer(self)
        self.homing_dialog_timer.setInterval(300)
        self.homing_dialog_timer.timeout.connect(self.update_homing_dialog)
        self.auto_retry_timer = QTimer(self)
        self.auto_retry_timer.setInterval(5000)
        self.auto_retry_timer.timeout.connect(self.auto_retry_devices)
        self.update_auto_retry_timer()
        self.update_supervisor_timer()
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
                gpio_config = self.pi_client.send("GPIO_CONFIG")
                self.log_signal.emit(gpio_config)
                self.cache_gpio_config(gpio_config)
                serial_ports = self.pi_client.send("SERIAL_PORTS")
                self.log_signal.emit(serial_ports)
                self.log_firmware_identity()
                self.status_timer.start()
                self.update_supervisor_timer()
                self.sync_estop_override_state()
                self.sync_limit_override_state()
                self.refresh_supervisor_snapshot()
            self.update_connection_label()
        except Exception as e:
            self.pi_connected = False
            self.set_pi_connected(False)
            self.status_timer.stop()
            self.update_supervisor_timer()
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

            port_info = self.find_port_info(port)
            identity = None
            for baudrate in self.baudrate_candidates(port_info):
                try:
                    self.clearcore_client = ClearCoreController(port=port, baudrate=baudrate)
                    self.clearcore_client.connect()
                    identity = self.read_clearcore_identity()
                    if self.is_clearcore_identity(identity):
                        break
                finally:
                    if not self.is_clearcore_identity(identity):
                        if self.clearcore_client is not None:
                            self.clearcore_client.close()
                        self.clearcore_client = None
            else:
                raise RuntimeError(f"{port} is not ClearCore; identity={identity!r}")

            self.log_signal.emit(f"ClearCore connection successful: {port}")
            self.log_firmware_identity(identity=identity)
            self.set_clearcore_connected(True)
            self.set_motor_status("M0", "disabled")
            self.set_motor_status("M1", "disabled")
            if self.local_gpio.enabled:
                gpio_config = self.local_gpio.config_summary()
                self.log_signal.emit(f"Local {gpio_config}")
                self.cache_gpio_config(gpio_config)
            self.update_supervisor_timer()
            self.sync_estop_override_state()
            self.sync_limit_override_state()
            self.clear_inactive_estop_latch()
            self.log_clearcore_diagnostics()
            self.status_timer.start()
            self.update_connection_label()
        except Exception as e:
            self.clearcore_client = None
            self.set_clearcore_connected(False)
            self.set_motor_status("M0", "off")
            self.set_motor_status("M1", "off")
            self.status_timer.stop()
            self.update_supervisor_timer()
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
        self.update_supervisor_timer()
        self.home_timer.stop()
        self.home_sequence_active = False
        self.set_machine_state("idle")
        self.update_connection_label()
        self.log_signal.emit("Disconnected all links")

    def send_command(self, cmd: str):
        self.log_signal.emit(f"Command given -> {cmd}")
        gate_reason = self.pi_software_motion_gate_reason(cmd)
        if gate_reason is not None:
            response = f"ERR PI_SOFTWARE_LIMIT {gate_reason}"
            self.log_signal.emit(f"Command failed ({cmd}): {response}")
            self.command_failed_signal.emit(cmd, response)
            return

        try:
            response = self.route_command(cmd)
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
            self.command_failed_signal.emit(cmd, str(e))

            if self.mode_combo.currentData() == "pi" and cmd == "PING":
                self.set_pi_connected(False)

            self.update_connection_label()
            return

        if self.is_benign_stop_response(cmd, response):
            self.track_motor_motion_from_command(cmd)
            self.log_signal.emit(f"{cmd} -> {response} (already stopped)")
            return

        if self.response_has_error(response):
            self.log_signal.emit(f"Command failed ({cmd}): {response}")
            self.command_failed_signal.emit(cmd, response)
            if self.is_actuator_command(cmd):
                self.schedule_actuator_diagnostics(cmd)
            else:
                self.log_clearcore_diagnostics()
            return

        self.track_motor_motion_from_command(cmd)
        self.update_motor_status_from_command(cmd)
        self.update_motor_diagnostics_from_response(cmd, response)
        self.update_actuator_status_from_command(cmd, response)
        self.schedule_actuator_diagnostics(cmd)
        if not cmd.startswith("PING"):
            self.refresh_motor_statuses()

        self.log_signal.emit(f"{cmd} -> {response}")

    def parse_csv_response(self, response: str, prefix: str):
        if response is None:
            return {}
        normalized = response.strip()
        if not normalized.startswith(prefix):
            return {}
        payload = normalized[len(prefix):]
        parts = [part.strip() for part in payload.split(",") if part.strip()]
        parsed = {}
        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            parsed[key.strip()] = value.strip()
        return parsed

    def cache_gpio_config(self, response: str):
        config = self.parse_csv_response(response, "GPIO_CONFIG:")
        if not config:
            return

        for key in ("M0_HOME", "M1_HOME"):
            pin_key = f"{key}_PIN"
            if pin_key in config:
                self.gpio_pin_map[key] = config[pin_key]

        m0_pin = self.gpio_pin_map.get("M0_HOME", "?")
        m1_pin = self.gpio_pin_map.get("M1_HOME", "?")
        self.log_signal.emit(
            f"Pi home switch mapping -> M0_HOME=GPIO{m0_pin}, M1_HOME=GPIO{m1_pin}"
        )
        if m0_pin == m1_pin:
            self.log_signal.emit(
                "Pi home switch warning -> M0_HOME and M1_HOME are configured for the same GPIO pin"
            )

    def log_home_switch_transitions(self, gpio_inputs):
        changed = []
        changed_after_initial = []
        for key in ("M0_HOME", "M1_HOME"):
            state = gpio_inputs.get(key)
            raw = gpio_inputs.get(f"{key}_RAW")
            if state is None and raw is None:
                continue

            previous = self.last_home_switch_snapshot[key]
            had_previous = previous["state"] is not None or previous["raw"] is not None
            if previous["state"] == state and previous["raw"] == raw:
                continue

            previous["state"] = state
            previous["raw"] = raw
            changed.append(key)
            if had_previous:
                changed_after_initial.append(key)
                self.last_home_switch_change = {
                    "time": time.monotonic(),
                    "key": key,
                    "state": state,
                    "raw": raw,
                }

            pin = self.gpio_pin_map.get(key, "?")
            status = "ACTIVE" if state == "1" else "INACTIVE"
            self.log_signal.emit(
                f"Pi home switch {key} GPIO{pin} -> {status} raw={raw if raw is not None else '?'}"
            )

        if len(changed_after_initial) > 1:
            pins = ", ".join(
                f"{key}=GPIO{self.gpio_pin_map.get(key, '?')}" for key in changed_after_initial
            )
            self.log_signal.emit(
                "Pi home switch warning -> multiple home switches changed together "
                f"({pins}); if only one physical switch moved, check for a shared node or jumper"
            )

    def log_estop_transitions(self, inputs):
        state = inputs.get("ESTOP")
        raw = inputs.get("ESTOP_RAW")
        override = inputs.get("ESTOP_OVERRIDE")
        if state is None and raw is None and override is None:
            return

        previous = self.last_estop_snapshot
        had_previous = (
            previous["state"] is not None
            or previous["raw"] is not None
            or previous["override"] is not None
        )
        if (
            previous["state"] == state
            and previous["raw"] == raw
            and previous["override"] == override
        ):
            return

        previous["state"] = state
        previous["raw"] = raw
        previous["override"] = override
        status = "ACTIVE" if state == "1" else "INACTIVE"
        self.log_signal.emit(
            f"ClearCore E-stop input -> {status} raw={raw if raw is not None else '?'} "
            f"override={override if override is not None else '?'}"
        )
        if state == "1":
            self.log_clearcore_pin_states("E-stop transition")

        if not had_previous or state != "1" or not self.last_home_switch_change:
            return

        elapsed_s = time.monotonic() - self.last_home_switch_change["time"]
        if elapsed_s > 2.0:
            return

        key = self.last_home_switch_change["key"]
        pin = self.gpio_pin_map.get(key, "?")
        home_state = self.last_home_switch_change.get("state")
        home_status = "ACTIVE" if home_state == "1" else "INACTIVE"
        self.log_signal.emit(
            "ClearCore E-stop warning -> E-stop tripped "
            f"{elapsed_s:.1f}s after {key} GPIO{pin} became {home_status}; "
            "check that this home switch is not tied to ClearCore IO-0 or the E-stop circuit"
        )

    def clearcore_supports_pin_states(self):
        return "PIN_STATES" in (self.clearcore_capabilities or "").upper()

    def log_clearcore_pin_states(self, reason: str):
        if not self.clearcore_supports_pin_states() or not self.command_transport_ready():
            return
        try:
            response = self.send_raw_command("PIN_STATES")
            self.log_signal.emit(f"ClearCore {reason} PIN_STATES -> {response}")
        except Exception as e:
            self.log_signal.emit(f"ClearCore PIN_STATES failed ({reason}): {e}")

    def is_benign_stop_response(self, cmd: str, response: str):
        normalized = (response or "").strip().upper()
        return cmd in {"STOP_M0", "STOP_M1"} and normalized == f"ERR {cmd}"

    def set_machine_state(self, state: str):
        self.machine_state = state
        if self.machine_state_label is not None:
            self.machine_state_label.setText(f"Machine: {state.upper()}")
        self.update_clearcore_leds()

    def set_machine_inputs_text(self, text: str):
        if self.machine_inputs_label is not None:
            self.machine_inputs_label.setText(text)

    def show_homing_dialog(self):
        if self.homing_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Homing")
            dialog.setModal(False)
            dialog.setFixedSize(340, 150)

            layout = QVBoxLayout(dialog)
            self.homing_dialog_label = QLabel("HOMING,,,,,")
            self.homing_dialog_label.setAlignment(Qt.AlignCenter)
            self.homing_dialog_label.setStyleSheet("font-size: 24px; font-weight: bold;")

            progress = QProgressBar()
            progress.setRange(0, 0)

            note = QLabel("Keep hands clear. Press STOP to abort.")
            note.setAlignment(Qt.AlignCenter)
            note.setWordWrap(True)

            layout.addWidget(self.homing_dialog_label)
            layout.addWidget(progress)
            layout.addWidget(note)
            self.homing_dialog = dialog

        self.homing_dialog_phase = 0
        self.update_homing_dialog()
        self.center_homing_dialog()
        self.homing_dialog.show()
        self.homing_dialog.raise_()
        self.homing_dialog_timer.start()

    def center_homing_dialog(self):
        if self.homing_dialog is None:
            return
        parent_rect = self.window().frameGeometry()
        dialog_rect = self.homing_dialog.frameGeometry()
        dialog_rect.moveCenter(parent_rect.center())
        self.homing_dialog.move(dialog_rect.topLeft())

    def update_homing_dialog(self):
        if self.homing_dialog_label is None:
            return
        comma_count = 1 + (self.homing_dialog_phase % 5)
        self.homing_dialog_label.setText("HOMING" + ("," * comma_count))
        self.homing_dialog_phase += 1

    def hide_homing_dialog(self):
        if hasattr(self, "homing_dialog_timer"):
            self.homing_dialog_timer.stop()
        if self.homing_dialog is not None:
            self.homing_dialog.hide()

    def set_estop_override_checked(self, checked: bool):
        self.estop_override_active = checked
        if self.estop_override_checkbox is None:
            return

        self.estop_override_checkbox.blockSignals(True)
        self.estop_override_checkbox.setChecked(checked)
        self.estop_override_checkbox.blockSignals(False)

    def set_limit_override_checked(self, checked: bool):
        self.limit_override_active = checked
        if self.limit_override_checkbox is None:
            return

        self.limit_override_checkbox.blockSignals(True)
        self.limit_override_checkbox.setChecked(checked)
        self.limit_override_checkbox.blockSignals(False)

    def sync_estop_override_state(self):
        if not self.command_transport_ready():
            return

        try:
            response = self.send_raw_command("ESTOP_OVERRIDE")
        except Exception as e:
            self.log_signal.emit(f"E-stop override state unavailable: {e}")
            self.set_estop_override_checked(False)
            return

        normalized = (response or "").strip().upper()
        if normalized == "ESTOP_OVERRIDE:1":
            self.set_estop_override_checked(True)
        elif normalized == "ESTOP_OVERRIDE:0":
            self.set_estop_override_checked(False)
        else:
            self.log_signal.emit(f"E-stop override state unavailable: {response}")
            self.set_estop_override_checked(False)

    def sync_limit_override_state(self):
        self.set_limit_override_checked(self.limit_override_active)

    def on_estop_override_toggled(self, checked: bool):
        command = f"SET_ESTOP_OVERRIDE:{1 if checked else 0}"
        previous = self.estop_override_active

        if not self.command_transport_ready():
            self.log_signal.emit("E-stop override skipped: no active ClearCore transport")
            self.set_estop_override_checked(previous)
            return

        self.log_signal.emit(f"Command given -> {command}")
        try:
            response = self.route_command(command)
            if self.response_has_error(response):
                raise RuntimeError(response)

            self.log_signal.emit(f"{command} -> {response}")
            self.set_estop_override_checked(checked)

            if checked:
                self.log_signal.emit("Command given -> CLEAR_FAULTS")
                clear_response = self.route_command("CLEAR_FAULTS")
                if self.response_has_error(clear_response):
                    self.log_signal.emit(f"Command failed (CLEAR_FAULTS): {clear_response}")
                else:
                    self.log_signal.emit(f"CLEAR_FAULTS -> {clear_response}")

            self.refresh_motor_statuses()
            self.log_clearcore_diagnostics()
        except Exception as e:
            self.log_signal.emit(f"Command failed ({command}): {e}")
            if checked:
                self.log_signal.emit("Upload the updated ClearCore firmware to use E-stop override.")
            self.set_estop_override_checked(previous)

    def on_limit_override_toggled(self, checked: bool):
        self.set_limit_override_checked(checked)
        state = "ON" if checked else "OFF"
        self.log_signal.emit(f"Pi software limit/home override -> {state}")

    def clear_inactive_estop_latch(self):
        if not self.command_transport_ready():
            return

        try:
            inputs_response = self.send_raw_command("INPUTS")
            faults_response = self.send_raw_command("FAULTS")
        except Exception as e:
            self.log_signal.emit(f"Startup fault clear skipped: {e}")
            return

        inputs = self.parse_csv_response(inputs_response, "INPUTS:")
        faults = self.parse_csv_response(faults_response, "FAULTS:")
        stale_estop_latch = (
            inputs.get("ESTOP") == "0"
            and faults.get("LATCH") == "1"
            and faults.get("LATCH_ESTOP") == "1"
            and faults.get("M0_DRIVER") != "1"
            and faults.get("M1_DRIVER") != "1"
        )
        if not stale_estop_latch:
            return

        self.log_signal.emit("Startup fault clear: stale E-stop latch detected")
        self.log_signal.emit("Command given -> CLEAR_FAULTS")
        try:
            response = self.route_command("CLEAR_FAULTS")
        except Exception as e:
            self.log_signal.emit(f"Command failed (CLEAR_FAULTS): {e}")
            return

        if self.response_has_error(response):
            self.log_signal.emit(f"Command failed (CLEAR_FAULTS): {response}")
        else:
            self.log_signal.emit(f"CLEAR_FAULTS -> {response}")

    def send_pi_best_effort(self, command: str):
        return self.send_machine_best_effort(command)

    def send_machine_best_effort(self, command: str):
        self.log_signal.emit(f"Command given -> {command}")
        try:
            response = self.route_command(command)
            self.log_signal.emit(f"{command} -> {response}")
            if not self.response_has_error(response):
                self.track_motor_motion_from_command(command)
            return response
        except Exception as e:
            self.log_signal.emit(f"Command failed ({command}): {e}")
            return None

    def refresh_supervisor_snapshot(self):
        self.update_supervisor_inputs()
        self.update_actuator_supervisor_status()
        self.update_clearcore_leds()

    def poll_supervisor_state(self):
        mode = self.mode_combo.currentData()
        if mode == "pi":
            if not self.pi_connected:
                return

            self.refresh_supervisor_snapshot()

            try:
                event_response = self.pi_client.send("GPIO_EVENTS")
            except Exception as e:
                self.log_signal.emit(f"Supervisor event poll failed: {e}")
                self.set_pi_connected(False)
                self.update_supervisor_timer()
                return

            if event_response == "EVENT:NONE":
                return

            if event_response.startswith("EVENT:"):
                self.log_signal.emit(f"GPIO event poll -> {event_response}")
                self.handle_clearcore_event(event_response.split(":", 1)[1].strip())
            return

        if mode != "local" or not self.local_gpio.available:
            return

        try:
            self.refresh_supervisor_snapshot()
            event_name = self.local_gpio.get_event()
        except Exception as e:
            self.log_signal.emit(f"Local GPIO poll failed: {e}")
            return

        if event_name == "NONE":
            return

        event_response = f"EVENT:{event_name}"
        self.log_signal.emit(f"GPIO event poll -> {event_response}")
        self.handle_clearcore_event(event_name)

    def update_supervisor_inputs(self):
        mode = self.mode_combo.currentData()

        try:
            if mode == "pi":
                if not self.pi_connected:
                    return
                gpio_input_response = self.pi_client.send("GPIO_INPUTS")
                clearcore_input_response = self.pi_client.send("INPUTS")
                controller_response = self.pi_client.send("CONTROLLER_STATE")
            elif mode == "local":
                if self.local_gpio.available:
                    gpio_input_response = self.local_gpio.input_summary()
                else:
                    gpio_input_response = (
                        "GPIO_INPUTS:START=0,STOP=0,HOME=0,"
                        "START_RAW=NA,STOP_RAW=NA,HOME_RAW=NA"
                    )
                if self.command_transport_ready():
                    clearcore_input_response = self.send_raw_command("INPUTS")
                    controller_response = self.send_raw_command("CONTROLLER_STATE")
                else:
                    clearcore_input_response = "INPUTS:"
                    controller_response = "CONTROLLER_STATE:"
            else:
                return
        except Exception as e:
            self.log_signal.emit(f"Supervisor input poll failed: {e}")
            return

        if gpio_input_response != self.last_gpio_inputs_response:
            self.log_signal.emit(f"GPIO inputs -> {gpio_input_response}")
            self.last_gpio_inputs_response = gpio_input_response

        gpio_inputs = self.parse_csv_response(gpio_input_response, "GPIO_INPUTS:")
        self.log_home_switch_transitions(gpio_inputs)
        inputs = self.parse_csv_response(clearcore_input_response, "INPUTS:")
        controller = self.parse_csv_response(controller_response, "CONTROLLER_STATE:")
        self.log_estop_transitions(inputs)

        self.estop_active = inputs.get("ESTOP") == "1"
        clearcore_fault = controller.get("FAULT") == "1"
        clearcore_homed = controller.get("M0_HOMED") == "1" and controller.get("M1_HOMED") == "1"
        self.system_homed = clearcore_homed and not self.home_sequence_active

        if self.estop_active:
            self.system_faulted = True
            self.set_machine_state("estop_active")
        elif clearcore_fault and not self.home_sequence_active:
            self.system_faulted = True
            self.set_machine_state("faulted")
        elif not self.home_sequence_active and not self.auto_cycle_running:
            self.system_faulted = False
            self.set_machine_state("ready" if self.system_homed else "idle")

        summary = (
            f"Inputs: estop={inputs.get('ESTOP', '?')} override={inputs.get('ESTOP_OVERRIDE', '?')} "
            f"pi_limit_override={int(self.limit_override_active)} "
            f"cc_limit_interlock={inputs.get('LIMIT_INTERLOCK', '?')} "
            f"start={gpio_inputs.get('START', '?')} "
            f"stop={gpio_inputs.get('STOP', '?')} home={gpio_inputs.get('HOME', '?')} "
            f"pi_m0_home={gpio_inputs.get('M0_HOME', '?')} "
            f"pi_m1_home={gpio_inputs.get('M1_HOME', '?')} "
            f"cc_m0_home={inputs.get('M0_HOME', '?')} m0_limit={inputs.get('M0_LIMIT', '?')} "
            f"cc_m1_home={inputs.get('M1_HOME', '?')} m1_limit={inputs.get('M1_LIMIT', '?')}"
        )
        self.set_machine_inputs_text(summary)
        self.enforce_pi_software_limits(gpio_inputs)

    def update_actuator_supervisor_status(self):
        if not self.actuator_transport_ready():
            return

        try:
            actuator_status = self.route_command("STATUS_ACTUATOR")
        except Exception:
            return

        normalized = (actuator_status or "").strip().upper()
        if self.actuator_state_label is not None and normalized:
            self.actuator_state_label.setText(f"State: {normalized}")

        if normalized == "FAULT":
            self.system_faulted = True
            if not self.estop_active and not self.home_sequence_active:
                self.set_machine_state("faulted")

    def update_clearcore_leds(self):
        ready = int(self.machine_state == "ready")
        running = int(self.machine_state in {"running", "homing", "actuator_retracting"})
        fault = int(self.machine_state in {"faulted", "estop_active"})
        led_state = (ready, running, fault)
        if led_state == self.last_led_state:
            return

        try:
            if self.mode_combo.currentData() == "pi":
                if not self.pi_connected:
                    return
                self.pi_client.send(f"GPIO_SET_LEDS:{ready},{running},{fault}")
            elif self.local_gpio.available:
                self.local_gpio.set_leds(bool(ready), bool(running), bool(fault))
            else:
                return
            self.last_led_state = led_state
        except Exception as e:
            self.log_signal.emit(f"LED update failed: {e}")

    def handle_clearcore_event(self, event_name: str):
        normalized = event_name.upper()
        self.log_signal.emit(f"Hardware event -> {normalized}")
        if normalized == "START":
            self.handle_hardware_start()
        elif normalized == "STOP":
            self.handle_hardware_stop()
        elif normalized == "HOME":
            self.handle_hardware_home()

    def handle_hardware_start(self):
        self.log_signal.emit(
            "Hardware START gate -> "
            f"estop={int(self.estop_active)} "
            f"faulted={int(self.system_faulted)} "
            f"homed={int(self.system_homed)} "
            f"homing={int(self.home_sequence_active)}"
        )
        if self.home_sequence_active:
            self.log_signal.emit("Hardware START rejected: homing active")
            self.set_machine_state("homing")
            return
        if self.estop_active:
            self.log_signal.emit("Hardware START rejected: E-stop active")
            self.set_machine_state("estop_active")
            return
        if self.system_faulted:
            self.log_signal.emit("Hardware START rejected: system faulted")
            self.set_machine_state("faulted")
            return

        self.log_signal.emit("Hardware START accepted: requesting auto queue start")
        self.set_machine_state("running")
        self.hardware_start_requested.emit()

    def handle_hardware_stop(self):
        self.hardware_stop_requested.emit()
        if self.home_sequence_active:
            self.home_timer.stop()
            self.home_sequence_active = False
            self.home_step = None
            self.home_motor = None
            self.hide_homing_dialog()
            self.log_signal.emit("Home sequence aborted by hardware STOP")
        for command in ("STOP_M0", "DISABLE_M0", "STOP_M1", "DISABLE_M1", "STOP_ACTUATOR"):
            self.send_machine_best_effort(command)
        if self.estop_active:
            self.set_machine_state("estop_active")
        else:
            self.set_machine_state("stopped")

    def handle_hardware_home(self):
        if self.home_sequence_active:
            self.log_signal.emit("Hardware HOME ignored: homing already active")
            return
        if self.estop_active:
            self.log_signal.emit("Hardware HOME rejected: E-stop active")
            self.set_machine_state("estop_active")
            return
        self.log_signal.emit("Hardware HOME accepted: retracting actuator and homing servos")
        self.start_home_sequence()

    def send_home_command(self, command: str):
        response = self.route_command(command)
        if self.response_has_error(response):
            raise RuntimeError(response)
        self.track_motor_motion_from_command(command)
        self.log_signal.emit(f"Home sequence -> {command} -> {response}")
        return response

    def read_clearcore_inputs_for_home(self):
        response = self.route_command("INPUTS")
        if self.response_has_error(response):
            raise RuntimeError(response)
        inputs = self.parse_csv_response(response, "INPUTS:")
        gpio_inputs = self.read_gpio_inputs_for_home()
        for motor_name in ("M0", "M1"):
            for input_name in ("HOME", "LIMIT"):
                input_key = f"{motor_name}_{input_name}"
                raw_key = f"{input_key}_RAW"
                if input_key in gpio_inputs:
                    inputs[input_key] = gpio_inputs[input_key]
                    inputs[raw_key] = gpio_inputs.get(raw_key, gpio_inputs[input_key])
                    inputs[f"{input_key}_SOURCE"] = "PI"
        return inputs

    def read_gpio_inputs_for_home(self):
        try:
            if self.mode_combo.currentData() == "pi":
                if not self.pi_connected:
                    return {}
                response = self.pi_client.send("GPIO_INPUTS")
            elif self.local_gpio.available:
                response = self.local_gpio.input_summary()
            else:
                return {}
        except Exception as e:
            self.log_signal.emit(f"Home GPIO input read failed: {e}")
            return {}

        return self.parse_csv_response(response, "GPIO_INPUTS:")

    def home_input_active(self, inputs, motor_name: str):
        raw_key = f"{motor_name}_HOME_RAW"
        effective_key = f"{motor_name}_HOME"
        if inputs.get(f"{motor_name}_HOME_SOURCE") == "PI":
            return inputs.get(effective_key, "0") == "1"
        return inputs.get(raw_key, inputs.get(effective_key, "0")) == "1"

    def limit_input_active(self, inputs, motor_name: str):
        raw_key = f"{motor_name}_LIMIT_RAW"
        effective_key = f"{motor_name}_LIMIT"
        if inputs.get(f"{motor_name}_LIMIT_SOURCE") != "PI":
            return False
        return inputs.get(raw_key, inputs.get(effective_key, "0")) == "1"

    def last_gpio_inputs(self):
        return self.parse_csv_response(self.last_gpio_inputs_response, "GPIO_INPUTS:")

    def pi_software_motion_gate_reason(self, cmd: str):
        if self.limit_override_active or self.home_sequence_active:
            return None

        for motor_name in ("M0", "M1"):
            if cmd == self.move_toward_home_command(motor_name):
                gpio_inputs = self.last_gpio_inputs()
                if gpio_inputs.get(f"{motor_name}_HOME") == "1":
                    return f"{motor_name}_HOME active"
        return None

    def track_motor_motion_from_command(self, cmd: str):
        for motor_name in ("M0", "M1"):
            if cmd == self.move_toward_home_command(motor_name):
                self.motor_motion_direction[motor_name] = "HOME"
            elif cmd == self.move_away_from_home_command(motor_name):
                self.motor_motion_direction[motor_name] = "AWAY"
            elif cmd in {f"STOP_{motor_name}", f"DISABLE_{motor_name}"}:
                self.motor_motion_direction[motor_name] = "STOP"

    def enforce_pi_software_limits(self, gpio_inputs):
        if self.limit_override_active or self.home_sequence_active:
            return
        if not self.command_transport_ready():
            return

        for motor_name in ("M0", "M1"):
            if (
                self.motor_motion_direction.get(motor_name) == "HOME"
                and gpio_inputs.get(f"{motor_name}_HOME") == "1"
            ):
                self.motor_motion_direction[motor_name] = "STOP"
                self.log_signal.emit(
                    f"Pi software limit -> {motor_name}_HOME active; stopping {motor_name}"
                )
                self.send_machine_best_effort(f"STOP_{motor_name}")

    def move_toward_home_command(self, motor_name: str):
        return f"MOVE_POS2_{motor_name}"

    def move_away_from_home_command(self, motor_name: str):
        return f"MOVE_POS1_{motor_name}"

    def start_servo_home(self, motor_name: str):
        self.home_motor = motor_name
        self.set_machine_state("homing")
        self.log_signal.emit(f"Home sequence -> software homing {motor_name}")

        self.send_home_command(f"SET_HOME_{motor_name}:0")
        self.send_home_command(f"ENABLE_{motor_name}")

        inputs = self.read_clearcore_inputs_for_home()
        if inputs.get("ESTOP") == "1":
            self.fail_home_sequence(self.format_estop_home_abort("before servo homing", inputs))
            return

        if self.home_input_active(inputs, motor_name):
            self.home_step = "servo_release"
            self.home_phase_started_at = time.monotonic()
            source = inputs.get(f"{motor_name}_HOME_SOURCE", "ClearCore")
            self.log_signal.emit(
                f"Home sequence -> {motor_name} releasing home switch ({source})"
            )
            self.send_home_command(self.move_away_from_home_command(motor_name))
            return

        self.start_servo_home_seek(motor_name)

    def start_servo_home_seek(self, motor_name: str):
        self.home_step = "servo_seek"
        self.home_phase_started_at = time.monotonic()
        inputs = self.read_clearcore_inputs_for_home()
        source = inputs.get(f"{motor_name}_HOME_SOURCE", "ClearCore")
        self.log_signal.emit(f"Home sequence -> {motor_name} seeking home switch ({source})")
        self.send_home_command(self.move_toward_home_command(motor_name))

    def complete_servo_home(self, motor_name: str):
        self.send_home_command(f"STOP_{motor_name}")
        self.send_home_command(f"SET_HOME_{motor_name}:1")
        self.log_signal.emit(f"Home sequence -> {motor_name} home complete")
        if motor_name == "M0":
            self.start_servo_home("M1")
        else:
            self.complete_home_sequence()

    def advance_servo_home_sequence(self):
        motor_name = self.home_motor
        if motor_name is None:
            self.fail_home_sequence("Servo homing state missing motor")
            return

        inputs = self.read_clearcore_inputs_for_home()
        if inputs.get("ESTOP") == "1":
            self.fail_home_sequence(self.format_estop_home_abort("during servo homing", inputs))
            return

        elapsed_s = time.monotonic() - self.home_phase_started_at
        home_active = self.home_input_active(inputs, motor_name)
        limit_active = (
            not self.limit_override_active
            and self.limit_input_active(inputs, motor_name)
        )

        if self.home_step == "servo_release":
            if limit_active:
                self.fail_home_sequence(f"{motor_name} limit active while releasing home")
                return
            if not home_active:
                try:
                    self.send_home_command(f"STOP_{motor_name}")
                    self.start_servo_home_seek(motor_name)
                except Exception as e:
                    self.fail_home_sequence(f"{motor_name} release stop failed: {e}")
                return
            if elapsed_s > self.home_release_timeout_s:
                self.fail_home_sequence(
                    f"{motor_name} failed to release home switch; "
                    f"{motor_name}_HOME stayed active"
                )
            return

        if self.home_step == "servo_seek":
            if home_active:
                try:
                    self.complete_servo_home(motor_name)
                except Exception as e:
                    self.fail_home_sequence(f"{motor_name} home completion failed: {e}")
                return
            if elapsed_s > self.home_seek_timeout_s:
                self.fail_home_sequence(f"{motor_name} failed to reach home switch")

    def start_home_sequence(self):
        self.send_machine_best_effort("CLEAR_FAULTS")
        self.send_machine_best_effort("CLEAR_FAULT")
        self.home_sequence_active = True
        self.system_faulted = False
        self.system_homed = False
        self.home_step = "actuator_retract"
        self.home_motor = None
        self.home_poll_attempts = 0
        self.home_actuator_started_at = time.monotonic()
        self.home_actuator_seen_retracting = False
        self.home_actuator_last_status = None
        self.set_machine_state("actuator_retracting")
        self.show_homing_dialog()
        self.log_signal.emit("Home sequence -> timed actuator retract before servo homing")

        try:
            response = self.send_home_command("RETRACT")
        except Exception as e:
            self.fail_home_sequence(f"Actuator retract command failed: {e}")
            return

        if response.strip().upper().startswith("ERR"):
            self.fail_home_sequence(f"Actuator retract rejected: {response}")
            return

        self.home_timer.start()

    def advance_home_sequence(self):
        if not self.command_transport_ready() or not self.actuator_transport_ready():
            self.fail_home_sequence("Hardware link unavailable during homing")
            return

        if self.home_step == "actuator_retract":
            self.home_poll_attempts += 1
            try:
                status = self.route_command("STATUS_ACTUATOR").strip().upper()
            except Exception as e:
                self.fail_home_sequence(f"Actuator status poll failed: {e}")
                return

            self.actuator_state_label.setText(f"State: {status}")
            if status != self.home_actuator_last_status:
                self.log_signal.emit(f"Home sequence -> actuator status {status}")
                self.home_actuator_last_status = status

            if status in {"RETRACTING", "HOMING"}:
                self.home_actuator_seen_retracting = True
                return

            retract_elapsed_s = time.monotonic() - self.home_actuator_started_at
            if status == "RETRACTED" or (
                status == "READY" and self.home_actuator_seen_retracting
            ):
                try:
                    self.log_signal.emit("Home sequence -> actuator retract complete")
                    self.start_servo_home("M0")
                except Exception as e:
                    self.fail_home_sequence(f"M0 software home setup failed: {e}")
                return

            if status == "FAULT" or retract_elapsed_s > self.home_actuator_timeout_s:
                self.fail_home_sequence("Actuator failed to reach retracted state")
                return
            return

        if self.home_step in {"servo_release", "servo_seek"}:
            try:
                self.advance_servo_home_sequence()
            except Exception as e:
                self.fail_home_sequence(f"Servo software home failed: {e}")
            return

    def fail_home_sequence(self, message: str):
        self.home_timer.stop()
        self.home_sequence_active = False
        self.home_step = None
        self.home_motor = None
        self.system_faulted = True
        self.system_homed = False
        self.hide_homing_dialog()
        for command in ("STOP_M0", "DISABLE_M0", "STOP_M1", "DISABLE_M1", "STOP_ACTUATOR"):
            self.send_machine_best_effort(command)
        self.set_machine_state("faulted")
        self.log_signal.emit(message)

    def format_estop_home_abort(self, context: str, inputs):
        return (
            f"E-stop active {context}; "
            f"ESTOP={inputs.get('ESTOP', '?')} "
            f"ESTOP_RAW={inputs.get('ESTOP_RAW', '?')} "
            f"ESTOP_OVERRIDE={inputs.get('ESTOP_OVERRIDE', '?')}"
        )

    def complete_home_sequence(self):
        self.home_timer.stop()
        self.home_sequence_active = False
        self.home_step = None
        self.home_motor = None
        self.system_faulted = False
        self.system_homed = True
        self.hide_homing_dialog()
        self.set_machine_state("ready")
        self.log_signal.emit("Home sequence complete")

    def on_cycle_state_changed(self, state: str):
        self.auto_cycle_running = state == "running"
        if self.estop_active:
            self.set_machine_state("estop_active")
        elif self.home_sequence_active:
            self.set_machine_state("homing")
        elif state == "running":
            self.set_machine_state("running")
        elif self.system_faulted:
            self.set_machine_state("faulted")
        elif self.system_homed:
            self.set_machine_state("ready")
        elif state == "stopped":
            self.set_machine_state("stopped")
        else:
            self.set_machine_state("idle")

    def update_motor_diagnostics_from_response(self, cmd: str, response: str):
        motor_name = "M0" if cmd.endswith("_M0") else "M1" if cmd.endswith("_M1") else None
        if motor_name is None:
            return

        normalized = (response or "").strip()
        if cmd.startswith("PING_"):
            self.set_motor_diag_text(motor_name, f"Diagnostics: ping={normalized}")
        elif cmd.startswith("ENABLE_"):
            self.set_motor_diag_text(motor_name, f"Diagnostics: enable={normalized}")
        elif cmd.startswith("DISABLE_"):
            self.set_motor_diag_text(motor_name, f"Diagnostics: disable={normalized}")
        elif cmd.startswith("MOVE_") or cmd.startswith("STOP_"):
            self.set_motor_diag_text(motor_name, f"Diagnostics: reply={normalized}")

    def command_transport_ready(self):
        if self.mode_combo.currentData() == "local":
            return self.clearcore_connected and self.clearcore_client is not None
        return self.pi_connected

    def actuator_transport_ready(self):
        if self.mode_combo.currentData() == "local":
            return self.arduino_connected and self.arduino_client is not None
        return self.pi_connected

    def is_actuator_command(self, cmd: str):
        return cmd in {
            "EXTEND",
            "RETRACT",
            "HOME",
            "HOME_ACTUATOR",
            "RETRACT_TO_HOME",
            "STOP_ACTUATOR",
            "STOP",
            "STATUS_ACTUATOR",
            "LIMITS",
            "CLEAR_FAULT",
            "CYCLE",
            "DIAG",
            "DIAGNOSTICS",
        }

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

    def schedule_actuator_diagnostics(self, cmd: str):
        if cmd in {"STATUS_ACTUATOR", "LIMITS", "DIAG", "DIAGNOSTICS"}:
            return
        if not self.is_actuator_command(cmd):
            return
        QTimer.singleShot(350, self.log_actuator_diagnostics)

    def log_actuator_diagnostics(self):
        if not self.actuator_transport_ready():
            return

        for command in ("STATUS_ACTUATOR", "LIMITS", "DIAG"):
            try:
                response = self.send_actuator_probe(command)
                self.log_signal.emit(f"{command} -> {response}")
                self.update_actuator_status_from_command(command, response)
            except Exception as e:
                self.log_signal.emit(f"Actuator diagnostic failed ({command}): {e}")

    def send_actuator_probe(self, cmd: str):
        if self.mode_combo.currentData() == "local":
            return self.send_local_arduino_command(cmd)
        return self.pi_client.send(cmd)

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
        self.update_supervisor_timer()
        self.update_connection_controls()

    def set_clearcore_connected(self, connected: bool):
        self.clearcore_connected = connected
        self.clearcore_connection_signal.emit(connected)
        self.refresh_port_labels()
        self.update_auto_retry_timer()
        self.update_supervisor_timer()
        if connected:
            self.set_motor_diag_text("M0", "Diagnostics: connected")
            self.set_motor_diag_text("M1", "Diagnostics: connected")
        else:
            self.set_motor_diag_text("M0", "Diagnostics: disconnected")
            self.set_motor_diag_text("M1", "Diagnostics: disconnected")
        self.update_connection_controls()

    def set_arduino_connected(self, connected: bool):
        self.arduino_connected = connected
        self.arduino_connection_signal.emit(connected)
        if self.arduino_status_label is not None:
            text = "Arduino: CONNECTED" if connected else "Arduino: DISCONNECTED"
            self.arduino_status_label.setText(text)
        self.refresh_port_labels()
        self.update_auto_retry_timer()
        self.update_supervisor_timer()
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

    def set_motor_diag_text(self, motor_name: str, text: str):
        if motor_name == "M0":
            if self.m0_diag_label is not None:
                self.m0_diag_label.setText(text)
        else:
            if self.m1_diag_label is not None:
                self.m1_diag_label.setText(text)

    def update_motor_status_from_command(self, cmd: str):
        motor_name = "M0" if cmd.endswith("_M0") else "M1" if cmd.endswith("_M1") else None
        if motor_name is None:
            return

        if cmd.startswith("PING_"):
            self.set_motor_diag_text(motor_name, f"Diagnostics: ping=sent")
            return

        if cmd.startswith("ENABLE_"):
            self.set_motor_status(motor_name, "enabled")
            self.set_clearcore_connected(True)
            self.set_motor_diag_text(motor_name, "Diagnostics: command=enable")
            return

        if cmd.startswith("DISABLE_"):
            if self.clearcore_connected:
                self.set_motor_status(motor_name, "disabled")
            else:
                self.set_motor_status(motor_name, "off")
            self.set_motor_diag_text(motor_name, "Diagnostics: command=disable")
            return

        if cmd.startswith("MOVE_") or cmd.startswith("STOP_"):
            if self.clearcore_connected:
                enabled = self.m0_enabled if motor_name == "M0" else self.m1_enabled
                self.set_motor_status(motor_name, "enabled" if enabled else "disabled")
            action = cmd.replace(f"_{motor_name}", "").lower()
            self.set_motor_diag_text(motor_name, f"Diagnostics: command={action}")

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
        elif cmd in {"HOME", "HOME_ACTUATOR", "RETRACT_TO_HOME"} and normalized in {"STARTED HOME", "DONE HOME", "RETRACTED"}:
            self.actuator_state_label.setText("State: HOMING")
            if normalized in {"DONE HOME", "RETRACTED"}:
                self.actuator_state_label.setText("State: RETRACTED")
        elif cmd == "STATUS_ACTUATOR" and normalized:
            self.actuator_state_label.setText(f"State: {normalized}")
        elif cmd in {"STOP_ACTUATOR", "STOP"} and normalized == "STOPPED":
            self.actuator_state_label.setText("State: STOPPED")
        elif cmd == "LIMITS" and normalized.startswith("LIMITS:") and self.actuator_limits_label is not None:
            self.set_actuator_detail_text(response)
        elif cmd in {"DIAG", "DIAGNOSTICS"} and normalized.startswith("DIAG:") and self.actuator_limits_label is not None:
            self.set_actuator_detail_text(response)

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
                self.set_motor_diag_text(motor_name, f"Diagnostics: status={status.upper()}")
                if status != previous:
                    self.log_signal.emit(f"{motor_name} status -> {status.upper()}")
                    if status == "fault":
                        self.log_clearcore_diagnostics()
                self.last_motor_status[motor_name] = status
            except Exception as e:
                self.log_signal.emit(f"{motor_name} status check failed: {e}")
                self.set_motor_status(motor_name, "off")
                self.set_motor_diag_text(motor_name, "Diagnostics: status=ERROR")

    def read_clearcore_identity(self):
        identity = {}
        for command in ("CAPS", "VERSION", "PING_M0"):
            try:
                identity[command] = self.clearcore_client.send_command(command)
            except Exception as e:
                identity[command] = f"ERR {e}"
        return identity

    def is_clearcore_identity(self, identity):
        if not identity:
            return False
        caps = (identity.get("CAPS") or "").strip().upper()
        version = (identity.get("VERSION") or "").strip().upper()
        ping_m0 = (identity.get("PING_M0") or "").strip().upper()
        if caps.startswith("CAPS:ACTUATOR"):
            return False
        return (
            (caps.startswith("CAPS:") and "M0" in caps)
            or "CLEARCORE" in version
            or ping_m0 == "PONG_M0"
        )

    def log_firmware_identity(self, identity=None):
        try:
            version = identity.get("VERSION") if identity is not None else self.send_raw_command("VERSION")
            self.log_signal.emit(f"ClearCore firmware: {version}")
        except Exception as e:
            self.log_signal.emit(f"ClearCore firmware version check failed: {e}")

        try:
            caps = identity.get("CAPS") if identity is not None else None
            if caps is None:
                caps = self.send_raw_command("CAPS")
            self.clearcore_capabilities = caps or ""
            self.log_signal.emit(f"ClearCore capabilities: {caps}")
        except Exception as e:
            self.log_signal.emit(f"ClearCore capability check failed: {e}")

    def log_clearcore_diagnostics(self):
        if not self.command_transport_ready():
            return

        diagnostic_responses = {}
        commands = [
            "INPUTS",
            "CONTROLLER_STATE",
            "FAULTS",
            "ESTOP_OVERRIDE",
            "LIMITS_M0",
            "LIMITS_M1",
            "STATUS_M0",
            "STATUS_M1",
        ]
        if self.clearcore_supports_pin_states():
            commands.insert(1, "PIN_STATES")

        for command in commands:
            try:
                response = self.send_raw_command(command)
                diagnostic_responses[command] = response
                self.log_signal.emit(f"ClearCore diagnostic {command} -> {response}")
            except Exception as e:
                self.log_signal.emit(f"ClearCore diagnostic {command} failed: {e}")

        inputs = self.parse_csv_response(diagnostic_responses.get("INPUTS"), "INPUTS:")
        if inputs.get("LIMIT_INTERLOCK") == "1":
            active_inputs = [
                name
                for name in ("M0_HOME", "M0_LIMIT", "M1_HOME", "M1_LIMIT")
                if inputs.get(name) == "1"
            ]
            if active_inputs:
                self.log_signal.emit(
                    "ClearCore motion gate -> active inputs while firmware interlock is enabled: "
                    f"{','.join(active_inputs)}"
                )

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
        if self.estop_override_checkbox is not None:
            self.estop_override_checkbox.setEnabled(clearpath_enabled)
        if self.limit_override_checkbox is not None:
            self.limit_override_checkbox.setEnabled(clearpath_enabled)

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
            label = self.port_label(port)
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
            label = self.port_label(port)
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
        try:
            self._auto_connect_startup_devices()
        except Exception as e:
            self.log_signal.emit(f"Startup auto-connect error: {e}")

    def _auto_connect_startup_devices(self):
        if self.mode_combo.currentData() != "local":
            return

        self.refresh_ports(quiet=True)
        clearcore_port = self.find_preferred_port("ClearCore")
        arduino_excluded = {clearcore_port} if clearcore_port else None

        if clearcore_port:
            index = self.port_combo.findData(clearcore_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            self.log_signal.emit(f"Startup auto-connect: trying ClearCore on {clearcore_port}")
            self.connect_local_clearcore()
            if not self.clearcore_connected:
                arduino_excluded = None
        else:
            self.log_signal.emit("Startup auto-connect: no ClearCore port detected")

        arduino_port = self.find_preferred_port("Arduino", exclude_devices=arduino_excluded)
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

        if self.auto_retry_timer.isActive():
            self.auto_retry_timer.stop()

    def update_supervisor_timer(self):
        if not hasattr(self, "supervisor_timer") or not hasattr(self, "mode_combo"):
            return

        mode = self.mode_combo.currentData()
        should_poll = (
            (mode == "pi" and self.pi_connected)
            or (
                mode == "local"
                and (self.local_gpio.available or self.clearcore_connected or self.arduino_connected)
            )
        )

        if should_poll and not self.supervisor_timer.isActive():
            self.supervisor_timer.start()
        elif not should_poll and self.supervisor_timer.isActive():
            self.supervisor_timer.stop()

    def find_preferred_port(self, role: str, exclude_devices=None):
        excluded = exclude_devices or set()
        for port in getattr(self, "available_ports", []):
            if port["device"] in excluded:
                continue
            if port.get("role") == role:
                return port["device"]
        return None

    def find_port_info(self, device: str):
        for port in getattr(self, "available_ports", []):
            if port.get("device") == device:
                return port
        return None

    def baudrate_candidates(self, port_info):
        baudrate = (port_info or {}).get("baudrate")
        if baudrate:
            return [baudrate]
        return list(PROBE_BAUDRATES)

    def display_role_for_port(self, port_info):
        device = port_info["device"]
        if self.clearcore_connected and self.clearcore_client is not None and self.clearcore_client.port == device:
            return "ClearCore"
        if self.arduino_connected and self.arduino_client is not None and self.arduino_client.port == device:
            return "Arduino"
        return port_info.get("role", "Unknown")

    def port_label(self, port_info):
        role = self.display_role_for_port(port_info)
        description = port_info.get("description") or "Serial port"
        return f"{port_info['device']} | {role} | {description}"

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

            port_info = self.find_port_info(port)
            connected = False
            for baudrate in self.baudrate_candidates(port_info):
                self.arduino_client = ArduinoController(port=port, baudrate=baudrate)
                connected = self.arduino_client.connect()
                if connected:
                    break
                self.arduino_client = None
            if not connected:
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

    def configure_fixed_detail_label(self, label: QLabel, lines: int = 3):
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        label.setFixedHeight(label.fontMetrics().lineSpacing() * lines + 8)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    def set_actuator_detail_text(self, text: str):
        if self.actuator_limits_label is None:
            return
        self.actuator_limits_label.setToolTip(text)
        self.actuator_limits_label.setText(text)

    def set_clearcore_port(self):
        port = self.port_combo.currentData()
        if port:
            if self.mode_combo.currentData() == "local":
                self.log_signal.emit(f"Local ClearCore port selected: {port}")
                return

            self.send_command(f"SET_CLEARCORE_PORT:{port}")

    def check_gpio_buttons(self):
        mode = self.mode_combo.currentData()
        if mode == "pi":
            if not self.pi_connected:
                self.log_signal.emit("GPIO check skipped: Pi Bridge is not connected")
                return

            for command in ("GPIO_CONFIG", "GPIO_INPUTS"):
                try:
                    response = self.pi_client.send(command)
                    self.log_signal.emit(f"GPIO check {command} -> {response}")
                    if command == "GPIO_CONFIG":
                        self.cache_gpio_config(response)
                    elif command == "GPIO_INPUTS":
                        self.log_home_switch_transitions(
                            self.parse_csv_response(response, "GPIO_INPUTS:")
                        )
                except Exception as e:
                    self.log_signal.emit(f"GPIO check failed ({command}): {e}")
            return

        gpio_config = self.local_gpio.config_summary()
        gpio_inputs = self.local_gpio.input_summary()
        self.log_signal.emit(f"GPIO check GPIO_CONFIG -> {gpio_config}")
        self.cache_gpio_config(gpio_config)
        self.log_signal.emit(f"GPIO check GPIO_INPUTS -> {gpio_inputs}")
        self.log_home_switch_transitions(
            self.parse_csv_response(gpio_inputs, "GPIO_INPUTS:")
        )

    def create_connection_group(self):
        box = QGroupBox("Connection / Ports")
        grid = QGridLayout(box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Local ClearCore", "local")
        self.mode_combo.addItem("Pi Bridge", "pi")
        self.connect_btn = QPushButton("Connect ClearCore")
        disconnect_btn = QPushButton("Disconnect Link")
        self.connection_status = QLabel("Status: Local mode idle")
        self.machine_state_label = QLabel("Machine: IDLE")
        self.machine_inputs_label = QLabel("Inputs: unavailable")
        self.estop_override_checkbox = QCheckBox("E-stop override")
        self.estop_override_checkbox.setToolTip(
            "Temporary integration mode: ignore the ClearCore E-stop input."
        )
        self.limit_override_checkbox = QCheckBox("Pi limit/home override")
        self.limit_override_checkbox.setToolTip(
            "Temporary integration mode: ignore Pi software limit checks. ClearCore home/limit inputs are report-only."
        )
        self.port_combo = QComboBox()
        refresh_btn = QPushButton("Refresh Ports")
        set_port_btn = QPushButton("Use Selected Port")
        gpio_check_btn = QPushButton("Check GPIO Buttons")

        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.connect_btn.clicked.connect(self.connect_selected_mode)
        disconnect_btn.clicked.connect(self.disconnect_all)
        refresh_btn.clicked.connect(self.refresh_ports)
        set_port_btn.clicked.connect(self.set_clearcore_port)
        gpio_check_btn.clicked.connect(self.check_gpio_buttons)
        self.estop_override_checkbox.toggled.connect(self.on_estop_override_toggled)
        self.limit_override_checkbox.toggled.connect(self.on_limit_override_toggled)

        grid.addWidget(QLabel("Connection Mode:"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1, 1, 2)
        grid.addWidget(self.connect_btn, 1, 0, 1, 2)
        grid.addWidget(disconnect_btn, 1, 2)
        grid.addWidget(self.connection_status, 2, 0, 1, 3)
        grid.addWidget(self.machine_state_label, 3, 0, 1, 3)
        grid.addWidget(self.machine_inputs_label, 4, 0, 1, 3)
        grid.addWidget(self.estop_override_checkbox, 5, 0, 1, 3)
        grid.addWidget(self.limit_override_checkbox, 6, 0, 1, 3)
        grid.addWidget(gpio_check_btn, 7, 0, 1, 3)
        grid.addWidget(QLabel("Detected Ports:"), 8, 0)
        grid.addWidget(self.port_combo, 8, 1, 1, 2)
        grid.addWidget(refresh_btn, 9, 0)
        grid.addWidget(set_port_btn, 9, 1)

        return box

    def on_mode_changed(self):
        self.update_connection_label()
        if self.mode_combo.currentData() != "pi":
            self.home_timer.stop()
            self.home_sequence_active = False
            self.set_machine_state("idle")
        self.update_supervisor_timer()
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
        self.m0_diag_label = QLabel("Diagnostics: unavailable")

        grid.addWidget(ping_btn, 0, 0)
        grid.addWidget(enable_btn, 0, 1)

        grid.addWidget(pos1_btn, 1, 0)
        grid.addWidget(pos2_btn, 1, 1)

        grid.addWidget(stop_btn, 2, 0)
        grid.addWidget(disable_btn, 2, 1)

        grid.addWidget(self.m0_state_label, 3, 0, 1, 2)
        grid.addWidget(self.m0_diag_label, 4, 0, 1, 2)

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
        self.m1_diag_label = QLabel("Diagnostics: unavailable")

        grid.addWidget(ping_btn, 0, 0)
        grid.addWidget(enable_btn, 0, 1)
        grid.addWidget(pos1_btn, 1, 0)
        grid.addWidget(pos2_btn, 1, 1)
        grid.addWidget(stop_btn, 2, 0)
        grid.addWidget(disable_btn, 2, 1)
        grid.addWidget(self.m1_state_label, 3, 0, 1, 2)
        grid.addWidget(self.m1_diag_label, 4, 0, 1, 2)

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
        status_btn = QPushButton("Status")
        limits_btn = QPushButton("Limits")
        diag_btn = QPushButton("Diagnostics")

        self.actuator_state_label = QLabel("State: IDLE")
        self.actuator_limits_label = QLabel("Limits: Unknown")
        self.configure_fixed_detail_label(self.actuator_limits_label)
        self.actuator_limits_label.setToolTip("Limits: Unknown")

        self.actuator_widgets = [extend_btn, retract_btn, stop_btn, status_btn, limits_btn, diag_btn]

        extend_btn.clicked.connect(lambda: self.send_command("EXTEND"))
        retract_btn.clicked.connect(lambda: self.send_command("RETRACT"))
        stop_btn.clicked.connect(lambda: self.send_command("STOP_ACTUATOR"))
        status_btn.clicked.connect(lambda: self.send_command("STATUS_ACTUATOR"))
        limits_btn.clicked.connect(lambda: self.send_command("LIMITS"))
        diag_btn.clicked.connect(lambda: self.send_command("DIAG"))

        layout.addWidget(extend_btn)
        layout.addWidget(retract_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(status_btn)
        layout.addWidget(limits_btn)
        layout.addWidget(diag_btn)
        layout.addWidget(self.actuator_state_label)
        layout.addWidget(self.actuator_limits_label)

        return box
