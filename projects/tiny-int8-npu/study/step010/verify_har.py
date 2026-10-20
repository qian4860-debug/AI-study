"""Freeze the trained model before opening test data, then run all test inputs in RTL."""
from pathlib import Path
import argparse
import csv
import sys
from prepare_data import ROOT, check_data, load, read_rows, save, sha

BASE = ROOT.parent
sys.path.insert(0, str(BASE / 'step009'))
import verify_step009 as deploy


def implementation():
    return {n: sha(ROOT / n) for n in ['prepare_data.py', 'train_har.py', 'verify_har.py',
                                      'test_har.py', 'run_all.ps1', 'experiment.json']}


def evaluate():
    from train_har import features, transform, quantize, forward, np
    from reference import infer
    result = dict(status='RUNNING')
    dest = ROOT / 'build/rtl'
    try:
        deploy.seal(check=True)
        data = check_data()
        training = load(ROOT / 'training_results.json')
        assert training['status'] == 'PASS'
        assert training['implementation_sha256'] == {n: sha(ROOT / n) for n in ['train_har.py', 'prepare_data.py']}
        for n, h in {**training['fit_sha256'], **training['output_sha256']}.items():
            assert sha(ROOT / n) == h, n
        # Only now open the official test split, after model and scales are frozen.
        rows = read_rows(ROOT / 'data/test.csv')
        membership = load(ROOT / 'split_membership.json')
        subject_sets = [set(membership['train_subjects']), set(membership['validation_subjects']),
                        {int(r['subject']) for r in rows}]
        assert all(not a & b for i, a in enumerate(subject_sets) for b in subject_sets[i + 1:])
        assert len(set.union(*subject_sets)) == 30
        pre = load(ROOT / 'preprocessing.json')
        desc = load(ROOT / 'deployment.json')
        float_model = [np.array(p, dtype=np.float64) for p in load(ROOT / 'float_model.json')['parameters']]
        x, y = features(rows)
        normalized = transform(x, pre)
        qx = quantize(normalized, pre['input_scale']).tolist()
        floating = forward(normalized, float_model)[1]
        integer = [infer(desc['model'], v) for v in qx]
        expected = [[q[0] for q in r[1]['quantized']] for r in integer]
        float_pred = floating.argmax(axis=1).tolist()
        int_pred = np.array(expected).argmax(axis=1).tolist()
        # Step009's generic numerical runner is reused unchanged. Its label helper
        # supports binary only, so multiclass labels stay in this evaluator.
        inputs = [dict(x=v) for v in qx]
        save(ROOT / 'rtl_inputs.json', inputs)
        # Legacy supplemental IDs=1000..1004 collide with a 2947-case test set.
        # Derive a local TB with IDs outside the main range; old sources stay sealed.
        original = deploy.backend.prepare_tb

        def prepare_large_tb(folder, tile=False):
            tb = original(folder, tile=tile)
            text = tb.read_text(encoding='utf-8')
            marker = 'id=1000+stage'
            assert text.count(marker) == 1
            tb.write_text(text.replace(marker, f'id={len(rows) + 100}+stage'), encoding='utf-8', newline='\n')
            return tb

        deploy.backend.prepare_tb = prepare_large_tb
        try:
            numerical = deploy.verify_one(desc, inputs, dest)
        finally:
            deploy.backend.prepare_tb = original
        assert numerical['input_samples'] == 2947 and numerical['main_tasks'] == 2954
        assert (numerical['compute_cycles'], numerical['cold_occupied'], numerical['warm_measured']) == (105, 330, 124)
        with (dest / 'mlp_events.csv').open() as f:
            events = list(csv.DictReader(f))
        actual = {i: [] for i in range(len(rows))}
        for event in events:
            tid = int(event['id'])
            if tid in actual and event['stage'] == 'output':
                assert int(event['index']) == len(actual[tid])
                actual[tid].append(int(event['data']))
        assert [actual[i] for i in range(len(rows))] == expected
        rtl_pred = [max(range(6), key=lambda j: actual[i][j]) for i in range(len(rows))]
        assert rtl_pred == int_pred
        confusion = [[0] * 6 for _ in range(6)]
        report_rows = []
        for i, row in enumerate(rows):
            truth = int(row['label'])
            confusion[truth][rtl_pred[i]] += 1
            report_rows.append(dict(source_row=int(row['source_row']), subject=int(row['subject']), label=truth,
                                    float_prediction=float_pred[i], integer_prediction=int_pred[i],
                                    rtl_prediction=rtl_pred[i], **{f'logit{j}': actual[i][j] for j in range(6)}))
        with (ROOT / 'predictions.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(report_rows)
        fa = sum(int(a == b) for a, b in zip(float_pred, y)) / len(y)
        ia = sum(int(a == b) for a, b in zip(rtl_pred, y)) / len(y)
        gate = load(ROOT / 'experiment.json')['quality_gate']
        assert ia >= gate['minimum_int8_accuracy'], 'predeclared accuracy gate'
        assert fa - ia <= gate['maximum_accuracy_loss'], 'predeclared quantization loss gate'
        result.update(status='PASS', dataset='UCI HAR public course distribution; real IMU feature benchmark',
                      test_count=len(rows), train_count=training['train_count'], validation_count=training['validation_count'],
                      subject_splits=dict(zip(['train', 'validation', 'test'], [sorted(s) for s in subject_sets])),
                      test_float_accuracy=fa, test_int8_accuracy=ia, test_rtl_accuracy=ia,
                      majority_class_baseline_accuracy=float(np.mean(y == training['majority_class'])),
                      prediction_agreement=sum(int(a == b) for a, b in zip(float_pred, rtl_pred)) / len(y),
                      rtl_integer_logit_matches=len(rows) * 6, confusion_matrix=confusion,
                      hidden_saturations=sum(q[1] for r in integer for q in r[0]['quantized']),
                      output_saturations=sum(q[1] for r in integer for q in r[1]['quantized']),
                      input_clips=int(np.sum(np.abs((x - np.array(pre['mean'])) / np.array(pre['std'])) > pre['clip_abs'])),
                      deployment=numerical, implementation_sha256=implementation(),
                      frozen_artifact_sha256={n: sha(ROOT / n) for n in ['data/provenance.json', 'data/train.csv', 'data/test.csv',
                                                                 'training_results.json', 'preprocessing.json', 'float_model.json',
                                                                 'trained_model.json', 'deployment.json', 'split_membership.json',
                                                                 'rtl_inputs.json', 'predictions.csv']},
                      dependency_sha256=deploy.dependencies() | {
                          'step009/' + n: sha(BASE / 'step009' / n)
                          for n in ['deployment.py', 'verify_step009.py', 'artifact_manifest.json']},
                      scope='Host preprocessing on supplied normalized features, real RTL FC/quantization. No raw feature extractor, gyro calibration or board timing.')
        print(f'PASS HAR test={len(rows)} float={fa:.6f} int8/RTL={ia:.6f} warm=124', flush=True)
    except Exception as e:
        result.update(status='FAIL', error=str(e))
        raise
    finally:
        save(ROOT / 'results.json', result)


EVIDENCE = {'package.json', 'parameters.json', 'physical_image.json', 'sources.json', 'vectors.json',
            'switched_package.json', 'task_catalog.json', 'mlp_cases.txt', 'scenario_flags.txt',
            'tb_resident.v', 'mlp_metrics.csv', 'mlp_events.csv', 'deployment_metrics.csv', 'report.json',
            'compile.log', 'elaborate.log', 'simulation.log'}


def seal(check=False):
    path = ROOT / 'artifact_manifest.json'
    if check:
        m = load(path)
        assert m['status'] == 'PASS'
        for n, h in m['sha256'].items():
            assert sha(ROOT / n) == h, n
        for n, h in m['dependency_sha256'].items():
            assert sha(BASE / n) == h, n
        print('PASS STEP010 artifacts and dependencies', len(m['sha256']))
        return
    result = load(ROOT / 'results.json')
    assert result['status'] == 'PASS'
    assert result['implementation_sha256'] == implementation()
    for n, h in result['frozen_artifact_sha256'].items():
        assert sha(ROOT / n) == h, n
    for n, h in result['dependency_sha256'].items():
        assert sha(BASE / n) == h, n
    files = []
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if not p.is_file() or p == path or any(v in rel.parts for v in ['cache', '__pycache__', 'xsim.dir']):
            continue
        if 'build' in rel.parts and (rel.parent.as_posix() != 'build/rtl' or p.name not in EVIDENCE):
            continue
        if p.suffix in {'.py', '.ps1', '.json', '.csv', '.txt', '.md', '.log', '.v'} or p.name == '.gitignore':
            files.append(p)
    save(path, dict(status='PASS', sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)},
                    dependency_sha256=result['dependency_sha256']))
    print('SEALED STEP010', len(files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal', action='store_true')
    parser.add_argument('--check', action='store_true')
    a = parser.parse_args()
    if a.seal or a.check:
        seal(a.check)
    else:
        evaluate()
