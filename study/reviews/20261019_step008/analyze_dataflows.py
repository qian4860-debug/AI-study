"""Structural screening for step008. Counts are analytical, NOT candidate RTL timing."""
from pathlib import Path
import csv,hashlib,json,math,sys,zipfile
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent.parent
LIB=Path('D:/学习资料/资料')
LAYOUTS=[(4,1),(2,2),(1,4)]

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def ceildiv(n,d):return (n+d-1)//d

def screen(k,m,pk,po):
    assert 1<=k<=256 and 1<=m<=8 and pk*po==4
    groups=ceildiv(k,pk)*ceildiv(m,po)
    return dict(K=k,M=m,P_K=pk,P_O=po,macs=k*m,issue_groups=groups,
        valid_x_read_bytes=k*ceildiv(m,po),valid_w_read_bytes=k*m,
        valid_operand_read_bytes=k*ceildiv(m,po)+k*m,
        useful_issue_slot_fraction=k*m/(4*groups),scalar_quant_values=m)

def prove_schedule(k,m,pk,po):
    visited=set();x_reads=0;groups=0
    for row0 in range(0,m,po):
        for j0 in range(0,k,pk):
            groups+=1
            # One read per active x index, broadcast to active output lanes.
            x_reads+=min(pk,k-j0)
            banks=[]
            for row in range(row0,min(m,row0+po)):
                for j in range(j0,min(k,j0+pk)):
                    assert (row,j) not in visited
                    visited.add((row,j));banks.append((row%po)*pk+j%pk)
            assert len(banks)==len(set(banks)),'concurrent W bank collision'
    expected=screen(k,m,pk,po)
    assert len(visited)==k*m and groups==expected['issue_groups'] and x_reads==expected['valid_x_read_bytes']

def prove_full_layout(pk,po):
    # Preserve two layers * 8 rows * 256 elements = 4096 weight bytes.
    addresses=set()
    for layer in range(2):
        for row in range(8):
            for j in range(256):
                bank=(row%po)*pk+j%pk
                address=layer*512+(row//po)*(256//pk)+j//pk
                assert 0<=bank<4 and 0<=address<1024
                addresses.add((bank,address))
    assert len(addresses)==4096

def write_csv(name,rows):
    with (ROOT/name).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)

def source_catalog():
    items=[
        dict(id='architecture_book',relative='AI处理器硬件架构设计15590195 书签.pdf',
             read_locations='PDF128/131/133/135/246/247; printed112/115/117/119/230/231; sections5.1,5.2.1-3,8.2.1',
             method='scanned PDF; rendered six complete pages and visually inspected',
             adoption='matrix-loop mapping, reuse and banking concepts; no reproduced figures/text'),
        dict(id='ls7_design',relative='LS-7-NPU实战项目/NPU设计文档.docx',
             read_locations='综述/模块结构图/处理流程/对外接口; OOXML paragraphs7/15/32/49 (not printed page numbers)',
             method='read-only word/document.xml paragraphs including interface tables',
             adoption='operator-control vs data path and optional direct forwarding; no code copied'),
        dict(id='lenet_fc',relative='LeNet-5 CNN加速器源码及文档/Conv_integration_0104/ANNfull.v',
             read_locations='lines1-14,31-111,119-140',method='read-only source',
             adoption='review wide FC/weight interface and fixed-address scheduling; not compatible as a drop-in core'),
        dict(id='lenet_top',relative='LeNet-5 CNN加速器源码及文档/Conv_integration_0104/Lenet.v',
             read_locations='lines3-4,35-43,53-67',method='read-only source',
             adoption='16-to-32 IEEE conversion and fixed-cycle phase control are differences to current contract'),
        dict(id='hipu_archive',relative='77830AI处理器：硬件架构设计资源/AI处理器：硬件架构设计资源/HiPU.zip',
             read_locations='members HiPU/README.md sections1/2.3/start3.1; HiPU/hpu_software/README.md; HiPU/hpu_software/LICENSE',
             method='ZIP directory and three in-memory member reads only; no extraction or execution',
             adoption='future system/quantization study; no design or performance result transplanted')]
    for item in items:
        path=LIB/item.pop('relative');assert path.is_file()
        item.update(path=str(path),sha256=sha(path),size_bytes=path.stat().st_size)
    with zipfile.ZipFile(LIB/'77830AI处理器：硬件架构设计资源/AI处理器：硬件架构设计资源/HiPU.zip') as z:
        items[-1]['members_sha256']={n:hashlib.sha256(z.read(n)).hexdigest() for n in ['HiPU/README.md','HiPU/hpu_software/README.md','HiPU/hpu_software/LICENSE']}
    return dict(library_root=str(LIB),read_only=True,no_reference_code_copied=True,
                licensing='No explicit license files found in inspected LS7/LeNet trees. MIT text exists under HiPU/hpu_software; hardware license coverage not established.',sources=items)

def main():
    result=dict(status='RUNNING',scope='analytical exploration; no step008 RTL, synthesis, power or accuracy gain is claimed')
    try:
        step7=BASE/'step007'
        manifest=json.loads((step7/'artifact_manifest.json').read_text())
        for name,want in manifest['sha256'].items():assert sha(step7/name)==want,name
        with (step7/'metrics.csv').open() as f:
            measured=[{k:(int(v) if k!='style' else v) for k,v in r.items()} for r in csv.DictReader(f) if r['style']=='hybrid']
        assert len(measured)==632
        shapes=[]
        for pk,po in LAYOUTS:
            prove_full_layout(pk,po)
            for k in range(1,257):
                for m in range(1,9):
                    prove_schedule(k,m,pk,po);shapes.append(screen(k,m,pk,po))
        write_csv('shape_screen.csv',shapes)
        workload=[]
        for r in measured:
            k,h,o=r['K'],r['H'],r['O']
            for pk,po in LAYOUTS:
                a,b=screen(k,h,pk,po),screen(h,o,pk,po)
                if (pk,po)==(4,1):
                    assert a['issue_groups']==r['groups1'] and b['issue_groups']==r['groups2']
                    assert a['macs']==r['pairs1'] and b['macs']==r['pairs2']
                workload.append(dict(id=r['id'],K=k,H=h,O=o,P_K=pk,P_O=po,
                    measured_step007_cycles=r['cycles'],issue_groups=a['issue_groups']+b['issue_groups'],
                    x_read_bytes=a['valid_x_read_bytes']+b['valid_x_read_bytes'],
                    w_read_bytes=a['valid_w_read_bytes']+b['valid_w_read_bytes'],
                    quant_values=h+o,host_initial_load_writes=r['host_loads'],
                    candidate_total_cycles=r['cycles'] if (pk,po)==(4,1) else 'NOT_IMPLEMENTED'))
        write_csv('workload_screen.csv',workload)
        trained=[]
        for pk,po in LAYOUTS:
            a,b=screen(16,8,pk,po),screen(8,2,pk,po)
            trained.append(dict(P_K=pk,P_O=po,issue_groups=a['issue_groups']+b['issue_groups'],
                x_read_bytes=a['valid_x_read_bytes']+b['valid_x_read_bytes'],
                w_read_bytes=144,operand_read_bytes=a['valid_x_read_bytes']+b['valid_x_read_bytes']+144,
                MACs=144,quant_values=10,total_cycles=104 if (pk,po)==(4,1) else 'NOT_IMPLEMENTED'))
        # Deployment hot-load hypothesis: layer parameters remain resident.
        # Current actual measured cold write count is x16+W144+bias10=170.
        sample=next(r for r in measured if r['id']==97)
        assert sample['cycles']==104 and sample['host_loads']==170
        cold=170+1+104;warm=16+1+104
        result.update(status='PASS',prior_artifacts_verified=len(manifest['sha256']),
            layout_shapes_checked=len(shapes),weight_capacity_per_layout=4096,
            prior_tasks_crosschecked=len(measured),trained_16_8_2_screen=trained,
            hot_load_hypothesis=dict(measured_cold_edges=cold,derived_warm_edges=warm,
                parameter_writes_avoided=154,derived_ratio=cold/warm,
                requires='dedicated retained-model RTL regression, model identity/change checks, reset/reload protocol',
                scope='formula for existing interface with no stalls; not a newly measured warm-run result'),
            source_sha256={str(p.relative_to(BASE)):sha(p) for p in [ROOT/'analyze_dataflows.py',step7/'metrics.csv',step7/'artifact_manifest.json',step7/'results.json']})
        (ROOT/'sources.json').write_text(json.dumps(source_catalog(),indent=2,ensure_ascii=False),encoding='utf-8',newline='\n')
        print(json.dumps(result,indent=2,ensure_ascii=False))
    except Exception as e:result.update(status='FAIL',error=str(e));raise
    finally:(ROOT/'analysis_results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8',newline='\n')

if __name__=='__main__':main()
