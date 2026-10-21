"""Step011 metrics, subject splits, exact vector integer model and resource policy."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
from pathlib import Path
import csv
import hashlib
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
for step in ['step006', 'step008b', 'step009', 'step010']:
    sys.path.insert(0, str(BASE / step))
from reference import infer, validate, requant
from select_variant import recommend
from deployment import descriptor, sources, compile_deployment
from prepare_data import FEATURES


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rows(p):
    with Path(p).open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(p, values):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with Path(p).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(values[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(values)


def metrics(truth, pred):
    if len(truth) != len(pred) or not len(truth):
        raise ValueError('empty or mismatched predictions')
    cm = np.zeros((6, 6), dtype=np.int64)
    for a, b in zip(truth, pred):
        if not 0 <= int(a) < 6 or not 0 <= int(b) < 6:
            raise ValueError('class range')
        cm[int(a), int(b)] += 1
    tp = cm.diagonal()
    support, predicted = cm.sum(axis=1), cm.sum(axis=0)
    recall = np.divide(tp, support, out=np.zeros(6, dtype=float), where=support != 0)
    precision = np.divide(tp, predicted, out=np.zeros(6, dtype=float), where=predicted != 0)
    f1 = np.divide(2 * tp, support + predicted, out=np.zeros(6, dtype=float), where=support + predicted != 0)
    return dict(count=int(cm.sum()), accuracy=float(tp.sum() / cm.sum()), macro_f1=float(f1.mean()),
                confusion_matrix=cm.tolist(), recall=recall.tolist(), precision=precision.tolist(),
                f1=f1.tolist(), support=support.tolist(), zero_division=0,
                macro_classes='all six, including absent classes')


def subject_metrics(data, truth, pred):
    subjects = sorted({int(r['subject']) for r in data})
    return {str(s): metrics([a for r, a in zip(data, truth) if int(r['subject']) == s],
                           [a for r, a in zip(data, pred) if int(r['subject']) == s]) for s in subjects}


def subject_folds(data, count=3):
    subjects = sorted({int(r['subject']) for r in data})
    if count < 2 or len(subjects) < count:
        raise ValueError('insufficient subjects')
    result = []
    for i in range(count):
        vs = set(subjects[i::count])
        fit = [j for j, r in enumerate(data) if int(r['subject']) not in vs]
        val = [j for j, r in enumerate(data) if int(r['subject']) in vs]
        result.append(dict(fold=i, fit_subjects=sorted(set(subjects) - vs), validation_subjects=sorted(vs),
                           fit_indices=fit, validation_indices=val))
    return result


def arrays(data, names):
    return (np.array([[float(r[n]) for n in names] for r in data], dtype=np.float64),
            np.array([int(r['label']) for r in data], dtype=np.int64))


def transform(x, pre):
    return np.clip((x - np.array(pre['mean'])) / np.array(pre['std']), -pre['clip_abs'], pre['clip_abs'])


def quantize(x, scale):
    return np.clip(np.rint(x / scale), -128, 127).astype(np.int64)


def integer(model, x):
    validate(model)
    x = np.asarray(x, dtype=np.int64)
    if x.ndim != 2 or x.shape[1] != model['shape'][0] or np.any((x < -128) | (x > 127)):
        raise ValueError('INT8 matrix input')
    counts = []
    for layer in model['layers']:
        dot = x @ np.array(layer['weight'], dtype=np.int64).T
        if np.any((dot < -(1 << 23)) | (dot >= 1 << 23)):
            raise ValueError('dot signed24 overflow')
        pre = dot + np.array(layer['bias'], dtype=np.int64)
        if np.any((pre < -(1 << 32)) | (pre >= 1 << 32)):
            raise ValueError('pre signed33 overflow')
        active = np.maximum(pre, 0) if layer['relu'] else pre
        mag = np.abs(active * layer['multiplier'])
        denom = 1 << layer['shift']
        base, rem = mag // denom, mag % denom
        tie = (rem * 2 == denom) if layer['shift'] else np.zeros_like(rem, dtype=bool)
        out = (base + ((rem * 2 > denom) | (tie & ((base & 1) != 0)))) * np.sign(active)
        counts.append(dict(saturations=int(np.sum((out < -128) | (out > 127))), ties=int(tie.sum())))
        x = np.clip(out, -128, 127).astype(np.int64)
    return x, counts


def geometry(shape, core):
    k, h, o = shape
    pred = recommend(k, h, o)
    tile = core == 'step008b_k2o2'
    cycles = pred['tile_cycles' if tile else 'baseline_cycles']
    macs = k * h + h * o
    return dict(compute_cycles=cycles, macs=macs, parameter_writes=macs + h + o,
                weight_bytes=macs, bias_bytes=4 * (h + o), input_bytes=k,
                expected_x_reads=k * ((h + 1) // 2) + h * ((o + 1) // 2) if tile else macs,
                expected_w_reads=macs, cold_occupied=macs + h + o + k + 1 + cycles,
                warm_occupied=k + 1 + cycles)


def profiles():
    result = []
    for stage, core in [('step007', 'step007_k4o1'), ('step008b', 'step008b_k2o2')]:
        path = BASE / stage / 'synthesis_results.json'
        report = load(path)
        assert report['status'] == 'PASS' and report['stage'] == 'out_of_context_synthesis'
        for n, h in report['source_sha256'].items():
            assert sha(BASE / n.replace('\\', '/')) == h, n
        for name, cfg in report['configs'].items():
            result.append(dict(core=core, ram_name=name, ram_mode=cfg['RAM_MODE'], resources=cfg,
                               provenance=f'{stage}/synthesis_results.json', source_report_sha256=sha(path),
                               timing_scope='Reused OOC synthesis estimate; not routed or board frequency',
                               part=report['part'], clock_period_ns=report['clock_period_ns']))
    return result


def choose_build(shape, reuse, limits, min_wns=0., available=None):
    if type(reuse) is not int or reuse < 1:
        raise ValueError('reuse must be positive integer')
    for key, value in limits.items():
        if key not in ['Slice_LUTs', 'FF', 'DSP', 'RAMB_cells'] or type(value) is not int or value < 0:
            raise ValueError('invalid resource limit')
    choices = []
    for profile in profiles() if available is None else available:
        res = profile['resources']
        if any(res[k] > v for k, v in limits.items()) or res['WNS_ns'] < min_wns:
            continue
        g = geometry(shape, profile['core'])
        choices.append(profile | g | dict(reuse=reuse, total_occupied_edges=g['parameter_writes'] + reuse * g['warm_occupied']))
    if not choices:
        raise ValueError('no feasible build; constraints are never silently relaxed')
    return min(choices, key=lambda x: (x['total_occupied_edges'], x['resources']['Slice_LUTs'],
                                      x['resources']['RAMB_cells'], x['core'], x['ram_mode']))
