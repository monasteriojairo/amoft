from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit
)


class DiagnosticsTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear Log")

        clear_btn.clicked.connect(self.log_box.clear)

        btn_row.addWidget(clear_btn)
        btn_row.addStretch()

        layout.addLayout(btn_row)
        layout.addWidget(self.log_box)

    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {message}")