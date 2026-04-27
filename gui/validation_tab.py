import csv
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils.config_manager import load_config
from utils.pi_gpio import BCM_TO_PHYSICAL_PIN


class SensorCalibrationDialog(QDialog):
    refresh_requested = Signal()
    save_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.last_values = {}
        self.setWindowTitle("Validation Sensor Readings")
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(self.build_readings_group())
        layout.addWidget(self.build_settings_group())
        layout.addWidget(self.build_actions_group())

        self.load_settings()

    def build_readings_group(self):
        box = QGroupBox("Live Readings")
        grid = QGridLayout(box)

        self.roll_reading_label = QLabel("Roll sensor: unavailable")
        self.tilt_reading_label = QLabel("Tilt sensor: unavailable")
        self.raw_reading_label = QLabel("Raw levels: unavailable")
        self.reading_config_label = QLabel("GPIO pins: unknown")

        grid.addWidget(self.roll_reading_label, 0, 0, 1, 2)
        grid.addWidget(self.tilt_reading_label, 1, 0, 1, 2)
        grid.addWidget(self.raw_reading_label, 2, 0, 1, 2)
        grid.addWidget(self.reading_config_label, 3, 0, 1, 2)
        return box

    def build_settings_group(self):
        box = QGroupBox("Calibration Settings")
        grid = QGridLayout(box)

        self.sensors_enabled_check = QCheckBox("Enable validation sensors")

        self.roll_pin_spin = QSpinBox()
        self.roll_pin_spin.setRange(0, 27)
        self.roll_pin_spin.valueChanged.connect(self.update_physical_pin_labels)

        self.tilt_pin_spin = QSpinBox()
        self.tilt_pin_spin.setRange(0, 27)
        self.tilt_pin_spin.valueChanged.connect(self.update_physical_pin_labels)

        self.roll_pin_label = QLabel("")
        self.tilt_pin_label = QLabel("")

        self.active_high_check = QCheckBox("Sensor is active when GPIO is high")
        self.pull_up_check = QCheckBox("Use internal pull-up")
        self.inactive_baseline_btn = QPushButton("Use Current State As Inactive")
        self.inactive_baseline_btn.clicked.connect(self.use_current_as_inactive)

        note = QLabel(
            "For NPN proximity sensors through an optocoupler, pull-up on and active-low is usually correct."
        )
        note.setWordWrap(True)

        grid.addWidget(self.sensors_enabled_check, 0, 0, 1, 2)
        grid.addWidget(QLabel("Roll GPIO:"), 1, 0)
        grid.addWidget(self.roll_pin_spin, 1, 1)
        grid.addWidget(self.roll_pin_label, 1, 2)
        grid.addWidget(QLabel("Tilt GPIO:"), 2, 0)
        grid.addWidget(self.tilt_pin_spin, 2, 1)
        grid.addWidget(self.tilt_pin_label, 2, 2)
        grid.addWidget(self.active_high_check, 3, 0, 1, 3)
        grid.addWidget(self.pull_up_check, 4, 0, 1, 3)
        grid.addWidget(self.inactive_baseline_btn, 5, 1, 1, 2)
        grid.addWidget(note, 6, 0, 1, 3)
        return box

    def build_actions_group(self):
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        self.refresh_btn = QPushButton("Refresh")
        self.save_btn = QPushButton("Save Calibration")
        self.close_btn = QPushButton("Close")

        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.save_btn.clicked.connect(self.emit_save)
        self.close_btn.clicked.connect(self.close)

        layout.addWidget(self.refresh_btn)
        layout.addStretch()
        layout.addWidget(self.save_btn)
        layout.addWidget(self.close_btn)
        return box

    def load_settings(self):
        gpio_config = load_config().get("pi_gpio", {})
        self.sensors_enabled_check.setChecked(
            bool(gpio_config.get("validation_sensors_enabled", True))
        )
        self.roll_pin_spin.setValue(int(gpio_config.get("roll_prox_pin", 20)))
        self.tilt_pin_spin.setValue(int(gpio_config.get("tilt_prox_pin", 21)))
        self.active_high_check.setChecked(
            bool(gpio_config.get("validation_sensor_active_high", False))
        )
        self.pull_up_check.setChecked(
            bool(gpio_config.get("validation_sensor_pull_up", True))
        )
        self.update_physical_pin_labels()

    def physical_pin_text(self, bcm_pin: int):
        physical = BCM_TO_PHYSICAL_PIN.get(bcm_pin, "unknown")
        return f"physical {physical}"

    def update_physical_pin_labels(self):
        self.roll_pin_label.setText(self.physical_pin_text(self.roll_pin_spin.value()))
        self.tilt_pin_label.setText(self.physical_pin_text(self.tilt_pin_spin.value()))

    def format_state(self, name: str):
        state = self.last_values.get(name, "0") == "1"
        raw = self.last_values.get(f"{name}_RAW", "NA")
        return f"{'ACTIVE' if state else 'inactive'} raw={raw}"

    def update_sensor_inputs(self, values: dict, error_message: str = ""):
        self.last_values = values or {}
        if not self.last_values:
            message = error_message or "no response"
            self.roll_reading_label.setText("Roll sensor: unavailable")
            self.tilt_reading_label.setText("Tilt sensor: unavailable")
            self.raw_reading_label.setText(f"Raw levels: unavailable ({message})")
            self.reading_config_label.setText("GPIO pins: unavailable")
            return

        self.roll_reading_label.setText(f"Roll sensor: {self.format_state('ROLL_PROX')}")
        self.tilt_reading_label.setText(f"Tilt sensor: {self.format_state('TILT_PROX')}")
        self.raw_reading_label.setText(
            f"Raw levels: roll={self.last_values.get('ROLL_PROX_RAW', 'NA')}, "
            f"tilt={self.last_values.get('TILT_PROX_RAW', 'NA')}"
        )
        self.reading_config_label.setText(
            f"Roll GPIO{self.last_values.get('ROLL_PROX_PIN', 'NA')} physical "
            f"{self.last_values.get('ROLL_PROX_PHYSICAL_PIN', 'NA')}; "
            f"Tilt GPIO{self.last_values.get('TILT_PROX_PIN', 'NA')} physical "
            f"{self.last_values.get('TILT_PROX_PHYSICAL_PIN', 'NA')}; "
            f"active_high={self.last_values.get('ACTIVE_HIGH', 'NA')}; "
            f"pull_up={self.last_values.get('PULL_UP', 'NA')}"
        )

    def use_current_as_inactive(self):
        raw_values = [
            self.last_values.get("ROLL_PROX_RAW"),
            self.last_values.get("TILT_PROX_RAW"),
        ]
        if any(raw not in {"0", "1"} for raw in raw_values):
            self.raw_reading_label.setText(
                "Raw levels: unavailable - refresh with both sensors inactive first"
            )
            return
        if raw_values[0] != raw_values[1]:
            self.raw_reading_label.setText(
                "Raw levels disagree - move both sensors to inactive before calibrating polarity"
            )
            return

        inactive_raw_high = raw_values[0] == "1"
        self.active_high_check.setChecked(not inactive_raw_high)

    def current_settings(self):
        return {
            "enabled": self.sensors_enabled_check.isChecked(),
            "roll_pin": self.roll_pin_spin.value(),
            "tilt_pin": self.tilt_pin_spin.value(),
            "active_high": self.active_high_check.isChecked(),
            "pull_up": self.pull_up_check.isChecked(),
        }

    def emit_save(self):
        settings = self.current_settings()
        if settings["roll_pin"] == settings["tilt_pin"]:
            self.raw_reading_label.setText("Calibration not saved - roll and tilt need different GPIO pins")
            return
        if (
            settings["roll_pin"] not in BCM_TO_PHYSICAL_PIN
            or settings["tilt_pin"] not in BCM_TO_PHYSICAL_PIN
        ):
            self.raw_reading_label.setText("Calibration not saved - use GPIO pins on the 40-pin header")
            return
        self.save_requested.emit(settings)


class ValidationTab(QWidget):
    log_signal = Signal(str)
    validation_mode_signal = Signal(bool)
    start_sequence_signal = Signal(list, str)
    abort_signal = Signal()
    sensor_poll_signal = Signal()
    sensor_config_signal = Signal(dict)
    IDLE_SENSOR_POLL_MS = 500
    RUN_SENSOR_POLL_MS = 200

    TEST_DEFINITIONS = {
        "roll_home_to_pos1": {
            "label": "Roll | Extend",
            "moves": [("m0", "forward")],
        },
        "roll_pos1_to_home": {
            "label": "Roll | Retract",
            "moves": [("m0", "reverse")],
        },
        "roll_cycle": {
            "label": "Roll | Extend/Retract Cycle",
            "moves": [("m0", "forward"), ("m0", "reverse")],
        },
        "tilt_home_to_pos1": {
            "label": "Tilt | Extend",
            "moves": [("m1", "forward")],
        },
        "tilt_pos1_to_home": {
            "label": "Tilt | Retract",
            "moves": [("m1", "reverse")],
        },
        "tilt_cycle": {
            "label": "Tilt | Extend/Retract Cycle",
            "moves": [("m1", "forward"), ("m1", "reverse")],
        },
        "combined_home_to_pos1": {
            "label": "Roll + Tilt | Extend",
            "moves": [("m0", "forward"), ("m1", "forward")],
        },
        "combined_pos1_to_home": {
            "label": "Roll + Tilt | Retract",
            "moves": [("m0", "reverse"), ("m1", "reverse")],
        },
        "combined_cycle": {
            "label": "Roll + Tilt | Extend/Retract Cycle",
            "moves": [
                ("m0", "forward"),
                ("m1", "forward"),
                ("m0", "reverse"),
                ("m1", "reverse"),
            ],
        },
    }

    def __init__(self):
        super().__init__()

        self.validation_mode_active = False
        self.is_running = False
        self.abort_requested = False
        self.validation_tests = []
        self.last_sensor_states = {
            "ROLL_PROX": None,
            "TILT_PROX": None,
        }
        self.last_sensor_values = {}
        self.last_sensor_error = ""
        self.last_analog_values = {}
        self.last_analog_error = ""
        self.validation_log_handle = None
        self.validation_log_writer = None
        self.validation_log_path = None
        self.validation_log_started_at = 0.0
        self.sensor_dialog = None
        self.sensor_poll_timer = QTimer(self)
        self.sensor_poll_timer.setInterval(self.IDLE_SENSOR_POLL_MS)
        self.sensor_poll_timer.timeout.connect(self.request_sensor_poll)

        layout = QVBoxLayout(self)
        layout.addWidget(self.build_mode_group())
        layout.addWidget(self.build_sensor_group())
        layout.addWidget(self.build_builder_group())
        layout.addWidget(self.build_queue_group())
        layout.addWidget(self.build_run_group())
        self.update_button_states()

    def build_mode_group(self):
        box = QGroupBox("Validation Mode")
        layout = QVBoxLayout(box)

        self.validation_mode_check = QCheckBox("Validation mode")
        self.validation_mode_check.setToolTip(
            "Locks the Auto tab controls while this tab uses the Auto sequence runner."
        )
        self.validation_status_label = QLabel("Status: validation mode off")
        self.validation_mode_check.toggled.connect(self.on_validation_mode_toggled)

        layout.addWidget(self.validation_mode_check)
        layout.addWidget(self.validation_status_label)
        return box

    def build_sensor_group(self):
        box = QGroupBox("Proximity Sensor Inputs")
        grid = QGridLayout(box)

        self.roll_sensor_label = QLabel("Roll sensor: unavailable")
        self.tilt_sensor_label = QLabel("Tilt sensor: unavailable")
        self.roll_analog_label = QLabel("Roll analog (A0): unavailable")
        self.tilt_analog_label = QLabel("Tilt analog (A1): unavailable")
        self.analog_status_label = QLabel("Arduino ADC: unavailable")
        self.sensor_config_label = QLabel("GPIO pins: unknown")
        self.check_sensors_btn = QPushButton("Check Sensors")
        self.check_sensors_btn.clicked.connect(self.open_sensor_dialog)

        grid.addWidget(self.roll_sensor_label, 0, 0, 1, 2)
        grid.addWidget(self.tilt_sensor_label, 1, 0, 1, 2)
        grid.addWidget(self.roll_analog_label, 2, 0, 1, 2)
        grid.addWidget(self.tilt_analog_label, 3, 0, 1, 2)
        grid.addWidget(self.analog_status_label, 4, 0, 1, 2)
        grid.addWidget(self.sensor_config_label, 5, 0, 1, 2)
        grid.addWidget(self.check_sensors_btn, 6, 1)
        return box

    def open_sensor_dialog(self):
        if self.sensor_dialog is None:
            self.sensor_dialog = SensorCalibrationDialog(self)
            self.sensor_dialog.refresh_requested.connect(self.request_sensor_poll)
            self.sensor_dialog.save_requested.connect(self.save_sensor_calibration)
            self.sensor_dialog.finished.connect(self.on_sensor_dialog_finished)

        self.sensor_dialog.show()
        self.sensor_dialog.raise_()
        self.sensor_dialog.activateWindow()
        if self.last_sensor_values:
            self.sensor_dialog.update_sensor_inputs(self.last_sensor_values)
        self.ensure_sensor_polling()
        self.request_sensor_poll()

    def on_sensor_dialog_finished(self):
        self.sensor_dialog = None
        if not self.validation_mode_active:
            self.sensor_poll_timer.stop()

    def sensor_poll_interval_ms(self):
        return self.RUN_SENSOR_POLL_MS if self.is_running else self.IDLE_SENSOR_POLL_MS

    def refresh_sensor_poll_interval(self):
        self.sensor_poll_timer.setInterval(self.sensor_poll_interval_ms())

    def ensure_sensor_polling(self):
        self.refresh_sensor_poll_interval()
        if not self.sensor_poll_timer.isActive():
            self.sensor_poll_timer.start()

    def save_sensor_calibration(self, settings: dict):
        self.sensor_config_signal.emit(settings)

    def build_builder_group(self):
        box = QGroupBox("Validation Sequence Builder")
        grid = QGridLayout(box)

        self.test_combo = QComboBox()
        for key, definition in self.TEST_DEFINITIONS.items():
            self.test_combo.addItem(definition["label"], key)

        self.cycles_spin = QSpinBox()
        self.cycles_spin.setRange(1, 1000)
        self.cycles_spin.setValue(10)

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(0.1, 300.0)
        self.dwell_spin.setValue(5.0)
        self.dwell_spin.setSuffix(" s")

        self.tilt_home_switch_check = QCheckBox("Tilt retract until home switch")
        self.tilt_home_switch_check.setToolTip(
            "For tilt retract moves, M1 will retract toward M1_HOME and the home "
            "switch software stop will stop it. Move dwell is used as the safety timeout."
        )

        self.add_test_btn = QPushButton("Add Validation Test")
        self.add_test_btn.clicked.connect(self.add_test)
        self.test_combo.currentIndexChanged.connect(self.update_tilt_home_switch_option)

        grid.addWidget(QLabel("Movement:"), 0, 0)
        grid.addWidget(self.test_combo, 0, 1, 1, 3)
        grid.addWidget(QLabel("Cycles:"), 1, 0)
        grid.addWidget(self.cycles_spin, 1, 1)
        grid.addWidget(QLabel("Move Dwell:"), 1, 2)
        grid.addWidget(self.dwell_spin, 1, 3)
        grid.addWidget(self.tilt_home_switch_check, 2, 0, 1, 2)
        grid.addWidget(self.add_test_btn, 2, 2, 1, 2)
        return box

    def selected_test_supports_tilt_home_switch(self):
        test_key = self.test_combo.currentData()
        definition = self.TEST_DEFINITIONS.get(test_key, {})
        return any(
            peripheral == "m1" and action == "reverse"
            for peripheral, action in definition.get("moves", [])
        )

    def update_tilt_home_switch_option(self):
        if not hasattr(self, "tilt_home_switch_check"):
            return
        supported = self.selected_test_supports_tilt_home_switch()
        editable = self.validation_mode_active and not self.is_running
        self.tilt_home_switch_check.setEnabled(editable and supported)
        if not supported:
            self.tilt_home_switch_check.setChecked(False)

    def build_queue_group(self):
        box = QGroupBox("Validation Queue")
        layout = QVBoxLayout(box)

        self.validation_list = QListWidget()
        self.validation_list.currentRowChanged.connect(lambda _: self.update_button_states())
        layout.addWidget(self.validation_list)

        button_row = QHBoxLayout()
        self.remove_test_btn = QPushButton("Remove")
        self.clear_tests_btn = QPushButton("Clear")
        self.remove_test_btn.clicked.connect(self.remove_selected_test)
        self.clear_tests_btn.clicked.connect(self.clear_tests)
        button_row.addWidget(self.remove_test_btn)
        button_row.addWidget(self.clear_tests_btn)
        layout.addLayout(button_row)
        return box

    def build_run_group(self):
        box = QGroupBox("Run")
        layout = QHBoxLayout(box)

        self.start_validation_btn = QPushButton("Start Validation")
        self.abort_validation_btn = QPushButton("Abort Validation")
        self.run_summary_label = QLabel("Ready")
        self.start_validation_btn.clicked.connect(self.start_validation)
        self.abort_validation_btn.clicked.connect(self.abort_validation)

        layout.addWidget(self.start_validation_btn)
        layout.addWidget(self.abort_validation_btn)
        layout.addWidget(self.run_summary_label)
        return box

    def on_validation_mode_toggled(self, enabled: bool):
        if self.is_running and not enabled:
            self.validation_mode_check.blockSignals(True)
            self.validation_mode_check.setChecked(True)
            self.validation_mode_check.blockSignals(False)
            self.log_signal.emit("Validation: Stop the validation run before disabling validation mode")
            return

        self.validation_mode_active = enabled
        self.validation_mode_signal.emit(enabled)
        if enabled:
            self.ensure_sensor_polling()
            self.request_sensor_poll()
        elif self.sensor_dialog is None:
            self.sensor_poll_timer.stop()
        self.refresh_sensor_poll_interval()
        self.validation_status_label.setText(
            "Status: validation mode on - Auto tab locked"
            if enabled
            else "Status: validation mode off"
        )
        self.log_signal.emit(
            "Validation: Validation mode enabled; Auto tab controls locked"
            if enabled
            else "Validation: Validation mode disabled; Auto tab controls unlocked"
        )
        self.update_button_states()

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

    def request_sensor_poll(self):
        self.sensor_poll_signal.emit()

    def format_millivolts(self, value: str):
        try:
            return f"{int(value) / 1000.0:.3f}V"
        except (TypeError, ValueError):
            return "NA"

    def update_sensor_inputs(self, response: str):
        values = self.parse_csv_response(response, "GPIO_VALIDATION_INPUTS:")
        if not values:
            message = response if response else "no response"
            self.roll_sensor_label.setText("Roll sensor: unavailable")
            self.tilt_sensor_label.setText("Tilt sensor: unavailable")
            self.sensor_config_label.setText(f"GPIO pins: unavailable ({message})")
            self.last_sensor_values = {}
            self.last_sensor_error = message
            if self.sensor_dialog is not None:
                self.sensor_dialog.update_sensor_inputs({}, message)
            return

        self.last_sensor_values = values
        self.last_sensor_error = ""
        roll_state = values.get("ROLL_PROX", "0") == "1"
        tilt_state = values.get("TILT_PROX", "0") == "1"
        roll_raw = values.get("ROLL_PROX_RAW", "NA")
        tilt_raw = values.get("TILT_PROX_RAW", "NA")
        roll_pin = values.get("ROLL_PROX_PIN", "NA")
        tilt_pin = values.get("TILT_PROX_PIN", "NA")
        roll_phys = values.get("ROLL_PROX_PHYSICAL_PIN", "NA")
        tilt_phys = values.get("TILT_PROX_PHYSICAL_PIN", "NA")
        active_high = values.get("ACTIVE_HIGH", "0")
        pull_up = values.get("PULL_UP", "1")

        self.roll_sensor_label.setText(
            f"Roll sensor: {'ACTIVE' if roll_state else 'inactive'} raw={roll_raw}"
        )
        self.tilt_sensor_label.setText(
            f"Tilt sensor: {'ACTIVE' if tilt_state else 'inactive'} raw={tilt_raw}"
        )
        self.sensor_config_label.setText(
            f"Roll GPIO{roll_pin} physical {roll_phys}; "
            f"Tilt GPIO{tilt_pin} physical {tilt_phys}; "
            f"active_high={active_high}; pull_up={pull_up}"
        )

        for name, state in (("ROLL_PROX", roll_state), ("TILT_PROX", tilt_state)):
            if self.last_sensor_states.get(name) is None:
                self.last_sensor_states[name] = state
                continue
            if self.last_sensor_states[name] != state:
                self.last_sensor_states[name] = state
                self.log_signal.emit(
                    f"Validation sensor {name} -> {'ACTIVE' if state else 'inactive'}"
                )

        if self.sensor_dialog is not None:
            self.sensor_dialog.update_sensor_inputs(values)

    def update_analog_sensor_inputs(self, response: str):
        values = self.parse_csv_response(response, "SENSORS:")
        if not values:
            message = response if response else "no response"
            self.roll_analog_label.setText(f"Roll analog (A0): unavailable ({message})")
            self.tilt_analog_label.setText(f"Tilt analog (A1): unavailable ({message})")
            self.analog_status_label.setText(f"Arduino ADC: unavailable ({message})")
            self.last_analog_values = {}
            self.last_analog_error = message
            return

        self.last_analog_values = values
        self.last_analog_error = ""
        roll_adc = values.get("ROLL_ADC", "NA")
        tilt_adc = values.get("TILT_ADC", "NA")
        roll_mv = values.get("ROLL_MV", "NA")
        tilt_mv = values.get("TILT_MV", "NA")
        self.roll_analog_label.setText(
            f"Roll analog (A0): adc={roll_adc} {self.format_millivolts(roll_mv)}"
        )
        self.tilt_analog_label.setText(
            f"Tilt analog (A1): adc={tilt_adc} {self.format_millivolts(tilt_mv)}"
        )
        self.analog_status_label.setText(
            f"Arduino ADC: state={values.get('STATE', 'NA')}; ms={values.get('MS', 'NA')}"
        )

    def start_validation_log(self):
        self.stop_validation_log(log_saved=False)

        logs_dir = Path(__file__).resolve().parents[1] / "logs" / "validation"
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.log_signal.emit(f"Validation: Failed to create log directory: {exc}")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"validation_{timestamp}.csv"

        try:
            handle = path.open("w", newline="", encoding="utf-8")
        except Exception as exc:
            self.log_signal.emit(f"Validation: Failed to create sensor log: {exc}")
            return

        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp_iso",
                "elapsed_ms",
                "roll_active",
                "roll_raw",
                "tilt_active",
                "tilt_raw",
                "roll_adc",
                "roll_mv",
                "tilt_adc",
                "tilt_mv",
                "arduino_state",
                "arduino_ms",
                "digital_error",
                "analog_error",
            ],
        )
        writer.writeheader()
        handle.flush()

        self.validation_log_handle = handle
        self.validation_log_writer = writer
        self.validation_log_path = path
        self.validation_log_started_at = time.monotonic()
        self.log_signal.emit(f"Validation: Logging sensor data to {path}")

    def stop_validation_log(self, log_saved: bool = True):
        path = self.validation_log_path
        handle = self.validation_log_handle

        self.validation_log_handle = None
        self.validation_log_writer = None
        self.validation_log_path = None
        self.validation_log_started_at = 0.0

        if handle is None:
            return

        try:
            handle.close()
        except Exception as exc:
            self.log_signal.emit(f"Validation: Failed to close sensor log: {exc}")
            return

        if log_saved and path is not None:
            self.log_signal.emit(f"Validation: Sensor log saved -> {path}")

    def record_sensor_snapshot(self):
        if self.validation_log_writer is None or self.validation_log_handle is None:
            return

        elapsed_ms = 0
        if self.validation_log_started_at:
            elapsed_ms = int((time.monotonic() - self.validation_log_started_at) * 1000)

        digital_values = self.last_sensor_values or {}
        analog_values = self.last_analog_values or {}

        row = {
            "timestamp_iso": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_ms": elapsed_ms,
            "roll_active": digital_values.get("ROLL_PROX", ""),
            "roll_raw": digital_values.get("ROLL_PROX_RAW", ""),
            "tilt_active": digital_values.get("TILT_PROX", ""),
            "tilt_raw": digital_values.get("TILT_PROX_RAW", ""),
            "roll_adc": analog_values.get("ROLL_ADC", ""),
            "roll_mv": analog_values.get("ROLL_MV", ""),
            "tilt_adc": analog_values.get("TILT_ADC", ""),
            "tilt_mv": analog_values.get("TILT_MV", ""),
            "arduino_state": analog_values.get("STATE", ""),
            "arduino_ms": analog_values.get("MS", ""),
            "digital_error": self.last_sensor_error,
            "analog_error": self.last_analog_error,
        }

        try:
            self.validation_log_writer.writerow(row)
            self.validation_log_handle.flush()
        except Exception as exc:
            self.log_signal.emit(f"Validation: Sensor log write failed: {exc}")
            self.stop_validation_log(log_saved=False)

    def on_sensor_calibration_saved(self, response: str):
        if response and response.startswith("ERR"):
            self.log_signal.emit(f"Validation sensor calibration failed: {response}")
            return
        self.log_signal.emit("Validation sensor calibration saved")
        if response:
            self.update_sensor_inputs(response)
        self.request_sensor_poll()

    def build_test_from_inputs(self):
        test_key = self.test_combo.currentData()
        definition = self.TEST_DEFINITIONS[test_key]
        cycles = self.cycles_spin.value()
        dwell_ms = int(self.dwell_spin.value() * 1000)
        tilt_until_home_switch = (
            self.tilt_home_switch_check.isChecked()
            and self.selected_test_supports_tilt_home_switch()
        )
        display = f"{definition['label']} | {cycles} cycle(s) | {self.dwell_spin.value():.1f}s dwell"
        if tilt_until_home_switch:
            display += " | tilt retract to M1_HOME"
        return {
            "test_key": test_key,
            "cycles": cycles,
            "dwell_ms": dwell_ms,
            "tilt_retract_until_home_switch": tilt_until_home_switch,
            "display": display,
        }

    def add_test(self):
        test = self.build_test_from_inputs()
        self.validation_tests.append(test)
        self.validation_list.addItem(QListWidgetItem(test["display"]))
        self.validation_list.setCurrentRow(self.validation_list.count() - 1)
        self.log_signal.emit(f"Validation: Added test -> {test['display']}")
        self.update_button_states()

    def remove_selected_test(self):
        row = self.validation_list.currentRow()
        if row < 0:
            return
        removed = self.validation_tests.pop(row)
        self.validation_list.takeItem(row)
        self.log_signal.emit(f"Validation: Removed test -> {removed['display']}")
        self.update_button_states()

    def clear_tests(self):
        if self.is_running:
            self.log_signal.emit("Validation: Stop the run before clearing tests")
            return
        self.validation_tests.clear()
        self.validation_list.clear()
        self.log_signal.emit("Validation: Queue cleared")
        self.update_button_states()

    def auto_step(
        self,
        peripheral: str,
        action: str,
        dwell_ms: int,
        label: str,
        stop_on_home_switch: bool = False,
    ):
        command_action = "reverse" if stop_on_home_switch else action
        if stop_on_home_switch:
            direction = "Retract until M1_HOME switch"
        else:
            direction = "Extend" if action == "forward" else "Retract"
        motor_label = "Roll Servo" if peripheral == "m0" else "Tilt Servo"
        display = f"{label} | {motor_label} | {direction}"
        if stop_on_home_switch:
            display += f" | timeout {dwell_ms / 1000.0:.1f}s"
        return {
            "peripheral": peripheral,
            "action": command_action,
            "repeat": 1,
            "dwell_ms": dwell_ms,
            "enable_before": True,
            "stop_after": True,
            "disable_after": True,
            "validation_stop_on_home_switch": stop_on_home_switch,
            "wait_for_home_switch": "M1" if stop_on_home_switch else None,
            "display": display,
        }

    def expand_validation_steps(self):
        steps = []
        for test in self.validation_tests:
            definition = self.TEST_DEFINITIONS[test["test_key"]]
            tilt_until_home_switch = bool(
                test.get(
                    "tilt_retract_until_home_switch",
                    test.get("tilt_reverse_until_home_switch", False),
                )
            )
            for cycle in range(1, test["cycles"] + 1):
                label = f"Validation {definition['label']} cycle {cycle}/{test['cycles']}"
                for peripheral, action in definition["moves"]:
                    stop_on_home_switch = (
                        tilt_until_home_switch
                        and peripheral == "m1"
                        and action == "reverse"
                    )
                    steps.append(
                        self.auto_step(
                            peripheral,
                            action,
                            test["dwell_ms"],
                            label,
                            stop_on_home_switch,
                        )
                    )
        return steps

    def start_validation(self):
        if not self.validation_mode_active:
            self.log_signal.emit("Validation: Enable validation mode before starting")
            return
        if self.is_running:
            self.log_signal.emit("Validation: Run already active")
            return
        if not self.validation_tests:
            self.log_signal.emit("Validation: Add at least one validation test first")
            return

        steps = self.expand_validation_steps()
        label = "Validation"
        self.abort_requested = False
        self.run_summary_label.setText("Starting validation...")
        self.start_sequence_signal.emit(steps, label)

    def on_validation_start_result(self, started: bool):
        if started:
            self.is_running = True
            self.refresh_sensor_poll_interval()
            self.start_validation_log()
            self.run_summary_label.setText("Validation running")
            self.log_signal.emit("Validation: Run started")
            self.request_sensor_poll()
        else:
            self.is_running = False
            self.refresh_sensor_poll_interval()
            self.run_summary_label.setText("Validation start rejected")
            self.log_signal.emit("Validation: Run was not started")
        self.update_button_states()

    def abort_validation(self):
        if not self.is_running:
            return
        self.abort_requested = True
        self.abort_signal.emit()
        self.run_summary_label.setText("Aborting validation...")
        self.log_signal.emit("Validation: Abort requested")
        self.update_button_states()

    def on_auto_cycle_state_changed(self, state: str):
        if not self.is_running:
            return
        if state == "running":
            return

        self.is_running = False
        self.refresh_sensor_poll_interval()
        if state == "idle" and not self.abort_requested:
            self.run_summary_label.setText("Validation complete")
            self.log_signal.emit("Validation: Run complete")
        else:
            self.run_summary_label.setText("Validation stopped")
            self.log_signal.emit("Validation: Run stopped")
        self.abort_requested = False
        self.stop_validation_log()
        self.update_button_states()

    def update_button_states(self):
        selected = self.validation_list.currentRow() >= 0
        editable = self.validation_mode_active and not self.is_running
        self.test_combo.setEnabled(editable)
        self.cycles_spin.setEnabled(editable)
        self.dwell_spin.setEnabled(editable)
        self.update_tilt_home_switch_option()
        self.add_test_btn.setEnabled(editable)
        self.check_sensors_btn.setEnabled(True)
        self.remove_test_btn.setEnabled(editable and selected)
        self.clear_tests_btn.setEnabled(editable and bool(self.validation_tests))
        self.start_validation_btn.setEnabled(editable and bool(self.validation_tests))
        self.abort_validation_btn.setEnabled(self.is_running)
