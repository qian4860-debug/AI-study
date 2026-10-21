"""Deterministic accelerated thermal stimuli, not collected sensor measurements."""
from calibration import *


def generate(dest):
    dest = Path(dest)
    cfg = load(ROOT / 'experiment.json')
    rng = np.random.default_rng(cfg['seed'])
    data, sessions = [], []
    coefficients = {
        'SYNTH_A': [[.025, .008, .006], [-.018, -.006, .004], [.01, .004, -.003]],
        'SYNTH_B': [[-.016, .006, -.005], [.021, .009, .004], [-.008, -.005, .006]]}
    profiles = [('train_up', 'train', False, False), ('train_down', 'train', True, False),
                ('train_wave', 'train', False, False), ('validation_mix', 'validation', True, True),
                ('test_static', 'test', False, False), ('test_dynamic', 'test', True, True)]
    n, hz = cfg['samples_per_session'], cfg['sample_rate_hz']
    for device, coefficients_xyz in coefficients.items():
        for session, split, reverse, dynamic in profiles:
            sessions.append(dict(device_id=device, session_id=session, split=split,
                                 condition='synthetic thermal dynamic' if dynamic else 'synthetic thermal stationary'))
            phase = np.linspace(0, 1, n)
            temp = 10 + 35 * phase
            if session == 'train_wave':
                temp = 27.5 - 17.5 * np.cos(phase * 2 * np.pi)
            elif reverse:
                temp = temp[::-1]
            # Temperature changes intentionally accelerated: no thermal dynamics inference.
            batch_offset = rng.normal(0, .00003, 3)
            for j in range(n):
                t = j / hz
                moving = dynamic and j >= n // 3
                truth = np.array([.18 * math.sin(t * 2), -.12 * math.cos(t * 1.3), .1 * math.sin(t * .7)]) if moving else np.zeros(3)
                z = normalized_temperature(float(temp[j]), cfg)
                direction = 1 if j == 0 or temp[j] >= temp[j - 1] else -1
                bias = np.array([c[0] + c[1] * z + c[2] * z * z for c in coefficients_xyz])
                bias += .0001 * z ** 3 + direction * .00012 + batch_offset
                gyro = truth + bias + rng.normal(0, .0002, 3)
                data.append(dict(timestamp_s=f'{t:.6f}', device_id=device, session_id=session, split=split,
                                 temperature_C=f'{float(temp[j]):.10f}', stationary=int(not moving),
                                 **dict(zip(['gx', 'gy', 'gz'], [f'{v:.12f}' for v in gyro])),
                                 **dict(zip(['ref_gx', 'ref_gy', 'ref_gz'], [f'{v:.12f}' for v in truth]))))
    write_csv(dest / 'samples.csv', data)
    meta = dict(schema='gyro.calibration.dataset', version=1, kind='synthetic',
        source='Locally generated known truth; accelerated temperature ramp, quadratic bias plus unmatched cubic/hysteresis, batch offsets and white noise',
        sample_rate_hz=hz, units=dict(time='s', angular_rate='rad/s', temperature='degC'),
        frame=dict(name='sensor_body', handedness='right', axes=['x', 'y', 'z']),
        reference=dict(kind='synthetic_ground_truth', description='Known analytic angular rates from generate_synthetic.py; not sensor measurements'),
        sessions=sessions, data_file='samples.csv', data_sha256=sha(dest / 'samples.csv'))
    save(dest / 'metadata.json', meta)
    save(dest / 'generator_provenance.json', dict(seed=cfg['seed'], coefficient_truth=coefficients,
         generator_sha256=sha(ROOT / 'generate_synthetic.py'), config_sha256=sha(ROOT / 'experiment.json'),
         note='All data are synthetic. Temperature ramps are deliberately accelerated; no physical noise/thermal model is validated.'))


if __name__ == '__main__':
    generate(ROOT / 'data')
