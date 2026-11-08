# Architecture and library decision record

## Boundaries

1. `markets.py`: validated monthly price-return/dividend schema and seeded block
   bootstrap using NumPy; preserves shared monthly cross-asset sequences.
2. `accounts.py`: FIFO acquisition lots, cash, holding period and Roth principal.
3. `engine.py`: deterministic ordered month-start events, return replay, annual
   reconciliation and incremental household taxes.
4. `tax.py`: typed income events and tax-engine protocol. Synthetic test engine;
   executable federal Tax-Calculator adapter pinned to 6.8.5.
5. `policy.py`: transparent synthetic event mechanics and separate actual packaged
   lifelib IUL/VUL reference projection adapter pinned to 0.17.2.
6. `policy_runner.py`: standalone scenario annual summaries. No assumption that
   investment and insurance taxes can be independently summed for one household.
7. `cli.py`: JSON/CSV inputs, CSV/JSON outputs. No UI or server.

## Reuse, not unverified integration

- NumPy/Pandas: actually used for paths, time periods, ledger tables and exports.
- Tax-Calculator: installed and executed against 2026 federal cases. CC0.
  https://github.com/PSLmodels/Tax-Calculator
- lifelib: installed and both IUL_US_S and VUL_US_S packaged models executed.
  MIT. modelx is a transitive dependency. lifelib examples are standardised
  mechanics references and lack actual carrier-specific calibration.
  https://lifelib.io/libraries/uslib/index.html
- Owl: considered, not integrated. It is primarily an annual retirement optimizer
  with simplified taxable basis and retirement ordering. Its GPL-3 license and
  fit should be reviewed before embedding; running it separately for comparison
  is a useful next test. https://github.com/mdlacasse/Owl
- PolicyEngine-US: considered, not yet installed or numerically validated here.
  Federal/CA adapter is next, not a completed feature. AGPL-3 license requires
  deliberate architecture/distribution review.
  https://github.com/PolicyEngine/policyengine-us

## Next milestones

- Carrier illustration import and validation at monthly/annual checkpoints.
- Connect external events to actual lifelib model inputs with explicit supported
  features, instead of presenting synthetic event model as the carrier engine.
- Current-law California household adapter, tested against authoritative examples.
- Combined household event taxes, deposits limited by eligibility, after-tax budget
  equivalence, tax payments from cash, and reinvested tax savings.
- Wash sales and capital-loss carryforward state; Roth/IRA basis/conversion rules.
- Tax year policy versus historical market time selection exposed explicitly.
- Data license/source manifest for actual historical S&P/Nasdaq return paths.
- Only then add scenario/UI and decision comparisons.
