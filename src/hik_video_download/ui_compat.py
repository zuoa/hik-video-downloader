from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QWidget,
)

HAS_QT_MATERIAL = False

try:
    from qt_material import apply_stylesheet  # type: ignore

    HAS_QT_MATERIAL = True
except ImportError:

    def apply_stylesheet(app, theme: str = "", **kwargs) -> None:
        return None


CardWidget = QWidget
CheckBox = QCheckBox
ComboBox = QComboBox
DateTimeEdit = QDateTimeEdit
LineEdit = QLineEdit
PasswordLineEdit = QLineEdit
PrimaryPushButton = PushButton = QPushButton
ProgressBar = QProgressBar
SpinBox = QSpinBox
TextEdit = QTextEdit
