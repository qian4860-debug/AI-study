"""Fit and calibrate without opening the official test split."""
import os
# Fixed single-thread CPU arithmetic reduces platform variation and tiny GEMM overhead.
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import csv
import math
import numpy as np
from prepare_data import ROOT, FEATURES, check_data, load, read_rows, save, sha
import sys
sys.path.insert(0, str(ROOT.parent / 'step006'))
from reference import infer, validate
sys.path.insert(0, str(ROOT.parent / 'step009'))
from deployment import descriptor


def features(rows):
    x = np.array([[float(r[n]) for n in FEATURES] for r in rows], dtype=np.float64)
    y = np.array([int(r['label']) for r in rows], dtype=np.int64)
    if not np.isfinite(x).all() or np.any((y < 0) | (y >= 6)):
        raise ValueError('nonfinite or invalid data')
    return x, y


def transform(x, preprocessing):
    return np.clip((x - np.array(preprocessing['mean'])) / np.array(preprocessing['std']),
                   -preprocessing['clip_abs'], preprocessing['clip_abs'])


def quantize(a, scale):
    return np.clip(np.rint(a / scale), -128, 127).astype(np.int64)


def forward(x, params):
    w1, b1, w2, b2 = params
    hidden = np.maximum(0, x @ w1 + b1)
    return hidden, hidden @ w2 + b2


def scale(a):
    return 2. ** math.ceil(math.log2(max(float(np.max(np.abs(a))), 1e-9) / 127))


def main():
    # Validate the training derivative only; test bytes/labels do not enter fitting.
    provenance = load(ROOT / 'data/provenance.json')
    assert sha(ROOT / 'data/train.csv') == provenance['derivative_sha256']['train.csv']
    cfg = load(ROOT / 'experiment.json')
    if cfg['shape'] != [18, 8, 6] or cfg['input_clip_abs'] != 127 / 32:
        raise ValueError('this fixed experiment requires shape 18-8-6 and input clip 127/32')
    rows = read_rows(ROOT / 'data/train.csv')
    val_subjects = set(cfg['validation_subjects'])
    available = {int(r['subject']) for r in rows}
    assert val_subjects < available
    train = [r for r in rows if int(r['subject']) not in val_subjects]
    val = [r for r in rows if int(r['subject']) in val_subjects]
    xt, yt = features(train)
    xv, yv = features(val)
    mean, std = xt.mean(axis=0), xt.std(axis=0)
    std = np.maximum(std, 1e-6)
    pre = dict(feature_names=FEATURES, mean=mean.tolist(), std=std.tolist(),
               clip_abs=127 / 32, input_scale=1 / 32,
               source='mean/std fit on training subjects only; fixed clipping, not test calibration')
    xt, xv = transform(xt, pre), transform(xv, pre)
    rng = np.random.default_rng(cfg['seed'])
    params = [rng.normal(0, math.sqrt(2 / 18), (18, 8)), np.zeros(8),
              rng.normal(0, math.sqrt(2 / 8), (8, 6)), np.zeros(6)]
    mom = [np.zeros_like(p) for p in params]
    vel = [np.zeros_like(p) for p in params]
    best_key = (-1., -float('inf'))
    history = []
    for epoch in range(1, cfg['epochs'] + 1):
        hidden, logits = forward(xt, params)
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = exp / exp.sum(axis=1, keepdims=True)
        probs[np.arange(len(yt)), yt] -= 1
        probs /= len(yt)
        dh = (probs @ params[2].T) * (hidden > 0)
        grads = [xt.T @ dh + cfg['l2'] * params[0], dh.sum(axis=0),
                 hidden.T @ probs + cfg['l2'] * params[2], probs.sum(axis=0)]
        for p, g, m, v in zip(params, grads, mom, vel):
            m[:] = .9 * m + .1 * g
            v[:] = .999 * v + .001 * g * g
            p -= cfg['learning_rate'] * (m / (1 - .9 ** epoch)) / (np.sqrt(v / (1 - .999 ** epoch)) + 1e-8)
        z = forward(xv, params)[1]
        accuracy = float(np.mean(z.argmax(axis=1) == yv))
        zz = z - z.max(axis=1, keepdims=True)
        loss = float(np.mean(np.log(np.exp(zz).sum(axis=1)) - zz[np.arange(len(yv)), yv]))
        if (accuracy, -loss) > best_key:
            best_key, best_epoch = (accuracy, -loss), epoch
            saved = [p.copy() for p in params]
        history.append(dict(epoch=epoch, validation_accuracy=accuracy, validation_cross_entropy=loss))
    w1, b1, w2, b2 = saved
    sx, sw1, sw2 = pre['input_scale'], scale(w1), scale(w2)
    hidden, logits = forward(xt, saved)
    sh, sy = scale(hidden), scale(logits)
    s1 = int(round(math.log2(sh / (sx * sw1))))
    s2 = int(round(math.log2(sy / (sh * sw2))))
    model = dict(version=1, dtype='int8', zero_point=0, shape=[18, 8, 6], layers=[
        dict(weight=quantize(w1.T, sw1).tolist(), bias=np.rint(b1 / (sx * sw1)).astype(np.int64).tolist(),
             relu=True, multiplier=1, shift=s1),
        dict(weight=quantize(w2.T, sw2).tolist(), bias=np.rint(b2 / (sh * sw2)).astype(np.int64).tolist(),
             relu=False, multiplier=1, shift=s2)])
    validate(model)
    def evaluate(x, y):
        rec = [infer(model, v) for v in quantize(x, sx).tolist()]
        yp = np.array([np.argmax([q[0] for q in r[1]['quantized']]) for r in rec])
        return dict(float_accuracy=float(np.mean(forward(x, saved)[1].argmax(axis=1) == y)),
                    int8_accuracy=float(np.mean(yp == y)))
    save(ROOT / 'preprocessing.json', pre)
    save(ROOT / 'float_model.json', dict(parameters=[p.tolist() for p in saved]))
    save(ROOT / 'trained_model.json', model)
    save(ROOT / 'deployment.json', descriptor(model))
    membership = dict(train_subjects=sorted(available - val_subjects), validation_subjects=sorted(val_subjects),
                      train_rows=[int(r['source_row']) for r in train], validation_rows=[int(r['source_row']) for r in val])
    save(ROOT / 'split_membership.json', membership)
    with (ROOT / 'training_history.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(history[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(history)
    result = dict(status='PASS', numpy=np.__version__, config=cfg, train_count=len(train), validation_count=len(val),
                  implementation_sha256={n: sha(ROOT / n) for n in ['train_har.py', 'prepare_data.py']},
                  selected_epoch=best_epoch, train=evaluate(xt, yt), validation=evaluate(xv, yv),
                  train_class_counts=np.bincount(yt, minlength=6).tolist(),
                  majority_class=int(np.bincount(yt, minlength=6).argmax()),
                  scales=dict(input=sx, weight1=sw1, hidden=sh, weight2=sw2, output=sy),
                  fit_sha256={n: sha(ROOT / n) for n in ['data/train.csv', 'experiment.json']},
                  output_sha256={n: sha(ROOT / n) for n in ['preprocessing.json', 'float_model.json', 'trained_model.json',
                                                        'deployment.json', 'split_membership.json']},
                  scope='No official test inputs or labels opened during fit/calibration; one fixed experiment')
    save(ROOT / 'training_results.json', result)
    print('PASS TRAIN HAR', json_text(result), flush=True)


def json_text(value):
    import json
    return json.dumps(value, ensure_ascii=False)


if __name__ == '__main__':
    main()
