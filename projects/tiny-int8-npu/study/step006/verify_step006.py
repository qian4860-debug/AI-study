"""Real RTL regression; exact rounding oracle, per-layer intermediates, traffic counters."""
from pathlib import Path
import copy,csv,hashlib,json,os,random,subprocess
from reference import infer,lower_loads,requant,validate
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent;BUILD=ROOT/'build'
SEED=20261018

def generate_quant():
    rng=random.Random(SEED); rows=[]; ov=data=sat=tie=0;accepted=invalid=ties=saturated=0
    directed=[]
    for shift in range(48):
        for m in [1,3,32768,65535]:
            for value in [-(1<<32),(1<<32)-1,-129,-128,-127,-5,-3,-1,0,1,3,5,126,127,128,129]:
                directed.append((value,m,shift))
        if shift<32:
            for v in [-255,-253,-5,-3,-1,1,3,5,253,255]:directed.append((v*(1<<max(0,shift-1)),1,shift))
    directed = [q for q in directed if -(1<<32)<=q[0]<(1<<32)]
    directed += [(0,0,0),(10,1,48),(-10,65535,63)]
    directed += [(rng.randint(-(1<<32),(1<<32)-1),rng.randint(1,65535),rng.randint(0,47)) for _ in range(12000)]
    directed=[(0,1,0)]+directed
    idx=0
    while idx<len(directed) or ov:
        c=len(rows);reset=int(c==0 or c%997==0);rd=int(rng.random()>.35);iv=int(idx<len(directed) and rng.random()>.1)
        v,m,s=directed[min(idx,len(directed)-1)];ready=int(not reset and (not ov or rd));err=0
        if reset:ov=data=sat=tie=0
        elif ready:
            ov=0
            if iv:
                idx+=1
                if m==0 or s>47:err=1;invalid+=1
                else:
                    data,sat,tie=requant(v,m,s);ov=1;accepted+=1;ties+=tie;saturated+=sat
        rows.append((reset,iv,rd,v,m,s,ready,ov,data,sat,tie,err))
    (BUILD/'quant_stimulus.txt').write_text(''.join(' '.join(map(str,r))+'\n' for r in rows))
    accepted_rows=[(r[3],r[4],r[5],r[8],r[9],r[10]) for r in rows if not r[0] and r[1] and r[6] and not r[11]]
    with (BUILD/'quant_matlab.csv').open('w',newline='') as f:csv.writer(f).writerows(accepted_rows)
    return dict(cycles=len(rows),accepted=accepted,invalid=invalid,ties=ties,saturated=saturated,resets=sum(r[0] for r in rows))

def generate_cases():
    rng=random.Random(SEED);cases=[]
    def add(label,model,x,fused,flow=0,delay=0,test_index=None):
        records=infer(model,x);loads=lower_loads(model,x)
        cases.append(dict(id=len(cases),label=label,model=model,x=x,fused=fused,flow=flow,delay=delay,
                          records=records,loads=loads,test_index=test_index))
    for i in range(48):
        k=[1,2,3,4,5,7,8,9,17,63,255,256][i%12] if i<24 else rng.randint(1,64)
        h=[1,3,8][i%3];o=[8,2,1][i%3]
        model=dict(version=1,dtype='int8',zero_point=0,shape=[k,h,o],layers=[])
        for layer,ins,outs in [(0,k,h),(1,h,o)]:
            model['layers'].append(dict(weight=[[rng.randint(-128,127) for _ in range(ins)] for _ in range(outs)],
                bias=[rng.choice([-(1<<31),(1<<31)-1,rng.randint(-1000,1000)]) for _ in range(outs)],
                relu=not layer,multiplier=rng.choice([1,3,65535]),shift=rng.choice([0,7,16,31,47])))
        x=[rng.randint(-128,127) for _ in range(k)]
        for fused in [0,1]:add(f'random{i:02}',model,x,fused,flow=int(i%3==1),delay=[0,16,64][i%3])
    model=json.loads((ROOT/'trained_model.json').read_text());test=json.loads((ROOT/'test_dataset.json').read_text())
    for sample in test:
        # All 512 held-out samples run in RTL; first 16 also compare host bridge latency.
        if sample['index']<16:add(f'test{sample["index"]:03}',model,sample['x'],0,delay=16,test_index=sample['index'])
        add(f'test{sample["index"]:03}',model,sample['x'],1,test_index=sample['index'])
    lines=[]
    for c in cases:
        k,h,o=validate(c['model']);l1,l2=c['model']['layers']
        lines.append(' '.join(map(str,[c['id'],k,h,o,l1['multiplier'],l1['shift'],l2['multiplier'],l2['shift'],c['fused'],c['flow'],c['delay'],len(c['loads'])])))
        lines.extend(' '.join(map(str,v)) for v in c['loads'])
        for r in c['records']:
            lines.extend(' '.join(map(str,[pre,*q])) for pre,q in zip(r['pre'],r['quantized']))
    (BUILD/'mlp_cases.txt').write_text('\n'.join(lines)+'\n')
    # Reproducible graph-to-host lowering example used verbatim by the testbench.
    (ROOT/'lowered_example.json').write_text(json.dumps(dict(model=model,host_commands=lower_loads(model,test[0]['x'])),indent=2))
    return cases

def check_ir():
    source=json.loads((ROOT/'trained_model.json').read_text())
    for i in range(8):
        m=copy.deepcopy(source)
        if i==0:m['shape'][0]=16.0
        elif i==1:m['layers'][0]['weight'][0].pop()
        elif i==2:m['layers'][0]['weight'][0][0]=128
        elif i==3:m['layers'][0]['bias'][0]=1<<31
        elif i==4:m['layers'][1]['multiplier']=-1
        elif i==5:m['layers'][0]['shift']=1.5
        elif i==6:m['layers'].append(copy.deepcopy(m['layers'][1]))
        else:m['layers'][0]['relu']=False
        try:validate(m)
        except ValueError:pass
        else:raise AssertionError('invalid IR accepted '+str(i))
    return 8

def run(args,name):
    p=subprocess.run([str(a) for a in args],cwd=BUILD,capture_output=True,text=True,encoding='utf-8',errors='replace')
    log=p.stdout+p.stderr;(ROOT/name).write_text(log,encoding='utf-8')
    if p.returncode:raise RuntimeError(name+'\n'+log[-5000:])
    return log

def simulate(top,files):
    b=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    run([b/'xvlog.bat','--sv',*files],top+'_compile.log')
    run([b/'xelab.bat',top,'--timescale','1ns/1ps','-s',top+'_snapshot'],top+'_elaborate.log')
    return run([b/'xsim.bat',top+'_snapshot','-runall'],top+'_simulation.log')

def main():
    BUILD.mkdir(exist_ok=True);result=dict(status='RUNNING',seed=SEED)
    try:
        prior=json.loads((BASE/'step005/results.json').read_text())
        assert prior['status']=='PASS'
        assert all(hashlib.sha256((BASE/n).read_bytes()).hexdigest()==h for n,h in prior['sha256'].items())
        result['prerequisite']='step005 PASS with matching source SHA256'
        result['ir_rejection_checks']=check_ir()
        result['quant']=generate_quant();cases=generate_cases()
        log=simulate('tb_requant',[ROOT/'requant_i8.v',ROOT/'tb_requant.v'])
        assert f'PASS QUANT cycles={result["quant"]["cycles"]}' in log
        files=[BASE/'step004/dot_banked_core.v',BASE/'step004/bank_ram.v',BASE/'step005/fc_int8_top.v',ROOT/'requant_i8.v',ROOT/'mlp2_top.v',ROOT/'tb_mlp.v']
        log=simulate('tb_mlp',files);assert f'PASS MLP completed={len(cases)} invalid=8' in log,log[-5000:]
        with (BUILD/'mlp_metrics.csv').open() as f:metrics=[{k:int(v) for k,v in row.items()} for row in csv.DictReader(f)]
        with (BUILD/'mlp_events.csv').open() as f:events=list(csv.DictReader(f))
        assert len(metrics)==len(cases)
        for c,m in zip(cases,metrics):
            k,h,o=validate(c['model']);assert m['id']==c['id'] and m['pairs1']==k*h and m['pairs2']==h*o
            accepted=[e for e in events if int(e['id'])==c['id']]
            for stage,r in zip(['hidden','output'],c['records']):
                actual=[int(e['data']) for e in accepted if e['stage']==stage]
                assert actual==[q[0] for q in r['quantized']]
        pairs=[]
        for c,m in zip(cases,metrics):
            if not c['fused'] and not c['flow']:
                f=metrics[c['id']+1];assert f['fused']==1
                pairs.append(dict(label=c['label'],K=m['K'],H=m['H'],O=m['O'],host_delay=m['host_delay'],
                    host_cycles=m['cycles'],fused_cycles=f['cycles'],saved_cycles=m['cycles']-f['cycles'],
                    logical_hidden_bytes_saved=2*m['H'],payload_bus_bytes_saved=5*m['H'],
                    host_speedup=m['cycles']/f['cycles'],
                    incl_load_speedup=(m['cycles']+m['host_loads']+1)/(f['cycles']+f['host_loads']+1)))
        for name,rows in [('metrics.csv',metrics),('comparison.csv',pairs)]:
            with (ROOT/name).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        training=json.loads((ROOT/'training_results.json').read_text())
        test=json.loads((ROOT/'test_dataset.json').read_text())
        labels={r['index']:r['label'] for r in test};correct=0;count=0
        for c in cases:
            if c['test_index'] is not None and c['fused']:
                actual=[int(e['data']) for e in events if int(e['id'])==c['id'] and e['stage']=='output']
                correct+=int(int(actual[1]>actual[0])==labels[c['test_index']]);count+=1
        assert count==512 and correct/count==training['test_int8_accuracy']
        result.update(status='PASS',networks=len(cases),intermediate_values=sum(sum(c['model']['shape'][1:]) for c in cases),
            heldout_rtl_samples=count,heldout_rtl_accuracy=correct/count,training=training,comparison_pairs=len(pairs),
            mlp_summary=next(line for line in log.splitlines() if line.startswith('PASS MLP')),
            simulator='Vivado Simulator 2025.1',scope='RTL simulation; no board, sensor or timing closure claim')
        sources=files+[ROOT/'tb_requant.v',ROOT/'reference.py',ROOT/'verify_step006.py',ROOT/'train_tiny.py',ROOT/'trained_model.json',ROOT/'test_dataset.json',ROOT/'training_results.json',ROOT/'test_step006_reference.m']
        mp=ROOT/'matlab_results.json'
        if mp.exists():
            matlab=json.loads(mp.read_text());assert matlab['status']=='PASS' and matlab['quant_checks']==result['quant']['accepted']
            assert matlab['input_sha256']==hashlib.sha256((BUILD/'quant_matlab.csv').read_bytes()).hexdigest()
            assert mp.stat().st_mtime >= (ROOT/'test_step006_reference.m').stat().st_mtime
            result['matlab']=matlab
        result['sha256']={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        print(json.dumps({k:v for k,v in result.items() if k not in ['sha256','training']},indent=2))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
