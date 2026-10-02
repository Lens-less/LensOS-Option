"""Build frozen synthetic preview outputs using unchanged upstream Python logic."""
from pathlib import Path
import sys, json, itertools, hashlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from original_python.desk_demo import demo_desk_snapshot
from original_python.decision_desk import build_desk, compare_candidates
CLOCK = '2026-10-01T15:00:00Z'
SCENARIOS = [
 {'label':'原始假设', 'value':{'price_change_pct':0,'time_days':0,'iv_shift_points':0}},
 {'label':'上涨 10% · 7 天', 'value':{'price_change_pct':10,'time_days':7,'iv_shift_points':0}},
 {'label':'下跌 10% · IV +10', 'value':{'price_change_pct':-10,'time_days':7,'iv_shift_points':10}},
 {'label':'横盘 · 14 天 · IV −10', 'value':{'price_change_pct':0,'time_days':14,'iv_shift_points':-10}},
]
bundle={'clock':CLOCK,'upstream_commit':'30102e5d99994346a48d99e97972fd4266cf106b','synthetic':True,'scenarios':SCENARIOS,'assets':{}}
for asset in ['BTC','ETH']:
 desk=build_desk(demo_desk_snapshot(asset,captured_at=CLOCK),evaluation_clock=CLOCK)
 expiry=min(c['expiry_date'] for c in desk['candidates'] if c['status']=='comparable')
 selected=[next(c for c in desk['candidates'] if c['structure']==structure and c['expiry_date']==expiry and c['status']=='comparable')['candidate_id'] for structure in ['BULL_PUT_CREDIT','BEAR_CALL_CREDIT','IRON_CONDOR']]
 comparisons=[]
 for n in [2,3]:
  for ids in itertools.combinations(selected,n):
   for scenario in SCENARIOS:
    comparisons.append(compare_candidates(desk,ids,scenario['value'],evaluation_clock=CLOCK))
 bundle['assets'][asset]={'desk':desk,'selected_ids':selected,'comparisons':comparisons}
path=Path('src/decisionDesk/preview-fixtures.json')
path.write_text(json.dumps(bundle,ensure_ascii=False,separators=(',',':'))+'\n')
print(json.dumps({'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'comparisons':sum(len(a['comparisons']) for a in bundle['assets'].values())}))
