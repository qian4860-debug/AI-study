"""Strict sensor contract, train-only calibration and exact scalar fixed-point model."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parent
FIELDS = ['timestamp_s', 'device_id', 'session_id', 'split', 'temperature_C', 'stationary',
          'gx', 'gy', 'gz', 'ref_gx', 'ref_gy', 'ref_gz']


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_csv(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(data)


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(name + ': boolean is not a measurement')
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(name + ': nonfinite')
    return v


def read_dataset(metadata_path, cfg):
    metadata_path = Path(metadata_path)
    m = load(metadata_path)
    required = {'schema', 'version', 'kind', 'source', 'sample_rate_hz', 'units', 'frame',
                'reference', 'sessions', 'data_file', 'data_sha256'}
    if set(m) != required or m['schema'] != 'gyro.calibration.dataset' or type(m['version']) is not int or m['version'] != 1:
        raise ValueError('metadata schema or unknown fields')
    if m['kind'] not in ['synthetic', 'measured'] or not isinstance(m['source'], str) or not m['source'].strip():
        raise ValueError('source/kind')
    if m['units'] not in [dict(time='s', angular_rate='rad/s', temperature='degC'),
                          dict(time='s', angular_rate='deg/s', temperature='degC')]:
        raise ValueError('explicit supported units required')
    if m['frame'] != dict(name='sensor_body', handedness='right', axes=['x', 'y', 'z']):
        raise ValueError('sensor frame must be explicit right-handed XYZ')
    if set(m['reference']) != {'kind', 'description'} or not isinstance(m['reference']['description'], str) or not m['reference']['description'].strip():
        raise ValueError('reference provenance')
    rk = m['reference']['kind']
    if rk not in ['synthetic_ground_truth', 'independent', 'stationary_zero_assumption']:
        raise ValueError('reference kind')
    if (m['kind'] == 'synthetic') != (rk == 'synthetic_ground_truth'):
        raise ValueError('synthetic/measured reference mismatch')
    hz = number(m['sample_rate_hz'], 'sample_rate_hz')
    if hz <= 0:
        raise ValueError('sample rate must be positive')
    file_name = m['data_file']
    if not isinstance(file_name, str) or Path(file_name).name != file_name or '/' in file_name or '\\' in file_name:
        raise ValueError('data_file must be a sibling file name')
    path = metadata_path.parent / file_name
    if sha(path) != m['data_sha256']:
        raise ValueError('data SHA256 mismatch')
    sessions = {}
    for s in m['sessions']:
        if set(s) != {'device_id', 'session_id', 'split', 'condition'} or s['split'] not in ['train', 'validation', 'test']:
            raise ValueError('session declaration')
        if any(not isinstance(s[n], str) or not s[n].strip() for n in ['device_id', 'session_id', 'condition']):
            raise ValueError('session identifiers/condition')
        key = s['device_id'], s['session_id']
        if key in sessions:
            raise ValueError('duplicate session; sessions cannot straddle splits')
        sessions[key] = s
    if not sessions:
        raise ValueError('empty sessions')
    factor = math.pi / 180 if m['units']['angular_rate'] == 'deg/s' else 1.
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError('CSV columns/order')
        source = list(reader)
    data, last, counts = [], {}, {}
    for index, row in enumerate(source):
        if None in row or any(row.get(n) is None for n in FIELDS):
            raise ValueError('malformed CSV row')
        key = row['device_id'], row['session_id']
        if key not in sessions or row['split'] != sessions[key]['split']:
            raise ValueError('undeclared session or split mismatch')
        t = number(row['timestamp_s'], 'time')
        temp = number(row['temperature_C'], 'temperature')
        if t < 0 or not -100 <= temp <= 200:
            raise ValueError('time/temperature range')
        if key in last:
            dt = t - last[key]
            if dt <= 0 or abs(dt * hz - 1) > cfg['maximum_timestamp_relative_jitter'] + 1e-10:
                raise ValueError('nonmonotonic timestamp, gap or sample-rate mismatch')
        last[key], counts[key] = t, counts.get(key, 0) + 1
        if row['stationary'] not in ['0', '1']:
            raise ValueError('stationary must be 0 or 1')
        stationary = row['stationary'] == '1'
        gyro = [number(row[a], a) * factor for a in ['gx', 'gy', 'gz']]
        refs = [row[a] for a in ['ref_gx', 'ref_gy', 'ref_gz']]
        if rk == 'stationary_zero_assumption':
            if any(v.strip() for v in refs):
                raise ValueError('zero-assumption mode requires blank reference columns')
            ref = [0., 0., 0.] if stationary else None
        else:
            if not all(v.strip() for v in refs):
                raise ValueError('explicit three-axis reference required')
            ref = [number(v, 'reference') * factor for v in refs]
            if stationary and max(abs(v) for v in ref) > .001:
                raise ValueError('stationary mark contradicts reference angular rate')
        data.append(dict(index=index, device_id=key[0], session_id=key[1], split=row['split'],
                         t=t, temperature=temp, stationary=stationary, gyro=gyro, reference=ref))
    if set(counts) != set(sessions) or any(n < 2 for n in counts.values()):
        raise ValueError('empty or too short declared session')
    devices = {d['device_id'] for d in data}
    for device in devices:
        if {d['split'] for d in data if d['device_id'] == device} != {'train', 'validation', 'test'}:
            raise ValueError('each calibrated device needs independent train/validation/test sessions')
    return m, data


def normalized_temperature(temp, cfg):
    return (temp - cfg['temperature_center_C']) / cfg['temperature_scale_C']


def fit_devices(data, cfg, degree):
    models = {}
    for device in sorted({r['device_id'] for r in data}):
        train = [r for r in data if r['device_id'] == device and r['split'] == 'train' and r['stationary']]
        if len(train) < cfg['minimum_fit_samples'] or any(r['reference'] is None for r in train):
            raise ValueError('insufficient stationary training reference')
        temp = np.array([r['temperature'] for r in train])
        z = normalized_temperature(temp, cfg)
        if np.max(np.abs(z)) > cfg['maximum_normalized_temperature']:
            raise ValueError('fixed-point temperature domain')
        design = np.column_stack([z ** p for p in range(degree + 1)])
        condition = float(np.linalg.cond(design))
        if np.linalg.matrix_rank(design) != degree + 1 or condition > cfg['maximum_design_condition']:
            raise ValueError('temperature fit rank/conditioning')
        error = np.array([np.array(r['gyro']) - r['reference'] for r in train])
        coefficients = np.linalg.lstsq(design, error, rcond=None)[0].T
        padded = np.pad(coefficients, ((0, 0), (0, 2 - degree)))
        codes = np.rint(padded * (1 << cfg['rate_fraction_bits'])).astype(np.int64)
        if np.any((codes < -(1 << 31)) | (codes >= 1 << 31)):
            raise ValueError('coefficient signed32 overflow')
        models[device] = dict(degree=degree, coefficients=padded.tolist(), coefficient_codes=codes.tolist(),
                              fit_indices=[r['index'] for r in train], fit_count=len(train),
                              fit_sessions=sorted({r['session_id'] for r in train}),
                              temperature_range_C=[float(temp.min()), float(temp.max())], condition=condition)
    return dict(schema='gyro.temperature.model', version=1, cfg=cfg, devices=models)


def predict_bias(model, row):
    if row['device_id'] not in model['devices']:
        raise ValueError('unknown device: no cross-device calibration transfer')
    dev = model['devices'][row['device_id']]
    lo, hi = dev['temperature_range_C']
    if not lo - 1e-9 <= row['temperature'] <= hi + 1e-9:
        raise ValueError('temperature extrapolation rejected')
    z = normalized_temperature(row['temperature'], model['cfg'])
    return [c[0] + z * (c[1] + z * c[2]) for c in dev['coefficients']]


def rne_shift(value, shift):
    magnitude = abs(value)
    base, rem = divmod(magnitude, 1 << shift)
    base += int(rem * 2 > (1 << shift) or (rem * 2 == (1 << shift) and base & 1))
    return -base if value < 0 else base


def sat32(value):
    return max(-(1 << 31), min((1 << 31) - 1, value)), int(not -(1 << 31) <= value < (1 << 31))


def fixed_scalar(coeff, z, raw):
    if len(coeff) != 3 or any(type(c) is not int or not -(1 << 31) <= c < (1 << 31) for c in coeff):
        raise ValueError('signed32 coefficients')
    if type(z) is not int or not -(1 << 15) <= z < (1 << 15) or type(raw) is not int or not -(1 << 31) <= raw < (1 << 31):
        raise ValueError('signed16 temperature / signed32 rate')
    first, s1 = sat32(rne_shift(coeff[2] * z, 14) + coeff[1])
    bias, s2 = sat32(rne_shift(first * z, 14) + coeff[0])
    corrected, s3 = sat32(raw - bias)
    return bias, corrected, int(bool(s1 or s2 or s3))


def fixed_row(model, row):
    predict_bias(model, row)  # enforce device and trained temperature domain
    cfg = model['cfg']
    if (cfg['rate_fraction_bits'], cfg['temperature_fraction_bits']) != (24, 14):
        raise ValueError('RTL ABI only supports signed32 Q24 and signed16 Q14')
    z = int(round(normalized_temperature(row['temperature'], cfg) * (1 << 14)))
    if abs(normalized_temperature(row['temperature'], cfg)) > cfg['maximum_normalized_temperature']:
        raise ValueError('normalized temperature domain')
    codes = model['devices'][row['device_id']]['coefficient_codes']
    raw = [int(round(v * (1 << 24))) for v in row['gyro']]
    values = [fixed_scalar(c, z, r) for c, r in zip(codes, raw)]
    return values, z, raw


def error_metrics(data, corrected):
    scored = [(r, v) for r, v in zip(data, corrected) if r['reference'] is not None]
    if not scored:
        return dict(scored_samples=0, rmse_rad_s=None, mean_error_rad_s=None)
    err = np.array([np.array(v) - r['reference'] for r, v in scored])
    return dict(scored_samples=len(scored), rmse_rad_s=np.sqrt(np.mean(err ** 2, axis=0)).tolist(),
                aggregate_rmse_rad_s=float(np.sqrt(np.mean(err ** 2))), mean_error_rad_s=err.mean(axis=0).tolist(),
                maximum_abs_error_rad_s=np.max(np.abs(err), axis=0).tolist())


def calibrate(metadata_path, dest):
    dest = Path(dest)
    save(dest / 'results.json', dict(status='RUNNING'))
    try:
        cfg = load(ROOT / 'experiment.json')
        meta, data = read_dataset(metadata_path, cfg)
        # Do not refit on validation/test. Their samples are never used by fit_devices.
        constant = fit_devices(data, cfg, 0)
        validation = [r for r in data if r['split'] == 'validation']
        candidates = []
        for degree in cfg['polynomial_degrees']:
            model = fit_devices(data, cfg, degree)
            corrected = [(np.array(r['gyro']) - predict_bias(model, r)).tolist() for r in validation]
            metric = error_metrics(validation, corrected)
            if metric['scored_samples'] == 0:
                raise ValueError('validation needs reference or marked stationary samples')
            candidates.append(dict(degree=degree, model=model, validation=metric))
        best = min(candidates, key=lambda c: (c['validation']['aggregate_rmse_rad_s'], c['degree']))
        model = best['model']
        save(dest / 'constant_model.json', constant)
        save(dest / 'temperature_model.json', model)
        save(dest / 'candidates.json', candidates)
        save(dest / 'selection.json', dict(selected_degree=best['degree'],
             selection='validation aggregate three-axis RMSE; tie chooses lower degree; no refit',
             source_data_sha256=meta['data_sha256'], metadata_sha256=sha(metadata_path),
             implementation_sha256={n: sha(ROOT / n) for n in ['calibration.py', 'experiment.json']},
             model_sha256={n: sha(dest / n) for n in ['constant_model.json', 'temperature_model.json', 'candidates.json']}))
        # Only evaluate test after serializing and hashing the chosen model.
        test = [r for r in data if r['split'] == 'test']
        methods = {'raw': [], 'constant': [], 'temperature_float': [], 'temperature_fixed': []}
        corrected_rows, vectors = [], []
        max_bias_error = 0.
        saturated = 0
        for row in test:
            cb, tb = predict_bias(constant, row), predict_bias(model, row)
            fixed, z, raw = fixed_row(model, row)
            values = dict(raw=row['gyro'], constant=(np.array(row['gyro']) - cb).tolist(),
                          temperature_float=(np.array(row['gyro']) - tb).tolist(),
                          temperature_fixed=[v[1] / (1 << 24) for v in fixed])
            max_bias_error = max(max_bias_error, max(abs(v[0] / (1 << 24) - b) for v, b in zip(fixed, tb)))
            saturated += sum(v[2] for v in fixed)
            for method, value in values.items():
                methods[method].append(value)
                corrected_rows.append(dict(source_index=row['index'], device_id=row['device_id'], session_id=row['session_id'],
                    timestamp_s=row['t'], stationary=int(row['stationary']), method=method,
                    gx_rad_s=value[0], gy_rad_s=value[1], gz_rad_s=value[2]))
            for axis in range(3):
                c = model['devices'][row['device_id']]['coefficient_codes'][axis]
                vectors.append(dict(tag=len(vectors), source_index=row['index'], axis=axis, c0=c[0], c1=c[1], c2=c[2],
                                    z=z, raw=raw[axis], bias=fixed[axis][0], corrected=fixed[axis][1], saturated=fixed[axis][2]))
        if saturated or max_bias_error > cfg['fixed_float_bias_error_limit_rad_s']:
            raise ValueError('fixed-point accuracy/domain gate')
        by_method = {name: error_metrics(test, v) for name, v in methods.items()}
        by_session = {}
        for key in sorted({(r['device_id'], r['session_id']) for r in test}):
            indices = [i for i, r in enumerate(test) if (r['device_id'], r['session_id']) == key]
            sample = [test[i] for i in indices]
            session = {}
            for method, values in methods.items():
                corrected = [values[i] for i in indices]
                metric = error_metrics(sample, corrected)
                if all(r['reference'] is not None for r in sample):
                    errors = np.array([np.array(v) - r['reference'] for r, v in zip(sample, corrected)])
                    times = np.array([r['t'] for r in sample])
                    integral = np.sum((errors[:-1] + errors[1:]) * .5 * np.diff(times)[:, None], axis=0)
                    metric['integrated_rate_error_rad'] = integral.tolist()
                    metric['duration_s'] = float(times[-1] - times[0])
                else:
                    metric['integrated_rate_error_rad'] = None
                session[method] = metric
            by_session['/'.join(key)] = session
        write_csv(dest / 'corrected_test.csv', corrected_rows)
        write_csv(dest / 'sensor_vectors.csv', vectors)
        result = dict(status='PASS', dataset_kind=meta['kind'], physical_calibration_complete=False,
                      reference_kind=meta['reference']['kind'], selected_degree=best['degree'],
                      split_counts={s: sum(r['split'] == s for r in data) for s in ['train', 'validation', 'test']},
                      devices=list(model['devices']), test_methods=by_method, test_sessions=by_session,
                      fixed_float_max_bias_error_rad_s=max_bias_error, fixed_saturations=saturated,
                      sensor_vector_count=len(vectors), model_selection_sha256=sha(dest / 'selection.json'),
                      scope='Per-device additive bias calibration. Synthetic results do not establish real sensor accuracy; integrated rate error is not general 3D attitude error.')
        save(dest / 'results.json', result)
        return result
    except Exception as e:
        save(dest / 'results.json', dict(status='FAIL', error=str(e)))
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    print(json.dumps(calibrate(a.metadata, a.out), ensure_ascii=False, indent=2))
