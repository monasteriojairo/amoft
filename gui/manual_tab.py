from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QPushButton,
    QLabel, QDoubleSpinBox, QGridLayout
)


class ManualTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()

        layout = QHBoxLayout(self)

        # Left side: M0 + M1
        left_col = QVBoxLayout()
        left_col.addWidget(self.create_axis_group("M0 - Primary Axis", enabled=True))
        left_col.addWidget(self.create_axis_group("M1 - Secondary Axis", enabled=False))

        # Right side: actuator
        right_col = QVBoxLayout()
        right_col.addWidget(self.create_actuator_group())
        right_col.addStretch()

        layout.addLayout(left_col, 2)
        layout.addLayout(right_col, 1)

    def create_axis_group(self, title, enabled=True):
        box = QGroupBox(title)
        grid = QGridLayout(box)

        enable_btn = QPushButton("Enable")
        disable_btn = QPushButton("Disable")
        home_btn = QPushButton("Home")
        jog_plus_btn = QPushButton("Jog +")
        jog_minus_btn = QPushButton("Jog -")
        stop_btn = QPushButton("Stop")

        speed_spin = QDoubleSpinBox()
        speed_spin.setRange(0, 10000)
        speed_spin.setValue(500)
        speed_spin.setSuffix(" rpm")

        accel_spin = QDoubleSpinBox()
        accel_spin.setRange(0, 100000)
        accel_spin.setValue(1000)
        accel_spin.setSuffix(" units/s²")

        move_spin = QDoubleSpinBox()
        move_spin.setRange(0, 1000)
        move_spin.setValue(10)
        move_spin.setSuffix(" units")

        pos_label = QLabel("Position: 0.0")
        vel_label = QLabel("Velocity: 0.0")
        state_label = QLabel("State: DISABLED" if not enabled else "State: IDLE")

        grid.addWidget(enable_btn, 0, 0)
        grid.addWidget(disable_btn, 0, 1)
        grid.addWidget(home_btn, 0, 2)

        grid.addWidget(jog_minus_btn, 1, 0)
        grid.addWidget(stop_btn, 1, 1)
        grid.addWidget(jog_plus_btn, 1, 2)

        grid.addWidget(QLabel("Speed:"), 2, 0)
        grid.addWidget(speed_spin, 2, 1, 1, 2)

        grid.addWidget(QLabel("Acceleration:"), 3, 0)
        grid.addWidget(accel_spin, 3, 1, 1, 2)

        grid.addWidget(QLabel("Move Distance:"), 4, 0)
        grid.addWidget(move_spin, 4, 1, 1, 2)

        grid.addWidget(pos_label, 5, 0, 1, 3)
        grid.addWidget(vel_label, 6, 0, 1, 3)
        grid.addWidget(state_label, 7, 0, 1, 3)

        buttons = [enable_btn, disable_btn, home_btn, jog_plus_btn, jog_minus_btn, stop_btn]
        widgets = buttons + [speed_spin, accel_spin, move_spin]

        if not enabled:
            for w in widgets:
                w.setEnabled(False)

        enable_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Enable pressed"))
        disable_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Disable pressed"))
        home_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Home pressed"))
        jog_plus_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Jog + pressed"))
        jog_minus_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Jog - pressed"))
        stop_btn.clicked.connect(lambda: self.log_signal.emit(f"{title}: Stop pressed"))

        return box

    def create_actuator_group(self):
        box = QGroupBox("Linear Actuator")
        layout = QVBoxLayout(box)

        extend_btn = QPushButton("Extend")
        retract_btn = QPushButton("Retract")
        stop_btn = QPushButton("Stop")

        state_label = QLabel("State: IDLE")
        limit_label = QLabel("Limits: Unknown")

        extend_btn.clicked.connect(lambda: self.log_signal.emit("Actuator: Extend pressed"))
        retract_btn.clicked.connect(lambda: self.log_signal.emit("Actuator: Retract pressed"))
        stop_btn.clicked.connect(lambda: self.log_signal.emit("Actuator: Stop pressed"))

        layout.addWidget(extend_btn)
        layout.addWidget(retract_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(state_label)
        layout.addWidget(limit_label)

        return box
