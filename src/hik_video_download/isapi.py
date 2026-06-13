from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlparse

import requests
from requests.auth import AuthBase, HTTPBasicAuth, HTTPDigestAuth

from .models import ChannelInfo, NvrConnection, RecordingItem, RecordingQuery

ProgressCallback = Callable[[int, int | None], None]


class HikvisionError(RuntimeError):
    """Raised when a Hikvision ISAPI request fails."""


class AutoAuth(AuthBase):
    """Try Digest auth first, then fall back to Basic auth on 401 responses."""

    def __init__(self, username: str, password: str) -> None:
        self._digest = HTTPDigestAuth(username, password)
        self._basic = HTTPBasicAuth(username, password)

    def __call__(self, request):
        request = self._digest(request)
        request.register_hook("response", self._handle_401)
        return request

    def _handle_401(self, response, **kwargs):
        if response.status_code != 401 or "basic" not in response.headers.get("WWW-Authenticate", "").lower():
            return response
        response.content
        response.close()
        request = response.request.copy()
        request.headers.pop("Authorization", None)
        request = self._basic(request)
        return response.connection.send(request, **kwargs)


class HikvisionClient:
    def __init__(self, connection: NvrConnection) -> None:
        self.connection = connection
        self.session = requests.Session()
        self.session.auth = AutoAuth(connection.username, connection.password)
        self.session.verify = connection.verify_tls
        self.session.headers.update({"User-Agent": "hik-video-download/0.1"})

    def test_connection(self) -> str:
        response = self._request("GET", "/ISAPI/System/deviceInfo")
        root = _parse_xml(response.text)
        name = _find_text(root, "deviceName") or _find_text(root, "model") or "Hikvision NVR"
        model = _find_text(root, "model")
        serial = _find_text(root, "serialNumber")
        parts = [name]
        if model and model != name:
            parts.append(model)
        if serial:
            parts.append(serial)
        return " / ".join(parts)

    def list_channels(self) -> list[ChannelInfo]:
        for path in (
            "/ISAPI/ContentMgmt/InputChannels/channels",
            "/ISAPI/System/Video/inputs/channels",
            "/ISAPI/ContentMgmt/Streaming/channels",
        ):
            try:
                response = self._request("GET", path)
            except HikvisionError:
                continue
            channels = _parse_channels(response.text)
            if channels:
                return channels
        return []

    def search_recordings(self, query: RecordingQuery) -> list[RecordingItem]:
        xml_body = _build_search_xml(query)
        response = self._request(
            "POST",
            "/ISAPI/ContentMgmt/search",
            data=xml_body,
            headers={"Content-Type": "application/xml"},
        )
        return parse_search_result(response.text)

    def download_recording(
        self,
        recording: RecordingItem,
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / _filename_from_recording(recording)
        xml_body = _build_download_xml(recording.playback_uri)
        response = self._download_request("GET", xml_body)
        if response.status_code >= 400:
            response.close()
            response = self._download_request("PUT", xml_body)
        self._raise_for_response(response)

        total = _content_length(response)
        written = 0
        with target.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                file.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
        if progress:
            progress(written, total)
        return target

    def _download_request(self, method: str, xml_body: str) -> requests.Response:
        return self.session.request(
            method,
            self._url("/ISAPI/ContentMgmt/download"),
            data=xml_body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
            timeout=self.connection.timeout,
            stream=True,
        )

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self.session.request(
            method,
            self._url(path),
            timeout=self.connection.timeout,
            **kwargs,
        )
        self._raise_for_response(response)
        return response

    def _raise_for_response(self, response: requests.Response) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:500] if response.text else response.reason
        raise HikvisionError(f"HTTP {response.status_code}: {detail}")

    def _url(self, path: str) -> str:
        return f"{self.connection.base_url}{path}"


def parse_search_result(xml_text: str) -> list[RecordingItem]:
    root = _parse_xml(xml_text)
    items: list[RecordingItem] = []
    for element in _iter_by_local_name(root, "searchMatchItem"):
        playback_uri = _find_text(element, "playbackURI")
        if not playback_uri:
            continue
        track_id = _find_text(element, "trackID") or _track_id_from_uri(playback_uri) or "-"
        start_time = _find_text(element, "startTime") or "-"
        end_time = _find_text(element, "endTime") or "-"
        source = _find_text(element, "sourceID")
        items.append(
            RecordingItem(
                track_id=track_id,
                start_time=start_time,
                end_time=end_time,
                playback_uri=playback_uri,
                size=_size_from_uri(playback_uri),
                source=source,
            )
        )
    return items


def _build_search_xml(query: RecordingQuery) -> str:
    start = _to_utc_isapi(query.start_time)
    end = _to_utc_isapi(query.end_time)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<CMSearchDescription>
  <searchID>{uuid.uuid4()}</searchID>
  <trackIDList>
    <trackID>{query.track_id}</trackID>
  </trackIDList>
  <timeSpanList>
    <timeSpan>
      <startTime>{start}</startTime>
      <endTime>{end}</endTime>
    </timeSpan>
  </timeSpanList>
  <maxResults>{query.max_results}</maxResults>
  <searchResultPostion>{query.position}</searchResultPostion>
  <metadataList>
    <metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor>
  </metadataList>
</CMSearchDescription>"""


def _build_download_xml(playback_uri: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<downloadRequest version="1.0">
  <playbackURI>{_xml_escape(playback_uri)}</playbackURI>
</downloadRequest>"""


def _parse_xml(xml_text: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise HikvisionError(f"Invalid XML response: {exc}") from exc


def _find_text(element: ET.Element, local_name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == local_name and child.text:
            return child.text.strip()
    return None


def _iter_by_local_name(element: ET.Element, local_name: str) -> Iterable[ET.Element]:
    for child in element.iter():
        if _local_name(child.tag) == local_name:
            yield child


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_utc_isapi(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filename_from_recording(recording: RecordingItem) -> str:
    query = parse_qs(urlparse(recording.playback_uri).query)
    name = query.get("name", [""])[0] or f"track_{recording.track_id}_{recording.start_time}_{recording.end_time}"
    name = re.sub(r"[^0-9A-Za-z_.-]+", "_", name).strip("._") or "recording"
    if Path(name).suffix:
        return name
    return f"{name}.ps"


def _track_id_from_uri(playback_uri: str) -> str | None:
    match = re.search(r"/tracks/(\d+)", playback_uri)
    return match.group(1) if match else None


def _size_from_uri(playback_uri: str) -> int | None:
    value = parse_qs(urlparse(playback_uri).query).get("size", [""])[0]
    if not value:
        return None
    match = re.match(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _content_length(response: requests.Response) -> int | None:
    value = response.headers.get("Content-Length")
    return int(value) if value and value.isdigit() else None


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _parse_channels(xml_text: str) -> list[ChannelInfo]:
    root = _parse_xml(xml_text)
    channels: list[ChannelInfo] = []
    seen: set[int] = set()
    for elem in root.iter():
        local = _local_name(elem.tag)
        if local in ("InputChannel", "VideoInputChannel", "channel"):
            cid = _find_text(elem, "id")
            name = _find_text(elem, "name") or ""
            if cid:
                channels.append(ChannelInfo(id=int(cid), name=name))
        elif local == "StreamingChannel":
            cid = _find_text(elem, "id")
            name = _find_text(elem, "channelName") or _find_text(elem, "name") or ""
            if cid:
                channel_id = int(cid) // 100
                if channel_id not in seen:
                    seen.add(channel_id)
                    channels.append(ChannelInfo(id=channel_id, name=name))
    return channels

