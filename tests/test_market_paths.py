import unittest
import numpy as np
import pandas as pd
from wealthsim.markets import historical_replay, stochastic_market


class MarketPathTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame([dict(month=str(m), symbol=s, price_return=i / 100, dividend_yield=.001)
            for i, m in enumerate(pd.period_range('2000-01', periods=6, freq='M'))
            for s in ('SPY', 'QQQ')])

    def test_historical_replay_preserves_observations(self):
        result = historical_replay(self.history(), source_name='synthetic test fixture',
                                   source_start='2000-02', months=3, start='2030-01')
        self.assertEqual(result.month.min(), pd.Period('2030-01', freq='M'))
        self.assertEqual(result.source_month.iloc[0], '2000-02')
        self.assertEqual(result.price_return.iloc[0], .01)
        self.assertTrue(result.attrs['calendar_rebased'])
        self.assertEqual(len(result), 6)
        self.assertEqual(result.attrs['source_name'], 'synthetic test fixture')

    def test_no_invented_history_and_source_required(self):
        for kwargs in ({'source_name': ''}, {'source_name': 'test', 'months': 7},
                       {'source_name': 'test', 'months': 1.5},
                       {'source_name': 'test', 'source_start': '1999-12'}):
            with self.assertRaises(ValueError):
                historical_replay(self.history(), **kwargs)

    def test_stochastic_reproducibility_and_seed_variation(self):
        assets = {'SPY': {'annual_drift': .06, 'annual_volatility': .18}}
        a = stochastic_market(assets, months=24, seed=9)
        pd.testing.assert_frame_equal(a, stochastic_market(assets, months=24, seed=9))
        self.assertFalse(a.price_return.equals(stochastic_market(assets, months=24, seed=10).price_return))
        self.assertTrue((a.price_return > -1).all())

    def test_zero_volatility_and_separate_dividends(self):
        a = stochastic_market({'SPY': {'annual_drift': .06, 'annual_volatility': 0,
                                      'annual_dividend_yield': .024}}, months=12)
        self.assertAlmostEqual(np.prod(1 + a.price_return), np.exp(.06))
        self.assertTrue(np.allclose(a.dividend_yield, .002))

    def test_shared_correlation(self):
        assets = {s: {'annual_drift': .06, 'annual_volatility': .2} for s in ('A', 'B')}
        a = stochastic_market(assets, months=6000, correlation=[[1, .7], [.7, 1]], seed=7)
        logs = np.log1p(a.pivot(index='month', columns='symbol', values='price_return'))
        self.assertAlmostEqual(logs.corr().iloc[0, 1], .7, delta=.025)
        perfect = stochastic_market(assets, months=12, correlation=[[1, 1], [1, 1]])
        returns = perfect.pivot(index='month', columns='symbol', values='price_return')
        self.assertTrue(np.allclose(returns.A, returns.B))

    def test_validation(self):
        assets = {'A': {'annual_drift': .06, 'annual_volatility': .2},
                  'B': {'annual_drift': .06, 'annual_volatility': .2}}
        for corr in ([[1, 2], [2, 1]], [[1, .2], [.1, 1]], [[1]], [[1, np.nan], [np.nan, 1]]):
            with self.assertRaises(ValueError):
                stochastic_market(assets, months=12, correlation=corr)
        for months in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                stochastic_market(assets, months=months)
        with self.assertRaises(ValueError):
            stochastic_market({'A': {'annual_drift': .1, 'annual_volatility': -.1}}, months=12)
        with self.assertRaises(ValueError):
            stochastic_market({'A': {'annual_drift': .1, 'annual_volatility': .2, 'typo': 1}}, months=12)


if __name__ == '__main__':
    unittest.main()
