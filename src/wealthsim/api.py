"""JSON-friendly public scenario API; no HTTP server or external connections."""
import pandas as pd
from .lifecycle import simulate_household
from .markets import historical_replay, stochastic_market
from .policy import PolicyConfig
from .tax import SyntheticTaxEngine, TaxCalculatorEngine, TaxProfile


def simulate_scenario(scenario: dict):
    """Accept a JSON-compatible mapping and return SimulationResult.

    Market is {mode: stochastic, assets: ..., months: ..., seed: ...} or
    {mode: historical, rows: [...], source_name: ..., ...}. Historical rows are
    caller-supplied licensed data, not downloaded or verified by this API.
    Tax defaults synthetic; taxcalc is optional and federal-only.
    """
    data=dict(scenario); spec=dict(data.pop('market')); mode=spec.pop('mode')
    if mode=='stochastic': market=stochastic_market(**spec)
    elif mode=='historical':
        rows=spec.pop('rows'); market=historical_replay(pd.DataFrame(rows),**spec)
    else: raise ValueError('market.mode must be historical or stochastic')
    tax=dict(data.pop('tax',{'engine':'synthetic'})); name=tax.pop('engine')
    if name=='taxcalc': engine=TaxCalculatorEngine(**tax)
    elif name=='synthetic' and not tax: engine=SyntheticTaxEngine()
    else: raise ValueError('unsupported tax engine/configuration')
    profile=TaxProfile(**data.pop('tax_profile',{}))
    policies={n:{'config':PolicyConfig(**p['config']),'symbol':p['symbol']}
              for n,p in data.pop('policies',{}).items()}
    result=simulate_household(market,policies=policies,tax_engine=engine,profile=profile,**data)
    result.metadata['market']=dict(market.attrs)
    return result
