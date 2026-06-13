from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest

import requests

GITHUB_VERSION_URL = "https://raw.githubusercontent.com/zuoa/hik-video-downloader/main/VERSION"
GITHUB_RELEASES_URL = "https://github.com/zuoa/hik-video-downloader/releases"


@dataclass(frozen=True)
class UpdateInfo:
    latest_version: str | None
    has_update: bool
    error: str = ""


def fetch_latest_version(timeout: float = 5.0) -> str | None:
    try:
        resp = requests.get(GITHUB_VERSION_URL, timeout=timeout)
        resp.raise_for_status()
        text = (resp.text or "").strip()
        return text or None
    except Exception:
        return None


def is_newer(current: str, latest: str) -> bool:
    cur = [int(x) for x in re.findall(r"\d+", current or "")]
    lat = [int(x) for x in re.findall(r"\d+", latest or "")]
    if not lat:
        return False
    for c, l in zip_longest(cur, lat, fillvalue=0):
        if l > c:
            return True
        if l < c:
            return False
    return False


def check_for_update(current_version: str) -> UpdateInfo:
    latest = fetch_latest_version()
    if latest is None:
        return UpdateInfo(latest_version=None, has_update=False, error="fetch_failed")
    return UpdateInfo(latest_version=latest, has_update=is_newer(current_version, latest))
