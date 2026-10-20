"""One command: compile deployment, generate actual host loads, verify chosen RTL."""
from pathlib import Path
import argparse
import copy
import csv
import json
import re
import subprocess
import sys

from deployment import (BASE, ROOT, CORES, DeploymentSession, compile_deployment,
                        descriptor, export_package, infer, load, save, sha, sources)
import verify_step008a as backend


def prerequisites():
    counts = {}
    for stage in ['step007', 'step008a', 'step008b']:
        manifest = load(BASE / stage / 'artifact_manifest.json')
        for n, h in manifest['sha256'].items():
            if sha(BASE / stage / n) != h:
                raise ValueError('modified frozen artifact: ' + stage + '/' + n)
        counts[stage] = len(manifest['sha256'])
    return counts


def scenarios(package, vectors, dest):
    """The generated commands, not an estimated cost, drive actual RTL writes."""
    session = DeploymentSession()
    session.bind(package)
    tasks = []

    def add(label, plan, sample, reset=0, interrupt=0, heldout=False):
        if reset:
            session.invalidate()
        session.bind(plan)
        prefix = []
        if interrupt:
            pending = session.begin()
            prefix = pending[:interrupt]
            if len(prefix) != interrupt:
                raise ValueError('interruption needs cold upload')
            for c in prefix:
                session.acknowledge(c, True)
            session.invalidate()
        commands = session.begin()
        for c in commands:
            session.acknowledge(c, True)
        if commands:
            session.finish()
        inputs = session.inputs(sample['x'])
        tasks.append(dict(id=len(tasks), label=label, heldout=heldout,
                          truth=sample.get('label'), deployment_id=plan['deployment_id'],
                          parameter_writes=len(commands), prefix_writes=len(prefix),
                          reset_before=reset, interrupt_after=interrupt,
                          config=plan['config'], commands=prefix + commands + inputs,
                          x=sample['x'], records=infer(plan['descriptor']['model'], sample['x'])))

    for i, v in enumerate(vectors):
        add('input_' + str(i), package, v, heldout=True)
    other = copy.deepcopy(package['descriptor'])
    layer = other['model']['layers'][0]
    layer['weight'][0][0] += 1 if layer['weight'][0][0] < 127 else -1
    other['model']['layers'][1]['bias'][0] += 1 if other['model']['layers'][1]['bias'][0] < (1 << 31) - 1 else -1
    other = compile_deployment(other)
    # Persist every model referenced by the transaction stream.
    save(dest / 'switched_package.json', other)
    v = vectors[0]
    add('switch_B_cold', other, v)
    add('B_warm', other, v)
    add('switch_A_cold', package, v)
    add('reset_A_reload', package, v, reset=1)
    add('A_warm_after_reset', package, v)
    add('interrupt_B_upload_reload', other, v, interrupt=7)
    add('B_warm_after_interrupt', other, v)
    lines, flags = [], []
    for t in tasks:
        c = t['config']
        head = [t['id'], c['K'], c['H'], c['O'], c['mult1'], c['shift1'],
                c['mult2'], c['shift2'], 1, 0, 0, len(t['commands'])]
        lines.append(' '.join(map(str, head)))
        lines.extend(' '.join(map(str, command)) for command in t['commands'])
        for record in t['records']:
            lines.extend(' '.join(map(str, [pre, *q]))
                         for pre, q in zip(record['pre'], record['quantized']))
        flags.append(f"{t['reset_before']} {t['interrupt_after']}")
    (dest / 'mlp_cases.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    (dest / 'scenario_flags.txt').write_text('\n'.join(flags) + '\n', encoding='utf-8', newline='\n')
    save(dest / 'task_catalog.json', tasks)
    return tasks


def _verify_one(desc, dataset, dest):
    package, vectors = export_package(desc, dataset, dest)
    tasks = scenarios(package, vectors, dest)
    tile = package['build']['layout'] == 'k2o2'
    tb = backend.prepare_tb(dest, tile=tile)
    files = sources(package['build']['core'])
    backend.run([backend.BIN / 'xvlog.bat', '--sv', *files, tb], dest, 'compile.log')
    mode = package['build']['ram_mode']
    backend.run([backend.BIN / 'xelab.bat', f'tb_mode{mode}', '--timescale', '1ns/1ps', '-s', 'deploy_sim'], dest, 'elaborate.log')
    log = backend.run([backend.BIN / 'xsim.bat', 'deploy_sim', '-runall'], dest, 'simulation.log')
    match = re.search(r'PASS MLP completed=(\d+) invalid=8 aborted=5 cache_resets=2 cycles=(\d+) supplemental=5', log)
    if not match or int(match[1]) != len(tasks) or 'Fatal:' in log:
        raise RuntimeError(log[-3500:])
    with (dest / 'mlp_metrics.csv').open() as f:
        metrics = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(f)]
    with (dest / 'mlp_events.csv').open() as f:
        events = list(csv.DictReader(f))
    assert len(metrics) == len(tasks)
    params = len(package['parameter_commands'])
    rows = []
    correct = labelled = 0
    for task, metric in zip(tasks, metrics):
        assert task['id'] == metric['id']
        assert metric['host_loads'] == len(task['commands'])
        assert metric['cycles'] == package['expected_compute_cycles']
        for stage, record in zip(['hidden', 'output'], task['records']):
            values = [int(e['data']) for e in events if int(e['id']) == task['id'] and e['stage'] == stage]
            assert values == [q[0] for q in record['quantized']]
        if task['heldout'] and task['truth'] is not None:
            if package['config']['O'] != 2 or type(task['truth']) is not int or task['truth'] not in [0, 1]:
                raise ValueError('accuracy labels supported only for binary two-output classification')
            y = [q[0] for q in task['records'][1]['quantized']]
            correct += int(int(y[1] > y[0]) == task['truth'])
            labelled += 1
        rows.append(dict(id=task['id'], label=task['label'], parameter_writes=task['parameter_writes'],
                         prefix_writes=task['prefix_writes'], accepted_writes=metric['host_loads'],
                         compute_cycles=metric['cycles'], occupied_edges=1 + metric['host_loads'] + metric['cycles']))
    assert rows[0]['parameter_writes'] == params
    assert all(r['parameter_writes'] == 0 for r in rows[1:len(vectors)])
    assert [r['parameter_writes'] for r in rows[-7:]] == [params, 0, params, params, 0, params, 0]
    assert rows[-2]['prefix_writes'] == 7
    with (dest / 'deployment_metrics.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    result = dict(status='PASS', core=package['build']['core'], ram_mode=mode,
                  deployment_id=package['deployment_id'], shape=desc['model']['shape'],
                  input_samples=len(vectors), main_tasks=len(tasks), compute_cycles=rows[0]['compute_cycles'],
                  cold_occupied=rows[0]['occupied_edges'],
                  warm_occupied=1 + package['config']['K'] + rows[0]['compute_cycles'],
                  warm_measured=rows[-1]['occupied_edges'], model_parameter_writes=params,
                  labelled_samples=labelled, correct=correct, accuracy=correct / labelled if labelled else None,
                  summary=match[0], simulation_edges=int(match[2]))
    assert result['warm_occupied'] == result['warm_measured']
    save(dest / 'report.json', result)
    print(f"PASS {dest.name}: {result['core']} tasks={len(tasks)} compute={result['compute_cycles']} cold={result['cold_occupied']} warm={result['warm_measured']}", flush=True)
    return result


def verify_one(desc, dataset, dest):
    dest = Path(dest)
    save(dest / 'report.json', dict(status='RUNNING'))
    try:
        return _verify_one(desc, dataset, dest)
    except Exception as exc:
        save(dest / 'report.json', dict(status='FAIL', error=str(exc)))
        raise


def implementation():
    paths = [ROOT / n for n in ['deployment.py', 'verify_step009.py', 'test_deployment.py', 'run_all.ps1']]
    paths += sorted((ROOT / 'deployments').glob('*.json'))
    paths += sorted((ROOT / 'inputs').glob('*.json'))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def dependencies():
    files = set(sources('step007_k4o1') + sources('step008b_k2o2'))
    files.update(BASE / n for n in ['step006/reference.py', 'step006/trained_model.json',
                                  'step006/test_dataset.json', 'step008a/resident_model.py',
                                  'step008a/verify_step008a.py', 'step007/tb_shared.v',
                                  'step008b/select_variant.py'])
    return {p.relative_to(BASE).as_posix(): sha(p) for p in sorted(files)}


def seal(check=False):
    path = ROOT / 'artifact_manifest.json'
    if check:
        m = load(path)
        assert m['status'] == 'PASS'
        for n, h in m['sha256'].items():
            assert sha(ROOT / n) == h, n
        for n, h in m['dependency_sha256'].items():
            assert sha(BASE / n) == h, n
        print('PASS STEP009 sealed artifacts and dependencies')
        return
    r = load(ROOT / 'results.json')
    assert r['status'] == 'PASS' and r['dependency_sha256'] == dependencies()
    assert r['implementation_sha256'] == implementation(), 'rerun validation after source/config edits'
    allowed = {'.py', '.json', '.v', '.txt', '.csv', '.log', '.md', '.ps1'}
    files = [p for p in ROOT.rglob('*') if p.is_file() and p != path
             and '__pycache__' not in p.parts and 'xsim.dir' not in p.parts
             and p.suffix in allowed and not p.name.startswith('webtalk')]
    save(path, dict(status='PASS', dependency_sha256=dependencies(),
                    sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}))
    print('SEALED STEP009', len(files), 'files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment', type=Path)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--seal', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.seal or args.check:
        seal(args.check)
        return
    if args.deployment:
        if not args.inputs or not args.out:
            parser.error('--deployment requires --inputs and --out')
        prerequisites()
        verify_one(load(args.deployment), load(args.inputs), args.out.resolve())
        return
    if args.inputs or args.out:
        parser.error('--inputs/--out require --deployment')
    result = dict(status='RUNNING')
    try:
        result['prerequisites'] = prerequisites()
        log = backend.run([sys.executable, ROOT / 'test_deployment.py'], ROOT, 'unit_tests.log')
        assert 'OK' in log
        test = load(BASE / 'step006/test_dataset.json')
        model = load(BASE / 'step006/trained_model.json')
        # Checked-in descriptors are genuine pipeline inputs, never regenerated here.
        configurations = [
            ('trained_auto', 'deployments/trained_auto.json', test),
            ('trained_baseline', 'deployments/trained_baseline.json', test),
            ('fallback_auto', 'deployments/fallback_auto.json', load(ROOT / 'inputs/fallback.json')),
            ('odd_auto', 'deployments/odd_auto.json', load(ROOT / 'inputs/odd.json')),
        ]
        results = {}
        for name, path, inputs in configurations:
            desc = load(ROOT / path)
            if name.startswith('trained'):
                assert desc['model'] == model
            results[name] = verify_one(desc, inputs, ROOT / 'build' / name)
        for name, comp, cold, warm in [('trained_auto', 79, 250, 96), ('trained_baseline', 104, 275, 121)]:
            r = results[name]
            assert (r['compute_cycles'], r['cold_occupied'], r['warm_measured'], r['correct']) == (comp, cold, warm, 488)
        assert results['fallback_auto']['core'] == 'step007_k4o1'
        assert results['odd_auto']['core'] == 'step008b_k2o2'
        result.update(status='PASS', runs=results, dependency_sha256=dependencies(),
                      implementation_sha256=implementation(),
                      scope='Deployment-driven actual RTL simulation; fused two-FC, no board driver or FPGA runtime switching')
        print('PASS STEP009 END TO END', flush=True)
    except Exception as e:
        result.update(status='FAIL', error=str(e))
        raise
    finally:
        save(ROOT / 'results.json', result)


if __name__ == '__main__':
    main()
