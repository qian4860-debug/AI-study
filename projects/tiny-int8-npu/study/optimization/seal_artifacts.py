"""Snapshot evidence hashes; --check is read-only and fails on any later modification."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent;MANIFEST=ROOT/'artifact_manifest.json'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.check:
        saved=json.loads(MANIFEST.read_text())
        for n,h in saved['sha256'].items():assert digest(BASE/n)==h,n
        print(f'PASS artifact SHA256 checks={len(saved["sha256"])}');return
    # This records present artifact identity; it cannot retroactively prove old run inputs.
    for p in [ROOT/'audit_results.json',ROOT/'memory_results.json',ROOT/'synthesis_results.json',
              ROOT/'step006_pipelined/results.json',ROOT/'step006_pipelined/synthesis_results.json']:
        assert json.loads(p.read_text())['status']=='PASS',p
    folders=[BASE/'step006',ROOT]
    files=set()
    for folder in folders:
        for p in folder.rglob('*'):
            if not p.is_file() or p==MANIFEST or '__pycache__' in p.parts or 'research' in p.parts:continue
            if p.suffix.lower() in ['.v','.sv','.py','.m','.ps1','.tcl','.md','.json','.csv','.txt','.rpt','.log']:
                if 'xsim.dir' not in p.parts:files.add(p)
    files.update([BASE/'README.md',BASE/'OPTIMIZED_LEARNING_PLAN.md',BASE/'SOURCE_MAP.md'])
    for stage in ['step002','step003','step004','step005']:
        folder=BASE/stage
        files.update(p for p in folder.iterdir() if p.is_file() and p.suffix in ['.json','.rpt','.csv','.md'])
    files.update([BASE/'results.json',BASE/'step006/research/catalog.json',BASE/'step006/research/mit_catalog.json'])
    obj=dict(status='PASS',algorithm='SHA256',scope='Frozen current sources, inputs, traces, reports and teaching docs; old baselines checked against their saved source hashes',
        sha256={str(p.relative_to(BASE)):digest(p) for p in sorted(files)})
    MANIFEST.write_text(json.dumps(obj,indent=2),encoding='utf-8')
    print(f'SEALED artifacts={len(files)}')

if __name__=='__main__':main()
