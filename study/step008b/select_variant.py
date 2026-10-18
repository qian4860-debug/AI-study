"""Choose a compile-time kernel for one known model; does not switch RAM layouts at runtime."""
from pathlib import Path
import argparse,csv,json
ROOT=Path(__file__).resolve().parent

def ceildiv(n,d):return (n+d-1)//d

def recommend(k,h,o):
    if any(type(v) is not int for v in [k,h,o]) or not 1<=k<=256 or not 1<=h<=8 or not 1<=o<=8:raise ValueError('shape')
    baseline=h*(ceildiv(k,4)+6)+o*(ceildiv(h,4)+6)+8
    tile=ceildiv(h,2)*(ceildiv(k,2)+5)+h+ceildiv(o,2)*(ceildiv(h,2)+5)+o+8
    return dict(shape=[k,h,o],recommended='step008b_k2o2' if tile<baseline else 'step007_k4o1',
        baseline_cycles=baseline,tile_cycles=tile,
        scope='Unstalled fused compute-cycle formulas, validated against both RTLs; choose a build/model layout, not an on-chip runtime switch')

def audit():
    count=0
    with (ROOT/'comparison_all_shapes.csv').open() as f:
        for r in csv.DictReader(f):
            if r['flow']!='0' or r['fused']!='1':continue
            a=recommend(int(r['K']),int(r['H']),int(r['O']))
            assert a['baseline_cycles']==int(r['baseline_cycles']) and a['tile_cycles']==int(r['tile_cycles']),r['id']
            count+=1
    assert recommend(16,8,2)['recommended']=='step008b_k2o2'
    assert recommend(255,1,1)['recommended']=='step007_k4o1'
    print('PASS layout selector vs actual RTL shapes='+str(count))
    return count

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('shape',nargs='*',type=int);p.add_argument('--audit',action='store_true');a=p.parse_args()
    if a.audit:audit()
    else:
        if len(a.shape)!=3:p.error('provide K H O, or --audit')
        print(json.dumps(recommend(*a.shape),indent=2))
