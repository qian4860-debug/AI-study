"""Real 2x2 RTL against frozen math, independent shapes, physical reads and warm inputs."""
from pathlib import Path
import argparse,csv,hashlib,json,os,random,re,subprocess,sys
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
sys.path.insert(0,str(BASE/'step006'));sys.path.insert(0,str(BASE/'step008a'))
from reference import infer,lower_loads
import verify_step008a as residency
BIN=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,obj):p.write_text(json.dumps(obj,indent=2),encoding='utf-8',newline='\n')

def prerequisites():
    counts={}
    for stage in ['step007','step008a']:
        r=load(BASE/stage/'results.json');assert r['status']=='PASS'
        for n,h in r['sha256'].items():assert sha(BASE/n)==h,n
        m=load(BASE/stage/'artifact_manifest.json')
        for n,h in m['sha256'].items():assert sha(BASE/stage/n)==h,n
        counts[stage]=len(m['sha256'])
    return counts

def prepare_cases():
    lines=(BASE/'step007/cases.txt').read_text().strip().splitlines();rng=random.Random(20261019);added=[]
    for k in [1,3,4,5,17,255,256]:
        for h in [1,2,3,4,5,7,8]:
            for o in [1,2,3,4,5,7,8]:
                model=dict(version=1,dtype='int8',zero_point=0,shape=[k,h,o],layers=[])
                for layer,inputs,outputs in [(0,k,h),(1,h,o)]:
                    model['layers'].append(dict(weight=[[rng.randint(-128,127) for _ in range(inputs)] for _ in range(outputs)],
                        bias=[rng.choice([-(1<<31),(1<<31)-1,rng.randint(-10000,10000)]) for _ in range(outputs)],
                        relu=not layer,multiplier=rng.choice([1,3,65535]),shift=rng.choice([0,7,16,31,47])))
                x=[rng.randint(-128,127) for _ in range(k)];r=infer(model,x);commands=lower_loads(model,x)
                tid=632+len(added);flow=int((k+h+o)%11==0);a,b=model['layers']
                lines.append(' '.join(map(str,[tid,k,h,o,a['multiplier'],a['shift'],b['multiplier'],b['shift'],1,flow,0,len(commands)])))
                lines.extend(' '.join(map(str,v)) for v in commands)
                for record in r:lines.extend(' '.join(map(str,[pre,*q])) for pre,q in zip(record['pre'],record['quantized']))
                added.append(dict(id=tid,K=k,H=h,O=o,flow=flow,model=model,x=x,records=r))
    (ROOT/'cases.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    save(ROOT/'additional_vectors.json',added)
    return 632+len(added)

def prepare_tb():
    text=(BASE/'step007/tb_shared.v').read_text()
    text=text.replace('h*((k+3)/4)','((h+1)/2)*((k+1)/2)').replace('o*((h+3)/4)','((o+1)/2)*((h+1)/2)')
    text=text.replace(' integer stage,',' integer xreads1=0,xreads2=0;\n integer stage,')
    text=text.replace('  nh=0;no=0;', '  xreads1=0;xreads2=0;nh=0;no=0;')
    text=text.replace('  // Called just before','''
  for(t=0;t<4;t=t+1)begin
   if(dut.engine.x_rd_mask[t] && dut.state==2)xreads1=xreads1+1;
   if(dut.engine.x_rd_mask[t] && dut.state==5)xreads2=xreads2+1;
  end
  // Called just before''')
    text=text.replace('q_inputs,q_outputs");','q_inputs,q_outputs,xreads1,xreads2");')
    old='$fdisplay(mf,"'+','.join(['%0d']*24)+'",'
    assert old in text;text=text.replace(old,'$fdisplay(mf,"'+','.join(['%0d']*26)+'",')
    text=text.replace('quant_blocked,q_inputs,q_outputs);','quant_blocked,q_inputs,q_outputs,xreads1,xreads2);')
    text=text.replace('   completed=completed+1;',
        '   if(xreads1!=k*((h+1)/2) || xreads2!=h*((o+1)/2))$fatal(1,"x read reuse mismatch");\n   completed=completed+1;')
    (ROOT/'tb_tile.v').write_text(text,encoding='utf-8',newline='\n')

def sources():
    return [ROOT/'dot_tile_core.v',BASE/'optimization/step006_pipelined/requant_i8.v',BASE/'step007/sync_ram_style.v',ROOT/'fc_shared.v',BASE/'step007/mlp2_top.v']

def read_csv(p):
    with p.open() as f:return list(csv.DictReader(f))

def write_csv(p,rows):
    with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def verify():
    result=dict(status='RUNNING',seed=20261019,configs={})
    try:
        result['prerequisites']=prerequisites();count=prepare_cases();prepare_tb()
        old_metrics=[r for r in read_csv(BASE/'step007/metrics.csv') if r['style']=='hybrid']
        old_events=[{k:v for k,v in r.items() if k!='cycle'} for r in read_csv(BASE/'step007/build/hybrid/mlp_events.csv') if int(r['id'])<632]
        all_metrics=[];previous=None;events_previous=None
        for mode,name in [(0,'block'),(1,'hybrid'),(2,'distributed')]:
            dest=ROOT/'build'/name;dest.mkdir(parents=True,exist_ok=True)
            (dest/'mlp_cases.txt').write_bytes((ROOT/'cases.txt').read_bytes())
            residency.run([BIN/'xvlog.bat','--sv',*sources(),ROOT/'tb_tile.v'],dest,'compile.log')
            residency.run([BIN/'xelab.bat',f'tb_mode{mode}','--timescale','1ns/1ps','-s','tile_sim'],dest,'elaborate.log')
            log=residency.run([BIN/'xsim.bat','tile_sim','-runall'],dest,'simulation.log')
            match=re.search(r'PASS MLP completed=(\d+) invalid=8 aborted=(\d+) cycles=(\d+) supplemental=5 cancelled_quant=(\d+)',log)
            assert match and int(match[1])==count and 'Fatal:' not in log,log[-3500:]
            metrics=[{k:int(v) for k,v in r.items()} for r in read_csv(dest/'mlp_metrics.csv')];events=read_csv(dest/'mlp_events.csv')
            assert len(metrics)==count
            assert [{k:v for k,v in r.items() if k!='cycle'} for r in events if int(r['id'])<632]==old_events
            if previous is not None:assert metrics==previous and events==events_previous,'RAM implementation changed behavior'
            previous,events_previous=metrics,events
            for r in metrics:
                assert r['pairs1']==r['K']*r['H'] and r['pairs2']==r['H']*r['O']
                assert r['xreads1']==r['K']*((r['H']+1)//2) and r['xreads2']==r['H']*((r['O']+1)//2)
                if not r['flow'] and r['fused']:
                    expected=((r['H']+1)//2)*(((r['K']+1)//2)+5)+r['H']+((r['O']+1)//2)*(((r['H']+1)//2)+5)+r['O']+8
                    assert r['cycles']==expected,(r['id'],r['cycles'],expected)
                all_metrics.append(dict(style=name,**r))
            correct=0
            for sample in load(BASE/'step006/test_dataset.json'):
                i=sample['index'];tid=97+2*i if i<16 else 112+i
                out=[int(e['data']) for e in events if int(e['id'])==tid and e['stage']=='output'];assert len(out)==2
                correct+=int(int(out[1]>out[0])==sample['label'])
            assert correct==488
            sample=metrics[97];assert sample['cycles']==79 and sample['xreads1']+sample['xreads2']==72
            result['configs'][name]=dict(status='PASS',RAM_MODE=mode,main_tasks=count,prior_tasks=632,independent_shapes=count-632,
                golden_positions=sum(r['H']+r['O'] for r in metrics),aborted=int(match[2]),deep_reset_restarts=5,
                cancelled_quant=int(match[4]),simulation_edges=int(match[3]),heldout_samples=512,heldout_correct=correct,
                heldout_accuracy=correct/512,trained_fused_cycles=sample['cycles'],trained_x_reads=72,trained_w_reads=144)
            print(f'PASS STEP008B {name} tasks={count} edges={match[3]} trained_cycles={sample["cycles"]} xbytes=72',flush=True)
        write_csv(ROOT/'metrics.csv',all_metrics)
        comparisons=[]
        for new,old in zip(previous,old_metrics):
            comparisons.append(dict(id=new['id'],K=new['K'],H=new['H'],O=new['O'],flow=new['flow'],fused=new['fused'],
                baseline_cycles=int(old['cycles']),tile_cycles=new['cycles'],
                no_stall_speedup=int(old['cycles'])/new['cycles'] if not new['flow'] else '',
                baseline_x_reads=int(old['pairs1'])+int(old['pairs2']),tile_x_reads=new['xreads1']+new['xreads2'],
                w_reads=new['pairs1']+new['pairs2'],baseline_groups=int(old['groups1'])+int(old['groups2']),
                tile_groups=new['groups1']+new['groups2']))
        write_csv(ROOT/'comparison.csv',comparisons)
        result['resident']=residency.verify_backend(ROOT/'build/warm',sources(),tile=True,layout='k2o2')
        assert result['resident']['warm_occupied']==[96] and result['resident']['warm_compute']==[79]
        dependencies=sources()+[ROOT/'verify_step008b.py',ROOT/'tb_tile.v',ROOT/'cases.txt',ROOT/'additional_vectors.json',
            BASE/'step008a/resident_model.py',BASE/'step008a/verify_step008a.py',BASE/'step006/reference.py',
            BASE/'step006/test_dataset.json',BASE/'step007/results.json',BASE/'step007/metrics.csv']
        dependencies += [ROOT/n for n in ['synthesize.tcl','run_synthesis.ps1'] if (ROOT/n).exists()]
        result.update(status='PASS',sha256={str(p.relative_to(BASE)):sha(p) for p in dependencies})
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:save(ROOT/'verification_results.json',result)

def finalize():
    r=load(ROOT/'verification_results.json');assert r['status']=='PASS'
    for n,h in r['sha256'].items():assert sha(BASE/n)==h,n
    s=load(ROOT/'synthesis_results.json');assert s['status']=='PASS'
    for n,h in s['source_sha256'].items():assert sha(BASE/n)==h,n
    assert s['configs']['hybrid']['WNS_ns']>=0
    r.update(status='PASS',synthesis=s,scope='actual scalar output protocol, 2x2 RTL and RAM reads; clock-only synthesis estimates, no board frequency claim')
    save(ROOT/'results.json',r);print('PASS STEP008B FINAL')

def seal(check=False):
    path=ROOT/'artifact_manifest.json'
    if check:
        for n,h in load(path)['sha256'].items():assert sha(ROOT/n)==h,n
        print('PASS STEP008B artifact hashes');return
    assert load(ROOT/'results.json')['status']=='PASS';prerequisites()
    files=[p for p in ROOT.rglob('*') if p.is_file() and p!=path and '__pycache__' not in p.parts and 'xsim.dir' not in p.parts and p.suffix in ['.v','.py','.ps1','.tcl','.json','.csv','.txt','.md','.log','.rpt']]
    save(path,dict(status='PASS',sha256={str(p.relative_to(ROOT)):sha(p) for p in files}));print('SEALED STEP008B',len(files))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--finalize',action='store_true');parser.add_argument('--seal',action='store_true');parser.add_argument('--check',action='store_true');a=parser.parse_args()
    if a.finalize:finalize()
    elif a.seal or a.check:seal(a.check)
    else:verify()
