import unittest
from wealthsim.retirement import PlanLoan, available_plan_loan


def loan(**kwargs):
    return PlanLoan(**dict(principal=10000, annual_rate=.06, months=60,
        vested_balance=100000, plan_permitted=True, eligibility_validated=True, **kwargs))


class PlanLoanTests(unittest.TestCase):
    def test_limit_and_existing_loan(self):
        self.assertEqual(available_plan_loan(200000),50000)
        self.assertEqual(available_plan_loan(60000),30000)
        self.assertEqual(available_plan_loan(200000,outstanding_balance=20000,highest_balance_last12=30000),20000)
        self.assertEqual(available_plan_loan(100000,highest_balance_last12=50000),0)
        self.assertEqual(available_plan_loan(10000),5000)  # no optional $10k exception
    def test_paid_over_sixty_months(self):
        a=loan(); payments=[a.step() for _ in range(60)]
        self.assertAlmostEqual(sum(p.principal for p in payments),10000)
        self.assertGreater(sum(p.interest for p in payments),0)
        self.assertEqual(a.balance,0)
        self.assertAlmostEqual(payments[0].interest,50)
        with self.assertRaises(ValueError):a.step()
    def test_tiny_rate(self):
        a=PlanLoan(1200,1e-16,12,5000,True,True)
        self.assertAlmostEqual(a.payment,100)
    def test_zero_rate(self):
        a=PlanLoan(1200,0,12,5000,True,True)
        self.assertEqual(a.payment,100)
        for _ in range(12):a.step()
        self.assertEqual(a.balance,0)
    def test_early_payoff(self):
        a=loan();p=a.step(10050)
        self.assertEqual(p.balance,0)
        self.assertEqual(p.principal,10000)
    def test_invalid_inputs(self):
        for kwargs in [dict(principal=50001),dict(annual_rate=-1),dict(months=61),
                       dict(months=1.5),dict(plan_permitted=False),dict(eligibility_validated=False)]:
            args=dict(principal=10000,annual_rate=.06,months=60,vested_balance=100000,
                      plan_permitted=True,eligibility_validated=True);args.update(kwargs)
            with self.assertRaises(ValueError):PlanLoan(**args)
        for kwargs in [dict(vested_balance=float('nan')),dict(vested_balance=50000,outstanding_balance=1),
                       dict(vested_balance=50000,max_vested_fraction=1.1)]:
            with self.assertRaises(ValueError):available_plan_loan(**kwargs)
    def test_failed_payment_no_mutation(self):
        a=loan()
        for payment in [0,1,float('nan'),20000]:
            with self.assertRaises(ValueError):a.step(payment)
        self.assertEqual(a.balance,10000);self.assertEqual(a.month,0)
    def test_default_and_separation_are_not_taxed_automatically(self):
        for method in ('mark_default','mark_job_separation'):
            a=loan();getattr(a,method)()
            self.assertTrue(a.needs_tax_review);self.assertEqual(a.balance,10000)
            with self.assertRaises(ValueError):a.step()

if __name__=='__main__':unittest.main()
