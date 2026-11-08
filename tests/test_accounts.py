import unittest
from datetime import date
from wealthsim.accounts import Account

class AccountTests(unittest.TestCase):
    def test_fifo_and_anniversary(self):
        a=Account();a.deposit(200);a.buy('X',100,10,date(2025,1,1));a.buy('X',100,20,date(2025,7,1))
        st,lt=a.sell('X',12,30,date(2026,1,2))
        self.assertEqual(lt,200);self.assertEqual(st,20)
        self.assertAlmostEqual(a.units('X'),3)
    def test_roth_basis_and_cash_guards(self):
        a=Account('roth');a.deposit(100)
        with self.assertRaises(ValueError):a.buy('X',101,1,date.today())
        a.cash=200
        with self.assertRaises(ValueError):a.withdraw(101)
        a.withdraw(100);self.assertEqual(a.roth_basis,0)
    def test_nonfinite(self):
        with self.assertRaises(ValueError):Account().deposit(float('nan'))
