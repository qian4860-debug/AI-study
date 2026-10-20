"""Cycle oracle and RTL regression for synchronous RAM and tagged MAC pipeline."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
BUILD=ROOT/'build'
SEED=20261016
FIELDS=('cycle reset start k_cfg fetch_enable host_we host_addr host_x host_w '
        'start_fire read_fire host_fire read_addr busy start_ready host_ready k_latched '
        'issued_count retired_count rsp_valid rsp_last mul_valid mul_last product_reg '
        'acc out_valid out_data cfg_error').split()


class Oracle:
    def __init__(self):
        self.busy=self.k=self.issued=self.retired=self.acc=self.out=self.product=0
        self.rsp=None
        self.mul=None
        self.xmem=[None]*256
        self.wmem=[None]*256
        self.trace=[]
        self.stimulus=[]
        self.tasks=[]
        self.pending=None
        self.starts=self.invalid=self.aborted=self.requests=self.retires=self.writes=0
        self.drain_while_paused=0

    def tick(self,reset=0,start=0,k=0,fetch=1,host=0,addr=0,x=0,w=0,label=''):
        cycle=len(self.trace)+1
        sf=int(not reset and start and not self.busy)
        rf=int(not reset and self.busy and fetch and self.issued<self.k)
        hf=int(not reset and not self.busy and not start and host)
        ra=self.issued & 255
        if not reset and self.busy and not fetch and self.issued<self.k:
            self.pending['fetch_stall_cycles']+=1
        self.stimulus.append((reset,start,k,fetch,host,addr,x,w))
        ov=error=0
        old_rsp,old_mul=self.rsp,self.mul
        if reset:
            if self.busy: self.aborted+=1
            self.busy=self.k=self.issued=self.retired=self.acc=self.out=self.product=0
            self.rsp=self.mul=None
            self.pending=None
        else:
            self.rsp=None
            self.mul=old_rsp
            if old_rsp:
                self.product=old_rsp['product']
            if old_mul:
                self.retires+=1
                if not fetch: self.drain_while_paused+=1
                self.retired+=1
                self.acc+=old_mul['product']
                if old_mul['last']:
                    self.out=self.acc
                    self.busy=self.acc=0
                    ov=1
                    task=self.pending
                    stalls=task.pop('fetch_stall_cycles')
                    task.update(expected=self.out,completion_cycle=cycle,
                                latency_cycles=cycle-task['start_cycle'])
                    assert task['latency_cycles']==task['K']+2+stalls
                    task['fetch_stall_cycles']=stalls
                    assert self.out==sum(a*b for a,b in zip(task['x'],task['w']))
                    assert self.issued==self.retired==self.k
                    assert -(1<<23)<=self.out<(1<<23)
                    self.tasks.append(task)
                    self.pending=None
            if rf:
                xv,wv=self.xmem[ra],self.wmem[ra]
                assert xv is not None and wv is not None
                self.issued+=1
                self.requests+=1
                self.rsp=dict(product=xv*wv,last=int(self.issued==self.k))
            if hf:
                self.writes+=1
                self.xmem[addr]=x
                self.wmem[addr]=w
            if sf:
                if 1<=k<=256:
                    assert all(v is not None for v in self.xmem[:k]+self.wmem[:k])
                    self.starts+=1
                    self.busy=1
                    self.k=k
                    self.issued=self.retired=self.acc=0
                    self.rsp=self.mul=None
                    self.pending=dict(label=label,K=k,x=self.xmem[:k],w=self.wmem[:k],start_cycle=cycle,
                                      fetch_stall_cycles=0)
                else:
                    self.invalid+=1
                    error=1
        q0=int(self.rsp is not None)
        q1=int(self.mul is not None)
        assert self.issued-self.retired==q0+q1
        vals=[cycle,reset,start,k,fetch,host,addr,x,w,sf,rf,hf,ra,self.busy,1-self.busy,
              int(not self.busy and not start and not reset),self.k,self.issued,self.retired,
              q0,self.rsp['last'] if q0 else 0,q1,self.mul['last'] if q1 else 0,
              self.product,self.acc,ov,self.out,error]
        self.trace.append(dict(zip(FIELDS,vals)))


def generate():
    o=Oracle()
    rng=random.Random(SEED)
    examples={}
    def load(x,w):
        assert not o.busy and len(x)==len(w)
        for a,(xv,wv) in enumerate(zip(x,w)):
            o.tick(host=1,addr=a,x=xv,w=wv,fetch=0)
    def finish(policy=None):
        n=0
        while o.busy:
            if n>10000: raise AssertionError('generator watchdog')
            fetch=policy(n,o) if policy else 1
            # Host write attempts and starts while busy must be ignored.
            o.tick(fetch=fetch,start=int(n%7==2),k=rng.randrange(512),
                   host=1,addr=0,x=127,w=-128)
            n+=1
    def task(label,x,w,policy=None,example=False):
        load(x,w)
        begin=len(o.trace)
        o.tick(start=1,k=len(x),host=1,addr=0,x=127,w=-128,label=label)
        finish(policy)
        if example: examples[label]=o.trace[begin:]
        o.tick(fetch=0)
    o.tick(reset=1,start=1,k=1,host=1,x=127,w=127)
    o.tick(fetch=0)
    task('K1_extreme',[-128],[-128],example=True)
    task('K3_no_stall',[2,-3,4],[1,2,-1],example=True)
    task('K4_explicit',[1,2,-3,4],[1,-1,0,-1])
    task('K255',[1]*255,[1]*255)
    task('K256_positive',[-128]*256,[-128]*256)
    task('K256_negative',[-128]*256,[127]*256)
    task('K3_pause_and_drain',[2,-3,4],[1,2,-1],
         lambda n,m:int(n not in (0,1,3,4) and m.issued<m.k),example=True)
    task('K8_long_pause',[3,-4,7,0,8,-128,127,5],[1,2,-1,9,-2,-128,127,0],
         lambda n,m:int(n<2 or 34<=n<37 or n>=45))
    # Every illegal nine-bit length. Illegal start must suppress a host write.
    for k in [0,*range(257,512)]:
        o.tick(start=1,k=k,host=1,addr=0,x=-128,w=-128)
        o.tick(fetch=0)
    # Interrupt each stage and the final accumulation edge. RAM must survive.
    for label,k,ticks in [('before_request',3,0),('ram_response',3,1),
                          ('product_stage',3,2),('partial_sum',4,3),
                          ('K1_final',1,2),('K3_final',3,4),('K256_final',256,257)]:
        load([1]*k,[-2]*k)
        o.tick(start=1,k=k,label='abort_'+label)
        for _ in range(ticks):
            o.tick(k=511)
        assert o.busy
        o.tick(reset=1,start=1,k=1,host=1,addr=0,x=127,w=127)
        o.tick(fetch=0)
        # Restart using the retained RAM, without reloading it.
        o.tick(start=1,k=k,label='restart_'+label)
        finish()
        o.tick(fetch=0)
    load([2,-3,4],[1,2,-1])
    o.tick(start=1,k=3,label='held_start_old')
    while o.busy: o.tick(start=1,k=1)
    # The final accumulation edge was busy; only this next edge accepts start.
    o.tick(start=1,k=1,host=1,x=127,w=127,label='held_start_new')
    finish()
    o.tick()
    # New host write is allowed on the idle edge after an output pulse.
    o.tick(host=1,addr=0,x=-7,w=6)
    o.tick(start=1,k=1,label='host_write_after_complete')
    finish()
    o.tick()
    for i in range(128):
        k=rng.randint(1,256)
        xs=[rng.randint(-128,127) for _ in range(k)]
        ws=[rng.randint(-128,127) for _ in range(k)]
        # Stalls change request rate, not the fixed response/retirement timing.
        policy=lambda n,m:int(rng.randrange(5)!=0 and m.issued<m.k)
        task(f'random_{i:03}',xs,ws,policy)
    o.tick(reset=1,start=1,k=256,host=1,x=-128,w=-128)
    o.tick(fetch=0)
    return o,examples


def execute(args,name,cwd=BUILD):
    p=subprocess.run([str(a) for a in args],cwd=cwd,text=True,capture_output=True,
                     encoding='utf-8',errors='replace')
    log=p.stdout+p.stderr
    (ROOT/name).write_text(log,encoding='utf-8')
    if p.returncode: raise RuntimeError(f'{name}: exit={p.returncode}\n{log[-6000:]}')
    return log


def simulate():
    files=[ROOT/n for n in ['dot_serial_mem.v','sync_byte_ram.v','dot_mem_top.v','tb_dot_mem.v']]
    iv,vv=shutil.which('iverilog'),shutil.which('vvp')
    if iv and vv:
        execute([iv,'-g2012','-s','tb_dot_mem','-o','step003.vvp',*files],'compile.log')
        return execute([vv,'step003.vvp'],'simulation.log'),'Icarus Verilog'
    bp=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    if not (bp/'xvlog.bat').exists(): raise RuntimeError('Set VIVADO_BIN or install Icarus Verilog')
    execute([bp/'xvlog.bat','--sv',*files],'compile.log')
    execute([bp/'xelab.bat','tb_dot_mem','--timescale','1ns/1ps','-s','step003_snapshot'],'elaborate.log')
    return execute([bp/'xsim.bat','step003_snapshot','-runall'],'simulation.log'),'Vivado Simulator 2025.1'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--matlab',type=Path)
    parser.add_argument('--use-matlab-results',action='store_true')
    args=parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    result=dict(status='RUNNING',seed=SEED,matlab='NOT_RUN',synthesis='NOT_RUN')
    oracle=None
    try:
        step2=ROOT.parent/'step002'
        prereq=json.loads((step2/'results.json').read_text(encoding='utf-8'))
        assert prereq['status']=='PASS' and prereq['matlab']['status']=='PASS' and prereq['synthesis']['status']=='PASS'
        assert all(hashlib.sha256((step2/n).read_bytes()).hexdigest()==h for n,h in prereq['sha256'].items()), 'Step002 source hashes changed since verification'
        result['step002_prerequisite']='PASS: MATLAB, RTL, synthesis and saved source hashes verified'
        oracle,examples=generate()
        (BUILD/'stimulus.txt').write_text('\n'.join(' '.join(map(str,r)) for r in oracle.stimulus)+'\n')
        vector_path=ROOT/'vectors.json'
        text=json.dumps(oracle.tasks,indent=2)
        if not vector_path.exists() or vector_path.read_text()!=text: vector_path.write_text(text)
        for name,rows in examples.items():
            with (ROOT/f'trace_{name}.csv').open('w',newline='') as fd:
                writer=csv.DictWriter(fd,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
        log,tool=simulate()
        summary=(f'PASS STEP003 cycles={len(oracle.trace)} starts={oracle.starts} '
                 f'completed={len(oracle.tasks)} invalid={oracle.invalid} aborted={oracle.aborted} '
                 f'requests={oracle.requests} retired={oracle.retires} host_writes={oracle.writes}')
        assert summary in log,log[-5000:]
        with (BUILD/'rtl_trace.csv').open(newline='') as fd: rows=list(csv.DictReader(fd))
        assert len(rows)==len(oracle.trace)
        for actual,expected in zip(rows,oracle.trace):
            got={k:int(actual[k]) for k in FIELDS}
            if got!=expected: raise AssertionError(f'FAIL cycle={expected["cycle"]} actual={got} expected={expected}')
        for task in oracle.tasks:
            assert task['latency_cycles']>=task['K']+2
        result.update(status='PASS',simulator=tool,cycles_checked=len(rows),trace_fields=len(FIELDS),
                      legal_starts=oracle.starts,completed_tasks=len(oracle.tasks),random_tasks=128,
                      illegal_starts=oracle.invalid,aborted_tasks=oracle.aborted,requests=oracle.requests,
                      retired=oracle.retires,host_writes=oracle.writes,
                      retirements_with_fetch_disabled=oracle.drain_while_paused,
                      tasks=[{k:v for k,v in t.items() if k not in ('x','w')} for t in oracle.tasks])
        if args.matlab:
            execute([args.matlab,'-batch','test_step003_reference'],'matlab_process.log',cwd=ROOT)
        if args.matlab or args.use_matlab_results:
            mp=ROOT/'matlab_results.json'
            assert mp.stat().st_mtime>=max(p.stat().st_mtime for p in
                [vector_path,ROOT/'test_step003_reference.m',ROOT.parent/'step002/dot_int8_reference.m']), 'MATLAB results stale'
            m=json.loads(mp.read_text())
            assert m['status']=='PASS' and m['task_checks']==len(oracle.tasks)
            result['matlab']=m
        sp=ROOT/'synthesis_results.json'
        if sp.exists() and sp.stat().st_mtime>=max(p.stat().st_mtime for p in
            [ROOT/'dot_serial_mem.v',ROOT/'dot_mem_top.v',ROOT/'sync_byte_ram.v',ROOT/'synthesize.tcl']):
            result['synthesis']=json.loads(sp.read_text())
        result['python']=sys.version
        sources=[ROOT/n for n in ['dot_serial_mem.v','dot_mem_top.v','sync_byte_ram.v','tb_dot_mem.v',
                                   'verify_step003.py','test_step003_reference.m','synthesize.tcl','run_synthesis.ps1']]
        sources.append(ROOT.parent/'step002/dot_int8_reference.m')
        result['sha256']={str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        print(summary)
        print('PASS exact Python/RTL trace comparison; MATLAB='+str(result['matlab']))
    except Exception as e:
        result.update(status='FAIL',error=str(e))
        fp=ROOT/'first_failure.json'
        if not fp.exists():
            detail=dict(error=str(e))
            match=re.search(r'FAIL cycle=(\d+)',str(e))
            if match and oracle:
                idx=int(match.group(1))-1
                detail.update(cycle=idx+1,stimulus=oracle.stimulus[idx],expected=oracle.trace[idx])
            fp.write_text(json.dumps(detail,indent=2),encoding='utf-8')
        raise
    finally:
        (ROOT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__': main()
