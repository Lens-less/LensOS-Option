"""Read-only reference calculations from the retained, unmodified Python model."""
from pathlib import Path
import sys,json,random
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from original_python.structures import build_structure
r=random.Random(20261002)
expiry='2027-01-15T08:00:00Z';cases=[]
for index in range(60):
 base=r.choice([100,2000,50000]); width=base*r.choice([.02,.05,.1]); mult=r.choice([.1,1,100]); qty=r.choice([1,2,5])
 family=index%3
 if family==0: raw=[{'option_type':'put','strike':base-width,'quantity':qty},{'option_type':'put','strike':base,'quantity':-qty}]
 elif family==1: raw=[{'option_type':'call','strike':base,'quantity':-qty},{'option_type':'call','strike':base+width,'quantity':qty}]
 else: raw=[{'option_type':'put','strike':base-width*2,'quantity':qty},{'option_type':'put','strike':base-width,'quantity':-qty},{'option_type':'call','strike':base+width,'quantity':-qty},{'option_type':'call','strike':base+width*2,'quantity':qty}]
 entry=round(width*mult*qty*r.uniform(.1,.8),8);fee=round(mult*qty*base*.0001,8)
 for i,leg in enumerate(raw):leg.update(expiry_date=expiry,instrument_name=f'CASE-{index}-{i}')
 structure=build_structure(structure_type=str(family),legs=raw,contract_size=mult)
 prices=[0,base*.5,base-width*2,base-width,base,base+width,base+width*2,base*2]
 cases.append({'legs':[{'instrument':a['instrument_name'],'asset':'BTC','currency':'USDC','expiry':expiry,'optionType':a['option_type'],'strike':a['strike'],'quantity':a['quantity'],'multiplier':mult,'exercise':'european','settlement':'cash_linear'} for a in raw],'entryCash':entry,'fixedExpiryCosts':fee,'expected':structure.risk_profile(entry_cash=entry-fee).to_dict(),'points':[{'price':x,'pnl':structure.pnl_at(x,entry_cash=entry-fee)} for x in prices]})
Path('src/quoteWorkbench/payoff-oracle.json').write_text(json.dumps(cases,separators=(',',':'))+'\n')
print(f'{len(cases)} cases: original Python exact expiry profile and 480 payoff values')
