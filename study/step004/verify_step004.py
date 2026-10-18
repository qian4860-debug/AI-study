"""Compare 1/2/4 banked MAC lanes using identical numerical workloads."""
from pathlib import Path
import argparse,csv,hashlib,json,os,random,re,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parent
BUILD=ROOT/'build'
SEED=20261016
FIELDS=('cycle reset start k_cfg fetch_enable host_we host_addr host_x host_w start_fire '
        'read_fire host_fire read_addr read_mask busy host_ready k_latched issued_groups '
        'retired_groups retired_elements rsp_mask rsp_last mul_mask mul_last reduce_pending '
        'product0 product1 product2 product3 sum0 sum1 sum2 sum3 out_valid out_data cfg_error').split()


class Oracle:
    def __init__(self,p):
        self.p=p
        self.busy=self.k=self.issued=self.retired=self.elems=self.out=0
        self.rsp=self.mul=None
        self.reduce=False
        self.products=[0]*4;self.sums=[0]*4
        self.xmem=[None]*256;self.wmem=[None]*256
        self.trace=[];self.stimulus=[];self.tasks=[];self.pending=None
        self.starts=self.invalid=self.aborted=self.reads=self.elements=self.macs=self.writes=0

    def tick(self,reset=0,start=0,k=0,fetch=1,host=0,addr=0,x=0,w=0,label=''):
        c=len(self.trace)+1;p=self.p
        sf=int(not reset and start and not self.busy)
        hf=int(not reset and not self.busy and not start and host)
        rf=int(not reset and self.busy and fetch and self.issued*p<self.k)
        ra=self.issued&255
        mask=sum(1<<i for i in range(p) if rf and self.issued*p+i<self.k)
        self.stimulus.append((reset,start,k,fetch,host,addr,x,w))
        old_rsp,old_mul=self.rsp,self.mul
        ov=error=0
        if reset:
            if self.busy:self.aborted+=1
            self.busy=self.k=self.issued=self.retired=self.elems=self.out=0
            self.rsp=self.mul=None;self.reduce=False
            self.products=[0]*4;self.sums=[0]*4;self.pending=None
        else:
            if self.busy and self.issued*p<self.k and not fetch:self.pending['fetch_stall_cycles']+=1
            if self.reduce:
                self.out=sum(self.sums);self.sums=[0]*4
                self.busy=0;ov=1
                t=self.pending
                t.update(expected=self.out,completion_cycle=c,latency_cycles=c-t['start_cycle'])
                assert self.elems==self.k
                assert self.out==sum(a*b for a,b in zip(t['x'],t['w']))
                assert t['latency_cycles']==(self.k+p-1)//p+3+t['fetch_stall_cycles']
                self.tasks.append(t);self.pending=None
            self.reduce=False
            if old_mul:
                self.retired+=1
                for lane in range(p):
                    if old_mul['mask']>>lane&1:
                        self.sums[lane]+=old_mul['products'][lane]
                        self.elems+=1;self.macs+=1
                if old_mul['last']:self.reduce=True
            if old_rsp:
                for lane in range(p):
                    if old_rsp['mask']>>lane&1:self.products[lane]=old_rsp['products'][lane]
            self.mul=old_rsp;self.rsp=None
            if rf:
                values=[0]*4
                for lane in range(p):
                    if mask>>lane&1:
                        values[lane]=self.xmem[ra*p+lane]*self.wmem[ra*p+lane]
                        self.elements+=1
                self.issued+=1;self.reads+=1
                self.rsp=dict(mask=mask,products=values,last=int(self.issued*p>=self.k))
            if hf:
                self.xmem[addr]=x;self.wmem[addr]=w;self.writes+=1
            if sf:
                if 1<=k<=256:
                    self.busy=1;self.k=k;self.issued=self.retired=self.elems=0
                    self.rsp=self.mul=None;self.reduce=False;self.sums=[0]*4;self.starts+=1
                    assert all(v is not None for v in self.xmem[:k]+self.wmem[:k])
                    self.pending=dict(label=label,K=k,x=self.xmem[:k],w=self.wmem[:k],start_cycle=c,fetch_stall_cycles=0)
                else:self.invalid+=1;error=1
        rspmask=self.rsp['mask'] if self.rsp else 0
        mulmask=self.mul['mask'] if self.mul else 0
        assert self.issued-self.retired==int(self.rsp is not None)+int(self.mul is not None)
        vals=[c,reset,start,k,fetch,host,addr,x,w,sf,rf,hf,ra,mask,self.busy,
              int(not self.busy and not start and not reset),self.k,self.issued,self.retired,self.elems,
              rspmask,self.rsp['last'] if self.rsp else 0,mulmask,self.mul['last'] if self.mul else 0,
              int(self.reduce),*self.products,*self.sums,ov,self.out,error]
        self.trace.append(dict(zip(FIELDS,vals)))


def workloads():
    rng=random.Random(SEED)
    cases=[]
    def add(label,x,w,paused=False):cases.append(dict(label=label,K=len(x),x=x,w=w,expected=sum(a*b for a,b in zip(x,w)),paused=paused))
    for k in [1,2,3,4,5,6,7,8,9,15,16,17,31,32,33,63,64,65,127,128,129,254,255,256]:
        add(f'boundary_{k}',[rng.randint(-128,127) for _ in range(k)],[rng.randint(-128,127) for _ in range(k)])
    add('K3_hand',[2,-3,4],[1,2,-1])
    add('K256_positive',[-128]*256,[-128]*256)
    add('K256_negative',[-128]*256,[127]*256)
    add('K5_zero',[0]*5,[-128]*5)
    for i in range(128):
        k=rng.randint(1,256)
        add(f'random_{i:03}',[rng.randint(-128,127) for _ in range(k)],[rng.randint(-128,127) for _ in range(k)])
    for i,k in enumerate([1,3,4,5,7,9,17,33,63,127,255,256]):
        add(f'paused_{i:02}',[rng.randint(-128,127) for _ in range(k)],[rng.randint(-128,127) for _ in range(k)],True)
    return cases


def generate(p,cases):
    o=Oracle(p);rng=random.Random(SEED+100*p)
    def load(x,w):
        for i,(a,b) in enumerate(zip(x,w)):o.tick(host=1,addr=i,x=a,w=b,fetch=0)
    def finish(paused=False):
        n=0
        while o.busy:
            assert n<10000
            fetch=int(rng.randrange(4)!=0) if paused else 1
            if paused and o.issued*p>=o.k:fetch=0
            o.tick(fetch=fetch,start=int(n%7==2),k=rng.randrange(512),host=1,addr=0,x=127,w=-128)
            n+=1
    o.tick(reset=1,start=1,k=256,host=1,x=127,w=127)
    # Fill all locations with nonzero poison. Masked tail lanes must never read them.
    load([127]*256,[-128]*256)
    for case in cases:
        load(case['x'],case['w'])
        o.tick(start=1,k=case['K'],host=1,x=127,w=127,label=case['label'])
        finish(case['paused']);o.tick(fetch=0)
    for k in [0,*range(257,512)]:
        o.tick(start=1,k=k,host=1,x=-128,w=-128)
        o.tick(fetch=0)
    # Interrupt request, response, product, accumulation and final reduction.
    for stage in range(5):
        load([1]*17,[-2]*17)
        o.tick(start=1,k=17,label=f'abort_stage{stage}')
        count=stage if stage<4 else (17+p-1)//p+2
        for _ in range(count):o.tick(k=511)
        assert o.busy
        o.tick(reset=1,start=1,k=256,host=1,x=127,w=127)
        o.tick(fetch=0)
        o.tick(start=1,k=17,label=f'restart_stage{stage}')
        finish();o.tick(fetch=0)
    o.tick(reset=1);o.tick(fetch=0)
    return o


def execute(args,name,cwd=BUILD):
    r=subprocess.run([str(a) for a in args],cwd=cwd,text=True,capture_output=True,encoding='utf-8',errors='replace')
    log=r.stdout+r.stderr;(ROOT/name).write_text(log,encoding='utf-8')
    if r.returncode:raise RuntimeError(f'{name}: exit={r.returncode}\n{log[-6000:]}')
    return log


def simulate():
    files=[ROOT/n for n in ['dot_banked_core.v','bank_ram.v','dot_banked_top.v','tb_dot_banked.v']]
    iv,vv=shutil.which('iverilog'),shutil.which('vvp')
    if iv and vv:
        execute([iv,'-g2012','-s','tb_dot_banked','-o','step004.vvp',*files],'compile.log')
        return execute([vv,'step004.vvp'],'simulation.log'),'Icarus Verilog'
    bp=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    execute([bp/'xvlog.bat','--sv',*files],'compile.log')
    execute([bp/'xelab.bat','tb_dot_banked','--timescale','1ns/1ps','-s','step004_snapshot'],'elaborate.log')
    return execute([bp/'xsim.bat','step004_snapshot','-runall'],'simulation.log'),'Vivado Simulator 2025.1'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--use-matlab-results',action='store_true');args=parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    result=dict(status='RUNNING',seed=SEED,matlab='NOT_RUN',synthesis='NOT_RUN')
    oracles={}
    try:
        base=ROOT.parent
        prev=json.loads((base/'step003/results.json').read_text(encoding='utf-8'))
        assert prev['status']=='PASS' and prev['synthesis']['status']=='PASS' and prev['matlab']['status']=='PASS'
        assert all(hashlib.sha256((base/n).read_bytes()).hexdigest()==h for n,h in prev['sha256'].items())
        result['step003_prerequisite']='PASS, source hashes verified'
        cases=workloads();vp=ROOT/'vectors.json';text=json.dumps(cases,indent=2)
        if not vp.exists() or vp.read_text()!=text:vp.write_text(text)
        for p in [1,2,4]:
            o=generate(p,cases);oracles[p]=o
            (BUILD/f'stimulus_p{p}.txt').write_text('\n'.join(' '.join(map(str,v)) for v in o.stimulus)+'\n')
        log,tool=simulate();assert 'PASS ALL_CONFIGS' in log,log[-5000:]
        configurations={}
        for p,o in oracles.items():
            summary=(f'PASS STEP004 P={p} cycles={len(o.trace)} starts={o.starts} completed={len(o.tasks)} '
                     f'invalid={o.invalid} aborted={o.aborted} reads={o.reads} elements={o.elements} macs={o.macs} host_writes={o.writes}')
            assert summary in log,summary+'\n'+log[-5000:]
            with (BUILD/f'trace_p{p}.csv').open(newline='') as fd:rows=list(csv.DictReader(fd))
            assert len(rows)==len(o.trace)
            for got,want in zip(rows,o.trace):
                actual={k:int(got[k]) for k in FIELDS}
                if actual!=want:raise AssertionError(f'FAIL P={p} cycle={want["cycle"]} actual={actual} expected={want}')
            configurations[str(p)]=dict(cycles_checked=len(rows),complete_tasks=len(o.tasks),starts=o.starts,aborted=o.aborted,
                illegal_starts=o.invalid,read_groups=o.reads,read_elements=o.elements,macs=o.macs,host_writes=o.writes)
        metrics=[]
        maps={p:{t['label']:t for t in o.tasks} for p,o in oracles.items()}
        for case in cases:
            expected=case['expected']
            for p in [1,2,4]:
                t=maps[p][case['label']];assert t['expected']==expected
                groups=(t['K']+p-1)//p
                trace=oracles[p].trace
                active=trace[t['start_cycle']-1:t['completion_cycle']]
                loaded=trace[t['start_cycle']-1-t['K']:t['start_cycle']-1]
                measured_groups=sum(row['read_fire'] for row in active)
                measured_elements=sum(row['read_mask'].bit_count() for row in active)
                measured_loads=sum(row['host_fire'] for row in loaded)
                measured_macs=active[-1]['retired_elements']
                assert measured_groups==groups and measured_elements==measured_macs==measured_loads==t['K']
                metrics.append(dict(label=case['label'],K=t['K'],lanes=p,groups=measured_groups,
                    cycles=t['latency_cycles'],stalls=t['fetch_stall_cycles'],macs=measured_macs,ram_read_bytes=2*measured_elements,
                    host_load_cycles=measured_loads,occupied_edges_with_load=measured_loads+1+t['latency_cycles'],
                    mac_per_cycle=t['K']/t['latency_cycles'],tail_utilization=t['K']/(p*groups),
                    speedup_vs_p1=(maps[1][case['label']]['latency_cycles']/t['latency_cycles'] if not case['paused'] else None),paused=case['paused']))
        with (ROOT/'comparison.csv').open('w',newline='') as fd:
            writer=csv.DictWriter(fd,fieldnames=list(metrics[0]));writer.writeheader();writer.writerows(metrics)
        for p,o in oracles.items():
            t=maps[p]['K3_hand'];start=t['start_cycle']-1;end=t['completion_cycle']
            with (ROOT/f'trace_K3_p{p}.csv').open('w',newline='') as fd:
                writer=csv.DictWriter(fd,fieldnames=FIELDS);writer.writeheader();writer.writerows(o.trace[start:end])
        result.update(status='PASS',simulator=tool,workloads=len(cases),random_workloads=128,
                      configurations=configurations,trace_fields=len(FIELDS),comparison_rows=len(metrics))
        if args.use_matlab_results:
            mp=ROOT/'matlab_results.json'
            assert mp.stat().st_mtime>=max(p.stat().st_mtime for p in [vp,ROOT/'test_step004_reference.m',base/'step002/dot_int8_reference.m'])
            m=json.loads(mp.read_text());assert m['status']=='PASS' and m['cases']==len(cases);result['matlab']=m
        sp=ROOT/'synthesis_results.json'
        if sp.exists() and sp.stat().st_mtime>=max((ROOT/n).stat().st_mtime for n in ['dot_banked_core.v','dot_banked_top.v','bank_ram.v','synthesize.tcl']):
            result['synthesis']=json.loads(sp.read_text())
            result['synthesis']['timing_scope']='Post-synthesis clock-only 10 ns estimate; I/O delays and clock location unconstrained; no implementation closure'
        sources=[ROOT/n for n in ['dot_banked_core.v','bank_ram.v','dot_banked_top.v','tb_dot_banked.v','verify_step004.py']]
        sources+=[p for p in [ROOT/'test_step004_reference.m',ROOT/'synthesize.tcl',ROOT/'run_synthesis.ps1'] if p.exists()]
        sources.append(base/'step002/dot_int8_reference.m')
        result['sha256']={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        print(f'PASS STEP004 workloads={len(cases)} configs=1,2,4 trace_edges={sum(len(o.trace) for o in oracles.values())}')
    except Exception as e:
        result.update(status='FAIL',error=str(e));fp=ROOT/'first_failure.json'
        if not fp.exists():
            detail=dict(error=str(e));m=re.search(r'FAIL P=(\d+) cycle=(\d+)',str(e))
            if m and int(m[1]) in oracles:
                p,c=int(m[1]),int(m[2]);detail.update(lanes=p,cycle=c,stimulus=oracles[p].stimulus[c-1],expected=oracles[p].trace[c-1])
            fp.write_text(json.dumps(detail,indent=2),encoding='utf-8')
        raise
    finally:(ROOT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
