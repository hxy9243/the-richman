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
            simulate_household(market(),spending=[Spending('2026-01','2026-12',1)],shortfall_mode='raise')
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
            simulate_household(market(2),accounts={'t':'traditional'},shortfall_mode='raise',
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


class ShortfallEventTests(unittest.TestCase):
    def test_obligations_and_insolvency_continue(self):
        r=simulate_household(market(12),initial_cash=50,
            spending=[Spending('2026-01','2026-12',100)],tax_engine=ZERO)
        self.assertEqual(len(r.monthly),12)
        self.assertEqual(r.monthly.checking.min(),0)
        self.assertEqual(r.annual.iloc[0].unpaid_obligations,1150)
        self.assertEqual(r.annual.iloc[0].end_net_equity,-1150)
        self.assertEqual(r.annual.iloc[0].investment_policy_net_change,0)
        self.assertEqual(len(r.events[r.events.type=='cash_shortfall']),12)
        self.assertEqual(len(r.events[r.events.type=='balance_sheet_insolvency']),1)

    def test_settle_obligations_does_not_double_count_spending(self):
        r=simulate_household(market(2),events=[
            {'month':'2026-01','type':'spend','amount':100},
            {'month':'2026-02','type':'deposit','amount':150},
            {'month':'2026-02','type':'settle_obligations','amount':100}],tax_engine=ZERO)
        self.assertEqual(r.monthly.iloc[-1].checking,50)
        self.assertEqual(r.annual.iloc[0].unpaid_obligations,0)
        self.assertEqual(r.annual.iloc[0].end_net_equity,50)
        self.assertEqual(r.annual.iloc[0].investment_policy_net_change,0)

    def test_unfunded_premium_not_a_new_obligation(self):
        cfg=PolicyConfig('iul')
        r=simulate_household(market(2),policies={'custom':{'config':cfg,'symbol':'SPY'}},
            events=[{'start':'2026-01','end':'2026-02','type':'premium','policy':'custom','amount':100}],tax_engine=ZERO)
        self.assertEqual(r.annual.iloc[0].unpaid_obligations,0)
        self.assertEqual(r.annual.iloc[0].end_net_equity,0)
        self.assertEqual(r.monthly.policy_value_custom.sum(),0)

    def test_partial_premium_and_lapsed_policy_do_not_stop_run(self):
        cfg=PolicyConfig('vul',premium_load=0,monthly_admin_fee=10,annual_coi_rate=0)
        r=simulate_household(market(3),initial_cash=5,policies={'v':{'config':cfg,'symbol':'SPY'}},
            events=[{'start':'2026-01','end':'2026-03','type':'premium','policy':'v','amount':100}],tax_engine=ZERO)
        self.assertTrue(r.monthly.iloc[0].policy_lapsed_v)
        self.assertEqual(len(r.events[r.events.type=='policy_event_rejected']),2)
        self.assertEqual(r.annual.iloc[0].premium,5)

    def test_insufficient_plan_installment_emits_review_not_false_balance(self):
        r=simulate_household(market(3),accounts={'t':'traditional'},
            salaries=[Salary('2026-01','2026-01',10000,'t',1,annual_employee_limit=10000)],
            events=[{'month':'2026-01','type':'plan_loan','loan_id':'x','account':'t','amount':2000,
                     'annual_rate':.06,'months':2,'plan_permitted':True,'eligibility_validated':True},
                    {'month':'2026-01','type':'spend','amount':2000},
                    {'start':'2026-02','end':'2026-03','type':'plan_repay','loan_id':'x'}],tax_engine=ZERO)
        self.assertEqual(len(r.monthly),3)
        self.assertIsNone(r.annual.iloc[0].end_net_equity)
        self.assertTrue(r.monthly.iloc[-1].loan_balance_unresolved)
        self.assertEqual(len(r.events[r.events.type=='plan_loan_review_required']),1)

    def test_missing_plan_installment_continues(self):
        r=simulate_household(market(3),accounts={'t':'traditional'},
            salaries=[Salary('2026-01','2026-01',10000,'t',1,annual_employee_limit=10000)],
            events=[{'month':'2026-01','type':'plan_loan','loan_id':'x','account':'t','amount':2000,
                     'annual_rate':.06,'months':2,'plan_permitted':True,'eligibility_validated':True}],tax_engine=ZERO)
        self.assertEqual(len(r.monthly),3)
        self.assertEqual(len(r.events[r.events.type=='plan_loan_review_required']),1)
        self.assertIn('plan-loan',r.annual.iloc[0].tax_status)

    def test_custom_policies_json_api(self):
        from wealthsim.api import simulate_scenario
        r=simulate_scenario({'market':{'mode':'historical','rows':market(12).to_dict('records'),
             'source_name':'synthetic zeros','source_start':'2026-01','months':12,'start':'2026-01'},
             'initial_cash':3000,'policies':{
                 'my_iul':{'symbol':'SPY','config':{'kind':'iul','face_amount':100000,'iul_cap':.07}},
                 'my_vul':{'symbol':'SPY','config':{'kind':'vul','annual_fund_expense':.005}}},
             'events':[{'month':'2026-01','type':'premium','policy':'my_iul','amount':1000},
                       {'month':'2026-01','type':'premium','policy':'my_vul','amount':1000}]})
        self.assertIn('policy_value_my_iul',r.monthly)
        self.assertIn('policy_value_my_vul',r.monthly)
