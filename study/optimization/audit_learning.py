"""All-stage provenance, bounds, bank mapping and independent NumPy convolution checks."""
from pathlib import Path
import hashlib,importlib.util,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent

def import_file(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    result=dict(status='RUNNING',stages={})
    try:
        for stage in ['step001','step002','step003','step004','step005','step006']:
            folder=BASE if stage=='step001' else BASE/stage
            saved=json.loads((folder/'results.json').read_text(encoding='utf-8'));assert saved['status']=='PASS',stage
            if stage in ['step002','step003','step004','step005']:
                assert saved['matlab']['status']=='PASS' and saved['synthesis']['status']=='PASS',stage
            manifest=saved.get('sha256',saved.get('source_sha256',{}));assert manifest
            anchor=BASE.parent if stage=='step001' else folder if stage=='step002' else BASE
            for name,want in manifest.items():assert hashlib.sha256((anchor/name).read_bytes()).hexdigest()==want,(stage,name)
            result['stages'][stage]=dict(status='PASS',source_hashes=len(manifest),note='saved RTL PASS with current matching sources')
        ref=import_file('original_reference',BASE/'reference.py')
        generator=import_file('lab_convolution',BASE.parent/'lab3-1/data_generator.py')
        rng=np.random.default_rng(20261018);cases=[]
        for i in range(72):
            m=int(rng.integers(1,25));n=int(rng.integers(1,m+1))
            image=rng.integers(0,256,(m,m),dtype=np.uint8);kernel=rng.integers(0,256,(n,n),dtype=np.uint8)
            want=ref.convolution(image.tolist(),kernel.tolist());actual=generator.convolution(image,kernel)
            assert actual.tolist()==want
            cases.append(dict(M=m,N=n))
        max_image=np.full((254,254),255,dtype=np.uint8)
        assert generator.convolution(max_image,max_image).tolist()==[[4195152900]]==ref.convolution(max_image.tolist(),max_image.tolist())
        result['step001_numpy']=dict(status='PASS',numpy=np.__version__,cases=len(cases)+1,max_result=4195152900,
            generator_sha256=hashlib.sha256((BASE.parent/'lab3-1/data_generator.py').read_bytes()).hexdigest(),
            scope='current local lab data generator vs Python arbitrary-precision reference; convolution RTL remains scaffold')
        # Bounds include asymmetric signed INT8 endpoints and bias before ReLU.
        bounds=[];mappings=0
        for k in range(1,257):
            lo=-16256*k;hi=16384*k
            assert -(1<<23)<=lo<=hi<(1<<23)
            assert -(1<<32)<=lo-(1<<31) and hi+(1<<31)-1<(1<<32)
            for lanes in [1,2,4]:
                groups=(k+lanes-1)//lanes
                accessed=[g*lanes+l for g in range(groups) for l in range(lanes) if g*lanes+l<k]
                assert accessed==list(range(k));assert len(set((j%lanes,j//lanes) for j in accessed))==k
                mappings+=1
            bounds.append(dict(K=k,min=lo,max=hi))
        result['range_and_layout']=dict(status='PASS',all_lengths=256,bank_shape_checks=mappings,
            max_dot=4194304,min_dot=-4161536,min_bias_sum=-2151645184,max_bias_sum=2151677951,
            required_dot_bits=24,required_pre_bits=33,scope='exhaustive dimension/mapping analysis, supplement to RTL regressions')
        mem=json.loads((ROOT/'memory_results.json').read_text());assert mem['status']=='PASS'
        for stage,v in mem['variants'].items():
            for n,h in v['source_sha256'].items():assert hashlib.sha256((ROOT/stage/n).read_bytes()).hexdigest()==h
            for n,h in v['baseline_source_sha256'].items():assert hashlib.sha256((BASE/n).read_bytes()).hexdigest()==h
        result['memory_variants']=mem
        pipeline=json.loads((ROOT/'step006_pipelined/results.json').read_text());assert pipeline['status']=='PASS'
        for n,h in pipeline['sha256'].items():assert hashlib.sha256((BASE/n).read_bytes()).hexdigest()==h,n
        synth=json.loads((ROOT/'step006_pipelined/synthesis_results.json').read_text())
        assert synth['status']=='PASS' and synth['configs']['block']['WNS_ns']>=0
        result['pipeline']=dict(status='PASS',quant=pipeline['quant'],networks=pipeline['networks'],
            synthesis=synth,timing_scope='Post-synthesis clock-only 10ns estimate; not placed/routed board timing')
        result['status']='PASS'
        print('PASS stages=001..006 numpy_cases=73 bank_shapes=768 memory_variant_edges='+str(sum(v['edges_checked'] for v in mem['variants'].values())))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'audit_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

if __name__=='__main__':main()
