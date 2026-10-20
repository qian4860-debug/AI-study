"""Same numerical gold/models/TB as step006; independent elastic-stage cycle model."""
from pathlib import Path
import csv,hashlib,json,random,sys
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent.parent
sys.path.insert(0,str(BASE/'step006'))
import verify_step006 as original
from reference import requant

def prepare_top():
    text=(BASE/'step006/mlp2_top.v').read_text()
    text=text.replace('reg [2:0] hidden_index_q,output_index_q;','wire [3:0] hidden_tag,output_tag;\n    wire [2:0] hidden_index_q=hidden_tag[2:0],output_index_q=output_tag[2:0];')
    text=text.replace('reg hidden_last_q,output_last_q;','wire hidden_last_q=hidden_tag[3],output_last_q=output_tag[3];')
    text=text.replace('q1_sat,q1_tie,q1_error);','q1_sat,q1_tie,q1_error,{fc1_last,fc1_index},hidden_tag);')
    text=text.replace('q2_sat,q2_tie,q2_error);','q2_sat,q2_tie,q2_error,{fc2_last,fc2_index},output_tag);')
    text=text.replace(';hidden_index_q<=0;output_index_q<=0;hidden_last_q<=0;output_last_q<=0;',';')
    text='\n'.join(line for line in text.splitlines() if 'if(fc1_valid && q1_ready && state==RUN1) begin hidden_index_q<=' not in line and 'if(fc2_valid && q2_ready && state==RUN2) begin output_index_q<=' not in line)+'\n'
    text=text.replace('// Two unchanged step005 FC engines.','// Three-stage requantization with index/last tags. Two unchanged step005 FC engines.')
    (ROOT/'mlp2_top.v').write_text(text)

def generate_quant():
    with (BASE/'step006/build/quant_matlab.csv').open() as f:values=[tuple(map(int,r[:3])) for r in csv.reader(f)]
    values.extend([(0,0,0),(4,1,48),(-4,65535,63)])
    rng=random.Random(20261018);p=b=None;c=None;out=(0,0,0,0);ov=0;rows=[];i=0;accepted=delivered=aborted=invalid=0
    while i<len(values) or p is not None or b is not None or ov:
        cycle=len(rows);reset=int(cycle==0 or cycle%719==0);ready=int(rng.random()>.45);iv=int(i<len(values) and rng.random()>.1)
        v,m,s=values[min(i,len(values)-1)];tag=i%16
        cr=not ov or ready;br=b is None or cr;pr=p is None or br;ir=int(not reset and pr);err=0
        if reset:
            aborted+=int(p is not None)+int(b is not None)+ov;p=b=None;ov=0;out=(0,0,0,0)
        else:
            if ov and ready:delivered+=1
            oldp,oldb=p,b
            if cr:
                ov=int(oldb is not None)
                if oldb is not None:out=oldb
            if br:b=None if oldp is None else (*requant(*oldp[:3]),oldp[3])
            if pr:
                p=None
                if iv:
                    i+=1
                    if m==0 or s>47:err=1;invalid+=1
                    else:p=(v,m,s,tag);accepted+=1
        rows.append((reset,iv,ready,v,m,s,tag,ir,ov,*out[:3],err,out[3]))
    assert accepted==delivered+aborted
    (ROOT/'build/quant_pipeline_stimulus.txt').write_text(''.join(' '.join(map(str,r))+'\n' for r in rows))
    return dict(cycles=len(rows),accepted=accepted,delivered=delivered,reset_discarded=aborted,invalid=invalid,
                resets=sum(r[0] for r in rows),conservation='accepted=delivered+reset_discarded')

def main():
    result=dict(status='RUNNING')
    try:
        prior=json.loads((BASE/'step006/results.json').read_text())
        assert prior['status']=='PASS'
        for name,want in prior['sha256'].items():assert hashlib.sha256((BASE/name).read_bytes()).hexdigest()==want,name
        (ROOT/'build').mkdir(exist_ok=True);prepare_top()
        original.ROOT=ROOT;original.BUILD=ROOT/'build'
        result['quant']=generate_quant()
        log=original.simulate('tb_quant_pipeline',[ROOT/'requant_i8.v',ROOT/'tb_quant_pipeline.v'])
        assert f'PASS QUANT_PIPELINE cycles={result["quant"]["cycles"]}' in log
        # Read the exact same frozen graph-derived commands and per-layer gold.
        (ROOT/'build/mlp_cases.txt').write_bytes((BASE/'step006/build/mlp_cases.txt').read_bytes())
        files=[BASE/'step004/dot_banked_core.v',BASE/'step004/bank_ram.v',BASE/'step005/fc_int8_top.v',ROOT/'requant_i8.v',ROOT/'mlp2_top.v',BASE/'step006/tb_mlp.v']
        log=original.simulate('tb_mlp',files);assert 'PASS MLP completed=624 invalid=8 aborted=125' in log
        with (ROOT/'build/mlp_metrics.csv').open() as f:metrics=list(csv.DictReader(f))
        with (ROOT/'build/mlp_events.csv').open() as f:events=list(csv.DictReader(f))
        with (BASE/'step006/build/mlp_events.csv').open() as f:prior=list(csv.DictReader(f))
        assert [{k:v for k,v in e.items() if k!='cycle'} for e in events]==[{k:v for k,v in e.items() if k!='cycle'} for e in prior]
        comparisons=[]
        for a,b in zip(metrics[::2],metrics[1::2]):
            # Early cases alternate host/fused; heldout stream later contains fused-only cases.
            if a['fused']=='0' and b['fused']=='1' and a['flow']=='0':
                comparisons.append(dict(id=a['id'],K=a['K'],H=a['H'],O=a['O'],host_cycles=a['cycles'],fused_cycles=b['cycles'],host_delay=a['host_delay']))
        result.update(status='PASS',networks=624,intermediate_values=6016,heldout_rtl_samples=512,heldout_rtl_accuracy=.953125,
            mlp_summary=next(line for line in log.splitlines() if line.startswith('PASS MLP')),stages=3,
            numerical_equivalence='all hidden/final/index events equal original step006; every pre value checked by unchanged TB')
        for name,rows in [('metrics.csv',metrics),('comparison.csv',comparisons)]:
            with (ROOT/name).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        sources=files+[ROOT/'verify_pipeline.py',ROOT/'tb_quant_pipeline.v',BASE/'step006/reference.py',BASE/'step006/verify_step006.py',BASE/'step006/results.json',BASE/'step006/build/mlp_cases.txt',BASE/'step006/build/quant_matlab.csv']
        result['sha256']={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        print(json.dumps({k:v for k,v in result.items() if k!='sha256'},indent=2))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
