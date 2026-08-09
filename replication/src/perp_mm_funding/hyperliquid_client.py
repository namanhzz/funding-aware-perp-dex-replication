from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from perp_mm_funding.time_utils import MS_PER_HOUR, interval_to_ms


INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidAPIError(RuntimeError):
    """Raised when Hyperliquid returns an unusable API response."""


@dataclass(slots=True)
class HyperliquidClient:
    base_url: str = INFO_URL
    timeout: float = 30.0
    max_retries: int = 3
    retry_sleep: float = 0.4
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> "HyperliquidClient":
        self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _post_info(self, payload: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                if self._client is None:
                    with httpx.Client(timeout=self.timeout) as client:
                        response = client.post(self.base_url, json=payload)
                else:
                    response = self._client.post(self.base_url, json=payload)
                if response.status_code >= 500:
                    raise HyperliquidAPIError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # httpx raises several transport/status subclasses.
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(self.retry_sleep * (2**attempt))
        raise HyperliquidAPIError(f"Hyperliquid info request failed: {last_error}") from last_error

    def funding_history(self, coin: str, start_ms: int, end_ms: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "type": "fundingHistory",
            "coin": coin.upper(),
            "startTime": int(start_ms),
        }
        if end_ms is not None:
            payload["endTime"] = int(end_ms)
        rows = self._post_info(payload)
        if not isinstance(rows, list):
            raise HyperliquidAPIError(f"Unexpected fundingHistory response: {rows!r}")
        return sorted(rows, key=lambda row: int(row["time"]))

    def candle_snapshot(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin.upper(),
                "interval": interval,
                "startTime": int(start_ms),
                "endTime": int(end_ms),
            },
        }
        rows = self._post_info(payload)
        if not isinstance(rows, list):
            raise HyperliquidAPIError(f"Unexpected candleSnapshot response: {rows!r}")
        return sorted(rows, key=lambda row: int(row["t"]))

    def paginate_funding_history(self, coin: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        rows_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        cursor = int(start_ms)
        final_ms = int(end_ms)

        while cursor <= final_ms:
            batch = self.funding_history(coin, cursor, final_ms)
            if not batch:
                break
            for row in batch:
                key = (str(row.get("coin", coin.upper())), int(row["time"]))
                rows_by_key[key] = row
            last_time = max(int(row["time"]) for row in batch)
            next_cursor = last_time + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 500:
                break

        return [rows_by_key[key] for key in sorted(rows_by_key, key=lambda item: item[1])]

    def paginate_candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        rows_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
        cursor = int(start_ms)
        final_ms = int(end_ms)
        step_ms = interval_to_ms(interval)

        while cursor <= final_ms:
            batch = self.candle_snapshot(coin, interval, cursor, final_ms)
            if not batch:
                break
            for row in batch:
                key = (str(row.get("s", coin.upper())), str(row.get("i", interval)), int(row["t"]))
                rows_by_key[key] = row
            last_time = max(int(row["t"]) for row in batch)
            next_cursor = last_time + step_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 500:
                break

        return [rows_by_key[key] for key in sorted(rows_by_key, key=lambda item: item[2])]
