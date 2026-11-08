import unittest
import importlib.util
from wealthsim.policy import PolicyConfig, PolicyState, step


def config(kind, **kwargs):
    return PolicyConfig(kind, premium_load=0, monthly_admin_fee=0,
                        annual_coi_rate=0, annual_fund_expense=0, **kwargs)


class PolicyTests(unittest.TestCase):
    def test_vul_gains_losses_and_basis(self):
        s = PolicyState()
        row = step(s, config('vul'), premium=1000, market_return=.1)
        self.assertAlmostEqual(row.account_value, 1100)
        self.assertEqual(row.taxable_income, 0)
        row = step(s, config('vul'), market_return=-.5)
        self.assertAlmostEqual(row.account_value, 550)
        self.assertEqual(s.tax_basis, 1000)

    def test_iul_cap_applies_at_twelve_month_maturity(self):
        s = PolicyState()
        for m in range(12):
            row = step(s, config('iul'), premium=1000 if m == 0 else 0,
                       market_return=.02)
            if m < 11:
                self.assertEqual(row.credited_return, 0)
        self.assertAlmostEqual(row.credited_return, 100)
        self.assertAlmostEqual(s.account_value, 1100)

    def test_iul_floor_does_not_prevent_fee_losses(self):
        s = PolicyState()
        c = PolicyConfig('iul', premium_load=0, monthly_admin_fee=10, annual_coi_rate=0)
        for m in range(12):
            row = step(s, c, premium=1000 if m == 0 else 0, market_return=-.02)
        self.assertAlmostEqual(s.account_value, 880)
        self.assertEqual(row.credited_return, 0)

    def test_staggered_segments(self):
        s = PolicyState()
        for m in range(12):
            row = step(s, config('iul'), premium=1000, market_return=.02)
        self.assertAlmostEqual(row.credited_return, 100)
        self.assertAlmostEqual(s.account_value, 12100)

    def test_basis_first_withdrawal(self):
        s = PolicyState()
        step(s, config('vul'), premium=1000, market_return=.5)
        row = step(s, config('vul'), withdrawal=1100)
        self.assertEqual(row.taxable_income, 100)
        self.assertEqual(s.tax_basis, 0)
        self.assertEqual(s.account_value, 400)

    def test_loan_is_debt_not_taxable_withdrawal(self):
        s = PolicyState()
        c = config('vul', annual_loan_rate=.12)
        step(s, c, premium=1000)
        row = step(s, c, loan=200, market_return=.1)
        self.assertAlmostEqual(row.account_value, 1080)
        self.assertAlmostEqual(row.loan_balance, 202)
        self.assertEqual(row.taxable_income, 0)
        self.assertEqual(s.tax_basis, 1000)

    def test_loan_repayment_releases_collateral(self):
        s = PolicyState()
        c = config('iul', annual_loan_rate=0)
        step(s, c, premium=1000, loan=100)
        step(s, c, loan_repayment=100)
        self.assertEqual(s.loan_collateral, 0)
        self.assertEqual(s.account_value, 1000)
        self.assertAlmostEqual(sum(x.balance for x in s.segments), 1000)
        self.assertEqual(s.tax_basis, 1000)

    def test_lapse_and_no_reactivation(self):
        s = PolicyState()
        c = PolicyConfig('vul', premium_load=0, monthly_admin_fee=100, annual_coi_rate=0)
        row = step(s, c, premium=20)
        self.assertTrue(row.lapsed)
        self.assertEqual(row.net_death_benefit, 0)
        with self.assertRaises(ValueError):
            step(s, c, premium=1000)

    def test_invalid_inputs_leave_balance_untouched(self):
        s = PolicyState()
        for kw in ({'premium': -1}, {'market_return': float('nan')}, {'withdrawal': 1}):
            with self.assertRaises(ValueError):
                step(s, config('vul'), **kw)
            self.assertEqual(s.account_value, 0)
            self.assertEqual(s.month, 0)

    def test_surrender_value_and_cashflow_reconcile(self):
        s = PolicyState()
        c = PolicyConfig('vul', annual_coi_rate=0, surrender_charge=100)
        row = step(s, c, premium=1000, market_return=.01)
        self.assertAlmostEqual(row.account_value, row.premium-row.premium_load-row.charges+row.credited_return)
        self.assertAlmostEqual(row.cash_surrender_value, row.account_value-100)


class LifelibIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('lifelib'),
                         'optional insurance dependency not installed')
    def test_actual_packaged_iul_and_vul_models(self):
        from wealthsim.policy import lifelib_reference_projection
        for kind, expected_first, expected_24th in (
            ('iul', 9383.636985, 16517.060472),
            ('vul', 50506.224463, 62749.184599),
        ):
            df = lifelib_reference_projection(kind, months=24)
            self.assertEqual(df.shape, (24, 7))
            self.assertAlmostEqual(df.iloc[0]['av_pp'], expected_first, places=4)
            self.assertAlmostEqual(df.iloc[-1]['av_pp'], expected_24th, places=4)


if __name__ == '__main__':
    unittest.main()
