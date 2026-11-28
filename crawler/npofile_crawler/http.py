from __future__ import annotations

import time

import httpx

USER_AGENT = "NPOFile-crawler/0.1 (public-data transparency project)"


class PoliteClient:
    """每個請求之間至少間隔 min_interval 秒；網路錯誤或 5xx 最多重試 retries 次。"""

    def __init__(self, min_interval: float = 1.0, retries: int = 2, timeout: float = 30.0):
        self.min_interval = min_interval
        self.retries = retries
        self._last = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
        )

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self._client.request(method, url, **kwargs)
                if resp.status_code < 500:
                    resp.raise_for_status()
                    return resp
                error: Exception = httpx.HTTPStatusError(
                    f"server error {resp.status_code}", request=resp.request, response=resp
                )
            except httpx.TransportError as exc:
                error = exc
            attempt += 1
            if attempt > self.retries:
                raise error
            time.sleep(self.min_interval * 2**attempt)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
