import pytest

from pipeline.http import Fetcher, HTTPStatusError, OfflineCacheMiss


def test_offline_cache_miss_is_an_error(tmp_path):
    f = Fetcher("demo", offline=True, cache_dir=tmp_path)
    with pytest.raises(OfflineCacheMiss):
        f.get("https://example.test/data.csv")


def test_blob_is_cached_and_reused_offline(tmp_path):
    calls = []
    online = Fetcher("demo", cache_dir=tmp_path)
    assert online.blob("file.zip", lambda: calls.append(1) or b"PK-data") == b"PK-data"
    offline = Fetcher("demo", offline=True, cache_dir=tmp_path)
    assert offline.blob("file.zip", lambda: calls.append(1) or b"other") == b"PK-data"
    assert calls == [1]
    assert offline.latest_fetch()


def test_cached_error_status_replays_offline(tmp_path):
    import json
    f = Fetcher("demo", cache_dir=tmp_path)
    body, meta = f._paths(__import__("pipeline.http", fromlist=["cache_key"]).cache_key("GET", "https://x.test/a", None, None, ""))
    body.write_bytes(b"too many")
    meta.write_text(json.dumps({"url": "https://x.test/a", "fetched_at": "2026-01-01T00:00:00+00:00", "status": 503}))
    with pytest.raises(HTTPStatusError) as exc:
        Fetcher("demo", offline=True, cache_dir=tmp_path).get("https://x.test/a")
    assert exc.value.status == 503
