import unittest
import pandas as pd
from wealthsim.policy import PolicyConfig
from wealthsim.policy_runner import simulate_policy

class RunnerTests(unittest.TestCase):
    def test_annual_policy_summary(self):
        frame=pd.DataFrame([dict(month=str(m),symbol='SPY',price_return=.01,dividend_yield=.001)
              for m in pd.period_range('2026-01',periods=24,freq='M')])
        events=[{'month':str(m),'premium':1000} for m in pd.period_range('2026-01',periods=24,freq='M')]
        r=simulate_policy(frame,events,PolicyConfig('iul'),'SPY')
        self.assertEqual(len(r.monthly),24)
        self.assertEqual(len(r.annual),2)
        self.assertEqual(r.annual.premiums.iloc[0],12000)
        self.assertGreater(r.annual.credited_return.iloc[0],0)
        self.assertEqual(r.annual.start_surrender_equity.iloc[1],r.annual.end_surrender_equity.iloc[0])
