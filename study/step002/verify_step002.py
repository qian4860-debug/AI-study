"""Generate reproducible cycles; check Python, RTL scoreboard, and MATLAB.

Run: python verify_step002.py [--matlab D:/matlab/bin/matlab.exe]
Only Python's standard library is needed.
"""
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

ROOT = Path(__file__).resolve().parent
BUILD = ROOT/'build'
SEED = 20261015
FIELDS = 'cycle reset start k_cfg in_valid x w start_fire data_fire busy start_ready in_ready k_latched accepted_count acc out_valid out_data cfg_error'.split()


class Oracle:
    def __init__(self):
        self.busy=self.k=self.count=self.acc=self.out=0
        self.stimulus=[]
        self.trace=[]
        self.tasks=[]
        self.pending=None
        self.starts=self.invalid=self.aborted=self.accepted=0

    def tick(self,reset=0,start=0,k=0,valid=0,x=0,w=0,label=''):
        sf=int(not reset and start and not self.busy)
        df=int(not reset and valid and self.busy)
        self.stimulus.append((reset,start,k,valid,x,w))
        cycle=len(self.stimulus)
        ov=err=0
        if reset:
            if self.busy:
                self.aborted+=1
            self.busy=self.k=self.count=self.acc=self.out=0
            self.pending=None
        elif sf:
            if 1<=k<=256:
                self.busy=1
                self.k=k
                self.count=self.acc=0
                self.starts+=1
                self.pending=dict(label=label,K=k,x=[],w=[],start_cycle=cycle)
            else:
                err=1
                self.invalid+=1
        elif df:
            self.accepted+=1
            self.pending['x'].append(x)
            self.pending['w'].append(w)
            self.count+=1
            self.acc+=x*w
            if self.count==self.k:
                self.out=self.acc
                assert -(1<<23)<=self.out<(1<<23)
                self.busy=self.count=self.acc=0
                ov=1
                task=self.pending
                task.update(expected=self.out,completion_cycle=cycle,
                            latency_cycles=cycle-task['start_cycle'])
                task['stall_cycles']=task['latency_cycles']-task['K']
                assert sum(a*b for a,b in zip(task['x'],task['w']))==self.out
                self.tasks.append(task)
                self.pending=None
        row=[cycle,reset,start,k,valid,x,w,sf,df,self.busy,1-self.busy,self.busy,
             self.k,self.count,self.acc,ov,self.out,err]
        self.trace.append(dict(zip(FIELDS,row)))


def generate():
    o=Oracle()
    rng=random.Random(SEED)
    def emit_task(label,x,w,gaps=None):
        assert not o.busy and len(x)==len(w)
        # Idle input pair is deliberately wrong, and must not be consumed.
        o.tick(start=1,k=len(x),valid=1,x=127,w=-128,label=label)
        for j,(a,b) in enumerate(zip(x,w)):
            stalls=(gaps[j] if gaps is not None else 0)
            for _ in range(stalls):
                o.tick(k=rng.randrange(512),valid=0,x=-128,w=-128)
            # A start pulse withdrawn while busy must not start another task.
            o.tick(start=int(j==0 or j==len(x)-1),k=rng.randrange(512),valid=1,x=a,w=b)
        assert not o.busy
        o.tick(valid=1,x=-128,w=-128)  # output data holds, output pulse clears

    o.tick(reset=1,start=1,k=3,valid=1,x=2,w=1)
    o.tick(valid=1,x=-128,w=-128)
    emit_task('T01_K1_extreme',[-128],[-128])
    example_begin=len(o.trace)
    # Matches C0..C5 in the document exactly, with no config disturbance.
    o.tick(start=1,k=3,label='T02_document_trace')
    o.tick(k=3,valid=1,x=2,w=1)
    o.tick(k=3,valid=0)
    o.tick(k=3,valid=1,x=-3,w=2)
    o.tick(k=3,valid=1,x=4,w=-1)
    o.tick(k=3)
    example=o.trace[example_begin:]
    emit_task('T03_K4_explicit_example',[1,2,-3,4],[1,-1,0,-1])
    emit_task('T04_K255',[1]*255,[1]*255)
    emit_task('T05_positive_limit',[-128]*256,[-128]*256)
    emit_task('T06_negative_limit',[-128]*256,[127]*256)
    # All illegal 9-bit values, separated by idle cycles to inspect pulse width.
    for k in [0,*range(257,512)]:
        o.tick(start=1,k=k,valid=1,x=1,w=1,label='T07_invalid')
        o.tick(k=1,valid=1,x=127,w=127)
    emit_task('T08_T09_T10_snapshot_stalls_busy_start',[2,-3,4],[1,2,-1],[32,1,7])
    # Reset at several progress points, including a would-be completion edge.
    for k,received in [(1,0),(3,2),(256,255)]:
        o.tick(start=1,k=k,label=f'T11_abort_K{k}')
        for _ in range(received):
            o.tick(valid=1,x=-128,w=-128,k=511)
        o.tick(reset=1,start=1,k=3,valid=1,x=-128,w=-128)
        o.tick()
        emit_task(f'T11_restart_K{k}',[2,-3,4],[1,2,-1])
    for k in [1,256,3,1,256,3]:
        emit_task(f'T12_back_to_back_K{k}',[1]*k,[-1]*k)
    # Held request is accepted on the first idle edge, not on the final data edge.
    o.tick(start=1,k=3,label='held_request_old')
    for _ in range(3):
        o.tick(start=1,k=2,valid=1,x=1,w=1)
    o.tick(start=1,k=2,valid=1,x=127,w=-128,label='held_request_new')
    o.tick(valid=1,x=-2,w=3,k=511)
    o.tick(valid=1,x=4,w=5,k=0)
    o.tick()
    # Reset clears a pending output pulse and result; ignored requests stay canceled.
    emit_task('before_idle_reset',[7],[8])
    o.tick(reset=1,start=1,k=1,valid=1,x=127,w=127)
    o.tick()
    for i in range(128):
        k=rng.randint(1,256)
        emit_task(f'random_{i:03}',[rng.randint(-128,127) for _ in range(k)],
                  [rng.randint(-128,127) for _ in range(k)],
                  [rng.choices([0,1,2,5],[65,20,10,5])[0] for _ in range(k)])
    o.tick()
    return o,example


def execute(args,name,cwd=BUILD):
    completed=subprocess.run([str(a) for a in args],cwd=cwd,text=True,capture_output=True,
                             encoding='utf-8',errors='replace')
    log=completed.stdout+completed.stderr
    (ROOT/name).write_text(log,encoding='utf-8')
    if completed.returncode:
        raise RuntimeError(f'{name}: exit={completed.returncode}\n{log[-6000:]}')
    return log


def rtl_simulate(dut,name='simulation.log'):
    iv,vv=shutil.which('iverilog'),shutil.which('vvp')
    if iv and vv:
        execute([iv,'-g2012','-s','tb_dot_serial_cfg','-o','step002.vvp',dut,ROOT/'tb_dot_serial_cfg.v'],'compile.log')
        return execute([vv,'step002.vvp'],name),'Icarus Verilog'
    binpath=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    if not (binpath/'xvlog.bat').exists():
        raise RuntimeError('Set VIVADO_BIN or install Icarus Verilog.')
    execute([binpath/'xvlog.bat','--sv',dut,ROOT/'tb_dot_serial_cfg.v'],'compile.log')
    execute([binpath/'xelab.bat','tb_dot_serial_cfg','--timescale','1ns/1ps','-s','step002_snapshot'],'elaborate.log')
    return execute([binpath/'xsim.bat','step002_snapshot','-runall'],name),'Vivado Simulator 2025.1'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--matlab',type=Path,help='MATLAB executable; runs its independent numerical oracle')
    parser.add_argument('--use-matlab-results',action='store_true',help='Check fresh MATLAB results produced by a separate MATLAB batch run')
    args=parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    result={'status':'RUNNING','seed':SEED,'matlab':'NOT_RUN','synthesis':'NOT_RUN'}
    (ROOT/'results.json').write_text(json.dumps(result,indent=2))
    oracle=None
    try:
        oracle,example=generate()
        (BUILD/'stimulus.txt').write_text('\n'.join(' '.join(map(str,row)) for row in oracle.stimulus)+'\n')
        vector_text=json.dumps(oracle.tasks,indent=2)
        vector_path=ROOT/'vectors.json'
        if not vector_path.exists() or vector_path.read_text()!=vector_text:
            vector_path.write_text(vector_text)
        with (ROOT/'trace_example.csv').open('w',newline='') as fd:
            writer=csv.DictWriter(fd,fieldnames=FIELDS)
            writer.writeheader();writer.writerows(example)
        log,tool=rtl_simulate(ROOT/'dot_serial_cfg.v')
        expected_summary=(f'PASS STEP002 cycles={len(oracle.trace)} starts={oracle.starts} '
                          f'completed={len(oracle.tasks)} invalid={oracle.invalid} aborted={oracle.aborted} accepted={oracle.accepted}')
        assert expected_summary in log,log[-5000:]
        with (BUILD/'rtl_trace.csv').open(newline='') as fd:
            rows=list(csv.DictReader(fd))
        assert len(rows)==len(oracle.trace)
        for actual,expected in zip(rows,oracle.trace):
            got={key:int(actual[key]) for key in FIELDS}
            if got!=expected:
                raise AssertionError(f'FAIL cycle={expected["cycle"]} actual={got} expected={expected}')
        result.update(status='PASS',simulator=tool,cycles_checked=len(rows),completed_tasks=len(oracle.tasks),
                      random_tasks=128,legal_starts=oracle.starts,illegal_starts=oracle.invalid,
                      aborted_tasks=oracle.aborted,accepted_pairs=oracle.accepted,
                      tasks=[{k:v for k,v in t.items() if k not in ('x','w')} for t in oracle.tasks])
        if args.matlab:
            # The working directory is the step folder; all generated files stay here.
            execute([args.matlab,'-batch','test_step002_reference'],'matlab_process.log',cwd=ROOT)
        if args.matlab or args.use_matlab_results:
            matlab_path=ROOT/'matlab_results.json'
            assert matlab_path.stat().st_mtime >= max(p.stat().st_mtime for p in
                [vector_path,ROOT/'dot_int8_reference.m',ROOT/'test_step002_reference.m']), 'MATLAB results are stale; rerun test_step002_reference'
            matlab=json.loads((ROOT/'matlab_results.json').read_text())
            assert matlab['status']=='PASS' and matlab['completed_task_checks']==len(oracle.tasks)
            result['matlab']=matlab
        synthesis_path=ROOT/'synthesis_results.json'
        if synthesis_path.exists() and synthesis_path.stat().st_mtime >= max((ROOT/'dot_serial_cfg.v').stat().st_mtime,(ROOT/'synthesize.tcl').stat().st_mtime):
            result['synthesis']=json.loads(synthesis_path.read_text())
            utilization=(ROOT/'synthesis_utilization.rpt').read_text()
            slice_luts=re.search(r'\| Slice LUTs\*\s*\|\s*(\d+)',utilization)
            assert slice_luts,'Slice LUT count missing from utilization report'
            result['synthesis']['Slice_LUTs']=int(slice_luts.group(1))
            result['synthesis']['timing_scope']='Post-synthesis estimate, 10 ns clock only, no I/O delays or clock location; not implementation closure'
        result['python']=sys.version
        result['sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                          [ROOT/'dot_serial_cfg.v',ROOT/'tb_dot_serial_cfg.v',Path(__file__),
                           ROOT/'dot_int8_reference.m',ROOT/'test_step002_reference.m',ROOT/'synthesize.tcl']}
        print(expected_summary)
        print('PASS exact Python/RTL cycle comparison; MATLAB='+str(result['matlab']))
    except Exception as e:
        result.update(status='FAIL',error=str(e))
        first=ROOT/'first_failure.json'
        if not first.exists():
            detail={'error':str(e)}
            match=re.search(r'FAIL cycle=(\d+)',str(e))
            if match and oracle:
                idx=int(match.group(1))-1
                detail.update(cycle=idx+1,stimulus=oracle.stimulus[idx],expected=oracle.trace[idx])
            first.write_text(json.dumps(detail,indent=2),encoding='utf-8')
        raise
    finally:
        (ROOT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':
    main()
