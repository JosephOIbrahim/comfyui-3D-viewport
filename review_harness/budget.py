"""Hard cost kill-switch.

Tracks cumulative USD spend across all expert calls. Aborts the run
if the budget is exceeded — fail loudly rather than silently downgrade.
"""
from __future__ import annotations


class BudgetExceeded(RuntimeError):
    pass


# Opus 4.x pricing (approximate, per 1M tokens). Used for cost estimation
# when a call doesn't return a USD figure directly.
OPUS_INPUT_PER_MTOK = 15.0
OPUS_INPUT_CACHED_PER_MTOK = 1.50
OPUS_OUTPUT_PER_MTOK = 75.0


def estimate_cost_usd(input_tokens: int, cache_read_tokens: int, output_tokens: int) -> float:
    fresh_input = max(0, input_tokens - cache_read_tokens)
    return (
        fresh_input / 1_000_000 * OPUS_INPUT_PER_MTOK
        + cache_read_tokens / 1_000_000 * OPUS_INPUT_CACHED_PER_MTOK
        + output_tokens / 1_000_000 * OPUS_OUTPUT_PER_MTOK
    )


class Budget:
    def __init__(self, cap_usd: float):
        self.cap_usd = cap_usd
        self.spent_usd = 0.0

    def charge(self, amount_usd: float) -> None:
        self.spent_usd += amount_usd
        if self.spent_usd > self.cap_usd:
            raise BudgetExceeded(
                f"budget cap ${self.cap_usd:.2f} exceeded; spent ${self.spent_usd:.2f}"
            )

    def remaining(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)

    def can_spend(self, amount_usd: float) -> bool:
        return (self.spent_usd + amount_usd) <= self.cap_usd
