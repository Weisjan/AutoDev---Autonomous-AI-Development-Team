from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class BudgetExceededError(RuntimeError):
    """Raised before a model call would exceed the configured API budget."""


@dataclass
class ApiBudgetTracker:
    budget_usd: Decimal
    estimated_cost_per_model_call_usd: Decimal
    calls_reserved: int = 0

    def reserve_call(self, purpose: str) -> None:
        projected = (self.calls_reserved + 1) * self.estimated_cost_per_model_call_usd
        if projected > self.budget_usd:
            raise BudgetExceededError(
                f"API budget exceeded before {purpose}: "
                f"projected {projected} USD > budget {self.budget_usd} USD"
            )
        self.calls_reserved += 1
