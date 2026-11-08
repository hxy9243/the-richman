"""Transparent annual tax *demonstration*, not tax-return software.

The default brackets are deliberately SYNTHETIC. They are not a representation
of any US tax year. Supply an explicitly versioned config or replace TaxEngine
with a validated production adapter before making financial decisions.

Supported: ordinary income, capital-gain netting/carryforwards, preferential
LTCG/qualified-dividend stacking, simplified MAGI-based NIIT and optional state
ordinary-income tax plus surcharge. Traditional distributions increase MAGI but
are not themselves investment income. Qualified Roth distributions should not
be supplied as taxable events. policy_income is assumed taxable ordinary life-
insurance gain included in NII; actual taxation must be validated separately.

Not supported: itemized deductions, credits, AMT, payroll taxes, tax treaties,
foreign-income MAGI adjustments, investment expense allocation, special-rate
capital gains, qualified dividend eligibility, retirement contribution limits,
IRA deduction phaseouts, early-distribution penalties, MEC taxation or tax-law
qualification. Deductible contributions must be externally validated. State
capital-loss/deduction rules are assumed to follow federal AGI. Loss amounts
carried forward are positive balances. No implicit tax payment is made here.
"""
from dataclasses import dataclass, fields
from math import isfinite
from typing import Protocol


@dataclass(frozen=True)
class IncomeEvents:
    ordinary_income: float = 0.0
    policy_income: float = 0.0
    short_term_gains: float = 0.0
    long_term_gains: float = 0.0
    qualified_dividends: float = 0.0
    ordinary_dividends: float = 0.0
    interest: float = 0.0
    traditional_withdrawals: float = 0.0
    deductible_contributions: float = 0.0
    short_term_loss_carryforward: float = 0.0
    long_term_loss_carryforward: float = 0.0

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if not isfinite(value):
                raise ValueError(f"{f.name} must be finite")
            if f.name not in ("short_term_gains", "long_term_gains") and value < 0:
                raise ValueError(f"{f.name} must be nonnegative")


@dataclass(frozen=True)
class TaxProfile:
    filing_status: str = "single"
    baseline_ordinary_income: float = 0.0

    def __post_init__(self):
        if self.filing_status not in ("single", "married_joint", "married_separate", "head_of_household"):
            raise ValueError("Unsupported filing status")
        if not isfinite(self.baseline_ordinary_income) or self.baseline_ordinary_income < 0:
            raise ValueError("baseline_ordinary_income must be finite and nonnegative")


@dataclass(frozen=True)
class TaxConfig:
    """Lower-bound/rate bracket pairs; defaults are illustrative, not current law.

    Filing status only controls default NIIT thresholds and capital-loss limits.
    The caller must supply status-specific ordinary/LTCG/state brackets and
    deductions. Defaults are intentionally the same synthetic values for all.
    """
    law_version: str = "SYNTHETIC-DEMO-v1"
    ordinary_brackets: tuple = ((0.0, 0.10), (50000.0, 0.20), (100000.0, 0.30))
    capital_gains_brackets: tuple = ((0.0, 0.0), (50000.0, 0.15), (500000.0, 0.20))
    state_brackets: tuple = ((0.0, 0.05), (100000.0, 0.10))
    federal_deduction: float = 0.0
    state_deduction: float = 0.0
    niit_rate: float = 0.038
    niit_threshold: float | None = None
    state_surcharge_rate: float = 0.01
    state_surcharge_threshold: float = 1000000.0
    capital_loss_limit: float | None = None

    def __post_init__(self):
        if not self.law_version:
            raise ValueError("law_version is required")
        for name in ("ordinary_brackets", "capital_gains_brackets", "state_brackets"):
            brackets = getattr(self, name)
            if not brackets or brackets[0][0] != 0:
                raise ValueError(f"{name} must start at zero")
            previous = -1.0
            for threshold, rate in brackets:
                if not isfinite(threshold) or threshold <= previous or not isfinite(rate) or not 0 <= rate <= 1:
                    raise ValueError(f"Invalid {name}")
                previous = threshold
        for name in ("federal_deduction", "state_deduction", "state_surcharge_threshold", "niit_threshold", "capital_loss_limit"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"Invalid {name}")
        for name in ("niit_rate", "state_surcharge_rate"):
            if not isfinite(getattr(self, name)) or not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"Invalid {name}")


def progressive_tax(income: float, brackets: tuple) -> float:
    """Tax a nonnegative amount against ordered lower-bound/rate pairs."""
    amount = max(0.0, income)
    total = 0.0
    for i, (lower, rate) in enumerate(brackets):
        upper = brackets[i + 1][0] if i + 1 < len(brackets) else amount
        total += max(0.0, min(amount, upper) - lower) * rate
    return total


@dataclass(frozen=True)
class TaxResult:
    federal_ordinary: float
    federal_capital_gains: float
    niit: float
    state_income: float
    state_surcharge: float
    agi: float
    net_investment_income: float
    short_term_loss_carryforward: float
    long_term_loss_carryforward: float
    law_version: str
    is_incremental: bool = False

    @property
    def total(self) -> float:
        return self.federal_ordinary + self.federal_capital_gains + self.niit + self.state_income + self.state_surcharge


class TaxEngine(Protocol):
    def calculate(self, events: IncomeEvents, profile: TaxProfile) -> TaxResult: ...
    def incremental(self, events: IncomeEvents, profile: TaxProfile) -> TaxResult: ...


class SyntheticTaxEngine:
    def __init__(self, config: TaxConfig | None = None):
        self.config = config or TaxConfig()

    def calculate(self, events: IncomeEvents, profile: TaxProfile | None = None) -> TaxResult:
        p = profile or TaxProfile()
        c = self.config
        st = events.short_term_gains - events.short_term_loss_carryforward
        lt = events.long_term_gains - events.long_term_loss_carryforward
        if st * lt < 0:
            combined = st + lt
            if st > 0:
                st, lt = max(0.0, combined), min(0.0, combined)
            else:
                st, lt = min(0.0, combined), max(0.0, combined)
        loss_limit = c.capital_loss_limit
        if loss_limit is None:
            loss_limit = 1500.0 if p.filing_status == "married_separate" else 3000.0
        # Use short-term losses first for the ordinary-income deduction.
        st_deduction = min(max(0.0, -st), loss_limit)
        lt_deduction = min(max(0.0, -lt), loss_limit - st_deduction)
        loss_deduction = st_deduction + lt_deduction
        st_carry = max(0.0, -st - st_deduction)
        lt_carry = max(0.0, -lt - lt_deduction)
        preferential = max(0.0, lt) + events.qualified_dividends
        investment_ordinary = events.interest + events.ordinary_dividends
        agi = (p.baseline_ordinary_income + events.ordinary_income + events.traditional_withdrawals
               + investment_ordinary + events.policy_income + max(0.0, st) + preferential
               - events.deductible_contributions - loss_deduction)
        ordinary_taxable = max(0.0, agi - preferential - c.federal_deduction)
        taxable_preferential = max(0.0, min(preferential, agi - c.federal_deduction))
        federal_ordinary = progressive_tax(ordinary_taxable, c.ordinary_brackets)
        capital_tax = (progressive_tax(ordinary_taxable + taxable_preferential, c.capital_gains_brackets)
                       - progressive_tax(ordinary_taxable, c.capital_gains_brackets))
        nii = max(0.0, investment_ordinary + events.policy_income + events.qualified_dividends + max(st, 0.0) + max(lt, 0.0) - loss_deduction)
        threshold = c.niit_threshold
        if threshold is None:
            threshold = {"single": 200000.0, "head_of_household": 200000.0,
                         "married_joint": 250000.0, "married_separate": 125000.0}[p.filing_status]
        niit = c.niit_rate * min(nii, max(0.0, agi - threshold))
        state_taxable = max(0.0, agi - c.state_deduction)
        state_income = progressive_tax(state_taxable, c.state_brackets)
        surcharge = c.state_surcharge_rate * max(0.0, state_taxable - c.state_surcharge_threshold)
        return TaxResult(federal_ordinary, capital_tax, niit, state_income, surcharge,
                         agi, nii, st_carry, lt_carry, c.law_version)

    def incremental(self, events: IncomeEvents, profile: TaxProfile | None = None) -> TaxResult:
        """With-strategy tax minus household baseline. Negative deltas are valid.

        Tax components are deltas; AGI, NII and carryforwards remain the absolute
        with-strategy values so consumers can persist loss balances correctly.
        """
        p = profile or TaxProfile()
        actual = self.calculate(events, p)
        baseline = self.calculate(IncomeEvents(), p)
        return TaxResult(*(getattr(actual, name) - getattr(baseline, name) for name in
                           ("federal_ordinary", "federal_capital_gains", "niit", "state_income", "state_surcharge")),
                         actual.agi, actual.net_investment_income,
                         actual.short_term_loss_carryforward, actual.long_term_loss_carryforward,
                         actual.law_version, True)


@dataclass(frozen=True)
class TaxCalculatorResult:
    """Federal income tax result. NIIT is included in total, not added twice.

    There is no claimed ordinary/preferential decomposition. California/state
    taxes are absent, not zero. Payroll taxes are outside this adapter's scope.
    """
    federal_income_tax: float
    niit: float
    agi: float
    short_term_loss_carryforward: float
    long_term_loss_carryforward: float
    law_version: str
    is_incremental: bool = False
    state_income: None = None

    @property
    def total(self):
        return self.federal_income_tax


class TaxCalculatorEngine:
    """Optional real federal adapter backed by PSL Tax-Calculator.

    Install the project's tax extra. Version 6.8.5 was integration-tested.
    Inputs are nominal dollars for `tax_year`; no automatic aging/growth occurs.
    Profile baseline and ordinary_income map to wages; retirement distributions
    to taxable IRA income; deductible_contributions to *already validated IRA
    deductions*. Do not pass policy surrender gains, Roth conversions with basis,
    or pretax 401(k) deferrals as those generic fields. Those require richer
    event mappings. Default age is 40; deduction/credit eligibility beyond this
    narrow input schema is not represented. Taxcalc's current-law projection is
    used, not a guarantee of future legislation. No CA adapter is provided here.

    Carryforwards follow the synthetic netting helper. That simplified helper
    can overconsume losses when ordinary income is below the deduction; avoid
    such cases until full capital-loss carryover worksheets are implemented.
    """
    def __init__(self, tax_year: int = 2026):
        if not isinstance(tax_year, int):
            raise ValueError("tax_year must be an integer")
        self.tax_year = tax_year

    def calculate(self, events: IncomeEvents, profile: TaxProfile | None = None) -> TaxCalculatorResult:
        if events.policy_income:
            raise NotImplementedError("TaxCalculatorEngine does not map taxable policy gains; use a validated insurance-tax adapter")
        try:
            import pandas as pd
            import taxcalc
        except ImportError as exc:
            raise ImportError("Install wealth-sim-core[federal-tax] for TaxCalculatorEngine") from exc
        p = profile or TaxProfile()
        mars = {"single": 1, "married_joint": 2, "married_separate": 3, "head_of_household": 4}[p.filing_status]
        wages = p.baseline_ordinary_income + events.ordinary_income
        row = dict(RECID=1, MARS=mars, age_head=40, age_spouse=40 if mars == 2 else 0,
                   e00200=wages, e00200p=wages, e00200s=0,
                   e00300=events.interest,
                   e00600=events.ordinary_dividends + events.qualified_dividends,
                   e00650=events.qualified_dividends,
                   e01400=events.traditional_withdrawals,
                   e03150=events.deductible_contributions,
                   p22250=events.short_term_gains - events.short_term_loss_carryforward,
                   p23250=events.long_term_gains - events.long_term_loss_carryforward)
        policy = taxcalc.Policy()
        policy.set_year(self.tax_year)
        records = taxcalc.Records(data=pd.DataFrame([row]), start_year=self.tax_year,
                                  gfactors=None, weights=None)
        calc = taxcalc.Calculator(policy=policy, records=records)
        calc.calc_all()
        carry = SyntheticTaxEngine().calculate(events, p)
        return TaxCalculatorResult(float(calc.array('iitax')[0]), float(calc.array('niit')[0]),
                                   float(calc.array('c00100')[0]), carry.short_term_loss_carryforward,
                                   carry.long_term_loss_carryforward,
                                   f"Tax-Calculator-{taxcalc.__version__}/year-{self.tax_year}")

    def incremental(self, events: IncomeEvents, profile: TaxProfile | None = None) -> TaxCalculatorResult:
        p = profile or TaxProfile()
        actual = self.calculate(events, p)
        baseline = self.calculate(IncomeEvents(), p)
        return TaxCalculatorResult(actual.federal_income_tax - baseline.federal_income_tax,
                                   actual.niit - baseline.niit, actual.agi,
                                   actual.short_term_loss_carryforward, actual.long_term_loss_carryforward,
                                   actual.law_version, True)
