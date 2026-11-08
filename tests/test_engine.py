import unittest
import pandas as pd
from wealthsim.engine import simulate
from wealthsim.markets import bootstrap_blocks, validate_market


class EngineTests(unittest.TestCase):
    def market(self, returns):
        return pd.DataFrame([dict(month=str(m), symbol="SPY", price_return=r, dividend_yield=0)
             for m, r in zip(pd.period_range("2026-01", periods=len(returns), freq="M"), returns)])

    def test_market_gain_is_not_taxable_until_sold(self):
        e = [dict(month="2026-01", account="a", type="deposit", amount=1000),
             dict(month="2026-01", account="a", type="buy", symbol="SPY", amount=1000)]
        result = simulate(self.market([.1, -.1]), e, {"a": "taxable"})
        self.assertAlmostEqual(result.annual.end_equity.iloc[0], 990)
        self.assertEqual(result.annual.incremental_tax.iloc[0], 0)
        self.assertAlmostEqual(result.annual.equity_reconciliation_error.iloc[0], 0)

    def test_sale_tax_and_loss_refusal(self):
        e = [dict(month="2026-01", account="a", type="deposit", amount=1000),
             dict(month="2026-01", account="a", type="buy", symbol="SPY", amount=1000),
             dict(month="2026-02", account="a", type="sell", symbol="SPY", units=10)]
        result = simulate(self.market([.1, 0]), e, {"a": "taxable"})
        self.assertAlmostEqual(result.annual.short_term_gains.iloc[0], 100)
        result = simulate(self.market([-.1, 0]), e, {"a": "taxable"})
        self.assertIsNone(result.annual.incremental_tax.iloc[0])
        self.assertIn("unsupported", result.annual.tax_status.iloc[0])

    def test_retirement_trade_no_realized_tax(self):
        e = [dict(month="2026-01", account="a", type="deposit", amount=1000),
             dict(month="2026-01", account="a", type="buy", symbol="SPY", amount=1000),
             dict(month="2026-02", account="a", type="sell", symbol="SPY", units=10)]
        result = simulate(self.market([.1, 0]), e, {"a": "roth"})
        self.assertEqual(result.annual.incremental_tax.iloc[0], 0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            simulate(self.market([0]), [dict(month="2025-01",account="a",type="deposit",amount=1)], {"a":"taxable"})
        with self.assertRaises(ValueError):
            validate_market(self.market([-1]))
        with self.assertRaises(ValueError):
            validate_market(pd.concat([self.market([0]), self.market([0])]))

    def test_reproducible_bootstrap(self):
        f = self.market([.01] * 24)
        pd.testing.assert_frame_equal(bootstrap_blocks(f, 2, seed=42), bootstrap_blocks(f, 2, seed=42))

    def test_year_boundaries(self):
        e=[dict(month="2026-01",account="a",type="deposit",amount=1000),
           dict(month="2026-01",account="a",type="buy",symbol="SPY",amount=1000),
           dict(month="2027-02",account="a",type="sell",symbol="SPY",units=10)]
        r=simulate(self.market([.01]*14),e,{"a":"taxable"})
        self.assertEqual(len(r.annual),2)
        self.assertGreater(r.annual.long_term_gains.iloc[1],0)
        self.assertAlmostEqual(r.annual.start_equity.iloc[1],r.annual.end_equity.iloc[0])

    def test_loss_contaminates_subsequent_year_tax(self):
        e=[dict(month='2026-01',account='a',type='deposit',amount=1000),
           dict(month='2026-01',account='a',type='buy',symbol='SPY',amount=1000),
           dict(month='2026-02',account='a',type='sell',symbol='SPY',units=5)]
        r=simulate(self.market([-.1]+[0]*12),e,{'a':'taxable'})
        self.assertTrue(r.annual.incremental_tax.isna().all())

    def test_market_normalization_and_initial_price(self):
        f=self.market([.1]); f['price_return']='0.1'
        v=validate_market(f)
        pd.testing.assert_frame_equal(v,validate_market(v))
        self.assertEqual(v.price_return.iloc[0],.1)
        f['month']=None
        with self.assertRaises(ValueError):validate_market(f)
        with self.assertRaises(ValueError):simulate(self.market([0]),[],{'a':'taxable'},initial_prices={'SPY':float('nan')})
