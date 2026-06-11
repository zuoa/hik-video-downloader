# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A PySide6 desktop application for searching and downloading Hikvision NVR recordings via the ISAPI protocol. Chinese-language UI (海康 NVR 录像下载).

## Commands

```bash
# Install (editable)
pip install -e .

# Run
python -m hik_video_download
# or after install:
hik-video-download

# Run without installing the package
pip install -r requirements.txt
PYTHONPATH=src python -m hik_video_download

# Tests
pytest
pytest tests/test_isapi.py -k test_build_search_xml  # single test
```

Dev dependencies: `pip install -e ".[dev]"`

## Architecture

The package lives in `src/hik_video_download/` with these layers:

- **`__main__.py`** — Entry point, calls `app.main()`
- **`app.py`** — `MainWindow` (QMainWindow) builds the full GUI: connection form, recording table, progress bar, log panel. All button handlers create a `TaskWorker` and submit it to `QThreadPool`
- **`ui_compat.py`** — Optional import of `PySide6-Fluent-Widgets`. Falls back to plain Qt widgets with `HAS_FLUENT=False`. The app remains fully functional without the Fluent package
- **`workers.py`** — `TaskWorker` (QRunnable) wraps a callable and emits Qt signals (`started`, `result`, `error`, `finished`, `progress`). Factory functions: `connection_test_worker`, `search_worker`, `download_worker`
- **`isapi.py`** — `HikvisionClient` handles all ISAPI communication over HTTP(S). `AutoAuth` tries Digest auth first, falls back to Basic on 401. XML is used for both request bodies and response parsing. Download tries GET first, falls back to PUT on error
- **`models.py`** — Frozen dataclasses: `NvrConnection`, `RecordingQuery`, `RecordingItem`, `DownloadTarget`

### Key ISAPI Endpoints

- `GET /ISAPI/System/deviceInfo` — Connection test
- `POST /ISAPI/ContentMgmt/search` — Search recordings (XML body with track ID, time range)
- `GET/PUT /ISAPI/ContentMgmt/download` — Download recording (XML body with `playbackURI`)

Downloaded files are `.ps` format (Hikvision raw). Convert to MP4 with FFmpeg if needed.

## Code Conventions

- Python 3.10+, `from __future__ import annotations` in all files
- All data models are frozen dataclasses
- Network operations must run in `TaskWorker` (never on the Qt main thread)
- XML parsing uses `xml.etree.ElementTree` with namespace-agnostic local-name matching (`_local_name`, `_iter_by_local_name`)
- UI text is in Chinese
