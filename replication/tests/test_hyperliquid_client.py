from perp_mm_funding.hyperliquid_client import HyperliquidClient


class FakeFundingClient(HyperliquidClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def funding_history(self, coin, start_ms, end_ms=None):
        self.calls.append((coin, start_ms, end_ms))
        if start_ms <= 10:
            return [{"coin": "ETH", "time": i, "fundingRate": "0"} for i in range(1, 501)]
        if start_ms <= 501:
            return [{"coin": "ETH", "time": 501, "fundingRate": "0"}]
        return []


def test_paginate_funding_history_dedupes_and_advances():
    client = FakeFundingClient()
    rows = client.paginate_funding_history("ETH", 1, 1_000)
    assert len(rows) == 501
    assert rows[-1]["time"] == 501
    assert client.calls[1][1] == 501

