from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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


class ValidationTab(QWidget):
    log_signal = Signal(str)
    validation_mode_signal = Signal(bool)
    start_sequence_signal = Signal(list, str)
    abort_signal = Signal()
    sensor_poll_signal = Signal()

    TEST_DEFINITIONS = {
        "roll_home_to_pos1": {
            "label": "Roll | Home -> Pos 1",
            "moves": [("m0", "forward")],
        },
        "roll_pos1_to_home": {
            "label": "Roll | Pos 1 -> Home",
            "moves": [("m0", "reverse")],
        },
        "roll_cycle": {
            "label": "Roll | Home <-> Pos 1",
            "moves": [("m0", "forward"), ("m0", "reverse")],
        },
        "tilt_home_to_pos1": {
            "label": "Tilt | Home -> Pos 1",
            "moves": [("m1", "forward")],
        },
        "tilt_pos1_to_home": {
            "label": "Tilt | Pos 1 -> Home",
            "moves": [("m1", "reverse")],
        },
        "tilt_cycle": {
            "label": "Tilt | Home <-> Pos 1",
            "moves": [("m1", "forward"), ("m1", "reverse")],
        },
        "combined_home_to_pos1": {
            "label": "Roll + Tilt | Home -> Pos 1",
            "moves": [("m0", "forward"), ("m1", "forward")],
        },
        "combined_pos1_to_home": {
            "label": "Roll + Tilt | Pos 1 -> Home",
            "moves": [("m0", "reverse"), ("m1", "reverse")],
        },
        "combined_cycle": {
            "label": "Roll + Tilt | Home <-> Pos 1",
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
        self.sensor_poll_timer = QTimer(self)
        self.sensor_poll_timer.setInterval(500)
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
        self.sensor_config_label = QLabel("GPIO pins: unknown")
        self.check_sensors_btn = QPushButton("Check Sensors")
        self.check_sensors_btn.clicked.connect(self.request_sensor_poll)

        grid.addWidget(self.roll_sensor_label, 0, 0, 1, 2)
        grid.addWidget(self.tilt_sensor_label, 1, 0, 1, 2)
        grid.addWidget(self.sensor_config_label, 2, 0, 1, 2)
        grid.addWidget(self.check_sensors_btn, 3, 1)
        return box

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

        self.add_test_btn = QPushButton("Add Validation Test")
        self.add_test_btn.clicked.connect(self.add_test)

        grid.addWidget(QLabel("Movement:"), 0, 0)
        grid.addWidget(self.test_combo, 0, 1, 1, 3)
        grid.addWidget(QLabel("Cycles:"), 1, 0)
        grid.addWidget(self.cycles_spin, 1, 1)
        grid.addWidget(QLabel("Move Dwell:"), 1, 2)
        grid.addWidget(self.dwell_spin, 1, 3)
        grid.addWidget(self.add_test_btn, 2, 2, 1, 2)
        return box

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
            self.sensor_poll_timer.start()
            self.request_sensor_poll()
        else:
            self.sensor_poll_timer.stop()
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

    def update_sensor_inputs(self, response: str):
        values = self.parse_csv_response(response, "GPIO_VALIDATION_INPUTS:")
        if not values:
            message = response if response else "no response"
            self.roll_sensor_label.setText("Roll sensor: unavailable")
            self.tilt_sensor_label.setText("Tilt sensor: unavailable")
            self.sensor_config_label.setText(f"GPIO pins: unavailable ({message})")
            return

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

    def build_test_from_inputs(self):
        test_key = self.test_combo.currentData()
        definition = self.TEST_DEFINITIONS[test_key]
        cycles = self.cycles_spin.value()
        dwell_ms = int(self.dwell_spin.value() * 1000)
        display = f"{definition['label']} | {cycles} cycle(s) | {self.dwell_spin.value():.1f}s dwell"
        return {
            "test_key": test_key,
            "cycles": cycles,
            "dwell_ms": dwell_ms,
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

    def auto_step(self, peripheral: str, action: str, dwell_ms: int, label: str):
        direction = "Home -> Pos 1" if action == "forward" else "Pos 1 -> Home"
        motor_label = "Roll Servo" if peripheral == "m0" else "Tilt Servo"
        return {
            "peripheral": peripheral,
            "action": action,
            "repeat": 1,
            "dwell_ms": dwell_ms,
            "enable_before": True,
            "stop_after": True,
            "disable_after": True,
            "display": f"{label} | {motor_label} | {direction}",
        }

    def expand_validation_steps(self):
        steps = []
        for test in self.validation_tests:
            definition = self.TEST_DEFINITIONS[test["test_key"]]
            for cycle in range(1, test["cycles"] + 1):
                label = f"Validation {definition['label']} cycle {cycle}/{test['cycles']}"
                for peripheral, action in definition["moves"]:
                    steps.append(self.auto_step(peripheral, action, test["dwell_ms"], label))
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
            self.run_summary_label.setText("Validation running")
            self.log_signal.emit("Validation: Run started")
        else:
            self.is_running = False
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
        if state == "idle" and not self.abort_requested:
            self.run_summary_label.setText("Validation complete")
            self.log_signal.emit("Validation: Run complete")
        else:
            self.run_summary_label.setText("Validation stopped")
            self.log_signal.emit("Validation: Run stopped")
        self.abort_requested = False
        self.update_button_states()

    def update_button_states(self):
        selected = self.validation_list.currentRow() >= 0
        editable = self.validation_mode_active and not self.is_running
        self.test_combo.setEnabled(editable)
        self.cycles_spin.setEnabled(editable)
        self.dwell_spin.setEnabled(editable)
        self.add_test_btn.setEnabled(editable)
        self.check_sensors_btn.setEnabled(self.validation_mode_active)
        self.remove_test_btn.setEnabled(editable and selected)
        self.clear_tests_btn.setEnabled(editable and bool(self.validation_tests))
        self.start_validation_btn.setEnabled(editable and bool(self.validation_tests))
        self.abort_validation_btn.setEnabled(self.is_running)
