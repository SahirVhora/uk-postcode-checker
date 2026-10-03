"""Cached HTTP access with retries.

Every response body is written to pipeline/cache/<source>/ together with a small
metadata file (URL, fetch time). In offline mode nothing touches the network: a
missing cache entry is an error, so an offline rebuild uses exactly the same bytes
as the last online run.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from . import CACHE_DIR
from .db import utc_now

log = logging.getLogger(__name__)

USER_AGENT = "uk-postcode-checker-area-pack/1.0 (+https://github.com/SahirVhora/uk-postcode-checker)"
RETRY_STATUSES = {429, 500, 502, 504}


class OfflineCacheMiss(RuntimeError):
    pass


class HTTPStatusError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url
        self.body = body


def cache_key(method: str, url: str, params=None, data=None, extra: str = "") -> str:
    payload = json.dumps([method, url, params, data, extra], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


class Fetcher:
    def __init__(self, source: str, offline: bool = False, refresh: bool = False,
                 cache_dir: Path = CACHE_DIR, session: requests.Session | None = None,
                 min_interval: float = 0.0, extra_retry: tuple[int, ...] = ()):
        self.source = source
        self.offline = offline
        self.refresh = refresh
        self.dir = cache_dir / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.min_interval = min_interval
        self.retry_statuses = RETRY_STATUSES | set(extra_retry)
        self._last_call = 0.0
        self.fetched_at: list[str] = []

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.dir / f"{key}.body", self.dir / f"{key}.meta.json"

    def request(self, method: str, url: str, *, params=None, data=None, headers=None,
                key_extra: str = "", timeout: int = 120, use_cache: bool = True,
                allowed_statuses: tuple[int, ...] = ()) -> bytes:
        key = cache_key(method, url, params, data, key_extra)
        body_path, meta_path = self._paths(key)
        if use_cache and body_path.exists() and meta_path.exists() and not (self.refresh and not self.offline):
            meta = json.loads(meta_path.read_text())
            self.fetched_at.append(meta["fetched_at"])
            if meta.get("status", 200) >= 400:
                raise HTTPStatusError(meta["status"], url)
            return body_path.read_bytes()
        if self.offline:
            raise OfflineCacheMiss(
                f"[{self.source}] offline mode but no cached response for {method} {url} params={params}. "
                "Run once without --offline to populate the cache."
            )
        body, status = self._live(method, url, params=params, data=data, headers=headers,
                                  timeout=timeout, allowed_statuses=allowed_statuses)
        fetched = utc_now()
        if use_cache:
            body_path.write_bytes(body)
            meta_path.write_text(json.dumps({"url": url, "method": method, "params": params,
                                             "fetched_at": fetched, "status": status}, default=str))
        self.fetched_at.append(fetched)
        if status >= 400:
            raise HTTPStatusError(status, url, body[:500].decode("utf-8", "replace"))
        return body

    def _live(self, method, url, *, params, data, headers, timeout, allowed_statuses):
        delay = 2.0
        for attempt in range(6):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = self.session.request(method, url, params=params, data=data,
                                            headers=headers, timeout=timeout)
            except requests.RequestException as exc:
                log.warning("[%s] %s on %s, retry %d", self.source, exc.__class__.__name__, url, attempt + 1)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in self.retry_statuses and resp.status_code not in allowed_statuses:
                retry_after = resp.headers.get("Retry-After")
                sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("[%s] HTTP %d on %s, sleeping %.0fs", self.source, resp.status_code, url, sleep_for)
                time.sleep(sleep_for)
                delay *= 2
                continue
            if resp.status_code >= 400 and resp.status_code not in allowed_statuses:
                raise HTTPStatusError(resp.status_code, url, resp.text[:500])
            return resp.content, resp.status_code
        raise RuntimeError(f"[{self.source}] giving up on {url} after repeated failures")

    def blob(self, name: str, producer, url: str | None = None) -> bytes:
        """Cache the result of a multi-step download under a stable name.

        Used where the live flow involves one-time tokens (form posts), so the
        request itself cannot be the cache key. producer() runs only online.
        """
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        body_path, meta_path = self.dir / f"blob-{safe}.body", self.dir / f"blob-{safe}.meta.json"
        if body_path.exists() and meta_path.exists() and not (self.refresh and not self.offline):
            self.fetched_at.append(json.loads(meta_path.read_text())["fetched_at"])
            return body_path.read_bytes()
        if self.offline:
            raise OfflineCacheMiss(f"[{self.source}] offline mode but no cached download '{name}'.")
        body = producer()
        fetched = utc_now()
        body_path.write_bytes(body)
        meta_path.write_text(json.dumps({"name": name, "url": url, "fetched_at": fetched}))
        self.fetched_at.append(fetched)
        return body

    def blob_meta(self, name: str) -> dict | None:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        meta_path = self.dir / f"blob-{safe}.meta.json"
        return json.loads(meta_path.read_text()) if meta_path.exists() else None

    def invalidate(self, method: str, url: str, params=None, data=None, key_extra: str = ""):
        """Drop a cached response (used when a 200 response turns out to be an API error)."""
        if self.offline:
            return
        for p in self._paths(cache_key(method, url, params, data, key_extra)):
            p.unlink(missing_ok=True)

    def get(self, url, **kw) -> bytes:
        return self.request("GET", url, **kw)

    def get_json(self, url, **kw):
        return json.loads(self.get(url, **kw))

    def get_text(self, url, encoding="utf-8", **kw) -> str:
        return self.get(url, **kw).decode(encoding, "replace")

    def post(self, url, **kw) -> bytes:
        return self.request("POST", url, **kw)

    def latest_fetch(self) -> str | None:
        return max(self.fetched_at) if self.fetched_at else None
