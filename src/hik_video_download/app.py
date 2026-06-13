from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QObject, QSettings, QThreadPool, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import ChannelInfo, DownloadStatus, DownloadTask, NvrConnection, RecordingItem, RecordingQuery
from .ui_compat import (
    CardWidget,
    CheckBox,
    ComboBox,
    DateTimeEdit,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    TextEdit,
)
from .workers import DownloadCancelled, download_worker


class DownloadTaskItem(QWidget):
    """A single row showing one download's progress and status."""

    cancel_requested = Signal(str)

    def __init__(self, task: DownloadTask, parent=None) -> None:
        super().__init__(parent)
        self._task_id = task.id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.name_label = QLabel(
            f"{task.recording.start_time} ~ {task.recording.end_time}"
        )
        self.name_label.setFixedWidth(180)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)

        self.status_label = QLabel("排队中")
        self.status_label.setFixedWidth(60)

        self.cancel_button = PushButton("取消")
        self.cancel_button.setMinimumWidth(50)
        self.cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self._task_id))

        layout.addWidget(self.name_label)
        layout.addWidget(self.progress_bar, 1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.cancel_button)

    def update_progress(self, written: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(min(100, int(written * 100 / total)))
        else:
            self.progress_bar.setMaximum(0)

    def set_status(self, status: DownloadStatus, error: str = "") -> None:
        labels = {
            DownloadStatus.QUEUED: "排队中",
            DownloadStatus.DOWNLOADING: "下载中",
            DownloadStatus.COMPLETED: "完成",
            DownloadStatus.FAILED: f"失败: {error}" if error else "失败",
            DownloadStatus.CANCELLED: "已取消",
        }
        self.status_label.setText(labels.get(status, ""))
        if status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            self.cancel_button.setEnabled(False)
            if status == DownloadStatus.COMPLETED:
                self.progress_bar.setMaximum(100)
                self.progress_bar.setValue(100)


class DownloadManager(QObject):
    MAX_CONCURRENT = 3

    task_started = Signal(str)
    task_progress = Signal(str, int, int)
    task_completed = Signal(str, object)
    task_failed = Signal(str, str)
    task_cancelled = Signal(str)
    all_done = Signal()

    def __init__(self, thread_pool: QThreadPool, parent=None) -> None:
        super().__init__(parent)
        self._pool = thread_pool
        self._queue: deque[DownloadTask] = deque()
        self._active: dict[str, DownloadTask] = {}
        self._workers: dict[str, object] = {}

    @property
    def active_count(self) -> int:
        return len(self._active)

    def enqueue(self, tasks: list[DownloadTask]) -> None:
        for task in tasks:
            self._queue.append(task)
        self._start_next()

    def cancel(self, task_id: str) -> None:
        if task_id in self._active:
            self._active[task_id].cancel_event.set()
        self._queue = deque(t for t in self._queue if t.id != task_id)

    def cancel_all(self) -> None:
        for task_id in list(self._active):
            self._active[task_id].cancel_event.set()
        self._queue.clear()

    def _start_next(self) -> None:
        while len(self._active) < self.MAX_CONCURRENT and self._queue:
            task = self._queue.popleft()
            task.status = DownloadStatus.DOWNLOADING
            self._active[task.id] = task
            worker = download_worker(task)
            worker.signals.started.connect(lambda tid=task.id: self.task_started.emit(tid))
            worker.signals.progress.connect(lambda w, t, tid=task.id: self.task_progress.emit(tid, w, t))
            worker.signals.result.connect(lambda r, tid=task.id: self._on_result(tid, r))
            worker.signals.error.connect(lambda e, tid=task.id: self._on_error(tid, e))
            worker.signals.finished.connect(lambda tid=task.id: self._on_worker_finished(tid))
            self._workers[task.id] = worker
            self._pool.start(worker)

    def _on_result(self, task_id: str, result: object) -> None:
        task = self._active.get(task_id)
        if task:
            task.status = DownloadStatus.COMPLETED
            task.result_path = result
            self.task_completed.emit(task_id, result)

    def _on_error(self, task_id: str, error: str) -> None:
        task = self._active.get(task_id)
        if not task:
            return
        if task.cancel_event.is_set():
            task.status = DownloadStatus.CANCELLED
            self.task_cancelled.emit(task_id)
        else:
            task.status = DownloadStatus.FAILED
            task.error_message = error
            self.task_failed.emit(task_id, error)

    def _on_worker_finished(self, task_id: str) -> None:
        self._active.pop(task_id, None)
        self._workers.pop(task_id, None)
        if not self._active and not self._queue:
            self.all_done.emit()
        else:
            self._start_next()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("海康 NVR 录像下载")
        self.resize(1180, 760)
        self.thread_pool = QThreadPool.globalInstance()
        self.recordings: list[RecordingItem] = []
        self._task_widgets: dict[str, DownloadTaskItem] = {}
        self._output_dir = Path.home() / "Downloads" / "hik-recordings"

        self._settings = QSettings("hik-video-downloader", "hik-video-downloader")
        self._build_ui()
        self._load_settings()
        self._set_idle_state()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Title bar with download directory config ──
        title_row = QHBoxLayout()
        title_row.addWidget(self._label("海康 NVR 录像下载", "title"))
        title_row.addStretch(1)
        dir_label = self._label("保存目录", "body")
        title_row.addWidget(dir_label)
        self.output_display = QLabel(str(self._output_dir))
        self.output_display.setObjectName("dirPath")
        self.output_display.setCursor(Qt.CursorShape.PointingHandCursor)
        self.output_display.setToolTip("点击更改保存目录")
        self.output_display.mousePressEvent = lambda _e: self._pick_output_dir()
        title_row.addWidget(self.output_display)
        title_row.addSpacing(16)
        self.connection_status = self._label("未连接", "body")
        self.connection_status.setObjectName("statusLabel")
        title_row.addWidget(self.connection_status)
        layout.addLayout(title_row)

        # ── Top row: Connection + Search side by side ──
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # Card 1: Connection settings
        conn_card = self._card()
        conn_layout = QGridLayout(conn_card)
        conn_layout.setContentsMargins(16, 14, 16, 14)
        conn_layout.setHorizontalSpacing(12)
        conn_layout.setVerticalSpacing(10)
        conn_layout.addWidget(self._label("连接设置", "section"), 0, 0, 1, 5)

        self.host_input = LineEdit()
        self.host_input.setPlaceholderText("192.168.1.64")
        self.port_input = SpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(80)
        self.https_check = CheckBox("HTTPS")
        self.rtsp_port_input = SpinBox()
        self.rtsp_port_input.setRange(1, 65535)
        self.rtsp_port_input.setValue(554)
        self.user_input = LineEdit()
        self.user_input.setText("admin")
        self.password_input = PasswordLineEdit()
        self.password_input.setEchoMode(LineEdit.EchoMode.Password)
        self.test_button = PrimaryPushButton("测试连接")
        self.test_button.setObjectName("primaryButton")
        self.test_button.clicked.connect(self._test_connection)

        self._add_form_row(conn_layout, 1, "主机", self.host_input)
        self._add_form_row(conn_layout, 1, "端口", self.port_input, column=2)
        conn_layout.addWidget(self.https_check, 1, 4)
        self._add_form_row(conn_layout, 2, "用户名", self.user_input)
        self._add_form_row(conn_layout, 2, "密码", self.password_input, column=2)
        self._add_form_row(conn_layout, 3, "RTSP端口", self.rtsp_port_input)
        conn_btn_row = QHBoxLayout()
        conn_btn_row.addStretch(1)
        conn_btn_row.addWidget(self.test_button)
        conn_layout.addLayout(conn_btn_row, 4, 0, 1, 5)
        top_row.addWidget(conn_card, 2)

        # Card 2: Search criteria
        search_card = self._card()
        search_layout = QGridLayout(search_card)
        search_layout.setContentsMargins(16, 14, 16, 14)
        search_layout.setHorizontalSpacing(12)
        search_layout.setVerticalSpacing(10)
        search_layout.addWidget(self._label("检索条件", "section"), 0, 0, 1, 5)

        self.channel_input = ComboBox()
        self.channel_input.addItem("请先连接设备", None)
        self._channels: list[ChannelInfo] = []

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.start_input = DateTimeEdit()
        self.start_input.setCalendarPopup(True)
        self.start_input.setDateTime(QDateTime(today))
        self.end_input = DateTimeEdit()
        self.end_input.setCalendarPopup(True)
        self.end_input.setDateTime(QDateTime(today.replace(hour=23, minute=59, second=59)))

        self._prev_start_date = self.start_input.date()
        self._prev_end_date = self.end_input.date()
        self.start_input.dateTimeChanged.connect(self._on_start_date_picked)
        self.end_input.dateTimeChanged.connect(self._on_end_date_picked)

        self.search_button = PrimaryPushButton("检索录像")
        self.search_button.setObjectName("primaryButton")
        self.search_button.clicked.connect(self._search_recordings)

        self.preview_button = PushButton("实时预览")
        self.preview_button.clicked.connect(self._preview_channel)

        self._add_form_row(search_layout, 1, "通道", self.channel_input, span=3)
        self._add_form_row(search_layout, 2, "开始时间", self.start_input)
        self._add_form_row(search_layout, 2, "结束时间", self.end_input, column=2)
        search_btn_row = QHBoxLayout()
        search_btn_row.addStretch(1)
        search_btn_row.addWidget(self.preview_button)
        search_btn_row.addWidget(self.search_button)
        search_layout.addLayout(search_btn_row, 3, 0, 1, 5)
        top_row.addWidget(search_card, 3)

        layout.addLayout(top_row)

        # ── Table card ──
        table_card = self._card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_header = QHBoxLayout()
        table_header.addWidget(self._label("录像片段", "section"))
        table_header.addStretch(1)
        self.download_button = PrimaryPushButton("下载所选")
        self.download_button.setObjectName("primaryButton")
        self.download_button.clicked.connect(self._download_selected)
        table_header.addWidget(self.download_button)
        table_layout.addLayout(table_header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["选择", "通道", "开始", "结束", "大小", "播放 URI"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self._select_all_check = CheckBox("全选")
        self._select_all_check.stateChanged.connect(self._on_select_all)
        table_header.addWidget(self._select_all_check)
        table_layout.addWidget(self.table)
        layout.addWidget(table_card, 1)

        # ── Bottom row: Tasks + Logs ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        task_card = self._card()
        task_layout = QVBoxLayout(task_card)
        task_layout.setContentsMargins(14, 14, 14, 14)
        task_header = QHBoxLayout()
        task_header.addWidget(self._label("下载任务", "section"))
        task_header.addStretch(1)
        self.cancel_all_button = PushButton("全部取消")
        self.cancel_all_button.clicked.connect(self._cancel_all_downloads)
        task_header.addWidget(self.cancel_all_button)
        task_layout.addLayout(task_header)
        self.task_list_container = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_list_container)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(4)
        self.task_list_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(self.task_list_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(120)
        task_layout.addWidget(scroll, 1)
        bottom_row.addWidget(task_card, 3)

        log_card = self._card()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 14, 14, 14)
        log_layout.addWidget(self._label("任务日志", "section"))
        self.log_view = TextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(180)
        log_layout.addWidget(self.log_view)
        bottom_row.addWidget(log_card, 2)

        layout.addLayout(bottom_row)

        self.setCentralWidget(root)
        self._apply_custom_style()

        # Download manager
        self.download_manager = DownloadManager(self.thread_pool, self)
        self.download_manager.task_started.connect(self._on_task_started)
        self.download_manager.task_progress.connect(self._on_task_progress)
        self.download_manager.task_completed.connect(self._on_task_completed)
        self.download_manager.task_failed.connect(self._on_task_failed)
        self.download_manager.task_cancelled.connect(self._on_task_cancelled)
        self.download_manager.all_done.connect(self._on_all_downloads_done)

    def _card(self) -> QWidget:
        card = CardWidget()
        card.setObjectName("card")
        return card

    def _label(self, text: str, kind: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(kind)
        return label

    def _add_form_row(self, layout: QGridLayout, row: int, label: str, widget: QWidget, column: int = 0, span: int = 1) -> None:
        label_widget = self._label(label, "body")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label_widget, row, column)
        layout.addWidget(widget, row, column + 1, 1, span)

    def _apply_custom_style(self) -> None:
        app = QApplication.instance()
        if not app:
            return
        extra = """
            QWidget#card {
                background: rgba(255, 255, 255, 0.65);
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 8px;
            }
            QLabel#title { font-size: 24px; font-weight: 700; }
            QLabel#section { font-size: 15px; font-weight: 700; }
            QLabel#statusLabel { font-weight: 600; }
            QLabel#dirPath {
                color: #1976d2;
                font-size: 13px;
            }
            QLabel#dirPath:hover {
                text-decoration: underline;
            }
            QPushButton#primaryButton {
                background-color: #1976d2;
                color: #ffffff;
                border: 1px solid #1565c0;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: 500;
            }
            QPushButton#primaryButton:hover {
                background-color: #1565c0;
            }
            QPushButton#primaryButton:pressed {
                background-color: #0d47a1;
            }
            QPushButton#primaryButton:disabled {
                background-color: #90caf9;
                border-color: #90caf9;
                color: #ffffff;
            }
            QTextEdit#logView {
                background: #f0f4ff;
                color: #2c3e6b;
                border: 0;
                border-radius: 6px;
                font-family: Menlo, Consolas, monospace;
                font-size: 12px;
            }
            """
        app.setStyleSheet(app.styleSheet() + extra)

    def _set_busy_state(self, busy: bool, message: str) -> None:
        self.test_button.setEnabled(not busy)
        self.search_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)
        if busy:
            self.download_button.setEnabled(False)
        else:
            self._update_download_button()
        self.connection_status.setText(message)

    def _set_idle_state(self) -> None:
        self._set_busy_state(False, self.connection_status.text())

    def _update_download_button(self) -> None:
        count = self._checked_count()
        if count > 0:
            self.download_button.setText(f"下载所选 ({count})")
        else:
            self.download_button.setText("下载所选")
        self.download_button.setEnabled(count > 0)

    def _on_select_all(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, CheckBox):
                widget.blockSignals(True)
                widget.setChecked(checked)
                widget.blockSignals(False)
        self._update_download_button()

    def _checked_rows(self) -> list[int]:
        rows = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, CheckBox) and widget.isChecked():
                rows.append(row)
        return rows

    def _checked_count(self) -> int:
        return len(self._checked_rows())

    def _load_settings(self) -> None:
        self.host_input.setText(self._settings.value("connection/host", ""))
        self.port_input.setValue(int(self._settings.value("connection/port", 80)))
        self.rtsp_port_input.setValue(int(self._settings.value("connection/rtsp_port", 554)))
        self.user_input.setText(self._settings.value("connection/username", "admin"))
        self.password_input.setText(self._settings.value("connection/password", ""))
        self.https_check.setChecked(self._settings.value("connection/https", False, type=bool))
        saved_dir = self._settings.value("output_dir", "")
        if saved_dir:
            self._output_dir = Path(saved_dir)
            self.output_display.setText(str(self._output_dir))

    def _save_connection_settings(self) -> None:
        self._settings.setValue("connection/host", self.host_input.text().strip())
        self._settings.setValue("connection/port", self.port_input.value())
        self._settings.setValue("connection/rtsp_port", self.rtsp_port_input.value())
        self._settings.setValue("connection/username", self.user_input.text().strip())
        self._settings.setValue("connection/password", self.password_input.text())
        self._settings.setValue("connection/https", self.https_check.isChecked())
        self._settings.setValue("output_dir", str(self._output_dir))

    def _on_start_date_picked(self, dt: QDateTime) -> None:
        if dt.date() != self._prev_start_date:
            self.start_input.blockSignals(True)
            self.start_input.setTime(QDateTime(dt.date()).time())
            self.start_input.blockSignals(False)
        self._prev_start_date = self.start_input.date()

    def _on_end_date_picked(self, dt: QDateTime) -> None:
        if dt.date() != self._prev_end_date:
            self.end_input.blockSignals(True)
            t = QDateTime(dt.date()).addSecs(86399).time()
            self.end_input.setTime(t)
            self.end_input.blockSignals(False)
        self._prev_end_date = self.end_input.date()

    def _connection(self) -> NvrConnection:
        host = self.host_input.text().strip()
        if not host:
            raise ValueError("请填写 NVR 主机地址")
        return NvrConnection(
            host=host,
            port=int(self.port_input.value()),
            username=self.user_input.text().strip(),
            password=self.password_input.text(),
            use_https=self.https_check.isChecked(),
            rtsp_port=int(self.rtsp_port_input.value()),
        )

    def _query(self) -> RecordingQuery:
        channel = self.channel_input.currentData()
        if channel is None:
            raise ValueError("请先连接设备获取通道列表")
        start = self.start_input.dateTime().toPython()
        end = self.end_input.dateTime().toPython()
        if end <= start:
            raise ValueError("结束时间必须晚于开始时间")
        return RecordingQuery(
            track_id=channel.track_id,
            start_time=start,
            end_time=end,
        )

    def _pick_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", str(self._output_dir))
        if directory:
            self._output_dir = Path(directory)
            self.output_display.setText(str(self._output_dir))
            self._settings.setValue("output_dir", str(self._output_dir))

    def _find_player(self) -> str | None:
        candidates = ["vlc", "ffplay", "mpv"]
        for name in candidates:
            path = shutil.which(name)
            if path:
                return path
        if sys.platform == "darwin":
            for app_path in (
                "/Applications/VLC.app/Contents/MacOS/VLC",
                "/Applications/IINA.app/Contents/MacOS/iina-cli",
            ):
                if Path(app_path).exists():
                    return app_path
        return None

    def _preview_channel(self) -> None:
        channel = self.channel_input.currentData()
        if channel is None:
            self._log("请先连接设备并选择通道")
            return
        try:
            connection = self._connection()
        except ValueError as exc:
            self._log(str(exc))
            return

        from .isapi import HikvisionClient
        client = HikvisionClient(connection)
        rtsp_url = client.build_rtsp_url(channel.id)

        player = self._find_player()
        if not player:
            self._log("未找到播放器，请安装 VLC、ffplay 或 mpv")
            return

        try:
            subprocess.Popen([player, rtsp_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log(f"正在打开预览：{channel.display_name} -> {player}")
        except OSError as exc:
            self._log(f"启动播放器失败：{exc}")

    def _test_connection(self) -> None:
        try:
            connection = self._connection()
        except ValueError as exc:
            self._log(str(exc))
            return
        from .workers import channels_worker, connection_test_worker
        conn_worker = connection_test_worker(connection)
        conn_worker.signals.started.connect(lambda: self._set_busy_state(True, "正在测试连接..."))
        conn_worker.signals.result.connect(self._on_connection_ok)
        conn_worker.signals.error.connect(self._on_task_error)
        self.thread_pool.start(conn_worker)

        ch_worker = channels_worker(connection)
        ch_worker.signals.result.connect(self._on_channels_loaded)
        ch_worker.signals.error.connect(lambda _: None)
        ch_worker.signals.finished.connect(self._set_idle_state)
        self.thread_pool.start(ch_worker)

    def _search_recordings(self) -> None:
        try:
            connection = self._connection()
            query = self._query()
        except ValueError as exc:
            self._log(str(exc))
            return
        from .workers import search_worker
        worker = search_worker(connection, query)
        worker.signals.started.connect(lambda: self._set_busy_state(True, "正在检索录像..."))
        worker.signals.result.connect(self._on_search_result)
        worker.signals.error.connect(self._on_task_error)
        worker.signals.finished.connect(self._set_idle_state)
        self.thread_pool.start(worker)

    def _download_selected(self) -> None:
        rows = sorted(self._checked_rows())
        if not rows:
            self._log("请先勾选录像片段")
            return
        try:
            connection = self._connection()
        except ValueError as exc:
            self._log(str(exc))
            return
        directory = self._output_dir.expanduser()

        tasks: list[DownloadTask] = []
        for row in rows:
            if row < 0 or row >= len(self.recordings):
                continue
            recording = self.recordings[row]
            task = DownloadTask(
                id=uuid.uuid4().hex[:8],
                recording=recording,
                directory=directory,
                connection=connection,
            )
            tasks.append(task)
            self._add_task_widget(task)

        self.download_manager.enqueue(tasks)
        self._log(f"已添加 {len(tasks)} 个下载任务（最多 {DownloadManager.MAX_CONCURRENT} 个并发）")
        self.download_button.setEnabled(False)

    def _cancel_all_downloads(self) -> None:
        self.download_manager.cancel_all()
        self._log("已取消所有下载任务")

    def _add_task_widget(self, task: DownloadTask) -> None:
        item = DownloadTaskItem(task)
        item.cancel_requested.connect(self.download_manager.cancel)
        count = self.task_list_layout.count()
        self.task_list_layout.insertWidget(count - 1, item)
        self._task_widgets[task.id] = item

    def _on_connection_ok(self, result: object) -> None:
        self.connection_status.setText("连接成功")
        self._log(f"连接成功：{result}")
        self._save_connection_settings()

    def _on_channels_loaded(self, result: object) -> None:
        channels = list(result) if isinstance(result, list) else []
        self._channels = [ch for ch in channels if isinstance(ch, ChannelInfo)]
        self.channel_input.blockSignals(True)
        self.channel_input.clear()
        if not self._channels:
            self.channel_input.addItem("未获取到通道", None)
            self._log("未获取到通道列表，请手动输入通道号")
        else:
            for ch in self._channels:
                self.channel_input.addItem(ch.display_name, ch)
            self._log(f"已加载 {len(self._channels)} 个通道")
        self.channel_input.blockSignals(False)

    def _on_search_result(self, result: object) -> None:
        self.recordings = list(result) if isinstance(result, list) else []
        self.table.setRowCount(0)
        self._select_all_check.setChecked(False)
        for recording in self.recordings:
            self._append_recording(recording)
        self.download_button.setEnabled(False)
        self._log(f"检索完成：找到 {len(self.recordings)} 条录像")

    def _append_recording(self, recording: RecordingItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = CheckBox()
        check.stateChanged.connect(self._update_download_button)
        self.table.setCellWidget(row, 0, check)
        values = [
            recording.track_id,
            recording.start_time,
            recording.end_time,
            recording.display_size,
            recording.playback_uri,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, column + 1, item)

    def _on_task_started(self, task_id: str) -> None:
        widget = self._task_widgets.get(task_id)
        if widget:
            widget.set_status(DownloadStatus.DOWNLOADING)

    def _on_task_progress(self, task_id: str, written: int, total: int) -> None:
        widget = self._task_widgets.get(task_id)
        if widget:
            widget.update_progress(written, total)

    def _on_task_completed(self, task_id: str, result: object) -> None:
        widget = self._task_widgets.get(task_id)
        if widget:
            widget.set_status(DownloadStatus.COMPLETED)
        self._log(f"下载完成：{result}")

    def _on_task_failed(self, task_id: str, error: str) -> None:
        widget = self._task_widgets.get(task_id)
        if widget:
            widget.set_status(DownloadStatus.FAILED, error)
        self._log(f"下载失败：{error}")

    def _on_task_cancelled(self, task_id: str) -> None:
        widget = self._task_widgets.get(task_id)
        if widget:
            widget.set_status(DownloadStatus.CANCELLED)
        self._log("下载已取消")

    def _on_all_downloads_done(self) -> None:
        self._update_download_button()
        self._log("所有下载任务已处理完毕")

    def _on_task_error(self, message: str) -> None:
        self.connection_status.setText("任务失败")
        self._log(f"错误：{message}")

    def _log(self, message: str) -> None:
        self.log_view.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def main() -> None:
    import os
    os.environ["QT_STYLE_OVERRIDE"] = "Fusion"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Force light palette (macOS dark mode overrides Qt defaults)
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1a1a2e"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f5f7ff"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1a1a2e"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1a1a2e"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#1976d2"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)

    try:
        from qt_material import apply_stylesheet
        apply_stylesheet(app, theme="light_cyan_500.xml", invert_secondary=False)
    except ImportError:
        pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
