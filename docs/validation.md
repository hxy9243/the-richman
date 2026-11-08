# Validation scope

Synthetic mechanics tests verify invariants and arithmetic, not financial advice.
Real optional integrations exercise actual installed libraries, not mocks.

Tests cover FIFO partial sales, long-term holding-period boundary, nonfinite
inputs, cash/units constraints, Roth basis, unrealized-gain tax exclusion,
retirement trade tax exclusion, annual equity reconciliation, realised-loss tax
refusal, shared seeded bootstrap, annual policy summaries, IUL annual/staggered
crediting, floors after charges, VUL drawdowns, loans/basis/lapse and validation.
Tax tests cover progressive stacking, NIIT, distributions, synthetic surcharge,
losses and actual Tax-Calculator federal cases. lifelib tests execute both
packaged models and compare 24-month checkpoints to observed reference results.

A passing test suite does not establish carrier contract accuracy or tax return
correctness. No real carrier illustration supplied; no numerical California
current-law validation performed. Real Tax-Calculator adapter deliberately
rejects policy-income mapping until tested. Federal examples use a fixed tax
law year, not actual historical tax rules.

Final verification (2026-11-08 workspace): 39 unittest tests passed, including
actual lifelib IUL/VUL and Tax-Calculator integrations; source compileall passed;
both synthetic and federal CLI examples completed. Review found and fixed missing
month/NaT handling, nonfinite initial prices, Period normalization, and unresolved
loss propagation into subsequent years. Regression tests cover these cases.

Annual tax_detail_* columns inherit their adapter's semantics: tax components
are incremental; AGI/NII/carryforwards are absolute with-strategy values. NIIT is
included in Tax-Calculator federal_income_tax and must not be added again.
