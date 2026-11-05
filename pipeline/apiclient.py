"""Client for the ad platform API. Owns paging and the retry rules."""

from __future__ import annotations

import os
import random
import re
import time

import httpx

TRANSIENT_STATUS = {429, 500, 502, 503, 504}
PAGE_SIZE = 1000
MAX_RETRY_AFTER = 120


class PermanentError(Exception):
    """Retrying won't help: bad key, bad request, unknown client."""


class RetriesExhausted(Exception):
    """Still failing after every attempt. Worth another run later."""


class AdsApi:
    def __init__(self, http: httpx.Client, api_key: str, *, max_attempts: int = 5,
                 base_delay: float = 8.0, sleep=time.sleep, rand=random.random):
        # 8 s doubling over 5 attempts waits 1 to 3 minutes in all, enough to
        # sit out a Render instance answering 503 while it wakes.
        self.http = http
        self.api_key = api_key
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.sleep = sleep
        self.rand = rand
        self.retries = 0

    @classmethod
    def from_env(cls) -> "AdsApi":
        url, key = os.environ.get("ADSAPI_URL"), os.environ.get("ADSAPI_KEY")
        if not url or not key:
            raise RuntimeError("ADSAPI_URL and ADSAPI_KEY must both be set")
        # A sleeping Render instance can hold the first request for about a
        # minute while it wakes, so the read timeout has to outlast that.
        return cls(httpx.Client(base_url=url, timeout=httpx.Timeout(90.0, connect=30.0)), key)

    def get_all(self, path: str, params: dict) -> list[dict]:
        rows, token = [], None
        while True:
            query = {"page_size": PAGE_SIZE, **params, **({"page_token": token} if token else {})}
            body = self._get(path, query)
            rows += body["data"]
            token = body["next_page_token"]
            if token is None:
                return rows

    def _get(self, path: str, query: dict) -> dict:
        problem = ""
        for attempt in range(1, self.max_attempts + 1):
            wait = None
            try:
                response = self.http.get(path, params=query, headers={"X-API-Key": self.api_key})
            except httpx.TransportError as e:
                problem = type(e).__name__
            else:
                if response.status_code == 200:
                    body = self._usable(response)
                    if body is not None:
                        return body
                    problem = "unusable body"
                else:
                    problem = f"HTTP {response.status_code}"
                    if response.status_code not in TRANSIENT_STATUS:
                        raise PermanentError(f"{path}: {problem}")
                    wait = response.headers.get("Retry-After")

            if attempt < self.max_attempts:
                self.retries += 1
                self.sleep(self._delay(attempt, wait))
        raise RetriesExhausted(f"{path}: {problem} after {self.max_attempts} attempts")

    @staticmethod
    def _usable(response: httpx.Response) -> dict | None:
        # A proxy error page can come back as a 200, so check before trusting it.
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) and {"data", "next_page_token"} <= body.keys() else None

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and re.fullmatch(r"[0-9]+", retry_after):
            return min(int(retry_after), MAX_RETRY_AFTER)
        # The jitter stops clients that failed together retrying together.
        return self.base_delay * 2 ** (attempt - 1) * (0.5 + self.rand())
