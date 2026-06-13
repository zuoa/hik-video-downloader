from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .isapi import HikvisionClient
from .models import ChannelInfo, DownloadTask, NvrConnection, RecordingQuery

T = TypeVar("T")


class DownloadCancelled(Exception):
    """Raised when the user cancels a download."""


class WorkerSignals(QObject):
    started = Signal()
    progress = Signal(int, int)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class TaskWorker(QRunnable):
    def __init__(self, job: Callable[[WorkerSignals], T], task_id: str = "") -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.task_id = task_id
        self._job = job

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self._job(self.signals)
        except Exception as exc:  # noqa: BLE001 - show operational errors in the UI
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


def connection_test_worker(connection: NvrConnection) -> TaskWorker:
    return TaskWorker(lambda _signals: HikvisionClient(connection).test_connection())


def search_worker(connection: NvrConnection, query: RecordingQuery) -> TaskWorker:
    return TaskWorker(lambda _signals: HikvisionClient(connection).search_recordings(query))


def channels_worker(connection: NvrConnection) -> TaskWorker:
    return TaskWorker(lambda _signals: HikvisionClient(connection).list_channels())


def download_worker(task: DownloadTask) -> TaskWorker:
    def job(signals: WorkerSignals) -> Path:
        def progress(written: int, total: int | None) -> None:
            if task.cancel_event.is_set():
                raise DownloadCancelled()
            signals.progress.emit(written, total or 0)

        return HikvisionClient(task.connection).download_recording(
            task.recording, task.directory, progress,
        )

    return TaskWorker(job, task_id=task.id)


def check_update_worker(current_version: str) -> TaskWorker:
    from .updater import check_for_update
    return TaskWorker(lambda _signals: check_for_update(current_version))

