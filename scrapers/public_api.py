"""HTTP client for the public, browser-independent gazette APIs."""
from __future__ import annotations

import json
import time
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MAX_ATTEMPTS = 4


def _retryable(error: Exception) -> bool:
    if isinstance(error, HTTPError):
        return error.code in (408, 425, 429) or 500 <= error.code < 600
    return isinstance(error, (TimeoutError, URLError, ConnectionError, IncompleteRead))


def _retry_delay(attempt: int) -> None:
    time.sleep(2 ** (attempt - 1))


def get_bytes(url: str, *, headers: dict | None = None, data: bytes | None = None) -> bytes:
    request = Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0", **(headers or {}),
    })
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            if attempt == MAX_ATTEMPTS or not _retryable(error):
                raise
            if isinstance(error, HTTPError):
                error.close()
            _retry_delay(attempt)
    raise RuntimeError("falha inesperada na requisição")


def get_json(url: str, *, headers: dict | None = None, data: bytes | None = None):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        content = get_bytes(url, headers=headers, data=data)
        try:
            return json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if attempt == MAX_ATTEMPTS:
                raise
            _retry_delay(attempt)
    raise RuntimeError("falha inesperada ao interpretar JSON")
