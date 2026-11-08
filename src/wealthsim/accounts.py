"""FIFO investment ledger. Wash sales intentionally rejected as unsupported."""
from dataclasses import dataclass, field
from datetime import date
from math import isfinite


def nonnegative(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


@dataclass
class Lot:
    acquired: date
    units: float
    cost: float


@dataclass
class Account:
    kind: str = "taxable"
    cash: float = 0.0
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    roth_basis: float = 0.0
    last_sale_had_loss: bool = False

    def __post_init__(self):
        if self.kind not in {"taxable", "traditional", "roth"}:
            raise ValueError("unsupported account kind")
        nonnegative(self.cash, "cash")

    def units(self, symbol):
        return sum(l.units for l in self.lots.get(symbol, []))

    def value(self, prices):
        return self.cash + sum(self.units(s) * prices[s] for s in self.lots)

    def deposit(self, amount):
        self.cash += nonnegative(amount, "deposit")
        if self.kind == "roth":
            self.roth_basis += amount

    def withdraw(self, amount, *, qualified=False):
        amount = nonnegative(amount, "withdrawal")
        if amount > self.cash + 1e-8:
            raise ValueError("insufficient cash; sell holdings first")
        if self.kind == "roth" and not qualified and amount > self.roth_basis + 1e-8:
            raise ValueError("nonqualified Roth earnings withdrawals are unsupported")
        self.cash -= amount
        if self.kind == "roth":
            self.roth_basis = max(0, self.roth_basis - amount)
        return amount if self.kind == "traditional" else 0.0

    def buy(self, symbol, amount, price, when):
        amount = nonnegative(amount, "purchase")
        if price <= 0 or not isfinite(price):
            raise ValueError("price must be positive and finite")
        if amount > self.cash + 1e-8:
            raise ValueError("insufficient cash")
        self.cash -= amount
        self.lots.setdefault(symbol, []).append(Lot(when, amount / price, amount))

    def sell(self, symbol, units, price, when):
        units = nonnegative(units, "sale units")
        if price <= 0 or not isfinite(price):
            raise ValueError("price must be positive and finite")
        if units > self.units(symbol) + 1e-8:
            raise ValueError("insufficient units")
        remaining, short, long = units, 0.0, 0.0
        self.last_sale_had_loss = False
        for lot in self.lots.get(symbol, []):
            take = min(remaining, lot.units)
            if take <= 0:
                continue
            basis = lot.cost * take / lot.units
            gain = take * price - basis
            if gain < -1e-8 and self.kind == "taxable":
                self.last_sale_had_loss = True
            # More than one year; same anniversary does not qualify.
            try:
                anniversary = lot.acquired.replace(year=lot.acquired.year + 1)
            except ValueError:
                anniversary = date(lot.acquired.year + 1, 2, 28)
            if when > anniversary:
                long += gain
            else:
                short += gain
            lot.units -= take
            lot.cost -= basis
            remaining -= take
        self.cash += units * price
        if self.kind != "taxable":
            return 0.0, 0.0
        return short, long
