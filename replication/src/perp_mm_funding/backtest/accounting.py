from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Account:
    cash: float = 0.0
    inventory: float = 0.0

    def buy_fill(self, price: float, size: float) -> None:
        self.cash -= price * size
        self.inventory += size

    def sell_fill(self, price: float, size: float) -> None:
        self.cash += price * size
        self.inventory -= size

    def apply_trade_cost(self, notional: float, rate: float) -> float:
        """Apply a proportional trading cost; a negative rate is a rebate."""

        payment = abs(float(notional)) * float(rate)
        self.cash -= payment
        return float(payment)

    def apply_funding(
        self,
        mid_price: float,
        funding_rate: float,
        accrual_fraction: float = 1.0,
    ) -> float:
        payment = self.inventory * mid_price * funding_rate * accrual_fraction
        self.cash -= payment
        return float(payment)

    def mark_to_market(self, mid_price: float) -> float:
        return float(self.cash + self.inventory * mid_price)
