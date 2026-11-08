"""Explicitly synthetic policy mechanics plus an optional real lifelib adapter.

The small event model is not a carrier illustration or IRC 7702/7702A validator.
It assumes a qualifying non-MEC contract, level face amount, constant COI rate,
no corridor or no-lapse guarantee, no grace period, and basis-first withdrawals.
IUL premiums open staggered 12-month segments. Charges/withdrawals reduce segment
balances pro rata. Loans use a separate zero-return collateral account; interest
capitalizes at a configurable nominal annual rate / 12. No loan arbitrage assumed.
Ordering: premium/load, withdrawals, loan repayment/advance, charges, returns,
loan interest, lapse. Return inputs exclude fees; IUL inputs are price returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Literal


def _nonnegative(name: str, value: float) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class PolicyConfig:
    kind: Literal["iul", "vul"]
    face_amount: float = 250_000
    premium_load: float = 0.05
    monthly_admin_fee: float = 10
    annual_coi_rate: float = 0.001
    annual_fund_expense: float = 0.01
    iul_cap: float = 0.10
    iul_floor: float = 0.0
    iul_participation: float = 1.0
    annual_loan_rate: float = 0.05
    surrender_charge: float = 0.0

    def __post_init__(self):
        if self.kind not in ("iul", "vul"):
            raise ValueError("kind must be iul or vul")
        for name, value in vars(self).items():
            if name != "kind":
                _nonnegative(name, value)
        if self.premium_load >= 1 or self.annual_fund_expense >= 1:
            raise ValueError("premium_load and annual_fund_expense must be < 1")
        if self.iul_floor > self.iul_cap:
            raise ValueError("IUL floor must not exceed cap")


@dataclass
class Segment:
    balance: float
    months: int = 0
    index_factor: float = 1.0


@dataclass
class PolicyState:
    account_value: float = 0.0  # Includes loan collateral.
    tax_basis: float = 0.0
    loan_balance: float = 0.0
    loan_collateral: float = 0.0
    month: int = 0
    lapsed: bool = False
    segments: list[Segment] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyMonth:
    month: int
    premium: float
    withdrawal: float
    loan_advance: float
    loan_repayment: float
    premium_load: float
    charges: float
    credited_return: float
    loan_interest: float
    account_value: float
    cash_surrender_value: float
    loan_balance: float
    net_death_benefit: float
    tax_basis: float
    taxable_income: float
    lapsed: bool


def step(state: PolicyState, config: PolicyConfig, *, premium: float = 0,
         market_return: float = 0, withdrawal: float = 0, loan: float = 0,
         loan_repayment: float = 0) -> PolicyMonth:
    """Advance one month, mutating state after input checks. Returns audit row.

    A gain is reported only on basis-exceeding withdrawals or synthetic lapse.
    Cash surrender value is net of loan and surrender charge, never a tax estimate.
    Explicit surrender, MECs, exchanges, and death taxation are not implemented.
    """
    for name, value in (("premium", premium), ("withdrawal", withdrawal),
                        ("loan", loan), ("loan_repayment", loan_repayment)):
        _nonnegative(name, value)
    if not isfinite(market_return) or market_return < -1:
        raise ValueError("market_return must be finite and >= -1")
    for name in ("account_value", "tax_basis", "loan_balance", "loan_collateral"):
        _nonnegative(name, getattr(state, name))
    if state.loan_collateral > state.account_value + 1e-8:
        raise ValueError("collateral exceeds account value")
    if state.lapsed:
        raise ValueError("cannot operate a lapsed policy")
    if loan_repayment > state.loan_balance:
        raise ValueError("repayment exceeds debt")
    net_premium = premium * (1 - config.premium_load)
    available = state.account_value + net_premium - state.loan_balance - config.surrender_charge
    unloaned_available = state.account_value + net_premium - state.loan_collateral + min(state.loan_collateral, loan_repayment)
    if withdrawal + loan > min(max(0, available + loan_repayment), unloaned_available) + 1e-8:
        raise ValueError("withdrawal/loan exceeds available surrender value")
    state.month += 1
    state.tax_basis += premium
    state.account_value += net_premium
    if config.kind == "iul":
        # Support a user-supplied opening account value with no segment history.
        represented = sum(s.balance for s in state.segments) + state.loan_collateral
        opening_unrepresented = state.account_value - net_premium - represented
        if opening_unrepresented > 1e-8:
            state.segments.append(Segment(opening_unrepresented))
        if net_premium:
            state.segments.append(Segment(net_premium))

    def remove_unloaned(amount):
        unloaned = max(0, state.account_value - state.loan_collateral)
        if amount > unloaned + 1e-7:
            raise ValueError("insufficient unloaned value")
        if config.kind == "iul" and unloaned:
            factor = max(0, 1 - amount / unloaned)
            for seg in state.segments:
                seg.balance *= factor
        state.account_value -= amount

    taxable = max(0, withdrawal - state.tax_basis)
    state.tax_basis = max(0, state.tax_basis - withdrawal)
    # Release collateral on repayment. Repayment itself is not premium/basis.
    if loan_repayment:
        released = min(state.loan_collateral, loan_repayment)
        state.loan_collateral -= released
        state.loan_balance -= loan_repayment
        if config.kind == "iul" and released:
            state.segments.append(Segment(released))
    remove_unloaned(withdrawal)
    if loan:
        remove_unloaned(loan)
        state.account_value += loan
        state.loan_collateral += loan
        state.loan_balance += loan

    coi = max(0, config.face_amount - state.account_value) * config.annual_coi_rate / 12
    requested_charges = config.monthly_admin_fee + coi
    unloaned = max(0, state.account_value - state.loan_collateral)
    charge_shortfall = requested_charges > unloaned + 1e-8
    charges = min(requested_charges, unloaned)
    remove_unloaned(charges)
    credited = 0.0
    if config.kind == "vul":
        unloaned = max(0, state.account_value - state.loan_collateral)
        gross_gain = unloaned * market_return
        fund_fee = (unloaned + gross_gain) * config.annual_fund_expense / 12
        credited = gross_gain
        charges += fund_fee
        state.account_value += gross_gain - fund_fee
    else:
        for seg in state.segments:
            seg.index_factor *= 1 + market_return
            seg.months += 1
            if seg.months == 12:
                rate = max(config.iul_floor, min(config.iul_cap,
                           config.iul_participation * (seg.index_factor - 1)))
                gain = seg.balance * rate
                credited += gain
                seg.balance += gain
                seg.months = 0
                seg.index_factor = 1.0
        state.account_value += credited
    interest = state.loan_balance * config.annual_loan_rate / 12
    state.loan_balance += interest
    if charge_shortfall or state.loan_balance > state.account_value + 1e-8:
        # Simplified deemed distribution on termination; taxes paid externally.
        taxable += max(0, max(state.account_value, state.loan_balance) - state.tax_basis)
        state.account_value = 0
        state.loan_balance = 0
        state.loan_collateral = 0
        state.segments.clear()
        state.tax_basis = 0
        state.lapsed = True
    return PolicyMonth(state.month, premium, withdrawal, loan, loan_repayment,
                       premium * config.premium_load, charges, credited, interest,
                       state.account_value,
                       max(0, state.account_value - config.surrender_charge - state.loan_balance),
                       state.loan_balance,
                       0 if state.lapsed else max(config.face_amount, state.account_value) - state.loan_balance,
                       state.tax_basis, taxable, state.lapsed)


def lifelib_reference_projection(kind: str, *, months: int = 24, point_id: int = 1):
    """Execute installed lifelib 0.17.2 reference model; return its account ledger.

    This optional adapter reuses the actual packaged model and standardized CSVs.
    It is separate from ``step`` and not a calibrated personal policy. No user
    events are mapped to this reference adapter yet. Install the insurance extra.
    """
    if kind not in ("iul", "vul") or not isinstance(months, int) or months < 1:
        raise ValueError("kind must be iul/vul and months a positive integer")
    try:
        import lifelib
        import modelx as mx
    except ImportError as exc:
        raise RuntimeError("Install lifelib==0.17.2 (insurance extra) for reference models") from exc
    folder, model_name = {"iul": ("indexed_ul", "IUL_US_S"),
                          "vul": ("variable_ul", "VUL_US_S")}[kind]
    path = Path(lifelib.__file__).parent / "libraries/uslib/products" / folder / model_name
    model = mx.read_model(str(path))
    try:
        projection = model.Projection[point_id]
        columns = ["prem_to_av_pp", "coi_pp", "mth_deduction_pp", "av_pp",
                   "surr_charge_pp", "ncsv_pp", "loan_bal_pp"]
        import pandas as pd
        return pd.DataFrame({c: [getattr(projection, c)(t) for t in range(months)]
                             for c in columns}, index=pd.Index(range(months), name="month"))
    finally:
        model.close()
