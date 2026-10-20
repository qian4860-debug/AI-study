"""Re-run ORIGINAL oracles and TBs with distributed RAM; keep prior sources/results intact."""
from pathlib import Path
import csv,hashlib,importlib.util,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
BIN=Path(os.environ.get('VIVADO_BIN',r'D:\vivado\2025.1\Vivado\bin'))

def load(step):
    p=BASE/step/f'verify_{step}.py';spec=importlib.util.spec_from_file_location(step,p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def main():
    result=dict(status='RUNNING',variants={})
    try:
        for step in ['step003','step004','step005','step006']:
            if step=='step006':sys.path.insert(0,str(BASE/'step006'))
            mod=load(step);dest=ROOT/step;build=dest/'build';build.mkdir(parents=True,exist_ok=True)
            if step=='step003':
                names=['dot_serial_mem.v','dot_mem_top.v','sync_byte_ram.v','tb_dot_mem.v'];top='tb_dot_mem';oracles=[mod.generate()[0]]
            elif step=='step004':
                names=['dot_banked_core.v','dot_banked_top.v','bank_ram.v','tb_dot_banked.v'];top='tb_dot_banked';oracles=[mod.generate(p,mod.workloads()) for p in [1,2,4]]
            elif step=='step005':
                names=['fc_int8_top.v','tb_fc_int8.v'];top='tb_fc_int8';oracles=[mod.generate(mod.cases_generate())]
            else:
                names=['requant_i8.v','mlp2_top.v','tb_mlp.v'];top='tb_mlp';oracles=[]
                shutil.copyfile(BASE/'step006/build/mlp_cases.txt',build/'mlp_cases.txt')
            sources={n:BASE/step/n for n in names}
            if step=='step005':sources.update({n:BASE/'step004'/n for n in ['dot_banked_core.v','bank_ram.v']})
            if step=='step006':
                sources.update({n:BASE/'step004'/n for n in ['dot_banked_core.v','bank_ram.v']})
                sources['fc_int8_top.v']=BASE/'step005/fc_int8_top.v'
            for name,p in sources.items():
                text=p.read_text(encoding='utf-8');(dest/name).write_text(re.sub(r'ram_style\s*=\s*"block"','ram_style="distributed"',text),encoding='utf-8')
            for i,o in enumerate(oracles):
                suffix=f'_p{[1,2,4][i]}' if step=='step004' else ''
                (build/f'stimulus{suffix}.txt').write_text(''.join(' '.join(map(str,r))+'\n' for r in o.stimulus))
            def run(args,name):
                p=subprocess.run([str(x) for x in args],cwd=build,capture_output=True,text=True,encoding='utf-8',errors='replace')
                (dest/name).write_text(p.stdout+p.stderr,encoding='utf-8');assert p.returncode==0,(step,name,p.stderr[-1500:]);return p.stdout+p.stderr
            run([BIN/'xvlog.bat','--sv',*[dest/n for n in sources]],'compile.log')
            run([BIN/'xelab.bat',top,'--timescale','1ns/1ps','-s','ram_variant'],'elaborate.log')
            log=run([BIN/'xsim.bat','ram_variant','-runall'],'simulation.log');assert 'PASS' in log and 'Fatal:' not in log
            edges=0
            if step=='step006':
                for name in ['mlp_events.csv','mlp_metrics.csv']:
                    assert (build/name).read_bytes()==(BASE/'step006/build'/name).read_bytes(),name
                match=re.search(r'PASS MLP completed=624 invalid=8 aborted=125 cycles=(\d+)',log);assert match
                edges=int(match.group(1))
            for i,o in enumerate(oracles):
                trace=build/(f'trace_p{[1,2,4][i]}.csv' if step=='step004' else 'rtl_trace.csv')
                with trace.open() as f:rows=list(csv.DictReader(f))
                assert len(rows)==len(o.trace)
                for got,want in zip(rows,o.trace):assert {k:int(got[k]) for k in mod.FIELDS}==want,(step,want['cycle'])
                edges+=len(rows)
            result['variants'][step]=dict(status='PASS',edges_checked=edges,trace_fields=len(mod.FIELDS) if oracles else 'per-layer golden and full event/metric equivalence',
                source_sha256={n:hashlib.sha256((dest/n).read_bytes()).hexdigest() for n in sources},
                baseline_source_sha256={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources.values()})
            print(f'PASS distributed {step} trace_edges={edges}',flush=True)
        result['status']='PASS'
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'memory_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
