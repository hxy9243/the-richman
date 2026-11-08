"""Explicit, simplified plan-permitted 401(k) participant-loan amortization.

This module is not a qualification determination. Caller must confirm plan
permission, eligible vested balance, aggregation with other employer plans,
prior-12-month balances and applicable law before setting eligibility_validated.
Defaults implement the usual $50,000 / 50%-vested cap and five-year ordinary
purpose term. The optional $10,000 exception, residence-loan extended terms,
quarterly-payment rules, cure periods and loan-offset rollover rules are absent.

Integration: origination moves plan cash into a participant-loan receivable and
household cash, with an equal household liability. Preserve both receivable and
liability (or eliminate both in consolidated net worth). Repayment uses household
cash: principal reduces liability/receivable; interest is income to the plan.
Do not call a participant repayment a contribution or consume contribution room.
No taxable distribution is inferred merely from origination or job separation.
Default/separation halts amortization until a richer tax/plan adapter resolves it.
"""
from dataclasses import dataclass, field
from math import isfinite, expm1, log1p


def _number(value, name, *, positive=False):
    value = float(value)
    if not isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def available_plan_loan(vested_balance, *, outstanding_balance=0.0,
                        highest_balance_last12=0.0, dollar_limit=50_000.0,
                        max_vested_fraction=0.5):
    """Maximum *additional* principal under the supplied simplified limits.

    The dollar cap is reduced by highest prior-12-month aggregate balance minus
    current aggregate balance. Then existing debt consumes the resulting total
    loan limit. Highest prior balance must include the current outstanding debt.
    """
    vested_balance = _number(vested_balance, 'vested_balance')
    outstanding_balance = _number(outstanding_balance, 'outstanding_balance')
    highest_balance_last12 = _number(highest_balance_last12, 'highest_balance_last12')
    dollar_limit = _number(dollar_limit, 'dollar_limit', positive=True)
    max_vested_fraction = _number(max_vested_fraction, 'max_vested_fraction', positive=True)
    if max_vested_fraction > 1:
        raise ValueError('max_vested_fraction must not exceed 1')
    if highest_balance_last12 < outstanding_balance:
        raise ValueError('highest_balance_last12 must include current outstanding_balance')
    adjusted_cap = max(0.0, dollar_limit - (highest_balance_last12 - outstanding_balance))
    return max(0.0, min(adjusted_cap, max_vested_fraction * vested_balance) - outstanding_balance)


@dataclass(frozen=True)
class LoanPayment:
    month: int
    payment: float
    principal: float
    interest: float
    balance: float


@dataclass
class PlanLoan:
    principal: float
    annual_rate: float
    months: int
    vested_balance: float
    plan_permitted: bool = False
    eligibility_validated: bool = False
    outstanding_balance: float = 0.0
    highest_balance_last12: float = 0.0
    dollar_limit: float = 50_000.0
    max_vested_fraction: float = 0.5
    balance: float = field(init=False)
    payment: float = field(init=False)
    month: int = field(default=0, init=False)
    needs_tax_review: bool = field(default=False, init=False)
    review_reason: str | None = field(default=None, init=False)

    def __post_init__(self):
        self.principal = _number(self.principal, 'principal', positive=True)
        self.annual_rate = _number(self.annual_rate, 'annual_rate')
        if not isinstance(self.months, int) or isinstance(self.months, bool) or not 1 <= self.months <= 60:
            raise ValueError('ordinary-purpose loan months must be an integer from 1 to 60')
        if self.plan_permitted is not True or self.eligibility_validated is not True:
            raise ValueError('loan requires explicit plan permission and externally validated eligibility')
        maximum = available_plan_loan(self.vested_balance,
            outstanding_balance=self.outstanding_balance,
            highest_balance_last12=self.highest_balance_last12,
            dollar_limit=self.dollar_limit, max_vested_fraction=self.max_vested_fraction)
        if self.principal > maximum + 1e-8:
            raise ValueError(f'principal exceeds available plan loan limit ({maximum})')
        self.balance = self.principal
        rate = self.annual_rate / 12
        self.payment = (self.principal / self.months if rate == 0 else
                        self.principal * rate / -expm1(-self.months * log1p(rate)))

    def step(self, payment=None):
        """Pay at month end; fixed nominal annual interest / 12, no rounding.

        Optional payment may exceed the scheduled amount for early payoff, but
        may not be below it (or the final payoff). Missing payments need explicit
        default handling rather than being silently capitalized. Overpayment is
        rejected except floating-point tolerance.
        """
        if self.needs_tax_review:
            raise ValueError(f'loan requires plan/tax review: {self.review_reason}')
        if self.balance <= 1e-8:
            raise ValueError('loan is already repaid')
        interest = self.balance * self.annual_rate / 12
        payoff = self.balance + interest
        scheduled = min(self.payment, payoff)
        actual = scheduled if payment is None else _number(payment, 'payment')
        if actual < scheduled - 1e-8:
            raise ValueError('payment below schedule requires explicit default/plan review')
        if actual > payoff + 1e-8:
            raise ValueError('payment exceeds payoff')
        actual = min(actual, payoff)
        principal = actual - interest
        self.balance = max(0.0, self.balance - principal)
        if self.balance < 1e-8:
            self.balance = 0.0
        self.month += 1
        return LoanPayment(self.month, actual, principal, interest, self.balance)

    def mark_default(self):
        self.needs_tax_review = True
        self.review_reason = 'default: deemed-distribution, penalty and basis treatment unresolved'

    def mark_job_separation(self):
        self.needs_tax_review = True
        self.review_reason = 'job separation: plan repayment/offset and rollover terms unresolved'
