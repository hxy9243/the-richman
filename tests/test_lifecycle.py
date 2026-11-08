import unittest
import pandas as pd
from wealthsim.lifecycle import simulate_household, Salary, Spending
from wealthsim.policy import PolicyConfig
from wealthsim.tax import SyntheticTaxEngine,TaxConfig


def market(months=12, rate=0):
    return pd.DataFrame([{'month':str(m),'symbol':'SPY','price_return':rate,'dividend_yield':0}
        for m in pd.period_range('2026-01',periods=months,freq='M')])

ZERO=SyntheticTaxEngine(TaxConfig(ordinary_brackets=((0,0),),state_brackets=((0,0),),
    capital_gains_brackets=((0,0),),niit_rate=0,state_surcharge_rate=0))

class LifecycleTests(unittest.TestCase):
    def test_payroll_limit_spending_and_consolidation(self):
        r=simulate_household(market(),accounts={'t':'traditional','r':'roth'},
            salaries=[Salary('2026-01','2026-12',10000,'t',.1,'r',.1,20000,
                             employer_match_rate=1,employer_match_max_salary_rate=.05,employer_account='t')],
            spending=[Spending('2026-01','2026-12',1000)],tax_engine=ZERO)
        a=r.annual.iloc[0]
        self.assertAlmostEqual(a.traditional_401k,10000)
        self.assertAlmostEqual(a.roth_401k,10000)
        self.assertAlmostEqual(a.employer_match,5000)
        self.assertAlmostEqual(a.end_net_equity,113000)
        self.assertAlmostEqual(a.investment_policy_net_change,0)
    def test_wage_taxes_paid_and_unpaid(self):
        r=simulate_household(market(),salaries=[Salary('2026-01','2026-12',10000)],
            spending=[Spending('2026-01','2026-12',10000)])
        a=r.annual.iloc[0]
        self.assertGreater(a.income_tax_payable,0)
        self.assertLess(a.end_net_equity,0)
        self.assertEqual(a.income_tax_paid,0)
    def test_spending_reproducible(self):
        s=Spending('2026-01','2026-12',1000,coefficient_of_variation=.2,seed=42)
        a=simulate_household(market(),initial_cash=50000,spending=[s],tax_engine=ZERO)
        b=simulate_household(market(),initial_cash=50000,spending=[s],tax_engine=ZERO)
        self.assertEqual(a.monthly.spending.tolist(),b.monthly.spending.tolist())
        self.assertGreater(a.monthly.spending.std(),0)
    def test_shortfall_is_not_hidden(self):
        with self.assertRaisesRegex(ValueError,'cash shortfall'):
            simulate_household(market(),spending=[Spending('2026-01','2026-12',1)])
    def test_policy_loan_does_not_create_equity(self):
        cfg=PolicyConfig('vul',premium_load=0,monthly_admin_fee=0,annual_coi_rate=0,
                         annual_fund_expense=0,annual_loan_rate=0)
        r=simulate_household(market(2),initial_cash=10000,policies={'v':{'config':cfg,'symbol':'SPY'}},
            events=[{'month':'2026-01','type':'premium','policy':'v','amount':10000},
                    {'month':'2026-02','type':'policy_loan','policy':'v','amount':1000},
                    {'month':'2026-02','type':'spend','amount':1000}],tax_engine=ZERO)
        self.assertAlmostEqual(r.annual.iloc[0].end_net_equity,9000)
    def test_plan_loan_repayment_no_double_count(self):
        r=simulate_household(market(3),accounts={'t':'traditional'},initial_cash=1000,
            salaries=[Salary('2026-01','2026-01',10000,'t',1,annual_employee_limit=10000)],
            events=[{'month':'2026-01','type':'plan_loan','loan_id':'x','account':'t','amount':2000,
                     'annual_rate':.06,'months':2,'plan_permitted':True,'eligibility_validated':True},
                    {'start':'2026-02','end':'2026-03','type':'plan_repay','loan_id':'x'}],tax_engine=ZERO)
        self.assertAlmostEqual(r.annual.iloc[0].end_net_equity,11000)
        self.assertAlmostEqual(r.monthly.iloc[-1].plan_loan_x,0)
    def test_missing_plan_repayment_rejected(self):
        with self.assertRaisesRegex(ValueError,'missed plan-loan'):
            simulate_household(market(2),accounts={'t':'traditional'},
              salaries=[Salary('2026-01','2026-01',10000,'t',1,annual_employee_limit=10000)],
              events=[{'month':'2026-01','type':'plan_loan','loan_id':'x','account':'t','amount':2000,
                       'annual_rate':.06,'months':2,'plan_permitted':True,'eligibility_validated':True}],tax_engine=ZERO)
    def test_unrealized_gain_not_taxed_and_realized_loss_unknown(self):
        r=simulate_household(market(3,-.1),accounts={'b':'taxable'},initial_cash=10000,
            events=[{'month':'2026-01','type':'buy','account':'b','symbol':'SPY','amount':1000,'from_checking':True},
                    {'month':'2026-03','type':'sell','account':'b','symbol':'SPY','units':1}],tax_engine=ZERO)
        self.assertIsNone(r.annual.iloc[0].end_net_equity)
        self.assertIn('realized losses',r.annual.iloc[0].tax_status)
    def test_caps_reset_and_real_dollars(self):
        r=simulate_household(market(24),accounts={'t':'traditional'},
            salaries=[Salary('2026-01','2027-12',1000,'t',1,annual_employee_limit=6000)],
            tax_engine=ZERO,annual_inflation=.1)
        self.assertEqual(r.annual.traditional_401k.tolist(),[6000,6000])
        self.assertAlmostEqual(r.annual.iloc[-1].end_real_net_equity,24000/1.1**2)

if __name__=='__main__': unittest.main()

class PublicApiTests(unittest.TestCase):
    def test_json_round_trip_and_provenance(self):
        import json
        from pathlib import Path
        from wealthsim.api import simulate_scenario
        scenario=json.loads((Path(__file__).parents[1]/'examples/household.json').read_text())
        result=simulate_scenario(scenario)
        self.assertEqual(len(result.annual),2)
        self.assertEqual(result.metadata['market']['path_type'],'stochastic_gbm')
        self.assertTrue((result.annual.end_net_equity>0).all())
