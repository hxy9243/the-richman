# Wealth simulation core

Core-first, local Python research project for replaying deposits, market changes,
trades and insurance cash flows, with monthly audit rows and year-end summaries.
**No UI, live accounts, personal data, or investment execution.**

## Run

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[federal-tax,insurance,test]'
wealthsim examples/demo.json --output output/demo
wealthsim examples/demo.json --output output/federal --tax taxcalc --tax-year 2026
python -m unittest discover -s tests -v
```

The default tax model is deliberately **SYNTHETIC**, not a representation of
California or any tax year. `--tax taxcalc` uses real Tax-Calculator 6.8.5 federal
income tax only. California tax is **not implemented as current law**. Tax year
is frozen across replay, independently from the market calendar. Outputs identify
the chosen engine. Do not use these estimates to make a policy purchase or file taxes.

The bundled 36-month market data is generated synthetic SPY/QQQ-labelled data,
**not historical returns or forecasts**. Replace it with licensed monthly price
returns and separate dividend yields using the same CSV schema.

## Implemented

- Taxable/traditional/Roth investment accounts, deposits, FIFO lots, buys/sells,
  explicit cash withdrawals, fees, cash dividends and monthly asset price changes.
- Distinct realized ST/LT gains; unrealized appreciation is not automatically taxed.
- Ordinary-dividend treatment is the conservative current default. Qualification
  requires richer explicit tax events, not a blanket assumption.
- Annual equity bridge: starting value + deposits - withdrawals - fees + market
  P&L (including dividends) = ending value; numerical reconciliation exported.
- Monthly event-driven synthetic IUL/VUL mechanics, premium loads, expenses,
  loans/repayment, basis-first withdrawals, surrender value, death benefit and lapse.
- IUL price-return segments mature after 12 months; annual caps aren't applied
  monthly. VUL consumes total returns with fund expenses deducted separately.
- **Actual lifelib 0.17.2 reference projections** for packaged IUL and VUL examples,
  via `wealthsim.policy.lifelib_reference_projection`. Executed and golden-tested.
- Seeded shared block-bootstrap return paths using NumPy; Pandas CSV exports.
- Real optional Tax-Calculator federal adapter, annual incremental tax relative
  to the same household wage baseline; synthetic bracket engine for tests.

Example actual library projection:

```python
from wealthsim.policy import lifelib_reference_projection
print(lifelib_reference_projection('iul', months=24))
print(lifelib_reference_projection('vul', months=24))
```

## Output and conventions

Each standalone strategy exports `monthly.csv`, `annual.csv`, `events.csv`, and
`metadata.json`. Investment events execute at **month start in supplied order**
using prior closing prices. Market returns and cash dividends follow. Taxes are
reported liabilities funded externally; they are **not debited**, and no claim
of reinvested tax savings or equal after-tax budget comparison is made yet.
Policy annual reports show premiums, loans, credited returns, fees, surrender
value, taxable policy income and estimated tax. Non-MEC status is an assumption.

The demo's investment strategy and policies each have their own budget. Their
standalone taxes must **not be added**: nonlinear household taxes require one
combined event calculation. The `IncomeEvents`/tax engine interface supports
that next integration step. This prototype does not rank strategies.

## Fail-closed and unsupported cases

- Tax estimates are withheld for investment years containing any realized loss and all subsequent years,
  because transaction-level wash sales and cross-year state are not integrated.
  The standalone synthetic tax arithmetic can net losses, but that is not enough
  to validate a real portfolio tax return.
- Traditional deposits require explicit deductible status; nondeductible basis,
  conversions, contribution limits, eligibility, employer match and RMDs are not
  implemented. IRA-deduction eligibility must be externally validated. Traditional
  withdrawals require explicit `penalty_exempt=True`.
- Roth contribution principal is tracked, but conversion ordering/five-year rules
  are not; nonqualified withdrawals above principal are rejected.
- Policy event mechanics are **not the lifelib adapter**: arbitrary external events
  have not yet been mapped into lifelib. Synthetic charges/COI are constant, not
  age-specific carrier tables; no corridor, no-lapse guarantee/grace, MEC/GPT,
  surrender event, 1035 exchange or tax-compliance determination is implemented.
- Real federal adapter refuses positive policy-income tax mapping until validated;
  such policy outputs say unavailable, not zero. No current-law CA adapter yet.
- No performance, data licensing or financial correctness certification.

## Library choices

Use NumPy/Pandas for scenario paths and exports; Tax-Calculator for federal tax;
lifelib/modelx for insurance reference-model reuse. See [architecture](docs/architecture.md)
and [validation](docs/validation.md). Owl and PolicyEngine remain evaluation
candidates, not claimed integrations. Next work should implement the actual
carrier-input adapter and California tax adapter before building a UI.
