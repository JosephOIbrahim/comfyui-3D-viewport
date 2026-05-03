import pytest

from review_harness.budget import Budget, BudgetExceeded, estimate_cost_usd


def test_budget_charges_and_blocks():
    b = Budget(cap_usd=1.0)
    b.charge(0.5)
    b.charge(0.4)
    assert pytest.approx(b.remaining(), 0.001) == 0.1
    with pytest.raises(BudgetExceeded):
        b.charge(0.2)


def test_can_spend():
    b = Budget(cap_usd=1.0)
    b.charge(0.7)
    assert b.can_spend(0.3)
    assert not b.can_spend(0.4)


def test_estimate_cost_uses_cache_pricing():
    cheap = estimate_cost_usd(input_tokens=100_000, cache_read_tokens=100_000, output_tokens=0)
    full = estimate_cost_usd(input_tokens=100_000, cache_read_tokens=0, output_tokens=0)
    assert cheap < full, "cache reads must be cheaper than fresh input"
