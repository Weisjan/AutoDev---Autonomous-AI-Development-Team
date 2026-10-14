from decimal import Decimal

import pytest

from autodev.budget import ApiBudgetTracker, BudgetExceededError


def test_budget_tracker_blocks_projected_overspend() -> None:
    budget = ApiBudgetTracker(
        budget_usd=Decimal("0.10"),
        estimated_cost_per_model_call_usd=Decimal("0.06"),
    )

    budget.reserve_call("first")
    with pytest.raises(BudgetExceededError):
        budget.reserve_call("second")
