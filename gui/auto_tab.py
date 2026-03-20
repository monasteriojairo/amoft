from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QPushButton,
    QLabel, QSpinBox, QDoubleSpinBox, QProgressBar, QCheckBox
)


class AutoTab(QWidget):
    log_signal = Signal(str)

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        box = QGroupBox("Automated Cycle")
        grid = QGridLayout(box)

        self.start_btn = QPushButton("Start Cycle")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.abort_btn = QPushButton("Abort")
        self.reset_btn = QPushButton("Reset")

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(0, 300)
        self.dwell_spin.setValue(5.0)
        self.dwell_spin.setSuffix(" s")

        self.cycle_spin = QSpinBox()
        self.cycle_spin.setRange(1, 1000)
        self.cycle_spin.setValue(1)

        self.speed_multiplier = QDoubleSpinBox()
        self.speed_multiplier.setRange(0.1, 5.0)
        self.speed_multiplier.setValue(1.0)
        self.speed_multiplier.setSingleStep(0.1)

        self.use_m1 = QCheckBox("Use M1")
        self.use_actuator = QCheckBox("Use Actuator")
        self.home_before_start = QCheckBox("Home Before Start")

        self.step_label = QLabel("Current Step: IDLE")
        self.progress = QProgressBar()
        self.progress.setValue(0)

        grid.addWidget(self.start_btn, 0, 0)
        grid.addWidget(self.pause_btn, 0, 1)
        grid.addWidget(self.resume_btn, 0, 2)
        grid.addWidget(self.abort_btn, 0, 3)
        grid.addWidget(self.reset_btn, 0, 4)

        grid.addWidget(QLabel("Dwell Time:"), 1, 0)
        grid.addWidget(self.dwell_spin, 1, 1)

        grid.addWidget(QLabel("Cycle Count:"), 1, 2)
        grid.addWidget(self.cycle_spin, 1, 3)

        grid.addWidget(QLabel("Speed Multiplier:"), 2, 0)
        grid.addWidget(self.speed_multiplier, 2, 1)

        grid.addWidget(self.use_m1, 2, 2)
        grid.addWidget(self.use_actuator, 2, 3)
        grid.addWidget(self.home_before_start, 2, 4)

        grid.addWidget(self.step_label, 3, 0, 1, 5)
        grid.addWidget(self.progress, 4, 0, 1, 5)

        layout.addWidget(box)

        self.start_btn.clicked.connect(self.start_cycle)
        self.pause_btn.clicked.connect(lambda: self.log_signal.emit("Auto: Pause pressed"))
        self.resume_btn.clicked.connect(lambda: self.log_signal.emit("Auto: Resume pressed"))
        self.abort_btn.clicked.connect(lambda: self.log_signal.emit("Auto: Abort pressed"))
        self.reset_btn.clicked.connect(self.reset_cycle)

    def start_cycle(self):
        self.step_label.setText("Current Step: STARTING")
        self.progress.setValue(10)
        self.log_signal.emit(
            f"Auto: Start pressed | dwell={self.dwell_spin.value()}s | "
            f"cycles={self.cycle_spin.value()} | speed x{self.speed_multiplier.value()}"
        )

    def reset_cycle(self):
        self.step_label.setText("Current Step: IDLE")
        self.progress.setValue(0)
        self.log_signal.emit("Auto: Reset pressed")

