"""Monthly event replay with auditable annual equity and tax bridges.

Events execute at month start in supplied order using prior closing prices.
Returns/dividends follow events; taxes are reported as external liabilities,
NOT silently deducted from an account. Policy cash flows use separate funding.
"""
from dataclasses import asdict, dataclass
from collections import defaultdict
from math import isfinite
import pandas as pd
from .accounts import Account, nonnegative
from .markets import validate_market
from .tax import IncomeEvents, TaxProfile, SyntheticTaxEngine


@dataclass
class SimulationResult:
    monthly: pd.DataFrame
    annual: pd.DataFrame
    events: pd.DataFrame
    metadata: dict

    def export(self, directory):
        from pathlib import Path
        import json
        p = Path(directory)
        p.mkdir(parents=True, exist_ok=True)
        for name in ("monthly", "annual", "events"):
            getattr(self, name).to_csv(p / f"{name}.csv", index=False)
        (p / "metadata.json").write_text(json.dumps(self.metadata, indent=2))


def simulate(market, events, accounts, *, initial_prices=None, tax_engine=None, profile=None):
    """accounts maps names to account kind; starts at zero with explicit deposits.

    Supported events: deposit(amount), buy(symbol,amount), sell(symbol,units),
    withdraw(amount, qualified for Roth), fee(amount). All need month/account.
    Traditional deposits require deductible=True/False; withdrawals require
    penalty_exempt=True (early penalties are deliberately not approximated).
    No loss tax benefit is claimed: realized losses cause tax-estimate refusal.
    """
    market = validate_market(market)
    state = {name: Account(kind) for name, kind in accounts.items()}
    symbols = set(market.symbol)
    prices = dict(initial_prices or {s: 100.0 for s in symbols})
    if set(prices) != symbols or any(not isfinite(v) or v <= 0 for v in prices.values()):
        raise ValueError("initial prices must cover all symbols and be positive")
    by_month = defaultdict(list)
    months = set(market.month)
    for event in events:
        e = dict(event)
        month = pd.Period(e["month"], freq="M")
        if month not in months or e["account"] not in state:
            raise ValueError("event month/account outside scenario")
        if "symbol" in e and e["symbol"] not in symbols:
            raise ValueError("event references unknown symbol")
        by_month[month].append(e)
    tax_engine = tax_engine or SyntheticTaxEngine()
    profile = profile or TaxProfile()
    monthly, journal, annual = [], [], []
    year_fields = defaultdict(lambda: defaultdict(float))
    for month, rows in market.groupby("month", sort=True):
        y = month.year
        start = sum(a.value(prices) for a in state.values())
        year_fields[y].setdefault("start_equity", start)
        flows = defaultdict(float)
        for e in by_month[month]:
            a = state[e["account"]]
            kind = e["type"]
            amount = float(e.get("amount", 0))
            st = lt = ordinary = deduction = 0.0
            loss = False
            if kind == "deposit":
                if a.kind == "traditional" and not e.get("deductible", False):
                    raise ValueError("only explicitly deductible traditional deposits supported; basis tracking not yet implemented")
                a.deposit(amount)
                flows["deposits"] += amount
                if a.kind == "traditional" and e["deductible"]:
                    deduction = amount
            elif kind == "buy":
                a.buy(e["symbol"], amount, prices[e["symbol"]], month.start_time.date())
            elif kind == "sell":
                st, lt = a.sell(e["symbol"], float(e["units"]), prices[e["symbol"]], month.start_time.date())
                loss = a.last_sale_had_loss
            elif kind == "withdraw":
                if a.kind == "traditional" and not e.get("penalty_exempt", False):
                    raise ValueError("traditional withdrawal requires penalty_exempt=True; penalty model not implemented")
                ordinary = a.withdraw(amount, qualified=e.get("qualified", False))
                flows["withdrawals"] += amount
            elif kind == "fee":
                nonnegative(amount, "fee")
                if amount > a.cash:
                    raise ValueError("insufficient cash for fee")
                a.cash -= amount
                flows["fees"] += amount
            else:
                raise ValueError(f"unsupported event type: {kind}")
            flows["short_term_gains"] += st
            flows["long_term_gains"] += lt
            flows["traditional_withdrawals"] += ordinary
            flows["deductible_contributions"] += deduction
            journal.append({**e, "short_term_gain": st, "long_term_gain": lt,
                            "cash_after": a.cash, "has_loss": loss})
        for row in rows.itertuples():
            for a in state.values():
                dividend = a.units(row.symbol) * prices[row.symbol] * row.dividend_yield
                a.cash += dividend
                flows["dividends"] += dividend
                if a.kind == "taxable":
                    flows["ordinary_dividends"] += dividend
            prices[row.symbol] *= 1 + row.price_return
        end = sum(a.value(prices) for a in state.values())
        pnl = end - start - flows["deposits"] + flows["withdrawals"] + flows["fees"]
        rec = {"month": str(month), "start_equity": start, "end_equity": end,
               "market_pnl_including_dividends": pnl, **dict(flows)}
        rec.update({f"equity_{name}": a.value(prices) for name, a in state.items()})
        monthly.append(rec)
        for key, value in flows.items():
            year_fields[y][key] += value
        year_fields[y]["market_pnl_including_dividends"] += pnl
        year_fields[y]["end_equity"] = end
    unresolved_loss = False
    for y, f in year_fields.items():
        tax_inputs = IncomeEvents(**{k: f.get(k, 0) for k in (
            "short_term_gains", "long_term_gains", "ordinary_dividends",
            "traditional_withdrawals", "deductible_contributions")})
        # Losing trades require cross-year capital-loss and wash-sale state.
        # Fail closed rather than manufacture a tax benefit.
        has_loss = any(e.get("has_loss", False)
                       and str(e["month"])[:4] == str(y) for e in journal)
        unresolved_loss = unresolved_loss or has_loss
        tax_details = {}
        if unresolved_loss:
            tax_status, tax = "unsupported_realized_loss_requires_wash_sale_and_carryforward_model", None
        else:
            tax_status = "estimated"
            result_tax = tax_engine.incremental(tax_inputs, profile)
            tax = result_tax.total
            tax_details = {f"tax_detail_{k}":v for k,v in asdict(result_tax).items()}
        reconciliation = f["end_equity"] - (f["start_equity"] + f.get("deposits", 0)
                            - f.get("withdrawals", 0) - f.get("fees", 0)
                            + f["market_pnl_including_dividends"])
        annual.append({"year": y, **dict(f), **tax_details, "incremental_tax": tax,
                       "tax_status": tax_status, "equity_reconciliation_error": reconciliation,
                       "end_equity_less_estimated_tax": None if tax is None else f["end_equity"] - tax})
    return SimulationResult(pd.DataFrame(monthly).fillna(0), pd.DataFrame(annual),
                            pd.DataFrame(journal), {
        "tax_engine": type(tax_engine).__name__,
        "tax_law_year": getattr(tax_engine, "tax_year", None),
        "tax_config": vars(tax_engine.config) if hasattr(tax_engine, "config") else "Tax-Calculator installed version", "tax_treatment": "external annual liability, not debited",
        "market_input": "monthly price returns plus separate cash dividend yields",
        "assumptions": ["All dividends ordinary unless a richer event adapter is supplied",
                        "no contribution-limit or eligibility enforcement", "no wash-sale/loss carryforward calculation",
                        "no retirement basis/conversion/RMD calculation", "not financial or tax advice"]})
