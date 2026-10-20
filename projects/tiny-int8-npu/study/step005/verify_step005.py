"""FC control/stream cycle oracle around the verified four-lane dot pipeline."""
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,os,random,re,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parent;BUILD=ROOT/'build';BASE=ROOT.parent;SEED=20261018
spec=importlib.util.spec_from_file_location('step004_oracle',BASE/'step004/verify_step004.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
FIELDS=('cycle reset start k_cfg m_cfg relu_cfg fetch_enable out_ready host_we host_kind host_addr host_data '
        'start_fire host_fire out_fire core_start_fire state busy host_ready k_latched m_latched relu_latched channel '
        'bias_latched out_valid out_index out_last out_dot out_pre out_data done cfg_error '
        'core_busy core_out_valid core_out_data issued_groups rsp_mask rsp_last mul_mask mul_last reduce_pending '
        'rd_mask x_rd_addr w_rd_addr').split()


def reference(x,w,bias,relu):
    if not 1<=len(x)<=256 or not 1<=len(w)<=8 or len(bias)!=len(w):raise ValueError('shape')
    if any(len(row)!=len(x) for row in w):raise ValueError('shape')
    if any(type(v) is not int or not -128<=v<=127 for v in x+[v for row in w for v in row]):raise ValueError('INT8')
    if any(type(v) is not int or not -(1<<31)<=v<(1<<31) for v in bias):raise ValueError('INT32')
    dot=[sum(a*b for a,b in zip(x,row)) for row in w]
    pre=[v+b for v,b in zip(dot,bias)]
    assert all(-(1<<32)<=v<(1<<32) for v in pre)
    return dot,pre,[max(0,v) if relu else v for v in pre]


def cases_generate():
    rng=random.Random(SEED);cases=[]
    def add(label,x,w,bias,relu,flow='none'):
        dot,pre,y=reference(x,w,bias,relu)
        cases.append(dict(label=label,K=len(x),M=len(w),x=x,w_flat=[v for row in w for v in row],
                          bias=bias,relu=bool(relu),dot=dot,pre=pre,expected=y,flow=flow))
    for relu in [False,True]:
        add('hand_relu_'+str(int(relu)),[2,-3,4],[[1,2,-1],[-1,0,2],[0,0,0]],[3,-2,-1],relu)
        add('extreme_relu_'+str(int(relu)),[-128]*256,[[-128]*256,[127]*256],[(1<<31)-1,-(1<<31)],relu)
    add('zero_boundary',[2,-3,4],[[1,2,-1],[-1,0,2],[0,0,0]],[8,-6,0],True)
    add('max_shape',[((j*29+3)%256)-128 for j in range(256)],
        [[((i*37+j*11+5)%256)-128 for j in range(256)] for i in range(8)],
        [-(1<<31),(1<<31)-1,0,-1,1,-12345,67890,42],False)
    for i,k in enumerate([1,2,3,4,5,7,8,9,15,16,17,63,255,256]):
        m=[1,3,8][i%3]
        add(f'boundary_{k}',[rng.randint(-128,127) for _ in range(k)],
            [[rng.randint(-128,127) for _ in range(k)] for _ in range(m)],
            [rng.choice([0,-(1<<31),(1<<31)-1]) for _ in range(m)],bool(i%2))
    for i in range(96):
        k=rng.randint(1,64);m=rng.randint(1,8)
        add(f'random_{i:03}',[rng.randint(-128,127) for _ in range(k)],
            [[rng.randint(-128,127) for _ in range(k)] for _ in range(m)],
            [rng.randint(-(1<<31),(1<<31)-1) for _ in range(m)],bool(rng.randrange(2)))
    for i,k in enumerate([1,3,5,17,256,1,3,5,17,256,255,9]):
        m=[1,3,8][i%3]
        add(f'flow_{i:02}',[rng.randint(-128,127) for _ in range(k)],
            [[rng.randint(-128,127) for _ in range(k)] for _ in range(m)],
            [rng.randint(-1000,1000) for _ in range(m)],bool(i%2),['fetch','output','both'][i%3])
    return cases


class Oracle:
    def __init__(self):
        self.core=prior.Oracle(4)
        self.state=self.k=self.m=self.relu=self.ch=self.bias_snap=0
        self.ov=self.oi=self.ol=self.odot=self.opre=self.odata=0
        self.x=[None]*256;self.w=[[None]*256 for _ in range(8)];self.bias=[None]*8
        self.trace=[];self.stimulus=[];self.tasks=[];self.pending=None;self.valid_cycle=0
        self.starts=self.invalid=self.aborted=self.host_writes=self.read_groups=self.read_pairs=self.accepted_outputs=0
        self.stalled_outputs=0

    @property
    def busy(self):return int(self.state!=0)

    def tick(self,reset=0,start=0,k=0,m=0,relu=0,fetch=1,ready=1,host=0,kind=0,addr=0,data=0,label=''):
        c=len(self.trace)+1;oldstate=self.state
        legal=(kind==0 and addr<256) or kind==1 or (kind==2 and addr<8)
        sf=int(not reset and start and not self.busy)
        hf=int(not reset and not self.busy and not start and legal and host)
        of=int(not reset and self.ov and ready)
        launch=int(not reset and oldstate==1)
        cr=self.core
        oldcv=cr.trace[-1]['out_valid'] if cr.trace else 0
        oldco=cr.out
        read=int(not reset and cr.busy and fetch and cr.issued*4<cr.k)
        ra=cr.issued&63;wa=self.ch*64+ra
        mask=sum(1<<i for i in range(4) if read and cr.issued*4+i<cr.k)
        self.stimulus.append((reset,start,k,m,relu,fetch,ready,host,kind,addr,data))
        done=err=0
        if not reset and self.busy:
            if cr.busy and cr.issued*4<cr.k and not fetch:self.pending['fetch_stalls']+=1
            if oldstate==3 and self.ov and not ready:
                self.pending['output_stalls']+=1;self.stalled_outputs+=1
        if launch:
            cr.xmem=self.x.copy();cr.wmem=self.w[self.ch].copy()
        cr.tick(reset=reset,start=launch,k=self.k,fetch=fetch,label=f'{label}_ch{self.ch}')
        if read:self.read_groups+=1;self.read_pairs+=mask.bit_count()
        if reset:
            if self.busy:self.aborted+=1
            self.state=self.k=self.m=self.relu=self.ch=self.bias_snap=0
            self.ov=self.oi=self.ol=self.odot=self.opre=self.odata=0
            self.pending=None
        else:
            if hf:
                self.host_writes+=1
                v=(data&255)-256 if data&128 else data&255
                if kind==0:self.x[addr]=v
                elif kind==1:self.w[addr//256][addr%256]=v
                else:self.bias[addr]=data
            if oldstate==0 and sf:
                if 1<=k<=256 and 1<=m<=8:
                    dot,pre,y=reference(self.x[:k],[row[:k] for row in self.w[:m]],self.bias[:m],bool(relu))
                    self.k=k;self.m=m;self.relu=relu;self.ch=0;self.ov=0;self.state=1;self.starts+=1
                    self.pending=dict(label=label,K=k,M=m,start_cycle=c,fetch_stalls=0,output_stalls=0,
                                      dot=dot,pre=pre,expected=y,outputs=[])
                else:err=1;self.invalid+=1
            elif oldstate==1:
                self.bias_snap=self.bias[self.ch];self.state=2
            elif oldstate==2 and oldcv:
                self.odot=oldco;self.opre=oldco+self.bias_snap
                self.odata=max(0,self.opre) if self.relu else self.opre
                self.oi=self.ch;self.ol=int(self.ch==self.m-1);self.ov=1;self.state=3;self.valid_cycle=c
            elif oldstate==3 and of:
                self.accepted_outputs+=1
                row=dict(index=self.oi,last=self.ol,dot=self.odot,pre=self.opre,data=self.odata,
                         valid_cycle=self.valid_cycle,accepted_cycle=c)
                self.pending['outputs'].append(row)
                assert row['dot']==self.pending['dot'][self.oi] and row['pre']==self.pending['pre'][self.oi] and row['data']==self.pending['expected'][self.oi]
                self.ov=0
                if self.ol:
                    t=self.pending;t.update(completion_cycle=c,latency_cycles=c-t['start_cycle'])
                    assert t['latency_cycles']==self.m*((self.k+3)//4+6)+t['fetch_stalls']+t['output_stalls']
                    assert len(t['outputs'])==self.m
                    self.tasks.append(t);self.pending=None;self.state=0;done=1
                else:self.ch+=1;self.state=1
        cv=cr.trace[-1]
        vals=[c,reset,start,k,m,relu,fetch,ready,host,kind,addr,data,sf,hf,of,launch,self.state,self.busy,
              int(not reset and not self.busy and not start and legal),self.k,self.m,self.relu,self.ch,self.bias_snap,
              self.ov,self.oi,self.ol,self.odot,self.opre,self.odata,done,err,
              cr.busy,cv['out_valid'],cr.out,cr.issued,cv['rsp_mask'],cv['rsp_last'],cv['mul_mask'],cv['mul_last'],int(cr.reduce),mask,ra,wa]
        self.trace.append(dict(zip(FIELDS,vals)))


def generate(cases):
    o=Oracle();rng=random.Random(SEED+1)
    def load(case):
        for j,x in enumerate(case['x']):o.tick(host=1,kind=0,addr=j,data=x)
        for i,v in enumerate(case['w_flat']):o.tick(host=1,kind=1,addr=(i//case['K'])*256+i%case['K'],data=v)
        for i,b in enumerate(case['bias']):o.tick(host=1,kind=2,addr=i,data=b)
    def finish(flow='none'):
        n=0;output_block=0
        while o.busy:
            assert n<100000
            fetch=1;ready=1
            if flow in ('fetch','both'):fetch=int(rng.randrange(4)!=0)
            if flow in ('output','both'):
                if o.state==3 and output_block<16:ready=0;output_block+=1
                else:ready=int(rng.randrange(3)!=0)
            o.tick(start=int(n%11==2),k=rng.randrange(512),m=rng.randrange(16),relu=rng.randrange(2),
                   fetch=fetch,ready=ready,host=1,kind=2,addr=0,data=(1<<31)-1)
            n+=1
    o.tick(reset=1,start=1,k=256,m=8,host=1,data=127)
    # Nonzero poison for every bank/row, then each layer loads only its real region.
    for j in range(256):o.tick(host=1,kind=0,addr=j,data=127)
    for j in range(2048):o.tick(host=1,kind=1,addr=j,data=-128)
    for j in range(8):o.tick(host=1,kind=2,addr=j,data=42)
    for case in cases:
        load(case)
        o.tick(start=1,k=case['K'],m=case['M'],relu=int(case['relu']),host=1,kind=2,addr=0,data=123,label=case['label'])
        finish(case['flow']);o.tick()
    for k in [0,*range(257,512)]:o.tick(start=1,k=k,m=1);o.tick()
    for m in [0,*range(9,16)]:o.tick(start=1,k=3,m=m);o.tick()
    o.tick(start=1,k=511,m=15);o.tick()
    for kind,addr in [(3,0),(0,256),(0,2047),(2,8),(2,2047)]:o.tick(host=1,kind=kind,addr=addr,data=0)
    # Interrupt launch, RAM, product, reduction, output stall and a later channel.
    test=dict(label='reset_template',K=5,M=3,x=[1]*5,w_flat=[-2]*15,bias=[3,4,5],relu=False)
    for phase in range(7):
        load(test);o.tick(start=1,k=5,m=3,label=f'abort_{phase}')
        if phase<=4:
            for _ in range(phase):o.tick(ready=0)
        elif phase==5:
            while o.state!=3:o.tick(ready=0)
            for _ in range(12):o.tick(ready=0)
        else:
            while o.ch<1:o.tick()
            o.tick()
        assert o.busy
        o.tick(reset=1,start=1,k=1,m=1,host=1,kind=2,data=(1<<31)-1)
        o.tick()
        o.tick(start=1,k=5,m=3,label=f'restart_{phase}')
        finish();o.tick()
    o.tick(reset=1);o.tick()
    return o


def execute(args,name,cwd=BUILD):
    p=subprocess.run([str(a) for a in args],cwd=cwd,text=True,capture_output=True,encoding='utf-8',errors='replace')
    log=p.stdout+p.stderr;(ROOT/name).write_text(log,encoding='utf-8')
    if p.returncode:raise RuntimeError(f'{name}: exit={p.returncode}\n{log[-6000:]}')
    return log


def simulate():
    files=[BASE/'step004/dot_banked_core.v',BASE/'step004/bank_ram.v',ROOT/'fc_int8_top.v',ROOT/'tb_fc_int8.v']
    iv,vv=shutil.which('iverilog'),shutil.which('vvp')
    if iv and vv:
        execute([iv,'-g2012','-s','tb_fc_int8','-o','step005.vvp',*files],'compile.log')
        return execute([vv,'step005.vvp'],'simulation.log'),'Icarus Verilog'
    bp=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))
    execute([bp/'xvlog.bat','--sv',*files],'compile.log')
    execute([bp/'xelab.bat','tb_fc_int8','--timescale','1ns/1ps','-s','step005_snapshot'],'elaborate.log')
    return execute([bp/'xsim.bat','step005_snapshot','-runall'],'simulation.log'),'Vivado Simulator 2025.1'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--use-matlab-results',action='store_true');args=parser.parse_args()
    BUILD.mkdir(exist_ok=True);result=dict(status='RUNNING',seed=SEED,matlab='NOT_RUN',synthesis='NOT_RUN');o=None
    try:
        p=json.loads((BASE/'step004/results.json').read_text(encoding='utf-8'))
        assert p['status']=='PASS' and p['matlab']['status']=='PASS' and p['synthesis']['status']=='PASS'
        assert all(hashlib.sha256((BASE/n).read_bytes()).hexdigest()==h for n,h in p['sha256'].items())
        result['step004_prerequisite']='PASS; saved source hashes verified'
        cases=cases_generate();vp=ROOT/'vectors.json';text=json.dumps(cases,indent=2)
        if not vp.exists() or vp.read_text()!=text:vp.write_text(text)
        o=generate(cases)
        (BUILD/'stimulus.txt').write_text('\n'.join(' '.join(map(str,v)) for v in o.stimulus)+'\n')
        log,tool=simulate()
        summary=(f'PASS STEP005 cycles={len(o.trace)} starts={o.starts} completed={len(o.tasks)} invalid={o.invalid} '
                 f'aborted={o.aborted} outputs={o.accepted_outputs} host_writes={o.host_writes} reads={o.read_groups} pairs={o.read_pairs}')
        assert summary in log,log[-6000:]
        with (BUILD/'rtl_trace.csv').open(newline='') as fd:rows=list(csv.DictReader(fd))
        assert len(rows)==len(o.trace)
        for got,want in zip(rows,o.trace):
            actual={k:int(got[k]) for k in FIELDS}
            if actual!=want:raise AssertionError(f'FAIL cycle={want["cycle"]} actual={actual} expected={want}')
        byname={t['label']:t for t in o.tasks};metrics=[];output_rows=[]
        for case in cases:
            t=byname[case['label']];assert t['dot']==case['dot'] and t['pre']==case['pre'] and t['expected']==case['expected']
            active=o.trace[t['start_cycle']-1:t['completion_cycle']]
            groups=sum(int(r['rd_mask']!=0) for r in active);pairs=sum(r['rd_mask'].bit_count() for r in active)
            assert groups==case['M']*((case['K']+3)//4) and pairs==case['M']*case['K']
            loads_count=case['K']+case['K']*case['M']+case['M']
            loaded=o.trace[t['start_cycle']-1-loads_count:t['start_cycle']-1]
            loads=sum(r['host_fire'] for r in loaded)
            bias_reads=sum(r['core_start_fire'] for r in active)
            accepted=sum(r['out_fire'] for r in active)
            assert loads==loads_count and bias_reads==accepted==case['M']
            metrics.append(dict(label=case['label'],K=case['K'],M=case['M'],relu=case['relu'],flow=case['flow'],
                cycles=t['latency_cycles'],fetch_stalls=t['fetch_stalls'],output_stalls=t['output_stalls'],
                macs=pairs,read_groups=groups,ram_read_bytes=2*pairs,bias_reads=bias_reads,
                host_load_cycles=loads))
            for row in t['outputs']:output_rows.append(dict(layer=case['label'],**row))
        for name,data in [('metrics.csv',metrics),('outputs.csv',output_rows)]:
            with (ROOT/name).open('w',newline='') as fd:
                wr=csv.DictWriter(fd,fieldnames=list(data[0]));wr.writeheader();wr.writerows(data)
        for name in ['hand_relu_0','hand_relu_1','flow_01']:
            t=byname[name]
            with (ROOT/f'trace_{name}.csv').open('w',newline='') as fd:
                wr=csv.DictWriter(fd,fieldnames=FIELDS);wr.writeheader();wr.writerows(o.trace[t['start_cycle']-1:t['completion_cycle']])
        result.update(status='PASS',simulator=tool,layers=len(cases),main_output_checks=sum(c['M'] for c in cases),
            random_layers=96,completed_layers=len(o.tasks),
            legal_starts=o.starts,aborted_layers=o.aborted,illegal_starts=o.invalid,outputs=o.accepted_outputs,
            cycles_checked=len(rows),trace_fields=len(FIELDS),host_writes=o.host_writes,read_groups=o.read_groups,
            read_pairs=o.read_pairs,output_stall_cycles=o.stalled_outputs)
        if args.use_matlab_results:
            mp=ROOT/'matlab_results.json'
            assert mp.stat().st_mtime>=max(q.stat().st_mtime for q in [vp,ROOT/'fc_int8_reference.m',ROOT/'test_step005_reference.m'])
            m=json.loads(mp.read_text());assert m['status']=='PASS' and m['layers']==len(cases);result['matlab']=m
        sp=ROOT/'synthesis_results.json'
        if sp.exists() and sp.stat().st_mtime>=max(q.stat().st_mtime for q in
            [ROOT/'fc_int8_top.v',BASE/'step004/dot_banked_core.v',BASE/'step004/bank_ram.v',ROOT/'synthesize.tcl']):
            result['synthesis']=json.loads(sp.read_text())
            result['synthesis']['timing_scope']='Post-synthesis clock-only 10 ns estimate; no I/O delays or clock location; no implementation closure'
        sources=[ROOT/n for n in ['fc_int8_top.v','tb_fc_int8.v','verify_step005.py','fc_int8_reference.m','test_step005_reference.m']]
        sources+=[q for q in [ROOT/'synthesize.tcl',ROOT/'run_synthesis.ps1'] if q.exists()]
        sources+=[BASE/'step004/dot_banked_core.v',BASE/'step004/bank_ram.v',BASE/'step004/verify_step004.py']
        result['sha256']={str(q.relative_to(BASE)):hashlib.sha256(q.read_bytes()).hexdigest() for q in sources}
        print(summary)
    except Exception as e:
        result.update(status='FAIL',error=str(e));fp=ROOT/'first_failure.json'
        if not fp.exists():
            detail=dict(error=str(e));match=re.search(r'FAIL cycle=(\d+)',str(e))
            if match and o:
                idx=int(match[1])-1;detail.update(cycle=idx+1,stimulus=o.stimulus[idx],expected=o.trace[idx])
            fp.write_text(json.dumps(detail,indent=2),encoding='utf-8')
        raise
    finally:(ROOT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
