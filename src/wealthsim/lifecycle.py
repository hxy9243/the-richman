"""Monthly household cash-flow API. Synthetic policy mechanics; explicit tax scope.

No network, brokerage orders, implicit borrowing, or silent asset liquidation.
All money is nominal. Taxes are assessed annually and paid from checking if
possible; the unpaid amount remains a liability. Unknown taxes remain unknown.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from math import isfinite
import numpy as np
import pandas as pd
from .accounts import Account, nonnegative
from .engine import SimulationResult
from .markets import validate_market
from .policy import PolicyConfig, PolicyState, step
from .tax import IncomeEvents, TaxProfile, SyntheticTaxEngine
from .retirement import PlanLoan


@dataclass(frozen=True)
class Salary:
    start: str
    end: str
    monthly_gross: float
    traditional_account: str | None = None
    traditional_rate: float = 0
    roth_account: str | None = None
    roth_rate: float = 0
    # Explicit scenario inputs, not an inferred eligibility or current-law claim.
    annual_employee_limit: float = 0
    employer_match_rate: float = 0
    employer_match_max_salary_rate: float = 0
    employer_account: str | None = None
    monthly_payroll_tax: float = 0
    annual_growth: float = 0


@dataclass(frozen=True)
class Spending:
    start: str
    end: str
    monthly_amount: float
    annual_inflation: float = 0
    coefficient_of_variation: float = 0
    seed: int = 0


def _active(month, start, end):
    return pd.Period(start, 'M') <= month <= pd.Period(end, 'M')


def _finite(value, name):
    if not isfinite(value):
        raise ValueError(f'{name} must be finite')


def simulate_household(market, *, accounts=None, policies=None, salaries=(), spending=(),
                       events=(), initial_cash=0., initial_prices=None,
                       tax_engine=None, profile=None, annual_inflation=0., shortfall_mode="event"):
    """Compose salary, accounts, insurance, events and spending into one ledger.

    ``accounts`` maps names to taxable/traditional/roth. ``policies`` maps names
    to {config: PolicyConfig, symbol: str}. Salary contributions enter retirement
    CASH, not an implicit investment. Supply recurring ``buy`` events to invest.
    ``events`` have month/type; recurring events may instead have start/end.
    Order: salary, user events in given order, recurring spending, market/policy
    growth, then December/final-month annual tax settlement. Event types:
    deposit, spend, settle_obligations, buy, sell, premium, policy_loan, policy_repay, policy_withdraw,
    plan_loan, plan_repay. Loan repayments are explicit, never automatic.
    Cash shortages emit events by default; unpaid spending becomes a liability.
    This models liquidity distress, not a legal bankruptcy proceeding.
    Plan loans currently support traditional accounts only; Roth plan loan tax
    and basis rules are deliberately unsupported. See docs/lifecycle.md.
    """
    if shortfall_mode not in ("event", "raise"):
        raise ValueError("shortfall_mode must be event or raise")
    market = validate_market(market)
    months = sorted(market.month.unique()); symbols = set(market.symbol)
    accounts = accounts or {}; policies = policies or {}
    state = {name: Account(kind) for name, kind in accounts.items()}
    if set(state) & set(policies):
        raise ValueError('account and policy names must be unique')
    prices = dict(initial_prices or {s: 100. for s in symbols})
    if set(prices) != symbols or any(not isfinite(p) or p <= 0 for p in prices.values()):
        raise ValueError('invalid initial prices')
    cash = nonnegative(initial_cash, 'initial_cash')
    nonnegative(annual_inflation, 'annual_inflation')
    pstate = {name: PolicyState() for name in policies}; active = set()
    for p in policies.values():
        if p['symbol'] not in symbols or not isinstance(p['config'], PolicyConfig):
            raise ValueError('invalid policy configuration')
    salary_rules = [s if isinstance(s, Salary) else Salary(**s) for s in salaries]
    spending_rules = [s if isinstance(s, Spending) else Spending(**s) for s in spending]
    for s in salary_rules:
        for name in ('monthly_gross', 'traditional_rate', 'roth_rate', 'annual_employee_limit',
                     'employer_match_rate','employer_match_max_salary_rate','monthly_payroll_tax'):
            nonnegative(getattr(s,name), name)
        if s.traditional_rate + s.roth_rate > 1 or s.annual_growth <= -1:
            raise ValueError('invalid salary rates')
        _finite(s.annual_growth, 'annual_growth')
        if s.traditional_rate and state[s.traditional_account].kind != 'traditional':
            raise ValueError('traditional contribution needs traditional account')
        if s.roth_rate and state[s.roth_account].kind != 'roth':
            raise ValueError('Roth contribution needs Roth account')
        if s.employer_match_rate and state[s.employer_account].kind != 'traditional':
            raise ValueError('employer match requires traditional account')
        if pd.Period(s.end,'M') < pd.Period(s.start,'M'):
            raise ValueError('salary end before start')
    for s in spending_rules:
        for name in ('monthly_amount', 'annual_inflation', 'coefficient_of_variation'):
            nonnegative(getattr(s,name),name)
        if pd.Period(s.end,'M') < pd.Period(s.start,'M'):
            raise ValueError('spending end before start')
    # Independent spending RNGs ensure adding a market generator does not change spending.
    rngs = [np.random.default_rng(s.seed) for s in spending_rules]
    expanded = defaultdict(list)
    for raw in events:
        e = dict(raw)
        if 'month' in e:
            selected = [pd.Period(e['month'],'M')]
            if selected[0] not in months: raise ValueError('event outside scenario')
        else:
            selected = [m for m in months if _active(m,e['start'],e['end'])]
            if not selected: raise ValueError('recurrence outside scenario')
        for m in selected: expanded[m].append(e)
    engine = tax_engine or SyntheticTaxEngine(); profile = profile or TaxProfile()
    if profile.baseline_ordinary_income:
        raise ValueError('household API requires explicit salary; baseline ordinary income must be zero')
    loans = {}; loan_accounts = {}; rows = []; journal = []; annual = []
    fields = defaultdict(float); year_start = initial_cash; taxes_payable = 0.; unknown_tax = False
    unpaid_obligations = 0.; loan_tax_unresolved = False; insolvency_last_month = False
    ever_loss = False; contributions = defaultdict(float); plan_limit = {}
    # A single combined employee-deferral limit applies across all employers/accounts.
    for s in salary_rules:
        for y in range(pd.Period(s.start,'M').year, pd.Period(s.end,'M').year+1):
            if y in plan_limit and plan_limit[y] != s.annual_employee_limit:
                raise ValueError('salary rules must share annual employee limit within year')
            plan_limit[y] = s.annual_employee_limit

    def debit(amount, source, *, obligation=False, allow_partial=True):
        nonlocal cash, unpaid_obligations
        amount = nonnegative(amount, 'cash outflow')
        available = max(0., cash)
        funded = min(amount, available) if allow_partial or amount <= available + 1e-8 else 0.
        shortage = max(0., amount - funded)
        if shortage > 1e-8:
            if shortfall_mode == 'raise':
                raise ValueError('cash shortfall: add an explicit sale/withdrawal/loan before spending')
            flows['cash_shortfall'] += shortage
            journal.append({'month':str(m), 'type':'cash_shortfall', 'source':source,
                'requested':amount, 'funded':funded, 'unfunded':shortage,
                'creates_obligation':obligation})
            if obligation:
                unpaid_obligations += shortage
                flows['new_unpaid_obligations'] += shortage
        cash = max(0., cash-funded)
        return funded

    def flag_plan_review(name, reason):
        nonlocal loan_tax_unresolved
        loan = loans[name]
        if not loan.needs_tax_review:
            loan.mark_default()
            loan_tax_unresolved = True
            journal.append({'month':str(m), 'type':'plan_loan_review_required',
                'loan_id':name, 'reason':reason, 'balance_at_review':loan.balance,
                'future_balance_status':'unmodeled_pending_plan_rules'})

    def equity():
        # Plan receivable is a plan asset and matching household liability.
        invested = sum(a.value(prices) for a in state.values())
        policy_equity = sum(max(0,pstate[n].account_value-pstate[n].loan_balance-
                           policies[n]['config'].surrender_charge) for n in policies)
        return cash + invested + policy_equity - taxes_payable - unpaid_obligations

    for index, m in enumerate(months):
        flows = defaultdict(float); policy_args = defaultdict(lambda: defaultdict(float))
        for s in salary_rules:
            if not _active(m,s.start,s.end): continue
            years = (m.ordinal-pd.Period(s.start,'M').ordinal)//12
            gross = s.monthly_gross*(1+s.annual_growth)**years
            room = max(0,plan_limit[m.year]-contributions[m.year])
            desired = gross*(s.traditional_rate+s.roth_rate)
            contribution = min(room,desired)
            trad = contribution*s.traditional_rate/(s.traditional_rate+s.roth_rate) if desired else 0
            roth = contribution-trad
            if gross < contribution+s.monthly_payroll_tax: raise ValueError('payroll exceeds salary')
            cash += gross-contribution-s.monthly_payroll_tax
            if trad: state[s.traditional_account].deposit(trad)
            if roth: state[s.roth_account].deposit(roth)
            contributions[m.year] += contribution
            match = s.employer_match_rate*min(contribution,gross*s.employer_match_max_salary_rate)
            if match: state[s.employer_account].deposit(match)
            flows['gross_wages'] += gross; flows['taxable_wages'] += gross-trad
            flows['traditional_401k'] += trad; flows['roth_401k'] += roth
            flows['employer_match'] += match; flows['payroll_tax_paid'] += s.monthly_payroll_tax
        for e in expanded[m]:
            kind = e['type']; amount = nonnegative(e.get('amount',0),'event amount')
            if kind == 'deposit': cash += amount; flows['external_deposits'] += amount
            elif kind == 'spend':
                paid = debit(amount, 'spend', obligation=True)
                flows['spending'] += paid; flows['spending_incurred'] += amount
            elif kind == 'settle_obligations':
                paid = debit(min(amount,unpaid_obligations), 'settle_obligations')
                unpaid_obligations -= paid; flows['obligations_paid'] += paid
            elif kind == 'buy':
                a=state[e['account']]
                # Explicit transfers from household checking only to taxable accounts.
                if e.get('from_checking',False):
                    if a.kind != 'taxable': raise ValueError('retirement funding must use payroll')
                    amount = debit(amount, "buy"); a.deposit(amount)
                a.buy(e['symbol'],amount,prices[e['symbol']],m.start_time.date())
            elif kind == 'sell':
                a=state[e['account']]
                st,lt=a.sell(e['symbol'],e['units'],prices[e['symbol']],m.start_time.date())
                ever_loss |= a.last_sale_had_loss
                flows['short_term_gains']+=st; flows['long_term_gains']+=lt
            elif kind == 'withdraw':
                a=state[e['account']]
                if a.kind != 'taxable': raise ValueError('retirement distributions require a future validated withdrawal adapter')
                a.withdraw(amount); cash+=amount
            elif kind in ('premium','policy_loan','policy_repay','policy_withdraw'):
                name=e['policy']; cfg=policies[name]['config']; ps=pstate[name]
                if ps.lapsed:
                    journal.append({'month':str(m),'type':'policy_event_rejected','policy':name,
                        'requested_type':kind,'requested':amount,'reason':'policy_lapsed'})
                    continue
                if kind in ('premium','policy_repay'): amount = debit(amount, kind)
                else: cash+=amount
                key={'premium':'premium','policy_loan':'loan','policy_repay':'loan_repayment','policy_withdraw':'withdrawal'}[kind]
                policy_args[name][key]+=amount
                if amount: active.add(name)
                flows[kind]+=amount
            elif kind == 'plan_loan':
                name=e['loan_id']; account=e['account']; a=state[account]
                if name in loans or a.kind!='traditional': raise ValueError('new loan id and traditional plan required')
                if any(loan_accounts[k]==account and loans[k].balance>1e-8 for k in loans):
                    raise ValueError('only one outstanding loan per account supported')
                loan=PlanLoan(principal=amount,vested_balance=a.value(prices),
                    annual_rate=e['annual_rate'],months=e['months'],plan_permitted=e.get('plan_permitted',False),
                    eligibility_validated=e.get('eligibility_validated',False),
                    highest_balance_last12=e.get('highest_balance_last12',0))
                a.withdraw(amount); cash+=amount; loans[name]=loan; loan_accounts[name]=account
                flows['plan_loan_advances']+=amount
            elif kind == 'plan_repay':
                loan=loans[e['loan_id']]
                if loan.needs_tax_review:
                    journal.append({'month':str(m),'type':'plan_repayment_unmodeled',
                        'loan_id':e['loan_id'],'reason':'prior_unresolved_installment'})
                    continue
                scheduled=min(loan.payment,loan.balance*(1+loan.annual_rate/12))
                paid=debit(scheduled, 'plan_repay', allow_partial=False)
                if paid < scheduled - 1e-8:
                    flag_plan_review(e['loan_id'], 'insufficient_cash_for_installment')
                    continue
                payment=loan.step()
                state[loan_accounts[e['loan_id']]].deposit(payment.payment)
                flows['plan_repayments']+=payment.payment; flows['plan_interest']+=payment.interest
            else: raise ValueError(f'unsupported household event: {kind}')
            journal.append({'month':str(m),**e,'checking_after':cash})
        for i,s in enumerate(spending_rules):
            if not _active(m,s.start,s.end): continue
            elapsed=m.ordinal-pd.Period(s.start,'M').ordinal
            mean=s.monthly_amount*(1+s.annual_inflation)**(elapsed/12)
            sigma=np.sqrt(np.log1p(s.coefficient_of_variation**2))
            amount=mean*np.exp(rngs[i].normal(-sigma*sigma/2,sigma)) if sigma else mean
            paid=debit(amount, 'recurring_spending', obligation=True)
            flows['spending']+=paid; flows['spending_incurred']+=amount
        returns=market[market.month==m]
        for r in returns.itertuples():
            for a in state.values():
                div=a.units(r.symbol)*prices[r.symbol]*r.dividend_yield; a.cash+=div
                if a.kind=='taxable': flows['ordinary_dividends']+=div
            prices[r.symbol]*=1+r.price_return
        policy_income=0.
        for name in active:
            if pstate[name].lapsed: continue
            p=policies[name]; r=returns[returns.symbol==p['symbol']].iloc[0]
            report=step(pstate[name],p['config'],market_return=r.price_return+
                (r.dividend_yield if p['config'].kind=='vul' else 0),**policy_args[name])
            policy_income+=report.taxable_income
            flows['policy_charges']+=report.charges+report.premium_load
            flows['policy_loan_interest']+=report.loan_interest
            journal.append({**asdict(report),'month':str(m),'type':'policy_month','policy':name})
        flows['policy_income']+=policy_income
        # Missing an installment is explicitly unsupported; no pretend interest-free loan.
        for name,loan in loans.items():
            if loan.balance>1e-8 and not any(e['type']=='plan_repay' and e['loan_id']==name for e in expanded[m]):
                if not any(e['type']=='plan_loan' and e['loan_id']==name for e in expanded[m]):
                    if shortfall_mode == 'raise':
                        raise ValueError('missed plan-loan repayment/default requires explicit tax review')
                    flag_plan_review(name, 'missing_installment_event')
        for key,value in flows.items(): fields[key]+=value
        before_tax=equity(); settled=0.; tax_due=None; status='not_year_end'
        if m.month==12 or index==len(months)-1:
            incomes=IncomeEvents(ordinary_income=fields['taxable_wages'],
                short_term_gains=fields['short_term_gains'],long_term_gains=fields['long_term_gains'],
                ordinary_dividends=fields['ordinary_dividends'],policy_income=fields['policy_income'])
            try:
                if loan_tax_unresolved: raise NotImplementedError('plan-loan missed payment needs plan/tax review')
                if ever_loss: raise NotImplementedError('realized losses require wash-sale/carryforward adapter')
                tax=engine.calculate(incomes,profile); tax_due=tax.total; status='estimated'
                # Total tax, not sum of standalone strategy incremental estimates.
                taxes_payable+=tax_due
                settled=min(cash,taxes_payable); cash-=settled; taxes_payable-=settled
                if taxes_payable > 1e-8:
                    journal.append({'month':str(m),'type':'unpaid_tax', 'amount':taxes_payable})
                details={f'tax_{k}':v for k,v in asdict(tax).items()}
            except NotImplementedError as exc:
                unknown_tax=True; status=str(exc); details={}
            end=equity(); real=end/(1+annual_inflation)**((index+1)/12)
            external=fields['gross_wages']+fields['employer_match']+fields['external_deposits']
            # Residual is market + policy effects, not salary or loan proceeds.
            pnl=before_tax-year_start-external+fields['spending_incurred']+fields['payroll_tax_paid']
            annual.append({'year':m.year,'partial_year':sum(x.year==m.year for x in months)<12,
                'start_net_equity':year_start,**dict(fields),'investment_policy_net_change':pnl,
                **details,'income_tax_assessed':tax_due,'income_tax_paid':settled,
                'income_tax_payable':taxes_payable,'unpaid_obligations':unpaid_obligations,
                'liquidity_distress':unpaid_obligations > 1e-8 or taxes_payable > 1e-8,
                'balance_sheet_insolvent_before_unknown_tax':end < -1e-8,'tax_status':status,
                'end_equity_before_unknown_tax':end,'end_net_equity':None if unknown_tax else end,
                'end_real_net_equity':None if unknown_tax else real})
            year_start=end; fields=defaultdict(float)
        insolvent=equity() < -1e-8
        if insolvent and not insolvency_last_month:
            journal.append({'month':str(m),'type':'balance_sheet_insolvency',
                'net_equity_before_unknown_tax':equity(), 'legal_bankruptcy':False})
        insolvency_last_month=insolvent
        rows.append({'month':str(m),'checking':cash,'unpaid_obligations':unpaid_obligations,
                     'balance_sheet_insolvent_before_unknown_tax':insolvent,
                     'loan_balance_unresolved':loan_tax_unresolved,'net_equity_before_unknown_tax':equity(),
                     'tax_paid':settled,'tax_payable':taxes_payable,**dict(flows),
                     **{f'policy_value_{n}':p.account_value for n,p in pstate.items()},
                     **{f'policy_debt_{n}':p.loan_balance for n,p in pstate.items()},
                     **{f'policy_lapsed_{n}':p.lapsed for n,p in pstate.items()},
                     **{f'equity_{n}':a.value(prices) for n,a in state.items()},
                     **{f'plan_loan_{n}':loan.balance for n,loan in loans.items()}})
    return SimulationResult(pd.DataFrame(rows).fillna(0),pd.DataFrame(annual),pd.DataFrame(journal),{
        'api':'simulate_household/v2','shortfall_mode':shortfall_mode,'tax_engine':type(engine).__name__,
        'tax_coverage':('federal income tax only; state/local taxes omitted; payroll supplied separately'
                        if type(engine).__name__=='TaxCalculatorEngine' else 'synthetic illustrative tax configuration, not current law'),
        'net_equity_scope':'net only of modeled taxes, not a full after-tax liquidation value',
        'tax_year':getattr(engine,'tax_year',None),'policy_engine':'synthetic_event_policy',
        'policy_configs':{name:{'symbol':p['symbol'],'config':asdict(p['config'])} for name,p in policies.items()},
        'scope':'nominal monthly household, annual taxes settled from checking; unpaid tax liability retained',
        'assumptions':['employee 401k cap caller supplied; no eligibility/catch-up/415(c) validation',
        'employer match immediately vested; Roth 401k distributions unsupported',
        'payroll tax is an explicit supplied monthly amount, not a FICA/SDI engine',
        'missed plan installments emit review events; balance freezes and taxes become unknown',
        'plan loan receivable and household liability offset in net equity',
        'no automatic liquidation or borrowing; shortages emit events by default',
        'unpaid spending is an interest-free modeled obligation; not a legal bankruptcy forecast',
        'unfunded investment/premium requests are skipped or partially funded, not new debt',
        'realized loss or unsupported policy tax mapping withholds net-after-tax estimate']})
