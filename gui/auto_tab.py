import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils.config_manager import load_config, save_config


class AutoTab(QWidget):
    log_signal = Signal(str)
    command_signal = Signal(str)
    reconnect_signal = Signal()
    cycle_state_signal = Signal(str)

    def __init__(self):
        super().__init__()

        self.sequence_steps = []
        self.current_step_index = -1
        self.is_running = False
        self.is_paused = False
        self.pending_delay_ms = 0
        self.delay_started_at = 0.0
        self.executing_command = None
        self.external_lock_active = False
        self.external_lock_reason = ""
        self.external_run_active = False
        self.external_run_label = ""
        self.delay_timer = QTimer(self)
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self.advance_sequence)

        layout = QVBoxLayout(self)
        layout.addWidget(self.build_builder_group())
        layout.addWidget(self.build_queue_group())
        layout.addWidget(self.build_preset_group())

        self.step_label = QLabel("Current Step: IDLE")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.step_label)
        layout.addWidget(self.progress)

        self.refresh_action_options()
        self.update_step_option_controls()
        self.refresh_presets()
        self.update_button_states()

    def build_builder_group(self):
        box = QGroupBox("Step Builder")
        grid = QGridLayout(box)

        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 1000)
        self.repeat_spin.setValue(1)

        self.peripheral_combo = QComboBox()
        self.peripheral_combo.addItem("M0 | Roll Servo", "m0")
        self.peripheral_combo.addItem("M1 | Tilt Servo", "m1")
        self.peripheral_combo.addItem("Actuator", "actuator")

        self.action_combo = QComboBox()

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(0, 300)
        self.dwell_spin.setValue(5.0)
        self.dwell_spin.setSuffix(" s")

        self.enable_before_check = QCheckBox("Enable Motor Before Step")
        self.stop_after_check = QCheckBox("Stop After Dwell")
        self.disable_after_check = QCheckBox("Disable Motor After Step")

        self.add_step_btn = QPushButton("Add Step")
        self.update_step_btn = QPushButton("Update Selected")

        self.peripheral_combo.currentIndexChanged.connect(self.on_peripheral_changed)
        self.add_step_btn.clicked.connect(self.add_step)
        self.update_step_btn.clicked.connect(self.update_selected_step)

        grid.addWidget(QLabel("Repeat Count:"), 0, 0)
        grid.addWidget(self.repeat_spin, 0, 1)
        grid.addWidget(QLabel("Peripheral:"), 0, 2)
        grid.addWidget(self.peripheral_combo, 0, 3)

        grid.addWidget(QLabel("Action:"), 1, 0)
        grid.addWidget(self.action_combo, 1, 1)
        grid.addWidget(QLabel("Dwell:"), 1, 2)
        grid.addWidget(self.dwell_spin, 1, 3)

        grid.addWidget(self.enable_before_check, 2, 0, 1, 2)
        grid.addWidget(self.stop_after_check, 2, 2, 1, 2)
        grid.addWidget(self.disable_after_check, 3, 0, 1, 2)
        grid.addWidget(self.add_step_btn, 3, 2)
        grid.addWidget(self.update_step_btn, 3, 3)

        return box

    def build_queue_group(self):
        box = QGroupBox("Sequence Queue")
        layout = QVBoxLayout(box)

        self.sequence_list = QListWidget()
        self.sequence_list.currentRowChanged.connect(self.load_selected_step_into_builder)
        self.sequence_list.currentRowChanged.connect(lambda _: self.update_button_states())
        layout.addWidget(self.sequence_list)

        button_row = QHBoxLayout()
        self.move_up_btn = QPushButton("Move Up")
        self.move_down_btn = QPushButton("Move Down")
        self.remove_btn = QPushButton("Remove")
        self.clear_btn = QPushButton("Clear Queue")
        self.start_btn = QPushButton("Start Queue")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.abort_btn = QPushButton("Abort")
        self.reset_btn = QPushButton("Reset")
        self.reconnect_btn = QPushButton("Reconnect Link")

        self.move_up_btn.clicked.connect(self.move_step_up)
        self.move_down_btn.clicked.connect(self.move_step_down)
        self.remove_btn.clicked.connect(self.remove_selected_step)
        self.clear_btn.clicked.connect(self.clear_queue)
        self.start_btn.clicked.connect(self.start_cycle)
        self.pause_btn.clicked.connect(self.pause_cycle)
        self.resume_btn.clicked.connect(self.resume_cycle)
        self.abort_btn.clicked.connect(self.abort_cycle)
        self.reset_btn.clicked.connect(self.reset_cycle)
        self.reconnect_btn.clicked.connect(self.request_reconnect)

        for button in (
            self.move_up_btn,
            self.move_down_btn,
            self.remove_btn,
            self.clear_btn,
            self.start_btn,
            self.pause_btn,
            self.resume_btn,
            self.abort_btn,
            self.reset_btn,
            self.reconnect_btn,
        ):
            button_row.addWidget(button)

        layout.addLayout(button_row)
        return box

    def build_preset_group(self):
        box = QGroupBox("Presets")
        grid = QGridLayout(box)

        self.preset_name_input = QLineEdit()
        self.preset_combo = QComboBox()
        self.save_preset_btn = QPushButton("Save Preset")
        self.load_preset_btn = QPushButton("Load Preset")
        self.delete_preset_btn = QPushButton("Delete Preset")

        self.save_preset_btn.clicked.connect(self.save_preset)
        self.load_preset_btn.clicked.connect(self.load_preset)
        self.delete_preset_btn.clicked.connect(self.delete_preset)

        grid.addWidget(QLabel("Preset Name:"), 0, 0)
        grid.addWidget(self.preset_name_input, 0, 1)
        grid.addWidget(self.save_preset_btn, 0, 2)
        grid.addWidget(QLabel("Saved Presets:"), 1, 0)
        grid.addWidget(self.preset_combo, 1, 1)
        grid.addWidget(self.load_preset_btn, 1, 2)
        grid.addWidget(self.delete_preset_btn, 1, 3)

        return box

    def refresh_action_options(self):
        current = self.peripheral_combo.currentData()
        self.action_combo.clear()

        if current in {"m0", "m1"}:
            self.action_combo.addItem("Forward", "forward")
            self.action_combo.addItem("Reverse", "reverse")
        else:
            self.action_combo.addItem("Extend", "extend")
            self.action_combo.addItem("Retract", "retract")

    def on_peripheral_changed(self):
        self.refresh_action_options()
        self.update_step_option_controls()

    def update_step_option_controls(self):
        peripheral = self.peripheral_combo.currentData()
        is_motor = peripheral in {"m0", "m1"}
        is_actuator = peripheral == "actuator"

        self.enable_before_check.setText("Enable Motor Before Step")
        self.stop_after_check.setText("Stop After Dwell")
        self.disable_after_check.setText("Disable Motor After Step")

        if is_motor:
            self.enable_before_check.setChecked(True)
            self.stop_after_check.setChecked(True)
            self.disable_after_check.setChecked(True)
        elif is_actuator:
            self.enable_before_check.setText("Start Actuator Before Step")
            self.disable_after_check.setText("Stop Actuator After Step")
            self.enable_before_check.setChecked(True)
            self.stop_after_check.setChecked(False)
            self.disable_after_check.setChecked(True)

        self.enable_before_check.setEnabled(False if (is_motor or is_actuator) else True)
        self.stop_after_check.setEnabled(not is_actuator)
        self.disable_after_check.setEnabled(False if (is_motor or is_actuator) else True)

    def add_step(self):
        step = self.build_step_from_inputs()
        self.sequence_steps.append(step)
        self.append_step_item(step)
        self.sequence_list.setCurrentRow(self.sequence_list.count() - 1)
        self.log_signal.emit(f"Auto: Added step -> {step['display']}")
        self.update_button_states()

    def update_selected_step(self):
        row = self.sequence_list.currentRow()
        if row < 0:
            self.log_signal.emit("Auto: No queue step selected")
            return

        step = self.build_step_from_inputs()
        self.sequence_steps[row] = step
        self.sequence_list.item(row).setText(step["display"])
        self.log_signal.emit(f"Auto: Updated step {row + 1} -> {step['display']}")
        self.update_button_states()

    def build_step_from_inputs(self):
        peripheral = self.peripheral_combo.currentData()
        action = self.action_combo.currentData()
        repeat = self.repeat_spin.value()
        dwell_s = self.dwell_spin.value()
        dwell_ms = int(dwell_s * 1000)

        display = (
            f"{self.peripheral_combo.currentText()} | "
            f"{self.action_combo.currentText()} | "
            f"{dwell_s:.1f}s | repeat {repeat}"
        )

        return {
            "peripheral": peripheral,
            "action": action,
            "repeat": repeat,
            "dwell_ms": dwell_ms,
            "enable_before": True if peripheral in {"m0", "m1", "actuator"} else self.enable_before_check.isChecked(),
            "stop_after": False if peripheral == "actuator" else self.stop_after_check.isChecked(),
            "disable_after": True if peripheral in {"m0", "m1", "actuator"} else self.disable_after_check.isChecked(),
            "display": display,
        }

    def append_step_item(self, step):
        self.sequence_list.addItem(QListWidgetItem(step["display"]))

    def load_selected_step_into_builder(self, row):
        if row < 0 or row >= len(self.sequence_steps):
            return

        step = self.sequence_steps[row]
        self.peripheral_combo.setCurrentIndex(self.peripheral_combo.findData(step["peripheral"]))
        self.action_combo.setCurrentIndex(self.action_combo.findData(step["action"]))
        self.repeat_spin.setValue(step["repeat"])
        self.dwell_spin.setValue(step["dwell_ms"] / 1000.0)
        self.enable_before_check.setChecked(step["enable_before"])
        self.stop_after_check.setChecked(step["stop_after"])
        self.disable_after_check.setChecked(step["disable_after"])
        self.update_step_option_controls()

    def move_step_up(self):
        row = self.sequence_list.currentRow()
        if row <= 0:
            return
        self.sequence_steps[row - 1], self.sequence_steps[row] = self.sequence_steps[row], self.sequence_steps[row - 1]
        self.refresh_sequence_list(row - 1)
        self.update_button_states()

    def move_step_down(self):
        row = self.sequence_list.currentRow()
        if row < 0 or row >= len(self.sequence_steps) - 1:
            return
        self.sequence_steps[row + 1], self.sequence_steps[row] = self.sequence_steps[row], self.sequence_steps[row + 1]
        self.refresh_sequence_list(row + 1)
        self.update_button_states()

    def remove_selected_step(self):
        row = self.sequence_list.currentRow()
        if row < 0:
            return
        removed = self.sequence_steps.pop(row)
        self.sequence_list.takeItem(row)
        self.log_signal.emit(f"Auto: Removed step -> {removed['display']}")
        self.update_button_states()

    def clear_queue(self):
        if self.is_running:
            self.log_signal.emit("Auto: Stop the queue before clearing it")
            return
        self.sequence_steps.clear()
        self.sequence_list.clear()
        self.step_label.setText("Current Step: IDLE")
        self.progress.setValue(0)
        self.log_signal.emit("Auto: Queue cleared")
        self.update_button_states()

    def refresh_sequence_list(self, selected_row):
        self.sequence_list.clear()
        for step in self.sequence_steps:
            self.append_step_item(step)
        self.sequence_list.setCurrentRow(selected_row)
        self.update_button_states()

    def save_preset(self):
        name = self.preset_name_input.text().strip()
        if not name:
            self.log_signal.emit("Auto: Enter a preset name before saving")
            return

        config = load_config()
        presets = config.setdefault("auto_sequences", {})
        presets[name] = self.sequence_steps.copy()
        save_config(config)
        self.refresh_presets(name)
        self.log_signal.emit(f"Auto: Saved preset '{name}'")

    def load_preset(self):
        name = self.preset_combo.currentText().strip()
        if not name:
            self.log_signal.emit("Auto: No preset selected")
            return

        config = load_config()
        presets = config.get("auto_sequences", {})
        steps = presets.get(name)
        if steps is None:
            self.log_signal.emit(f"Auto: Preset '{name}' was not found")
            return

        self.sequence_steps = [self.normalize_loaded_step(step) for step in steps]
        self.refresh_sequence_list(0 if self.sequence_steps else -1)
        self.preset_name_input.setText(name)
        self.log_signal.emit(f"Auto: Loaded preset '{name}'")
        self.update_button_states()

    def delete_preset(self):
        name = self.preset_combo.currentText().strip()
        if not name:
            return

        config = load_config()
        presets = config.get("auto_sequences", {})
        if name in presets:
            del presets[name]
            config["auto_sequences"] = presets
            save_config(config)
            self.refresh_presets()
            self.log_signal.emit(f"Auto: Deleted preset '{name}'")
            self.update_button_states()

    def refresh_presets(self, select_name=None):
        config = load_config()
        presets = sorted(config.get("auto_sequences", {}).keys())
        self.preset_combo.clear()
        self.preset_combo.addItems(presets)
        if select_name:
            index = self.preset_combo.findText(select_name)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

    def normalize_loaded_step(self, step):
        normalized = {
            "peripheral": step.get("peripheral", "m0"),
            "action": step.get("action", "forward"),
            "repeat": int(step.get("repeat", 1)),
            "dwell_ms": int(step.get("dwell_ms", 1000)),
            "enable_before": bool(step.get("enable_before", False)),
            "stop_after": bool(step.get("stop_after", True)),
            "disable_after": bool(step.get("disable_after", False)),
        }
        if normalized["peripheral"] in {"m0", "m1"}:
            normalized["enable_before"] = True
            normalized["stop_after"] = True
            normalized["disable_after"] = True
        elif normalized["peripheral"] == "actuator":
            normalized["enable_before"] = True
            normalized["stop_after"] = False
            normalized["disable_after"] = True
        normalized["display"] = (
            f"{normalized['peripheral'].upper()} | "
            f"{normalized['action'].replace('_', ' ').title()} | "
            f"{normalized['dwell_ms'] / 1000.0:.1f}s | repeat {normalized['repeat']}"
        )
        return normalized

    def start_cycle(self):
        if self.external_lock_active:
            self.log_signal.emit("Auto: Start ignored because controls are locked by external mode")
            return
        if self.is_running:
            self.log_signal.emit("Auto: Queue already running")
            return
        if not self.sequence_steps:
            self.log_signal.emit("Auto: Add at least one step to the queue first")
            return

        self.execution_steps = self.expand_steps_for_run()
        self.current_step_index = -1
        self.is_running = True
        self.is_paused = False
        self.pending_delay_ms = 0
        self.external_run_active = False
        self.external_run_label = ""
        self.progress.setValue(0)
        self.step_label.setText("Current Step: STARTING")
        self.log_signal.emit(f"Auto: Starting queued sequence with {len(self.execution_steps)} step(s)")
        self.cycle_state_signal.emit("running")
        self.update_button_states()
        self.advance_sequence()

    def start_from_hardware(self):
        self.log_signal.emit("Auto: Hardware START received")
        if self.external_lock_active:
            self.log_signal.emit("Auto: Hardware START ignored because controls are locked by external mode")
            return False
        if not self.sequence_steps:
            self.log_signal.emit("Auto: Hardware START ignored because no queue is loaded")
            self.cycle_state_signal.emit("idle")
            return False
        if self.is_running:
            self.log_signal.emit("Auto: Hardware START ignored because queue is already running")
            return False
        self.start_cycle()
        return True

    def expand_steps_for_run(self, steps=None):
        execution = []
        for step in steps if steps is not None else self.sequence_steps:
            for repeat_index in range(step["repeat"]):
                execution.extend(self.execution_entries_for_step(step, repeat_index + 1))
        return execution

    def set_external_lock(self, locked: bool, reason: str = ""):
        self.external_lock_active = locked
        self.external_lock_reason = reason
        self.update_button_states()
        if locked:
            suffix = f" ({reason})" if reason else ""
            self.log_signal.emit(f"Auto: Controls locked by external mode{suffix}")
        else:
            self.log_signal.emit("Auto: Controls unlocked")

    def start_external_sequence(self, steps, label: str = "External"):
        if self.is_running:
            self.log_signal.emit(f"Auto: {label} start ignored because queue is already running")
            return False
        if not steps:
            self.log_signal.emit(f"Auto: {label} start ignored because no steps were provided")
            return False

        self.execution_steps = self.expand_steps_for_run(steps)
        if not self.execution_steps:
            self.log_signal.emit(f"Auto: {label} start ignored because no commands were generated")
            return False

        self.current_step_index = -1
        self.is_running = True
        self.is_paused = False
        self.pending_delay_ms = 0
        self.external_run_active = True
        self.external_run_label = label
        self.progress.setValue(0)
        self.step_label.setText(f"Current Step: {label.upper()} STARTING")
        self.log_signal.emit(
            f"Auto: Starting {label} sequence with {len(self.execution_steps)} command step(s)"
        )
        self.cycle_state_signal.emit("running")
        self.update_button_states()
        self.advance_sequence()
        return True

    def execution_entries_for_step(self, step, repeat_index):
        entries = []
        label_prefix = f"{step['display']} | run {repeat_index}"

        if step["peripheral"] in {"m0", "m1"}:
            motor_name = step["peripheral"].upper()
            entries.append({
                "label": f"{label_prefix} | enable",
                "command": f"ENABLE_{motor_name}",
                "delay_ms": 250,
            })

            entries.append({
                "label": label_prefix,
                "command": self.command_for_step(step),
                "delay_ms": step["dwell_ms"],
            })

            if step["stop_after"]:
                entries.append({
                    "label": f"{label_prefix} | stop",
                    "command": f"STOP_{motor_name}",
                    "delay_ms": 250,
                })

            entries.append({
                "label": f"{label_prefix} | disable",
                "command": f"DISABLE_{motor_name}",
                "delay_ms": 0,
            })
            return entries

        entries.append({
            "label": label_prefix,
            "command": self.command_for_step(step),
            "delay_ms": step["dwell_ms"],
        })

        if step["disable_after"]:
            entries.append({
                "label": f"{label_prefix} | stop",
                "command": "STOP_ACTUATOR",
                "delay_ms": 250,
            })

        return entries

    def command_for_step(self, step):
        if step["peripheral"] == "m0":
            return "MOVE_POS1_M0" if step["action"] == "forward" else "MOVE_POS2_M0"
        if step["peripheral"] == "m1":
            return "MOVE_POS1_M1" if step["action"] == "forward" else "MOVE_POS2_M1"
        if step["action"] == "extend":
            return "EXTEND"
        return "RETRACT"

    def advance_sequence(self):
        if not self.is_running or self.is_paused:
            return

        self.current_step_index += 1
        if self.current_step_index >= len(self.execution_steps):
            self.finish_cycle("Auto: Sequence complete")
            return

        step = self.execution_steps[self.current_step_index]
        self.step_label.setText(f"Current Step: {step['label']}")
        progress = int(((self.current_step_index + 1) / len(self.execution_steps)) * 100)
        self.progress.setValue(progress)
        self.executing_command = step["command"]
        self.command_signal.emit(step["command"])
        if not self.is_running:
            return
        self.executing_command = None
        self.log_signal.emit(f"Auto: Command sent -> {step['command']}")

        if step["delay_ms"] > 0:
            self.pending_delay_ms = step["delay_ms"]
            self.delay_started_at = time.monotonic()
            self.delay_timer.start(step["delay_ms"])
        else:
            QTimer.singleShot(0, self.advance_sequence)

    def handle_command_failure(self, command: str, detail: str):
        if not self.is_running:
            return
        if self.current_step_index < 0 or self.current_step_index >= len(self.execution_steps):
            return

        active_step = self.execution_steps[self.current_step_index]
        if command != active_step["command"]:
            return

        self.delay_timer.stop()
        self.executing_command = None
        self.is_running = False
        self.is_paused = False
        self.pending_delay_ms = 0
        self.external_run_active = False
        self.external_run_label = ""
        self.step_label.setText("Current Step: ABORTED")
        self.progress.setValue(0)
        self.log_signal.emit(f"Auto: Aborted after command failed -> {command}: {detail}")
        self.cycle_state_signal.emit("stopped")

        for cleanup_command in (
            "STOP_M0",
            "DISABLE_M0",
            "STOP_M1",
            "DISABLE_M1",
            "STOP_ACTUATOR",
        ):
            self.command_signal.emit(cleanup_command)

        self.update_button_states()

    def pause_cycle(self):
        if not self.is_running or self.is_paused:
            return

        self.is_paused = True
        if self.delay_timer.isActive():
            elapsed_ms = int((time.monotonic() - self.delay_started_at) * 1000)
            self.pending_delay_ms = max(0, self.pending_delay_ms - elapsed_ms)
            self.delay_timer.stop()
        self.step_label.setText("Current Step: PAUSED")
        self.log_signal.emit("Auto: Pause pressed")
        self.update_button_states()

    def resume_cycle(self):
        if not self.is_running or not self.is_paused:
            return

        self.is_paused = False
        self.log_signal.emit("Auto: Resume pressed")
        self.update_button_states()

        if self.pending_delay_ms > 0:
            self.delay_started_at = time.monotonic()
            self.delay_timer.start(self.pending_delay_ms)
        else:
            self.advance_sequence()

    def abort_cycle(self):
        if not self.is_running:
            self.log_signal.emit("Auto: Abort pressed")
            self.cycle_state_signal.emit("stopped")
            return

        self.delay_timer.stop()
        self.executing_command = None
        self.command_signal.emit("STOP_M0")
        self.command_signal.emit("DISABLE_M0")
        self.command_signal.emit("STOP_M1")
        self.command_signal.emit("DISABLE_M1")
        self.command_signal.emit("STOP_ACTUATOR")

        self.is_running = False
        self.is_paused = False
        self.pending_delay_ms = 0
        self.external_run_active = False
        self.external_run_label = ""
        self.step_label.setText("Current Step: ABORTED")
        self.progress.setValue(0)
        self.log_signal.emit("Auto: Abort pressed")
        self.cycle_state_signal.emit("stopped")
        self.update_button_states()

    def abort_from_hardware(self):
        self.abort_cycle()

    def request_reconnect(self):
        if self.is_running:
            self.log_signal.emit("Auto: Reconnect requested while queue is running")
        else:
            self.log_signal.emit("Auto: Reconnect requested")
        self.reconnect_signal.emit()

    def reset_cycle(self):
        self.delay_timer.stop()
        self.executing_command = None
        self.is_running = False
        self.is_paused = False
        self.pending_delay_ms = 0
        self.current_step_index = -1
        self.external_run_active = False
        self.external_run_label = ""
        self.step_label.setText("Current Step: IDLE")
        self.progress.setValue(0)
        self.log_signal.emit("Auto: Reset pressed")
        self.cycle_state_signal.emit("idle")
        self.update_button_states()

    def finish_cycle(self, message):
        self.executing_command = None
        self.is_running = False
        self.is_paused = False
        self.pending_delay_ms = 0
        label = self.external_run_label
        self.external_run_active = False
        self.external_run_label = ""
        self.step_label.setText("Current Step: COMPLETE")
        self.progress.setValue(100)
        self.log_signal.emit(f"{label}: Sequence complete" if label else message)
        self.cycle_state_signal.emit("idle")
        self.update_button_states()

    def update_button_states(self):
        selected = self.sequence_list.currentRow() >= 0
        locked = self.external_lock_active
        auto_controls_enabled = not locked
        self.start_btn.setEnabled(auto_controls_enabled and not self.is_running and bool(self.sequence_steps))
        self.pause_btn.setEnabled(auto_controls_enabled and self.is_running and not self.is_paused)
        self.resume_btn.setEnabled(auto_controls_enabled and self.is_running and self.is_paused)
        self.abort_btn.setEnabled(auto_controls_enabled and self.is_running)
        self.reset_btn.setEnabled(auto_controls_enabled and (not self.is_running or self.is_paused))
        self.move_up_btn.setEnabled(auto_controls_enabled and not self.is_running and selected)
        self.move_down_btn.setEnabled(auto_controls_enabled and not self.is_running and selected)
        self.remove_btn.setEnabled(auto_controls_enabled and not self.is_running and selected)
        self.clear_btn.setEnabled(auto_controls_enabled and not self.is_running and bool(self.sequence_steps))
        self.add_step_btn.setEnabled(auto_controls_enabled and not self.is_running)
        self.update_step_btn.setEnabled(auto_controls_enabled and not self.is_running and selected)
