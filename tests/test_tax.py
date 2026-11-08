import unittest
from wealthsim.tax import IncomeEvents, TaxConfig, TaxProfile, SyntheticTaxEngine


class TaxTests(unittest.TestCase):
    def setUp(self):
        self.engine = SyntheticTaxEngine()

    def test_capital_gain_stacking(self):
        r = self.engine.calculate(IncomeEvents(long_term_gains=20000), TaxProfile(baseline_ordinary_income=40000))
        self.assertAlmostEqual(r.federal_capital_gains, 1500)
        self.assertAlmostEqual(r.federal_ordinary, 4000)
        self.assertAlmostEqual(r.state_income, 3000)

    def test_niit_is_lesser_of_excess_magi_or_investment_income(self):
        r = self.engine.calculate(IncomeEvents(long_term_gains=20000), TaxProfile(baseline_ordinary_income=190000))
        self.assertAlmostEqual(r.niit, 380)

    def test_retirement_withdrawal_is_not_itself_niit_income(self):
        r = self.engine.calculate(IncomeEvents(traditional_withdrawals=300000))
        self.assertEqual(r.niit, 0)
        r = self.engine.calculate(IncomeEvents(traditional_withdrawals=20000, interest=5000), TaxProfile(baseline_ordinary_income=190000))
        self.assertAlmostEqual(r.niit, 190)

    def test_married_niit_threshold(self):
        r = self.engine.calculate(IncomeEvents(interest=20000), TaxProfile('married_joint', 230000))
        self.assertEqual(r.niit, 0)

    def test_state_surcharge_separate(self):
        r = self.engine.calculate(IncomeEvents(ordinary_income=1100000))
        self.assertAlmostEqual(r.state_surcharge, 1000)
        self.assertEqual(r.niit, 0)

    def test_losses_net_against_other_character(self):
        r = self.engine.calculate(IncomeEvents(short_term_gains=-5000, long_term_gains=10000))
        self.assertEqual(r.agi, 5000)
        self.assertEqual(r.short_term_loss_carryforward, 0)
        self.assertEqual(r.long_term_loss_carryforward, 0)

    def test_loss_carryforward_short_first(self):
        r = self.engine.calculate(IncomeEvents(short_term_gains=-5000, long_term_gains=-6000), TaxProfile(baseline_ordinary_income=50000))
        self.assertEqual(r.agi, 47000)
        self.assertEqual(r.short_term_loss_carryforward, 2000)
        self.assertEqual(r.long_term_loss_carryforward, 6000)

    def test_carryforward_consumed_next_year(self):
        r = self.engine.calculate(IncomeEvents(short_term_gains=20000, short_term_loss_carryforward=2000, long_term_loss_carryforward=6000))
        self.assertEqual(r.agi, 12000)
        self.assertEqual(r.short_term_loss_carryforward + r.long_term_loss_carryforward, 0)

    def test_incremental_tax_not_whole_household(self):
        p = TaxProfile(baseline_ordinary_income=100000)
        r = self.engine.incremental(IncomeEvents(interest=10000), p)
        self.assertAlmostEqual(r.total, 4000)
        self.assertTrue(r.is_incremental)
        self.assertEqual(r.agi, 110000)

    def test_deductible_contribution_saves_tax(self):
        r = self.engine.incremental(IncomeEvents(deductible_contributions=10000), TaxProfile(baseline_ordinary_income=110000))
        self.assertAlmostEqual(r.total, -4000)

    def test_deduction_can_absorb_preferential_income(self):
        e = SyntheticTaxEngine(TaxConfig(federal_deduction=10000))
        r = e.calculate(IncomeEvents(qualified_dividends=5000))
        self.assertEqual(r.federal_ordinary + r.federal_capital_gains, 0)

    def test_validation(self):
        for bad in (float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                IncomeEvents(interest=bad)
        with self.assertRaises(ValueError):
            IncomeEvents(traditional_withdrawals=-1)
        with self.assertRaises(ValueError):
            TaxConfig(ordinary_brackets=((100, .1),))
        with self.assertRaises(ValueError):
            TaxProfile('invalid')


if __name__ == '__main__':
    unittest.main()


class TaxCalculatorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import taxcalc
        except ImportError:
            raise unittest.SkipTest('optional taxcalc dependency not installed')

    def test_real_adapter_niit(self):
        from wealthsim.tax import TaxCalculatorEngine
        r = TaxCalculatorEngine(2026).calculate(IncomeEvents(interest=10000), TaxProfile(baseline_ordinary_income=250000))
        self.assertAlmostEqual(r.niit, 380)
        self.assertEqual(r.agi, 260000)
        self.assertIsNone(r.state_income)
        self.assertEqual(r.total, r.federal_income_tax)

    def test_real_incremental_and_distribution_exclusion(self):
        from wealthsim.tax import TaxCalculatorEngine
        e = TaxCalculatorEngine(2026)
        p = TaxProfile(baseline_ordinary_income=100000)
        r = e.incremental(IncomeEvents(long_term_gains=20000), p)
        self.assertAlmostEqual(r.total, 3000)
        self.assertTrue(r.is_incremental)
        self.assertEqual(e.calculate(IncomeEvents(traditional_withdrawals=300000)).niit, 0)


class PolicyIncomeTests(unittest.TestCase):
    def test_policy_gain_ordinary_and_niit(self):
        r = SyntheticTaxEngine().incremental(IncomeEvents(policy_income=10000), TaxProfile(baseline_ordinary_income=250000))
        self.assertAlmostEqual(r.federal_ordinary, 3000)
        self.assertAlmostEqual(r.niit, 380)

    def test_real_adapter_rejects_policy_gain(self):
        from wealthsim.tax import TaxCalculatorEngine
        with self.assertRaises(NotImplementedError):
            TaxCalculatorEngine().calculate(IncomeEvents(policy_income=1))
