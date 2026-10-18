"""Actual RTL regression against frozen step006 workloads; no old file is rewritten."""
from pathlib import Path
import argparse,csv,hashlib,json,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
PRIOR=BASE/'optimization/step006_pipelined'
sys.path.insert(0,str(BASE/'step006'))
from reference import infer,lower_loads
SEED=20261019
BIN=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read_json(p):return json.loads(p.read_text(encoding='utf-8'))

def check_prior():
    for folder,anchor,key in [(BASE/'step006',BASE,'sha256'),(PRIOR,BASE,'sha256')]:
        r=read_json(folder/'results.json');assert r['status']=='PASS'
        for n,h in r[key].items():assert sha(anchor/n)==h,('prerequisite',n)
    manifest=read_json(BASE/'optimization/artifact_manifest.json')
    for n,h in manifest['sha256'].items():assert sha(BASE/n)==h,('frozen artifact',n)
    return len(manifest['sha256'])

def prepare_cases():
    text=(BASE/'step006/build/mlp_cases.txt').read_text();lines=text.strip().splitlines();idx=0;count=0
    while idx<len(lines):
        header=list(map(int,lines[idx].split()));assert len(header)==12 and header[0]==count
        idx+=1+header[11]+header[2]+header[3];count+=1
    assert count==624 and idx==len(lines)
    added=[]
    # Cross-layer highest row/column addresses, full H=O=8 and K=256 were absent
    # as a simultaneous shape in the original 624 tasks.
    for i,k in enumerate([256,1,255,17]):
        model=dict(version=1,dtype='int8',zero_point=0,shape=[k,8,8],layers=[])
        for layer,inputs in [(0,k),(1,8)]:
            model['layers'].append(dict(weight=[[(row*31+j*7+i*13)%256-128 for j in range(inputs)] for row in range(8)],
                bias=[[-(1<<31),(1<<31)-1,-1,0,1,-123456,789012,7][row] for row in range(8)],
                relu=not layer,multiplier=[1,65535,3,32768][i],shift=[0,47,16,7][i]))
        x=[(j*29+i*17)%256-128 for j in range(k)]
        for fused in [0,1]:
            task_id=624+len(added);loads=lower_loads(model,x);records=infer(model,x)
            header=[task_id,k,8,8,model['layers'][0]['multiplier'],model['layers'][0]['shift'],
                    model['layers'][1]['multiplier'],model['layers'][1]['shift'],fused,0,16,len(loads)]
            lines.append(' '.join(map(str,header)))
            lines.extend(' '.join(map(str,r)) for r in loads)
            for r in records:lines.extend(' '.join(map(str,[pre,*q])) for pre,q in zip(r['pre'],r['quantized']))
            added.append(dict(id=task_id,label=f'full_channels_K{k}',fused=fused,model=model,x=x,records=records))
    (ROOT/'cases.txt').write_text('\n'.join(lines)+'\n')
    (ROOT/'additional_vectors.json').write_text(json.dumps(added,indent=2))
    return 624+len(added)

SUPPLEMENTAL=r'''
  // Reset at RAM response, stalled hidden, partial replay, MAC product,
  // and stalled final output. Restart each case without reloading any RAM.
  for(stage=0;stage<5;stage=stage+1)begin
   id=1000+stage;fused=(stage==1 || stage==2)?0:1;
   configure_current();out_ready=(stage==4)?0:1;hidden_ready=(stage==1)?0:1;
   start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();
   reached=0;
   while(!reached)begin
    #1;
    case(stage)
     0:reached=(dut.state==2 && dut.engine.core.rsp_mask!=0);
     1:reached=(dut.state==2 && hidden_valid);
     2:reached=(dut.state==3);
     3:reached=(dut.state==5 && dut.engine.core.mul_mask!=0);
     4:reached=(dut.state==5 && out_valid);
    endcase
    if(!reached)begin observe();tick();end
    if(cycle-begin_cycle>20000)$fatal(1,"supplemental target watchdog");
   end
   if(stage==1 || stage==4)begin
    for(j=0;j<8;j=j+1)begin #1;observe();tick();end
   end
   if(stage==2)begin
    host_layer=1;host_kind=0;host_addr=0;host_data=gh[0];host_we=1;#1;
    if(!host_ready)$fatal(1,"partial replay refused");observe();tick();host_we=0;
    if(dut.written!=1)$fatal(1,"partial replay not counted");
   end
   cancelled_quant=cancelled_quant+dut.quant.p_valid+dut.quant.b_valid+dut.q_valid;
   reset=1;tick();aborts=aborts+1;
   if(busy || hidden_valid || out_valid || done || dut.quant.p_valid || dut.quant.b_valid)$fatal(1,"supplemental reset ghost");
   reset=0;hidden_ready=1;out_ready=1;fetch_enable=1;host_we=0;bridge_done=0;start=0;
   for(j=0;j<5;j=j+1)begin tick();if(busy || hidden_valid || out_valid || done)$fatal(1,"ghost after reset");end
   fused=1;configure_current();start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();
   while(busy)begin #1;observe();tick();if(cycle-begin_cycle>20000)$fatal(1,"restart watchdog");end
   if(!done || nh!=h || no!=o || npre1!=h || npre2!=o || q_inputs!=h+o || q_outputs!=h+o)$fatal(1,"restart mismatch");
   tick();supplemental=supplemental+1;
  end
'''

def prepare_tb():
    text=(BASE/'step006/tb_mlp.v').read_text()
    text=text.replace('module tb_mlp;','module tb_mlp #(parameter integer MODE=1);')
    text=text.replace('mlp2_top dut(.*);','mlp2_top #(.RAM_MODE(MODE)) dut(.*);')
    text=text.replace('dut.error1 || dut.error2 || dut.q1_error || dut.q2_error','dut.fc_error || dut.q_error || dut.engine.core_cfg_error')
    for old,new in [('fc1_valid','fc_valid'),('fc2_valid','fc_valid'),('q1_ready','q_ready'),('q2_ready','q_ready'),
                    ('fc1_index','fc_index'),('fc2_index','fc_index'),('unused_pre1','fc_pre'),('unused_pre2','fc_pre')]:
        text=text.replace('dut.'+old,'dut.'+new)
    text=text.replace('dut.fc1.rd_mask[t]','(dut.engine.rd_mask[t] && dut.state==2)')
    text=text.replace('dut.fc2.rd_mask[t]','(dut.engine.rd_mask[t] && dut.state==5)')
    text=text.replace('dut.fc1.rd_mask!=0','(dut.engine.rd_mask!=0 && dut.state==2)')
    text=text.replace('dut.fc2.rd_mask!=0','(dut.engine.rd_mask!=0 && dut.state==5)')
    declarations='''
 integer stage,reached,supplemental=0,cancelled_quant=0,q_inputs=0,q_outputs=0;
 integer launch_edges=0,run1_edges=0,bridge_edges=0,run2_edges=0;
 integer fetch_blocked=0,hidden_blocked=0,output_blocked=0,quant_blocked=0;
 task clear_counts;
 begin
  nh=0;no=0;npre1=0;npre2=0;replayed=0;waits=0;groups1=0;groups2=0;pairs1=0;pairs2=0;
  held_h=0;held_o=0;q_inputs=0;q_outputs=0;launch_edges=0;run1_edges=0;bridge_edges=0;run2_edges=0;
  fetch_blocked=0;hidden_blocked=0;output_blocked=0;quant_blocked=0;
 end endtask
 task configure_current;
 begin
  k_cfg=k;h_cfg=h;o_cfg=o;mult1_cfg=m1;shift1_cfg=s1;mult2_cfg=m2;shift2_cfg=s2;fused_cfg=fused;
 end endtask
'''
    text=text.replace(' task tick;',declarations+' task tick;')
    old='nh=0;no=0;npre1=0;npre2=0;replayed=0;waits=0;groups1=0;groups2=0;pairs1=0;pairs2=0;held_h=0;held_o=0;'
    assert old in text;text=text.replace(old,'clear_counts();')
    checks='''
  if(q_inputs-q_outputs != dut.quant.p_valid+dut.quant.b_valid+dut.q_valid)$fatal(1,"quant conservation id=%0d",id);
  if(dut.engine.core.issued_groups-dut.engine.core.retired_groups != (dut.engine.core.rsp_mask!=0)+(dut.engine.core.mul_mask!=0))$fatal(1,"MAC group conservation");
  if(dut.engine.host_fire && dut.fc_busy && dut.engine.host_layer==dut.engine.active_layer)$fatal(1,"active layer write");
  if(dut.engine.rd_mask!=0 && dut.engine.host_fire && dut.engine.host_kind==0 && dut.engine.x_wr_addr==dut.engine.x_rd_addr)$fatal(1,"RAM collision");
  if(dut.fc_valid && dut.q_ready && (dut.state==2 || dut.state==5))q_inputs=q_inputs+1;
  if(dut.q_valid && dut.quant_accept_ready)q_outputs=q_outputs+1;
  if(dut.state==1 || dut.state==4)launch_edges=launch_edges+1;
  if(dut.state==2)run1_edges=run1_edges+1;
  if(dut.state==3)bridge_edges=bridge_edges+1;
  if(dut.state==5)run2_edges=run2_edges+1;
  if(dut.engine.core.busy && dut.engine.core.issued_groups*4<dut.engine.core.k_latched && !fetch_enable)fetch_blocked=fetch_blocked+1;
  if(hidden_valid && !dut.hidden_accept_ready)hidden_blocked=hidden_blocked+1;
  if(out_valid && !out_ready)output_blocked=output_blocked+1;
  if(dut.fc_valid && !dut.q_ready)quant_blocked=quant_blocked+1;
'''
    text=text.replace('  // Called just before',checks+'  // Called just before')
    # Count every actual edge including the early reset path, but metrics concern
    # only the restarted complete task. The early abort has not accepted quant data.
    text=text.replace('start=1;begin_cycle=cycle+1;tick();start=0;\n   end',
                      'start=1;begin_cycle=cycle+1;tick();start=0;clear_counts();\n   end')
    extra_names=',launch_edges,run1_edges,bridge_edges,run2_edges,fetch_blocked,hidden_blocked,output_blocked,quant_blocked,q_inputs,q_outputs'
    text=text.replace('groups1,groups2,pairs1,pairs2");','groups1,groups2,pairs1,pairs2'+extra_names+'");')
    old='$fdisplay(mf,"'+','.join(['%0d']*14)+'",id,k,h,o,fused,flow,delay_host,cycle-begin_cycle,loads,replayed,groups1,groups2,pairs1,pairs2);'
    new='$fdisplay(mf,"'+','.join(['%0d']*24)+'",id,k,h,o,fused,flow,delay_host,cycle-begin_cycle,loads,replayed,groups1,groups2,pairs1,pairs2'+extra_names+');'
    assert old in text;text=text.replace(old,new)
    text=text.replace('   completed=completed+1;',
      '   if(q_inputs!=h+o || q_outputs!=h+o || launch_edges+run1_edges+bridge_edges+run2_edges!=cycle-begin_cycle)$fatal(1,"phase/count mismatch");\n   completed=completed+1;')
    marker='  $display("PASS MLP completed='
    assert marker in text;text=text.replace(marker,SUPPLEMENTAL+marker)
    text=text.replace('aborted=%0d cycles=%0d",completed,invalids,aborts,cycle',
                      'aborted=%0d cycles=%0d supplemental=%0d cancelled_quant=%0d",completed,invalids,aborts,cycle,supplemental,cancelled_quant')
    # Add blocked active-phase host writes. They must be ignored at the wrapper.
    text=text.replace('host_we=0;bridge_done=0;start=(flow && cycle%17==0);',
      'host_we=(flow && (dut.state==2 || dut.state==5));host_layer=0;host_kind=1;host_addr=2047;host_data=123;bridge_done=0;start=(flow && cycle%17==0);\n    #1;if(host_we && host_ready)$fatal(1,"busy host write accepted");')
    text+='\n'.join(f'module tb_mode{mode}; tb_mlp #(.MODE({mode})) run(); endmodule' for mode in range(3))+'\n'
    (ROOT/'tb_shared.v').write_text(text)

def run(args,cwd,logfile):
    p=subprocess.run([str(a) for a in args],cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    text=p.stdout+p.stderr;logfile.write_text(text,encoding='utf-8')
    if p.returncode:raise RuntimeError(str(logfile)+'\n'+text[-4000:])
    return text

def sources():
    return [BASE/'step004/dot_banked_core.v',PRIOR/'requant_i8.v',ROOT/'sync_ram_style.v',ROOT/'fc_shared.v',ROOT/'mlp2_top.v',ROOT/'tb_shared.v']

def verify():
    result=dict(status='RUNNING',seed=SEED,configs={})
    try:
        result['prior_artifacts_verified']=check_prior();count=prepare_cases();prepare_tb()
        with (PRIOR/'metrics.csv').open() as f:old_metrics=list(csv.DictReader(f))
        with (PRIOR/'build/mlp_events.csv').open() as f:old_events=list(csv.DictReader(f))
        test=read_json(BASE/'step006/test_dataset.json');training=read_json(BASE/'step006/training_results.json')
        previous_metrics=previous_events=None;all_metrics=[]
        for mode,name in [(0,'block'),(1,'hybrid'),(2,'distributed')]:
            dest=ROOT/'build'/name;dest.mkdir(parents=True,exist_ok=True)
            (dest/'mlp_cases.txt').write_bytes((ROOT/'cases.txt').read_bytes())
            run([BIN/'xvlog.bat','--sv',*sources()],dest,dest/'compile.log')
            run([BIN/'xelab.bat',f'tb_mode{mode}','--timescale','1ns/1ps','-s','step007_sim'],dest,dest/'elaborate.log')
            log=run([BIN/'xsim.bat','step007_sim','-runall'],dest,dest/'simulation.log')
            match=re.search(r'PASS MLP completed=(\d+) invalid=(\d+) aborted=(\d+) cycles=(\d+) supplemental=(\d+) cancelled_quant=(\d+)',log)
            assert match and 'Fatal:' not in log,log[-4000:]
            n,invalid,aborts,cycles,supplemental,cancelled=map(int,match.groups());assert n==count and invalid==8 and supplemental==5 and cancelled>0
            with (dest/'mlp_metrics.csv').open() as f:metrics=[{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
            with (dest/'mlp_events.csv').open() as f:events=list(csv.DictReader(f))
            assert len(metrics)==count
            baseline_events=[{k:v for k,v in e.items() if k!='cycle'} for e in old_events]
            actual=[{k:v for k,v in e.items() if k!='cycle'} for e in events if int(e['id'])<624]
            assert actual==baseline_events,'original event values/index order'
            if previous_metrics is not None:assert metrics==previous_metrics and events==previous_events,'RAM style changed behavior'
            previous_metrics,previous_events=metrics,events
            for r,old in zip(metrics,old_metrics):
                for key in ['K','H','O','host_loads','bridge_writes','groups1','groups2','pairs1','pairs2']:
                    assert r[key]==int(old[key]),(name,r['id'],key)
            correct=0
            for sample in test:
                i=sample['index'];task_id=97+2*i if i<16 else 112+i
                out=[int(e['data']) for e in events if int(e['id'])==task_id and e['stage']=='output']
                assert len(out)==2;correct+=int(int(out[1]>out[0])==sample['label'])
            assert correct/len(test)==training['test_int8_accuracy']
            deltas=[r['cycles']-int(old['cycles']) for r,old in zip(metrics,old_metrics)]
            result['configs'][name]=dict(status='PASS',RAM_MODE=mode,main_tasks=count,original_tasks=624,
                added_full_channel_tasks=count-624,invalid=invalid,aborted=aborts,supplemental_reset_restarts=supplemental,
                cancelled_quant_in_supplemental=cancelled,simulation_edges=cycles,heldout_rtl_samples=len(test),
                heldout_rtl_accuracy=correct/len(test),cycle_deltas_vs_dual=sorted(set(deltas)),
                golden_output_positions=sum(r['H']+r['O'] for r in metrics),
                original_pre_and_quant_golden='unchanged exact Python integers with adapted structural probes')
            for row in metrics:all_metrics.append(dict(style=name,**row))
            print(f'PASS STEP007 {name} tasks={count} edges={cycles} accuracy={correct/len(test)} cycle_deltas={sorted(set(deltas))}',flush=True)
        with (ROOT/'metrics.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(all_metrics[0]));w.writeheader();w.writerows(all_metrics)
        compare=[]
        for r,old in zip(previous_metrics,old_metrics):
            compare.append(dict(id=r['id'],K=r['K'],H=r['H'],O=r['O'],fused=r['fused'],flow=r['flow'],
                dual_cycles=int(old['cycles']),shared_cycles=r['cycles'],load_writes=r['host_loads'],
                shared_edges_with_load=1+r['host_loads']+r['cycles'],macs=r['pairs1']+r['pairs2'],
                physical_mac_lanes=4,mac_lane_utilization=(r['pairs1']+r['pairs2'])/(4*r['cycles'])))
        with (ROOT/'comparison.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(compare[0]));w.writeheader();w.writerows(compare)
        paths=sources()+[ROOT/'verify_step007.py',ROOT/'cases.txt',ROOT/'additional_vectors.json',BASE/'step006/reference.py',
                         BASE/'step006/test_dataset.json',BASE/'step006/training_results.json',PRIOR/'results.json',PRIOR/'synthesis_results.json',
                         PRIOR/'metrics.csv',PRIOR/'build/mlp_events.csv',BASE/'step006/build/mlp_cases.txt']
        paths += [ROOT/n for n in ['synthesize.tcl','run_synthesis.ps1'] if (ROOT/n).exists()]
        result.update(status='PASS',sha256={str(p.relative_to(BASE)):sha(p) for p in paths})
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'verification_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

def finalize():
    r=read_json(ROOT/'verification_results.json');assert r['status']=='PASS'
    for n,h in r['sha256'].items():assert sha(BASE/n)==h,('changed after regression',n)
    synth=read_json(ROOT/'synthesis_results.json');assert synth['status']=='PASS'
    for n,h in synth['source_sha256'].items():assert sha(BASE/n)==h,('changed after synthesis',n)
    assert synth['configs']['hybrid']['WNS_ns']>=0,'recommended config misses 10ns synthesis estimate'
    prior=read_json(PRIOR/'synthesis_results.json')['configs']['block']
    r.update(status='PASS',synthesis=synth,dual_baseline=prior,
             scope='same frozen model and host commands; clock-only post-synthesis estimates, no board/DRAM/energy claim')
    (ROOT/'results.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    print('PASS STEP007 FINAL: RTL + same-device synthesis + current source hashes')

def seal(check=False):
    p=ROOT/'artifact_manifest.json'
    if check:
        r=read_json(p)
        for n,h in r['sha256'].items():assert sha(ROOT/n)==h,n
        print('PASS STEP007 artifact hashes='+str(len(r['sha256'])));return
    assert read_json(ROOT/'results.json')['status']=='PASS';check_prior()
    paths=[p for p in ROOT.rglob('*') if p.is_file() and p.name!='artifact_manifest.json' and
           'xsim.dir' not in p.parts and '__pycache__' not in p.parts and
           p.suffix in ['.v','.py','.tcl','.ps1','.md','.json','.csv','.txt','.rpt','.log']]
    p.write_text(json.dumps(dict(status='PASS',sha256={str(q.relative_to(ROOT)):sha(q) for q in paths}),indent=2))
    print('SEALED STEP007 artifacts='+str(len(paths)))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--finalize',action='store_true');parser.add_argument('--seal',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.finalize:finalize()
    elif args.seal or args.check:seal(args.check)
    else:verify()
