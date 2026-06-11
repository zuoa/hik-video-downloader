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

HAS_FLUENT = False

try:
    from qfluentwidgets import (  # type: ignore
        BodyLabel,
        CardWidget,
        CheckBox,
        ComboBox,
        DateTimeEdit,
        FluentIcon,
        InfoBar,
        InfoBarPosition,
        LineEdit,
        PasswordLineEdit,
        PrimaryPushButton,
        ProgressBar,
        PushButton,
        SpinBox,
        StrongBodyLabel,
        SubtitleLabel,
        TextEdit,
        Theme,
        setTheme,
        setThemeColor,
    )

    HAS_FLUENT = True
except Exception:  # noqa: BLE001 - fallback keeps the app usable without the optional UI package
    BodyLabel = StrongBodyLabel = SubtitleLabel = None
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
    FluentIcon = None
    InfoBar = None
    InfoBarPosition = None
    Theme = None

    def setTheme(_theme) -> None:
        return None

    def setThemeColor(_color: str) -> None:
        return None

