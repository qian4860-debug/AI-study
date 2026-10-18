"""Run the unchanged step007 RTL with real cold/warm/model-switch host transactions."""
from pathlib import Path
import argparse,copy,csv,hashlib,json,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
sys.path.insert(0,str(BASE/'step006'))
from reference import infer
from resident_model import ResidentModel,model_id
BIN=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8',newline='\n')
def load(p):return json.loads(p.read_text(encoding='utf-8'))

def policy_checks(model):
    cache=ResidentModel();x=[0]*model['shape'][0];checks=0
    def reject(call):
        nonlocal checks
        try:call()
        except RuntimeError:checks+=1
        else:raise AssertionError('invalid cache operation accepted')
    reject(lambda:cache.input_writes(model,x))
    commands=cache.begin_model(model);reject(cache.finish_model)
    cache.acknowledge_write(commands[0],False);assert cache.acknowledged==0;checks+=1
    reject(lambda:cache.acknowledge_write(commands[1],True))
    cache.acknowledge_write(commands[0],True);reject(lambda:cache.input_writes(model,x))
    cache.invalidate();reject(cache.finish_model)
    commands=cache.begin_model(model)
    for c in commands:cache.acknowledge_write(c,True)
    cache.finish_model();assert cache.begin_model(copy.deepcopy(model))==[];checks+=1
    assert len(cache.input_writes(model,x))==len(x);checks+=1
    other=copy.deepcopy(model);other['layers'][0]['bias'][0]+=1
    cache.begin_model(other);reject(lambda:cache.input_writes(model,x))
    assert model_id(model,'k4o1')!=model_id(model,'k2o2');checks+=1
    return checks

def prepare_cases(dest,layout='k4o1'):
    dest.mkdir(parents=True,exist_ok=True)
    model=load(BASE/'step006/trained_model.json');test=load(BASE/'step006/test_dataset.json')
    cache=ResidentModel(layout);cases=[]
    def add(label,network,x,test_index=None,reset_before=0,interrupt=0):
        if reset_before:cache.invalidate()
        prefix=[]
        if interrupt:
            old=cache.begin_model(network);assert len(old)>interrupt
            prefix=old[:interrupt]
            for c in prefix:cache.acknowledge_write(c,True)
            cache.invalidate()
        params=cache.begin_model(network)
        for c in params:cache.acknowledge_write(c,True)
        if params:cache.finish_model()
        inputs=cache.input_writes(network,x)
        cases.append(dict(id=len(cases),label=label,model_id=model_id(network,layout),model=network,
            x=x,commands=prefix+params+inputs,parameter_writes=len(params),prefix_writes=len(prefix),
            test_index=test_index,reset_before=reset_before,interrupt_after=interrupt,records=infer(network,x)))
    for sample in test:add('heldout_'+str(sample['index']),model,sample['x'],sample['index'])
    other=copy.deepcopy(model);other['layers'][0]['weight'][0][0]=max(-128,min(127,other['layers'][0]['weight'][0][0]+3));other['layers'][1]['bias'][0]+=321
    add('switch_B_cold',other,test[0]['x']);add('B_warm',other,test[1]['x'])
    add('switch_A_cold',model,test[2]['x']);add('reset_A_reload',model,test[3]['x'],reset_before=1)
    add('A_warm_after_reset',model,test[4]['x']);add('interrupt_B_upload_reload',other,test[5]['x'],interrupt=7)
    add('B_warm_after_interrupt',other,test[6]['x'])
    lines=[];flags=[]
    for c in cases:
        k,h,o=c['model']['shape'];a,b=c['model']['layers']
        head=[c['id'],k,h,o,a['multiplier'],a['shift'],b['multiplier'],b['shift'],1,0,0,len(c['commands'])]
        lines.append(' '.join(map(str,head)));lines.extend(' '.join(map(str,v)) for v in c['commands'])
        for r in c['records']:lines.extend(' '.join(map(str,[pre,*q])) for pre,q in zip(r['pre'],r['quantized']))
        flags.append(f'{c["reset_before"]} {c["interrupt_after"]}')
    (dest/'mlp_cases.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    (dest/'scenario_flags.txt').write_text('\n'.join(flags)+'\n',encoding='utf-8',newline='\n')
    save(dest/'case_catalog.json',[{k:v for k,v in c.items() if k not in ['model','commands','records','x']} for c in cases])
    return cases,policy_checks(model)

def prepare_tb(dest,tile=False):
    text=(BASE/'step007/tb_shared.v').read_text()
    text=text.replace(' integer fd,mf,ef,scan,',' integer ff,reset_before,interrupt_after,cache_resets=0;\n integer fd,mf,ef,scan,')
    text=text.replace('if(!fd || !mf || !ef)',
        'ff=$fopen("scenario_flags.txt","r");\n  if(!ff || !fd || !mf || !ef)')
    marker='   if(scan!=12)$fatal(1,"bad case header");'
    text=text.replace(marker,marker+'''
   scan=$fscanf(ff,"%d %d\\n",reset_before,interrupt_after);if(scan!=2)$fatal(1,"bad flags");
   if(reset_before)begin host_we=0;reset=1;tick();reset=0;tick();cache_resets=cache_resets+1;end
''')
    marker='    if(!host_ready)$fatal(1,"load refused");tick();'
    assert marker in text
    text=text.replace(marker,marker+'''
    if(interrupt_after!=0 && j+1==interrupt_after)begin
     host_we=0;reset=1;tick();reset=0;tick();cache_resets=cache_resets+1;
    end
''')
    text=text.replace('if(id%5==0)','if(1\'b0)')
    text=text.replace('cycles=%0d supplemental=', 'cache_resets=%0d cycles=%0d supplemental=')
    text=text.replace('completed,invalids,aborts,cycle,supplemental,cancelled_quant',
                      'completed,invalids,aborts,cache_resets,cycle,supplemental,cancelled_quant')
    if tile:
        text=text.replace('h*((k+3)/4)','((h+1)/2)*((k+1)/2)').replace('o*((h+3)/4)','((o+1)/2)*((h+1)/2)')
    (dest/'tb_resident.v').write_text(text,encoding='utf-8',newline='\n')
    return dest/'tb_resident.v'

def run(args,cwd,name):
    p=subprocess.run([str(x) for x in args],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    log=p.stdout+p.stderr;(cwd/name).write_text(log,encoding='utf-8',newline='\n')
    if p.returncode:raise RuntimeError(name+'\n'+log[-3500:])
    return log

def rtl_sources():
    return [BASE/'step004/dot_banked_core.v',BASE/'optimization/step006_pipelined/requant_i8.v',
            BASE/'step007/sync_ram_style.v',BASE/'step007/fc_shared.v',BASE/'step007/mlp2_top.v']

def verify_backend(dest,files,tile=False,layout='k4o1'):
    cases,checks=prepare_cases(dest,layout);tb=prepare_tb(dest,tile)
    run([BIN/'xvlog.bat','--sv',*files,tb],dest,'compile.log')
    run([BIN/'xelab.bat','tb_mode1','--timescale','1ns/1ps','-s','resident_sim'],dest,'elaborate.log')
    log=run([BIN/'xsim.bat','resident_sim','-runall'],dest,'simulation.log')
    assert 'PASS MLP completed=519 invalid=8 aborted=5 cache_resets=2' in log and 'Fatal:' not in log,log[-3500:]
    with (dest/'mlp_metrics.csv').open() as f:metrics=[{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
    with (dest/'mlp_events.csv').open() as f:events=list(csv.DictReader(f))
    assert len(metrics)==len(cases)==519
    correct=0;test=load(BASE/'step006/test_dataset.json')
    summary=[]
    for c,r in zip(cases,metrics):
        assert r['id']==c['id'] and r['host_loads']==len(c['commands'])
        for stage,record in zip(['hidden','output'],c['records']):
            values=[int(e['data']) for e in events if int(e['id'])==c['id'] and e['stage']==stage]
            assert values==[q[0] for q in record['quantized']],(c['id'],stage)
        if c['test_index'] is not None:
            y=[int(e['data']) for e in events if int(e['id'])==c['id'] and e['stage']=='output']
            correct+=int(int(y[1]>y[0])==test[c['test_index']]['label'])
        summary.append(dict(id=c['id'],label=c['label'],parameter_writes=c['parameter_writes'],
            prefix_writes=c['prefix_writes'],input_writes=16,accepted_host_writes=r['host_loads'],
            compute_cycles=r['cycles'],occupied_edges=1+r['host_loads']+r['cycles'],
            reset_before=c['reset_before'],interrupt_after=c['interrupt_after']))
    assert correct/512==load(BASE/'step006/training_results.json')['test_int8_accuracy']
    assert summary[0]['parameter_writes']==154
    assert all(r['parameter_writes']==0 and r['accepted_host_writes']==16 for r in summary[1:512])
    with (dest/'resident_metrics.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]),lineterminator='\n');w.writeheader();w.writerows(summary)
    return dict(status='PASS',main_tasks=519,heldout_samples=512,heldout_correct=correct,heldout_accuracy=correct/512,
        warm_heldout_tasks=511,policy_checks=checks,cache_reset_scenarios=2,deep_reset_restart_scenarios=5,
        cold_compute=summary[0]['compute_cycles'],cold_occupied=summary[0]['occupied_edges'],
        warm_compute=sorted(set(r['compute_cycles'] for r in summary[1:512])),
        warm_occupied=sorted(set(r['occupied_edges'] for r in summary[1:512])),
        model_reload_writes=154,layout=layout,summary=next(x for x in log.splitlines() if x.startswith('PASS MLP')))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seal',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.seal or args.check:
        path=ROOT/'artifact_manifest.json'
        if args.check:
            for n,h in load(path)['sha256'].items():assert sha(ROOT/n)==h,n
            print('PASS STEP008A artifact hashes');return
        assert load(ROOT/'results.json')['status']=='PASS'
        files=[p for p in ROOT.rglob('*') if p.is_file() and p!=path and '__pycache__' not in p.parts and 'xsim.dir' not in p.parts and p.suffix in ['.py','.v','.json','.csv','.txt','.md','.log']]
        save(path,dict(status='PASS',sha256={str(p.relative_to(ROOT)):sha(p) for p in files}));print('SEALED STEP008A',len(files));return
    result=dict(status='RUNNING')
    try:
        manifest=load(BASE/'step007/artifact_manifest.json')
        for n,h in manifest['sha256'].items():assert sha(BASE/'step007'/n)==h,n
        files=rtl_sources();result=verify_backend(ROOT/'build',files)
        assert result['cold_compute']==104 and result['cold_occupied']==275 and result['warm_occupied']==[121]
        src=files+[ROOT/'resident_model.py',ROOT/'verify_step008a.py',BASE/'step006/reference.py',BASE/'step006/trained_model.json',BASE/'step006/test_dataset.json']
        result.update(scope='unchanged step007 RTL; host-side model residency and real simulator host handshakes',
            sha256={str(p.relative_to(BASE)):sha(p) for p in src})
        print(json.dumps(result,indent=2))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:save(ROOT/'results.json',result)

if __name__=='__main__':main()
