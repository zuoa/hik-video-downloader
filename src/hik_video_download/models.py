from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
import threading


class DownloadStatus(Enum):
    QUEUED = auto()
    DOWNLOADING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class NvrConnection:
    host: str
    port: int
    username: str
    password: str
    use_https: bool = False
    verify_tls: bool = False
    timeout: float = 12.0
    rtsp_port: int = 554

    @property
    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        host = self.host.strip().removeprefix("http://").removeprefix("https://").strip("/")
        return f"{scheme}://{host}:{self.port}"


@dataclass(frozen=True)
class ChannelInfo:
    id: int
    name: str

    @property
    def display_name(self) -> str:
        return f"通道 {self.id} - {self.name}" if self.name else f"通道 {self.id}"

    @property
    def track_id(self) -> int:
        """ISAPI trackID: channelId * 100 + streamType (1=main)."""
        return self.id * 100 + 1


@dataclass(frozen=True)
class RecordingQuery:
    track_id: int
    start_time: datetime
    end_time: datetime
    max_results: int = 64
    position: int = 0


@dataclass(frozen=True)
class RecordingItem:
    track_id: str
    start_time: str
    end_time: str
    playback_uri: str
    size: int | None = None
    source: str | None = None

    @property
    def display_size(self) -> str:
        if not self.size:
            return "-"
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{self.size} B"


@dataclass(frozen=True)
class DownloadTarget:
    recording: RecordingItem
    directory: Path


@dataclass
class DownloadTask:
    id: str
    recording: RecordingItem
    directory: Path
    connection: NvrConnection
    status: DownloadStatus = DownloadStatus.QUEUED
    progress_percent: int = 0
    error_message: str = ""
    result_path: Path | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

