from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from perp_mm_funding.time_utils import interval_to_ms


BINANCE_FAPI_URL = "https://fapi.binance.com"


class BinanceAPIError(RuntimeError):
    """Raised when Binance returns an unusable response."""


@dataclass(slots=True)
class BinanceFuturesClient:
    base_url: str = BINANCE_FAPI_URL
    timeout: float = 30.0
    max_retries: int = 4
    retry_sleep: float = 0.5
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> "BinanceFuturesClient":
        self._client = httpx.Client(timeout=self.timeout)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries):
            try:
                client = self._client
                if client is None:
                    with httpx.Client(timeout=self.timeout) as temp_client:
                        response = temp_client.get(url, params=params)
                else:
                    response = client.get(url, params=params)
                if response.status_code in {418, 429} or response.status_code >= 500:
                    raise BinanceAPIError(f"HTTP {response.status_code}: {response.text[:300]}")
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(self.retry_sleep * (2**attempt))
        raise BinanceAPIError(f"Binance request failed: {last_error}") from last_error

    def mark_price_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
        limit: int = 1500,
    ) -> list[list[Any]]:
        rows = self._get(
            "/fapi/v1/markPriceKlines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": int(start_ms),
                "endTime": int(end_ms),
                "limit": min(int(limit), 1500),
            },
        )
        if not isinstance(rows, list):
            raise BinanceAPIError(f"Unexpected markPriceKlines response: {rows!r}")
        return rows

    def paginate_mark_price_klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
        rows_by_time: dict[int, list[Any]] = {}
        cursor = int(start_ms)
        final_ms = int(end_ms)
        step_ms = interval_to_ms(interval)
        while cursor <= final_ms:
            batch = self.mark_price_klines(symbol, interval, cursor, final_ms)
            if not batch:
                break
            for row in batch:
                rows_by_time[int(row[0])] = row
            last_time = max(int(row[0]) for row in batch)
            next_cursor = last_time + step_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 1500:
                break
            time.sleep(0.03)
        return [rows_by_time[key] for key in sorted(rows_by_time)]

