"""Actual old 4x1 RTL on the SAME extended 975 cases; expose regressions as well as wins."""
from pathlib import Path
import json,re
import verify_step008b as tile
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent

def main():
    result=dict(status='RUNNING')
    try:
        candidate=tile.load(ROOT/'verification_results.json');assert candidate['status']=='PASS'
        for n,h in candidate['sha256'].items():assert tile.sha(BASE/n)==h,n
        dest=ROOT/'build/baseline';dest.mkdir(parents=True,exist_ok=True)
        (dest/'mlp_cases.txt').write_bytes((ROOT/'cases.txt').read_bytes())
        tb=BASE/'step007/tb_shared.v';sources=tile.residency.rtl_sources()
        tile.residency.run([tile.BIN/'xvlog.bat','--sv',*sources,tb],dest,'compile.log')
        tile.residency.run([tile.BIN/'xelab.bat','tb_mode1','--timescale','1ns/1ps','-s','baseline_sim'],dest,'elaborate.log')
        log=tile.residency.run([tile.BIN/'xsim.bat','baseline_sim','-runall'],dest,'simulation.log')
        assert 'PASS MLP completed=975 invalid=8' in log and 'Fatal:' not in log,log[-3500:]
        old=[{k:int(v) for k,v in r.items()} for r in tile.read_csv(dest/'mlp_metrics.csv')]
        new=[{k:int(v) for k,v in r.items()} for r in tile.read_csv(ROOT/'build/hybrid/mlp_metrics.csv')]
        assert len(old)==len(new)==975
        a=[{k:v for k,v in r.items() if k!='cycle'} for r in tile.read_csv(dest/'mlp_events.csv') if int(r['id'])<975]
        b=[{k:v for k,v in r.items() if k!='cycle'} for r in tile.read_csv(ROOT/'build/hybrid/mlp_events.csv') if int(r['id'])<975]
        assert a==b,'extended baseline/candidate numerical events'
        rows=[]
        for o,n in zip(old,new):
            assert o['id']==n['id'] and o['host_loads']==n['host_loads'] and o['pairs1']==n['pairs1'] and o['pairs2']==n['pairs2']
            rows.append(dict(id=o['id'],K=o['K'],H=o['H'],O=o['O'],flow=o['flow'],fused=o['fused'],
                baseline_cycles=o['cycles'],tile_cycles=n['cycles'],
                no_stall_speedup=o['cycles']/n['cycles'] if not o['flow'] else '',
                baseline_x_reads=o['pairs1']+o['pairs2'],tile_x_reads=n['xreads1']+n['xreads2'],
                w_reads=n['pairs1']+n['pairs2']))
        tile.write_csv(ROOT/'comparison_all_shapes.csv',rows)
        unpaused=[r for r in rows if not r['flow']]
        faster=[r for r in unpaused if r['tile_cycles']<r['baseline_cycles']]
        slower=[r for r in unpaused if r['tile_cycles']>r['baseline_cycles']]
        same=[r for r in unpaused if r['tile_cycles']==r['baseline_cycles']]
        result.update(status='PASS',tasks=975,unpaused_tasks=len(unpaused),faster=len(faster),slower=len(slower),same=len(same),
            worst=min(unpaused,key=lambda r:r['no_stall_speedup']),best=max(unpaused,key=lambda r:r['no_stall_speedup']),
            scope='Both actual RTLs, identical cases; throughput ratios only for flow=0. Stalled cases have different global-cycle injection phases.')
        dependencies=sources+[tb,ROOT/'verify_baseline_grid.py',ROOT/'verify_step008b.py',ROOT/'verification_results.json',ROOT/'cases.txt',ROOT/'build/hybrid/mlp_metrics.csv',ROOT/'build/hybrid/mlp_events.csv']
        result['sha256']={str(p.relative_to(BASE)):tile.sha(p) for p in dependencies}
        print(json.dumps({k:v for k,v in result.items() if k!='sha256'},indent=2))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:tile.save(ROOT/'baseline_comparison.json',result)

if __name__=='__main__':main()
