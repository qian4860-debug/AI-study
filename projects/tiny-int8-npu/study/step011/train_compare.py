"""Four predeclared models, subject CV, then refit; never opens official test."""
import math
from common import *
from train_har import forward, scale


def fit(x, y, names, cfg, hidden, seed, epochs, validation=None):
    pre = dict(feature_names=names, mean=x.mean(axis=0).tolist(),
               std=np.maximum(x.std(axis=0), 1e-6).tolist(), clip_abs=127 / 32, input_scale=1 / 32,
               source='fit subjects only, never validation or official test')
    xt = transform(x, pre)
    xv, yv = (transform(validation[0], pre), validation[1]) if validation is not None else (None, None)
    rng = np.random.default_rng(seed)
    params = [rng.normal(0, math.sqrt(2 / x.shape[1]), (x.shape[1], hidden)), np.zeros(hidden),
              rng.normal(0, math.sqrt(2 / hidden), (hidden, 6)), np.zeros(6)]
    mom, vel = [[np.zeros_like(p) for p in params] for _ in range(2)]
    best = (-1., -float('inf'))
    history = []
    for epoch in range(1, epochs + 1):
        h, logits = forward(xt, params)
        ex = np.exp(logits - logits.max(axis=1, keepdims=True))
        dp = ex / ex.sum(axis=1, keepdims=True)
        dp[np.arange(len(y)), y] -= 1
        dp /= len(y)
        dh = (dp @ params[2].T) * (h > 0)
        grads = [xt.T @ dh + cfg['l2'] * params[0], dh.sum(axis=0),
                 h.T @ dp + cfg['l2'] * params[2], dp.sum(axis=0)]
        for p, g, m, v in zip(params, grads, mom, vel):
            m[:] = .9 * m + .1 * g
            v[:] = .999 * v + .001 * g * g
            p -= cfg['learning_rate'] * (m / (1 - .9 ** epoch)) / (np.sqrt(v / (1 - .999 ** epoch)) + 1e-8)
        if xv is not None:
            z = forward(xv, params)[1]
            acc = float(np.mean(z.argmax(axis=1) == yv))
            zz = z - z.max(axis=1, keepdims=True)
            loss = float(np.mean(np.log(np.exp(zz).sum(axis=1)) - zz[np.arange(len(yv)), yv]))
            if (acc, -loss) > best:
                best, best_epoch, saved = (acc, -loss), epoch, [p.copy() for p in params]
            history.append(dict(epoch=epoch, validation_accuracy=acc, validation_cross_entropy=loss))
    if xv is None:
        saved, best_epoch = params, epochs
    w1, b1, w2, b2 = saved
    sx, sw1, sw2 = pre['input_scale'], scale(w1), scale(w2)
    h, logits = forward(xt, saved)
    sh, sy = scale(h), scale(logits)
    model = dict(version=1, dtype='int8', zero_point=0, shape=[x.shape[1], hidden, 6], layers=[
        dict(weight=quantize(w1.T, sw1).tolist(), bias=np.rint(b1 / (sx * sw1)).astype(np.int64).tolist(),
             relu=True, multiplier=1, shift=int(round(math.log2(sh / (sx * sw1))))),
        dict(weight=quantize(w2.T, sw2).tolist(), bias=np.rint(b2 / (sh * sw2)).astype(np.int64).tolist(),
             relu=False, multiplier=1, shift=int(round(math.log2(sy / (sh * sw2)))))])
    validate(model)
    return dict(preprocessing=pre, model=model, parameters=[p.tolist() for p in saved], best_epoch=best_epoch,
                scales=dict(input=sx, weight1=sw1, hidden=sh, weight2=sw2, output=sy)), history


def main():
    cfg = load(ROOT / 'experiment.json')
    data_path = BASE / 'step010/data/train.csv'
    assert sha(data_path) == load(BASE / 'step010/data/provenance.json')['derivative_sha256']['train.csv']
    data = rows(data_path)
    folds = subject_folds(data, cfg['folds'])
    # Store exact source-row membership, not just a count.
    save(ROOT / 'cv_splits.json', [{k: v for k, v in f.items() if not k.endswith('_indices')} |
                                  {kind + '_source_rows': [int(data[j]['source_row']) for j in f[kind + '_indices']]
                                   for kind in ['fit', 'validation']} for f in folds])
    summaries = []
    for candidate in cfg['candidates']:
        names = [FEATURES[j] for j in candidate['feature_indices']]
        x, y = arrays(data, names)
        reports = []
        for fold in folds:
            ti, vi = fold['fit_indices'], fold['validation_indices']
            fitted, history = fit(x[ti], y[ti], names, cfg, candidate['hidden'], cfg['seed'] + fold['fold'],
                                  cfg['epochs'], (x[vi], y[vi]))
            qx = quantize(transform(x[vi], fitted['preprocessing']), 1 / 32)
            logits, counts = integer(fitted['model'], qx)
            float_pred = forward(transform(x[vi], fitted['preprocessing']),
                                 [np.array(p) for p in fitted['parameters']])[1].argmax(axis=1)
            report = dict(candidate=candidate['id'], fold=fold['fold'], best_epoch=fitted['best_epoch'],
                          float=metrics(y[vi], float_pred), int8=metrics(y[vi], logits.argmax(axis=1)),
                          quantization=counts)
            reports.append(report)
            dest = ROOT / 'models' / candidate['id'] / f"fold{fold['fold']}"
            save(dest / 'fit.json', fitted)
            save(dest / 'metrics.json', report)
            write_csv(dest / 'history.csv', history)
            write_csv(dest / 'predictions.csv', [dict(source_row=data[j]['source_row'], subject=data[j]['subject'],
                      label=int(y[j]), float_prediction=int(fp), integer_prediction=int(ip))
                      for j, fp, ip in zip(vi, float_pred, logits.argmax(axis=1))])
            print(f"CV {candidate['id']} fold={fold['fold']} INT8 macro-F1={report['int8']['macro_f1']:.6f}", flush=True)
        shape = [len(names), candidate['hidden'], 6]
        cycle = recommend(*shape)
        summaries.append(dict(candidate=candidate['id'], shape=shape,
                              mean_int8_macro_f1=float(np.mean([r['int8']['macro_f1'] for r in reports])),
                              std_fold_macro_f1=float(np.std([r['int8']['macro_f1'] for r in reports])),
                              mean_int8_accuracy=float(np.mean([r['int8']['accuracy'] for r in reports])),
                              auto_compute_cycles=min(cycle['tile_cycles'], cycle['baseline_cycles']),
                              best_epochs=[r['best_epoch'] for r in reports]))
    winner = min(summaries, key=lambda r: (-r['mean_int8_macro_f1'], r['auto_compute_cycles'], r['candidate']))
    selected = next(c for c in cfg['candidates'] if c['id'] == winner['candidate'])
    names = [FEATURES[j] for j in selected['feature_indices']]
    x, y = arrays(data, names)
    epochs = int(np.median(winner['best_epochs']))
    fitted, _ = fit(x, y, names, cfg, selected['hidden'], cfg['seed'], epochs)
    save(ROOT / 'selected_fit.json', fitted)
    save(ROOT / 'selected_deployment.json', descriptor(fitted['model']))
    write_csv(ROOT / 'cv_summary.csv', [{k: json.dumps(v) if isinstance(v, list) else v for k, v in s.items()} for s in summaries])
    frozen = [ROOT / 'experiment.json', ROOT / 'common.py', ROOT / 'train_compare.py',
              ROOT / 'cv_splits.json', ROOT / 'cv_summary.csv', ROOT / 'selected_fit.json', ROOT / 'selected_deployment.json']
    frozen += sorted((ROOT / 'models').rglob('*.*'))
    save(ROOT / 'selection.json', dict(status='PASS', winner=winner, refit_epochs=epochs,
         fit_subjects=sorted({int(r['subject']) for r in data}), candidate_summaries=summaries,
         train_data_sha256=sha(data_path), artifacts_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in frozen},
         scope=cfg['scope'], numpy=np.__version__, official_test_opened_during_selection=False))
    print('SELECTED', winner['candidate'], 'refit_epochs', epochs, flush=True)


if __name__ == '__main__':
    main()
