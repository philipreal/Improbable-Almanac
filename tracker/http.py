"""Shared HTTP session with retries, plus an on-disk cache for data that never changes."""
import gzip
import hashlib
import json
import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import CACHE_DIR

log = logging.getLogger(__name__)

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers["User-Agent"] = "ImprobableAlmanac/1.0 (personal sports-oddity tracker)"
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


def get_json(url: str, params: dict | None = None, cache: bool = False, timeout: int = 30):
    """GET a JSON document. With cache=True the response is kept in .cache/ forever,
    which is only appropriate for finished games."""
    path = None
    if cache:
        key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        path = CACHE_DIR / "http" / key[:2] / f"{key}.json.gz"
        if path.exists():
            return json.loads(gzip.decompress(path.read_bytes()))
    resp = session().get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data).encode()))
    time.sleep(0.05)
    return data


def get_text(url: str, timeout: int = 30) -> str:
    resp = session().get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text
