from datetime import datetime, timezone

from hik_video_download.isapi import _build_search_xml, parse_search_result
from hik_video_download.models import RecordingQuery


def test_build_search_xml_uses_track_and_utc_time() -> None:
    query = RecordingQuery(
        track_id=101,
        start_time=datetime(2026, 1, 14, 12, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 14, 12, 5, tzinfo=timezone.utc),
    )

    xml = _build_search_xml(query)

    assert "<trackID>101</trackID>" in xml
    assert "<startTime>2026-01-14T12:00:00Z</startTime>" in xml
    assert "<endTime>2026-01-14T12:05:00Z</endTime>" in xml
    assert "<searchResultPostion>0</searchResultPostion>" in xml


def test_parse_search_result_extracts_recordings_with_namespace() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <CMSearchResult xmlns="http://www.isapi.org/ver20/XMLSchema">
      <searchMatchList>
        <searchMatchItem>
          <trackID>101</trackID>
          <timeSpan>
            <startTime>2026-01-14T12:00:00Z</startTime>
            <endTime>2026-01-14T12:05:00Z</endTime>
          </timeSpan>
          <mediaSegmentDescriptor>
            <playbackURI>rtsp://192.168.1.64/Streaming/tracks/101?starttime=20260114T120000Z&amp;endtime=20260114T120500Z&amp;name=ch01_clip&amp;size=1048576</playbackURI>
          </mediaSegmentDescriptor>
        </searchMatchItem>
      </searchMatchList>
    </CMSearchResult>
    """

    items = parse_search_result(xml)

    assert len(items) == 1
    assert items[0].track_id == "101"
    assert items[0].start_time == "2026-01-14T12:00:00Z"
    assert items[0].end_time == "2026-01-14T12:05:00Z"
    assert items[0].size == 1048576
    assert items[0].playback_uri.startswith("rtsp://192.168.1.64/Streaming/tracks/101")

