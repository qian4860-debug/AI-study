"""Join independent real-RTL comparison, resident tests, synthesis and selector checks."""
from pathlib import Path
import verify_step008b as core
import select_variant
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent

def main():
    baseline=core.load(ROOT/'baseline_comparison.json');assert baseline['status']=='PASS' and baseline['tasks']==975
    for n,h in baseline['sha256'].items():assert core.sha(BASE/n)==h,n
    cases=select_variant.audit()
    core.finalize()
    result=core.load(ROOT/'results.json');result['actual_baseline_comparison']=baseline
    result['layout_selector']=dict(status='PASS',actual_rtl_shapes_checked=cases,
        source_sha256=core.sha(ROOT/'select_variant.py'),scope='compile-time recommendation, no runtime layout switching')
    result['finalizer_sha256']=core.sha(ROOT/'finalize_all.py')
    core.save(ROOT/'results.json',result)
    print('PASS STEP008B complete comparative acceptance')

if __name__=='__main__':main()
