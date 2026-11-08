# Household lifecycle API v2

This is a **research API, not production tax/insurance advice**. No UI or HTTP
server is required. `wealthsim.api.simulate_scenario(dict)` accepts a JSON-friendly
scenario; `wealthsim.lifecycle.simulate_household(...)` accepts typed inputs.
Both return `SimulationResult` with monthly, annual, event DataFrames and metadata.

```sh
PYTHONPATH=src python -m wealthsim.cli examples/household.json --output output/household
# Optional real federal adapter, fixed tax-law year (not California):
PYTHONPATH=src python -m wealthsim.cli examples/household.json --output output/federal-household --tax taxcalc --tax-year 2026
```

## Coverage

| Requirement | API | Boundary |
|---|---|---|
| Routine W2 salary | Salary / `salaries` | Monthly gross, annual growth, start/end; interruptions use disjoint schedules. Payroll taxes supplied explicitly, not calculated from FICA/SDI law. |
| Routine spending with variance | Spending / `spending` | Mean-preserving nonnegative lognormal spending, CV, inflation, independent seed. |
| Traditional and Roth 401k | Salary allocation rates | Combined caller-supplied annual employee cap across accounts/employers, traditional reduces taxable wages; Roth does not. |
| Employer match | Salary match settings | Match-rate × lesser(employee contributions, salary cap); per-pay-period and immediately vested. No annual true-up, vesting or 415(c) validation. |
| Historical replay | `historical_replay` / `market.mode=historical` | Caller supplies actual licensed history and source name; no history bundled/downloaded or invented. |
| Stochastic market | `stochastic_market` / `market.mode=stochastic` | Seeded correlated GBM with explicit drift, volatility, separate dividends; not forecast or fat-tail model. |
| IUL/VUL | `policies`, policy events | Existing synthetic monthly mechanics; actual lifelib adapter remains separate, not carrier-calibrated. |
| Major cash deposits/spending | `deposit` / `spend` | Cash deposits are nontaxable external capital; taxable bonuses must be Salary. |
| Policy borrowing | `policy_loan`, `policy_repay`, `policy_withdraw` | Loans are debt, repayment not premium. Gains/lapse tax mapping may be unsupported. |
| 401k borrowing | `plan_loan`, `plan_repay` | Explicit plan permission/eligibility, simplified legal caps, ordinary-purpose term <=60 months, cash available first. Traditional plans only. |
| Annual report | `result.annual` | Salary, deferrals, spending, net market/policy change, modeled income taxes assessed/paid/payable, nominal and real equity. |

## Example usage

```python
import json
from wealthsim.api import simulate_scenario
scenario = json.load(open('examples/household.json'))
result = simulate_scenario(scenario)
print(result.annual.to_string(index=False))
result.export('output/household')
```

To replay real historical rows instead of generated returns:

```python
scenario['market'] = {
    'mode': 'historical',
    'rows': licensed_frame.to_dict('records'),
    'source_name': 'Your licensed dataset and version',
    'source_start': '2000-01', 'months': 24, 'start': '2026-01',
    'license_note': 'Describe permitted use'
}
```

History rows: month, symbol, price_return, dividend_yield. Adjusted total-return
prices plus dividends would double-count dividends. IUL consumes price returns;
VUL and investments receive dividends. Scenario calendar can differ from history
and the frozen tax-law year. QQQ pre-1999 must be a clearly labeled index proxy.

## Event contract

Single events use `month`; recurring events use inclusive `start`/`end`. They
execute in supplied order at month start, after salary and before recurring
spending/returns. `buy` transfers checking cash only when `from_checking=true`
and the target is taxable. Retirement contributions and matches enter retirement
cash; a separate `buy` invests it. Sales do not automatically distribute cash.
`withdraw` moves taxable-account cash to checking; retirement distributions are
currently rejected in this household facade pending qualified/penalty rules.

A policy event supplies `policy` and `amount`. Events for a policy are aggregated
per month and then follow the documented policy-step ordering. They are not
arbitrary intramonth trade sequencing. Policy charges, loans and lapse continue
after premiums stop. A policy does not start charging until its first event.

A plan-loan example (assuming sufficient accumulated plan cash):

```python
{'month':'2027-01', 'type':'plan_loan', 'loan_id':'repair',
 'account':'traditional401k', 'amount':5000, 'annual_rate':0.06,
 'months':60, 'plan_permitted':True, 'eligibility_validated':True,
 'highest_balance_last12':0}
{'start':'2027-02', 'end':'2032-01', 'type':'plan_repay', 'loan_id':'repair'}
```

Explicit eligibility includes balances across related plans and prior loans.
Only one current loan per account is supported. Earlier repaid loans require
correct caller-supplied prior-12-month balances; the engine does not infer that
history. Loan repayment debits checking and credits plan cash, without consuming
employee contribution room. Plan receivable and matching household liability
cancel in consolidated equity; **the loan does not create wealth**. Missing or
unfunded installments emit `plan_loan_review_required`. Further amortization
freezes, balances are labeled unresolved, and current/future after-tax equity
is withheld. The household API does not invent cure periods, default interest,
deemed-distribution or offset taxation. `shortfall_mode="raise"` preserves the
old fail-fast behavior. `PlanLoan.mark_default()` / `.mark_job_separation()`
remain lower-level review flags.

## Tax and reconciliation conventions

Salary deferrals reduce wage income directly, not an IRA deduction. Household
baseline income must be zero: all wages must be explicit to avoid liabilities
without cash. Annual tax is computed jointly over wages, taxable trades and policy
income, never summed from standalone incremental estimates. Payroll-tax cash
outflow is explicitly supplied and independent of income taxes.

At December (or the final partial-year month), modeled income tax is assessed and
paid from checking up to available cash. Remainder remains tax payable; future
annual settlement can pay it. Withholding/estimated payments, penalties, interest
on unpaid tax and statutory deadlines are not modeled. Partial-year totals are
flagged and not annualized. `end_net_equity` deducts only modeled taxes, **not
future liquidation tax on unsold investments or pretax retirement balances**.
Tax-Calculator covers federal income tax only; state/local tax is omitted. The
default engine remains synthetic, not California current law.

Any realized loss withholds current and future tax/net-after-tax estimates until
wash-sale/carryforward integration exists. Unsupported real-engine policy gains
also withhold the estimate. `end_equity_before_unknown_tax` is not after-tax
wealth in those cases. Unknown liability is never silently represented as zero.

## Valuable next scenarios

- Inflation shocks, unemployment/pay interruption, emergency-reserve requirements.
- Employer vesting, catch-up/415(c) limits, retirement withdrawals/RMDs/conversions.
- Explicit liquidation/funding priorities and tax-aware lots/wash sales.
- State moves, CA current-law taxes, payroll taxes and withholding.
- Debt interest, mortgage/property cash flows, disability/death and estate outcomes.
- Contract-specific COI, lapse guarantees, MEC/7702 validation, surrender events.
- Correlated inflation/returns, fat tails, sequence risk and reproducible batches.

No live accounts or trades, and no personal financial data are in this repository.


## Custom synthetic insurance policies

Yes: `policies` is an arbitrary name → configuration map, not a fixed menu of
predefined products. Each policy has independent state and a market symbol.
For the JSON API:

```json
"policies": {
  "custom_iul": {
    "symbol": "SPY",
    "config": {
      "kind": "iul", "face_amount": 250000,
      "premium_load": 0.05, "monthly_admin_fee": 10,
      "annual_coi_rate": 0.001, "iul_cap": 0.08,
      "iul_floor": 0.0, "iul_participation": 1.0,
      "annual_loan_rate": 0.05, "surrender_charge": 500
    }
  },
  "custom_vul": {
    "symbol": "SPY",
    "config": {
      "kind": "vul", "face_amount": 250000,
      "premium_load": 0.03, "monthly_admin_fee": 8,
      "annual_coi_rate": 0.001, "annual_fund_expense": 0.01,
      "annual_loan_rate": 0.05, "surrender_charge": 500
    }
  }
}
```

Fund each with `premium` events; vary premiums/loans by month independently of
configuration. The assumptions are illustrative, not suggested policy terms.
Rates are constant and COI is proportional to current net amount at risk. This
cannot express age-dependent COI tables, changing caps/participation, multiple
index options, changing surrender-charge schedules, carrier guarantees,
MEC/7702 limits, riders, or true bankruptcy protection. Configuring a new policy
does not make it a faithful representation of an actual carrier product.

## Cash distress is data, not an exception

`shortfall_mode="event"` is the default. Monthly ledgers continue through cash
shortages. `cash_shortfall` events report requested, funded and unfunded amounts
and whether the shortfall creates an obligation.

- Spending pays available checking cash; the unmet amount becomes an explicit
  `unpaid_obligations` liability, deducted from equity. `spending` means cash
  paid, while `spending_incurred` includes unmet spending. This assumes requested
  expenses are obligations, not discretionary purchases canceled for lack of cash.
- `settle_obligations` pays those liabilities from future cash. Settlement is not
  new spending and never double-counts the original expense. No interest or late
  fees accrue unless a future debt module implements them.
- Premiums, policy repayments and checking-funded investments execute only the
  funded amount; their unfilled requests do not create arbitrary new debt.
- A never-funded policy stays inactive. A lapsed policy rejects subsequent
  policy events with `policy_event_rejected` rather than ending the simulation.
- Plan-loan installments are all-or-nothing because partial-payment/default rules
  remain unmodeled. Insufficient cash emits shortfall and loan-review events;
  the attempted payment does not consume the remaining cash.
- Annual unpaid tax generates an `unpaid_tax` event and remains tax payable.
- Negative modeled net equity emits `balance_sheet_insolvency` on each transition
  into negative equity. It is **not a legal bankruptcy filing or prediction**.
  Assets may be illiquid even when equity is positive. Unknown taxes and unresolved
  plan-loan effects are excluded from that preliminary equity label.

Invalid configuration, unsupported distributions, insufficient securities and
borrowing above contract/plan capacity still raise errors. This change makes
cashflow distress an output; it does not silently permit invalid transactions.
The annual accounting bridge uses `spending_incurred`, not only cash spending,
to reconcile obligations. `end_equity_before_unknown_tax` can be negative.
