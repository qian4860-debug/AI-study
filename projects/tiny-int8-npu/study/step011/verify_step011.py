"""Replay frozen models, measure six builds each, and seal complete evidence."""
import argparse
import shutil
from common import *
import verify_step009 as deploy
import verify_har as legacy
from train_har import forward

EVIDENCE = legacy.EVIDENCE | {'memory_metrics.csv'}


def check_selection():
    s = load(ROOT / 'selection.json')
    assert s['status'] == 'PASS' and s['official_test_opened_during_selection'] is False
    assert sha(BASE / 'step010/data/train.csv') == s['train_data_sha256']
    for n, h in s['artifacts_sha256'].items():
        assert sha(ROOT / n) == h, n
    return s


def audit_selection():
    """Recompute saved CV statistics and predictions; do not refit or touch test data."""
    selection = check_selection()
    cfg = load(ROOT / 'experiment.json')
    data = rows(BASE / 'step010/data/train.csv')
    folds = subject_folds(data, cfg['folds'])
    membership = load(ROOT / 'cv_splits.json')
    seen = []
    for f, m in zip(folds, membership):
        for kind in ['fit', 'validation']:
            assert m[kind + '_subjects'] == f[kind + '_subjects']
            assert m[kind + '_source_rows'] == [int(data[j]['source_row']) for j in f[kind + '_indices']]
        assert not set(f['fit_subjects']) & set(f['validation_subjects'])
        seen.extend(f['validation_indices'])
    assert sorted(seen) == list(range(len(data)))
    for candidate in cfg['candidates']:
        names = [FEATURES[j] for j in candidate['feature_indices']]
        x, y = arrays(data, names)
        scores = []
        for fold in folds:
            ti, vi = fold['fit_indices'], fold['validation_indices']
            dest = ROOT / 'models' / candidate['id'] / f"fold{fold['fold']}"
            fitted = load(dest / 'fit.json')
            pre = fitted['preprocessing']
            np.testing.assert_allclose(pre['mean'], x[ti].mean(axis=0), rtol=0, atol=0)
            np.testing.assert_allclose(pre['std'], np.maximum(x[ti].std(axis=0), 1e-6), rtol=0, atol=0)
            qx = quantize(transform(x[vi], pre), pre['input_scale'])
            out, _ = integer(fitted['model'], qx)
            pred = out.argmax(axis=1).tolist()
            saved = rows(dest / 'predictions.csv')
            assert len(saved) == len(vi)
            for j, r, p in zip(vi, saved, pred):
                assert (int(r['source_row']), int(r['subject']), int(r['label']), int(r['integer_prediction'])) == (
                    int(data[j]['source_row']), int(data[j]['subject']), int(y[j]), p)
            calculated = metrics(y[vi], pred)
            assert calculated == load(dest / 'metrics.json')['int8']
            scores.append(calculated['macro_f1'])
        summary = next(s for s in selection['candidate_summaries'] if s['candidate'] == candidate['id'])
        assert float(np.mean(scores)) == summary['mean_int8_macro_f1']
    winner = min(selection['candidate_summaries'], key=lambda r: (
        -r['mean_int8_macro_f1'], r['auto_compute_cycles'], r['candidate']))
    assert selection['winner'] == winner
    fitted = load(ROOT / 'selected_fit.json')
    x, _ = arrays(data, fitted['preprocessing']['feature_names'])
    np.testing.assert_allclose(fitted['preprocessing']['mean'], x.mean(axis=0), rtol=0, atol=0)
    np.testing.assert_allclose(fitted['preprocessing']['std'], np.maximum(x.std(axis=0), 1e-6), rtol=0, atol=0)
    assert selection['refit_epochs'] == int(np.median(winner['best_epochs'])) == fitted['best_epoch']
    print('PASS selection audit: all CV subject memberships, training-only statistics, saved predictions and winner')


def prepare_metered_tb(original, count):
    def prepare(dest, tile=False):
        tb = original(dest, tile=tile)
        text = tb.read_text(encoding='utf-8')
        replacements = [
            ('id=1000+stage', f'id={count + 100}+stage'),
            (' integer fd,mf,ef,scan,', ' integer memf,mx_reads,mw_reads;\n integer fd,mf,ef,scan,'),
            ('  nh=0;', '  mx_reads=0;mw_reads=0;nh=0;'),
            ('  for(t=0;t<4;t=t+1)begin',
             '  for(t=0;t<4;t=t+1)begin\n'
             '   if(dut.state==2 || dut.state==5)begin\n'
             '    if(dut.engine.rd_mask[t])mw_reads=mw_reads+1;\n'
             f'    if(dut.engine.{"x_rd_mask" if tile else "rd_mask"}[t])mx_reads=mx_reads+1;\n'
             '   end'),
            ('  fd=$fopen("mlp_cases.txt","r");',
             '  memf=$fopen("memory_metrics.csv","w");if(!memf)$fatal(1,"memory file");\n'
             '  $fdisplay(memf,"id,x_reads,w_reads");\n  fd=$fopen("mlp_cases.txt","r");'),
            ('   $fdisplay(mf,"%0d', '   $fdisplay(memf,"%0d,%0d,%0d",id,mx_reads,mw_reads);\n   $fdisplay(mf,"%0d'),
            ('$fclose(mf);', '$fclose(memf);$fclose(mf);')]
        for before, after in replacements:
            assert text.count(before) == 1, (before, text.count(before))
            text = text.replace(before, after)
        tb.write_text(text, encoding='utf-8', newline='\n')
        return tb
    return prepare


def run_model(name, model, inputs, expected, cfg, full_build=None):
    measured = []
    for core in ['step007_k4o1', 'step008b_k2o2']:
        for mode in [0, 1, 2]:
            count = len(inputs) if full_build == (core, mode) else min(cfg['representative_rtl_samples'], len(inputs))
            run_name = f'{name}_{core}_ram{mode}'
            dest = ROOT / 'build' / run_name
            original = deploy.backend.prepare_tb
            deploy.backend.prepare_tb = prepare_metered_tb(original, count)
            try:
                result = deploy.verify_one(descriptor(model, core, mode), inputs[:count], dest)
            finally:
                deploy.backend.prepare_tb = original
            geo = geometry(model['shape'], core)
            assert result['compute_cycles'] == geo['compute_cycles']
            assert result['cold_occupied'] == geo['cold_occupied']
            assert result['warm_measured'] == geo['warm_occupied']
            memory = rows(dest / 'memory_metrics.csv')
            assert len(memory) == result['main_tasks']
            for r in memory:
                assert int(r['x_reads']) == geo['expected_x_reads'], r
                assert int(r['w_reads']) == geo['expected_w_reads'], r
            actual = {i: [] for i in range(count)}
            for event in rows(dest / 'mlp_events.csv'):
                tid = int(event['id'])
                if tid in actual and event['stage'] == 'output':
                    assert int(event['index']) == len(actual[tid])
                    actual[tid].append(int(event['data']))
            assert [actual[i] for i in range(count)] == expected[:count]
            evidence = ROOT / 'evidence' / run_name
            evidence.mkdir(parents=True, exist_ok=True)
            for n in EVIDENCE:
                shutil.copyfile(dest / n, evidence / n)
            profile = next(p for p in profiles() if (p['core'], p['ram_mode']) == (core, mode))
            res = profile['resources']
            measured.append(dict(model=name, shape=str(model['shape']), core=core, ram_mode=mode,
                samples=count, integer_logit_matches=count * model['shape'][2],
                predicted_compute=geo['compute_cycles'], measured_compute=result['compute_cycles'],
                cold_occupied=result['cold_occupied'], warm_occupied=result['warm_measured'],
                parameter_writes=geo['parameter_writes'], input_writes=model['shape'][0],
                macs=geo['macs'], measured_x_read_bytes=int(memory[0]['x_reads']),
                measured_w_read_bytes=int(memory[0]['w_reads']), fused_hidden_write_bytes=model['shape'][1],
                model_weight_bytes=geo['weight_bytes'], model_bias_bytes=geo['bias_bytes'],
                physical_weight_capacity_bytes=4096, physical_input_capacity_bytes=512, physical_bias_capacity_bytes=64,
                LUT=res['Slice_LUTs'], FF=res['FF'], DSP=res['DSP'], RAMB=res['RAMB_cells'],
                synthesis_WNS_ns=res['WNS_ns'], synthesis_report=profile['provenance'],
                synthesis_report_sha256=profile['source_report_sha256'],
                resource_scope='Reused OOC synthesis, unchanged RTL; not post-route/board measurement',
                evidence='evidence/' + run_name))
    return measured


def evaluate():
    save(ROOT / 'artifact_manifest.json', dict(status='RUNNING'))
    save(ROOT / 'results.json', dict(status='RUNNING'))
    try:
        legacy.seal(check=True)
        deploy.seal(check=True)
        audit_selection()
        selection = check_selection()
        cfg = load(ROOT / 'experiment.json')
        fitted = load(ROOT / 'selected_fit.json')
        model, pre = fitted['model'], fitted['preprocessing']
        policy = [dict(reuse=n, choice=choose_build(model['shape'], n, cfg['resource_limits'],
                                                  cfg['minimum_synthesis_wns_ns'])) for n in cfg['reuse_counts']]
        save(ROOT / 'build_choices.json', policy)
        chosen = policy[0]['choice']
        # First opening of official test in this new pipeline: selection files are sealed above.
        data = rows(BASE / 'step010/data/test.csv')
        assert not set(selection['fit_subjects']) & {int(r['subject']) for r in data}
        x, y = arrays(data, pre['feature_names'])
        norm = transform(x, pre)
        qx = quantize(norm, pre['input_scale'])
        logits, counts = integer(model, qx)
        expected = [[q[0] for q in infer(model, a)[1]['quantized']] for a in qx.tolist()]
        assert logits.tolist() == expected
        ip = logits.argmax(axis=1).tolist()
        fp = forward(norm, [np.array(p) for p in fitted['parameters']])[1].argmax(axis=1).tolist()
        pred_rows = [dict(source_row=r['source_row'], subject=r['subject'], label=int(t),
                         float_prediction=int(f), integer_prediction=int(p),
                         **{f'logit{j}': int(v) for j, v in enumerate(ls)})
                     for r, t, f, p, ls in zip(data, y, fp, ip, expected)]
        write_csv(ROOT / 'selected_predictions.csv', pred_rows)
        baseline = rows(BASE / 'step010/predictions.csv')
        assert len(baseline) == len(data)
        for a, b in zip(baseline, data):
            assert all(a[k] == b[k] for k in ['source_row', 'subject', 'label'])
        bp = [int(r['rtl_prediction']) for r in baseline]
        baseline_metrics = metrics(y, bp)
        assert abs(baseline_metrics['accuracy'] - load(BASE / 'step010/results.json')['test_int8_accuracy']) < 1e-12
        quality = dict(baseline_step010=dict(integer=baseline_metrics, by_subject=subject_metrics(data, y, bp)),
                       selected=dict(candidate=selection['winner']['candidate'], float=metrics(y, fp),
                                     integer=metrics(y, ip), by_subject=subject_metrics(data, y, ip), quantization=counts,
                                     input_clips=int(np.sum(np.abs((x - pre['mean']) / pre['std']) > pre['clip_abs']))),
                       scope='Fixed official test is a regression benchmark already observed in step010; no new unseen-test or significance claim')
        save(ROOT / 'quality_metrics.json', quality)
        subject_rows = []
        for name, info in [('baseline_step010', quality['baseline_step010']), ('selected', quality['selected'])]:
            for subject, m in info['by_subject'].items():
                subject_rows.append(dict(model=name, subject=subject, count=m['count'], accuracy=m['accuracy'], macro_f1=m['macro_f1']))
        write_csv(ROOT / 'subject_metrics.csv', subject_rows)
        baseline_model = load(BASE / 'step010/trained_model.json')
        baseline_inputs = load(BASE / 'step010/rtl_inputs.json')[:cfg['representative_rtl_samples']]
        base_expected = [[int(r[f'logit{j}']) for j in range(6)] for r in baseline[:len(baseline_inputs)]]
        measured = run_model('baseline010', baseline_model, baseline_inputs, base_expected, cfg)
        measured += run_model('selected', model, [dict(x=v) for v in qx.tolist()], expected, cfg,
                              full_build=(chosen['core'], chosen['ram_mode']))
        write_csv(ROOT / 'hardware_metrics.csv', measured)
        assert len(measured) == 12
        full = next(r for r in measured if r['model'] == 'selected' and r['samples'] == len(data))
        assert full['integer_logit_matches'] == 17682
        # Baseline and candidate have same outputs across every measured build.
        result = dict(status='PASS', candidate=selection['winner']['candidate'], selected_shape=model['shape'],
                      numpy=np.__version__, cv_fits=cfg['folds'] * len(cfg['candidates']),
                      official_test_count=len(data), selected_float_accuracy=quality['selected']['float']['accuracy'],
                      selected_int8_accuracy=quality['selected']['integer']['accuracy'],
                      selected_macro_f1=quality['selected']['integer']['macro_f1'],
                      baseline_macro_f1=baseline_metrics['macro_f1'], full_test_integer_logit_matches=17682,
                      measured_builds=len(measured), representative_samples=cfg['representative_rtl_samples'],
                      model_role='Experimental comparison only; step010 frozen model remains the default',
                      selected_full_run=full, source_selection_sha256=sha(ROOT / 'selection.json'),
                      policy='Resource-constrained host build planning, not dynamic on-chip switching',
                      latency_scope=dict(window_samples=128, sample_hz=50, window_duration_s=2.56,
                                         hop_duration_s=1.28, raw_feature_extraction_measured=False,
                                         host_transport_measured=False, board_frequency_measured=False),
                      limitations=[cfg['scope'], 'No new synthesis or energy measurement',
                                   'RAM counters count enabled 8-bit operand reads, not DRAM traffic or energy',
                                   'Cold/warm occupied edges assume accepted host writes with no transport wait',
                                   'Model selection is not constrained by a predeclared production accuracy target'])
        save(ROOT / 'results.json', result)
        print('PASS STEP011 full_test_logits=17682 builds=12', flush=True)
    except Exception as e:
        save(ROOT / 'results.json', dict(status='FAIL', error=str(e)))
        raise


def seal(check=False):
    path = ROOT / 'artifact_manifest.json'
    if check:
        m = load(path)
        assert m['status'] == 'PASS'
        for n, h in m['sha256'].items():
            assert sha(ROOT / n) == h, n
        for n, h in m['dependency_sha256'].items():
            assert sha(BASE / n) == h, n
        print('PASS STEP011 sealed files', len(m['sha256']))
        return
    assert load(ROOT / 'results.json')['status'] == 'PASS'
    check_selection()
    dependencies = deploy.dependencies()
    for stage in ['step007', 'step008b', 'step009', 'step010']:
        manifest = load(BASE / stage / 'artifact_manifest.json')
        for n in manifest['sha256']:
            dependencies[f'{stage}/{n}'] = sha(BASE / stage / n)
        dependencies[f'{stage}/artifact_manifest.json'] = sha(BASE / stage / 'artifact_manifest.json')
    files = [p for p in ROOT.rglob('*') if p.is_file() and p != path and
             not any(v in p.relative_to(ROOT).parts for v in ['build', '__pycache__'])]
    save(path, dict(status='PASS', sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)},
                    dependency_sha256=dependencies))
    print('SEALED STEP011', len(files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--seal', action='store_true')
    parser.add_argument('--audit-selection', action='store_true')
    a = parser.parse_args()
    if a.audit_selection:
        audit_selection()
    elif a.check or a.seal:
        seal(a.check)
    else:
        evaluate()
