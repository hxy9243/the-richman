import argparse
import json
from pathlib import Path
import pandas as pd
from .engine import simulate
from .policy import PolicyConfig
from .policy_runner import simulate_policy
from .tax import SyntheticTaxEngine, TaxProfile


def main():
    parser=argparse.ArgumentParser(description='Replay an auditable research scenario; no UI')
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, default=Path('output'))
    parser.add_argument('--tax',choices=['synthetic','taxcalc'],default='synthetic')
    parser.add_argument('--tax-year',type=int,default=2026,help='Fixed tax-law year across replay, not market year')
    args=parser.parse_args()
    data=json.loads(args.scenario.read_text())
    market=pd.read_csv(args.scenario.parent/data['market_csv'])
    tax=SyntheticTaxEngine()
    if args.tax == 'taxcalc':
        from .tax import TaxCalculatorEngine
        tax=TaxCalculatorEngine(tax_year=args.tax_year)
    profile=TaxProfile(**data.get('tax_profile',{}))
    result=simulate(market,data['events'],data['accounts'],tax_engine=tax,profile=profile)
    result.export(args.output/'investments')
    for name,p in data.get('policies',{}).items():
        result=simulate_policy(market,p['events'],PolicyConfig(**p['config']),p['symbol'],tax_engine=tax,profile=profile)
        result.export(args.output/name)
    print(f'Results saved to {args.output.resolve()} (standalone strategies; do not sum tax estimates).')

if __name__=='__main__':main()
