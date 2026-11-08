"""Run standalone policy scenarios, preserving monthly and annual ledgers."""
from dataclasses import asdict
import pandas as pd
from .markets import validate_market
from .policy import PolicyConfig, PolicyState, step
from .tax import IncomeEvents, TaxProfile, SyntheticTaxEngine
from .engine import SimulationResult


def simulate_policy(market, events, config, symbol, *, tax_engine=None, profile=None):
    market = validate_market(market)
    path = market[market.symbol == symbol]
    if path.empty:
        raise ValueError("unknown policy underlying symbol")
    by_month = {}
    for e in events:
        m = pd.Period(e['month'],freq='M')
        if m not in set(path.month):
            raise ValueError("policy event outside market path")
        if m in by_month:
            raise ValueError("combine policy events within each month explicitly")
        by_month[m] = {k:v for k,v in e.items() if k != 'month'}
    state=PolicyState()
    monthly=[]
    for row in path.itertuples():
        if state.lapsed:
            break
        # IUL credits price-only; VUL receives total return incl dividend cash reinvestment.
        ret=row.price_return + (row.dividend_yield if config.kind == 'vul' else 0)
        report=step(state,config,market_return=ret,**by_month.get(row.month,{}))
        monthly.append({'calendar_month':str(row.month),'year':row.month.year,**asdict(report)})
    df=pd.DataFrame(monthly)
    engine=tax_engine or SyntheticTaxEngine(); profile=profile or TaxProfile()
    annual=[]
    start=0.
    for year, rows in df.groupby('year'):
        end=rows.cash_surrender_value.iloc[-1]
        premium=rows.premium.sum(); withdrawal=rows.withdrawal.sum(); loans=rows.loan_advance.sum(); repayment=rows.loan_repayment.sum()
        tax_status="estimated"
        tax_details={}
        try:
            result_tax=engine.incremental(IncomeEvents(policy_income=rows.taxable_income.sum()),profile)
            tax=result_tax.total
            tax_details={f"tax_detail_{k}":v for k,v in asdict(result_tax).items()}
        except NotImplementedError:
            tax=None
            tax_status="unsupported_policy_tax_mapping"
        annual.append({'year':int(year),**tax_details,'start_surrender_equity':start,'end_surrender_equity':end,
                       'premiums':premium,'withdrawals':withdrawal,'loan_advances':loans,'loan_repayments':repayment,
                       'charges':rows.charges.sum(),'premium_loads':rows.premium_load.sum(),
                       'credited_return':rows.credited_return.sum(),'loan_interest':rows.loan_interest.sum(),
                       'net_death_benefit':rows.net_death_benefit.iloc[-1], 'loan_balance':rows.loan_balance.iloc[-1],
                       'taxable_policy_income':rows.taxable_income.sum(),'incremental_tax':tax,'tax_status':tax_status,
                       'net_change_excluding_external_flows':end-start-premium-repayment+withdrawal+loans,
                       'lapsed':bool(rows.lapsed.iloc[-1])})
        start=end
    return SimulationResult(df,pd.DataFrame(annual),pd.DataFrame(events),{
        'policy_engine':'synthetic_event_policy', 'policy_config':asdict(config),
        'tax_engine':type(engine).__name__, 'tax_law_year':getattr(engine,'tax_year',None), 'scope':'standalone scenario, not additive household tax',
        'warning':'Not carrier-calibrated; assumes qualifying non-MEC. Lapse terminates path. Taxes external.'})
