"""Failure-path tests for units, leakage, rank, references and integer arithmetic."""
import copy
import tempfile
import unittest
from fractions import Fraction
from calibration import *
from generate_synthetic import generate


class CalibrationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        generate(cls.folder)
        cls.cfg = load(ROOT / 'experiment.json')
        cls.meta, cls.data = read_dataset(cls.folder / 'metadata.json', cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reject_modified(self, change_meta=None, change_rows=None, match=None):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            meta = copy.deepcopy(self.meta)
            with (self.folder / 'samples.csv').open(encoding='utf-8', newline='') as f:
                data = list(csv.DictReader(f))
            if change_rows:
                change_rows(data)
            write_csv(dest / 'samples.csv', data)
            meta['data_sha256'] = sha(dest / 'samples.csv')
            if change_meta:
                change_meta(meta)
            save(dest / 'metadata.json', meta)
            with self.assertRaisesRegex(ValueError, match or '.'):
                read_dataset(dest / 'metadata.json', self.cfg)

    def test_units_frame_and_sample_rate_rejected(self):
        self.reject_modified(lambda m: m['units'].update(angular_rate='LSB'), match='units')
        self.reject_modified(lambda m: m['frame'].update(handedness='left'), match='frame')
        self.reject_modified(lambda m: m.update(sample_rate_hz=50), match='sample-rate')

    def test_nonfinite_duplicate_time_and_gap_rejected(self):
        self.reject_modified(change_rows=lambda r: r[1].update(gx='nan'), match='nonfinite')
        self.reject_modified(change_rows=lambda r: r[1].update(timestamp_s=r[0]['timestamp_s']), match='timestamp')
        self.reject_modified(change_rows=lambda r: r[1].update(timestamp_s='0.02'), match='timestamp')

    def test_session_split_and_reference_provenance_rejected(self):
        self.reject_modified(change_rows=lambda r: r[0].update(split='test'), match='split')
        self.reject_modified(lambda m: m['sessions'].append(m['sessions'][0].copy()), match='duplicate')
        self.reject_modified(change_rows=lambda r: r[0].update(ref_gx=''), match='reference')
        self.reject_modified(lambda m: m.update(kind='measured'), match='mismatch')
        self.reject_modified(change_rows=lambda r: r[0].update(ref_gx='1'), match='stationary')

    def test_training_coefficients_unchanged_by_heldout_values(self):
        model = fit_devices(self.data, self.cfg, 2)
        changed = copy.deepcopy(self.data)
        for r in changed:
            if r['split'] != 'train':
                r['gyro'] = [1e8] * 3
                r['reference'] = [-1e8] * 3
                r['temperature'] = 12345
        self.assertEqual(model, fit_devices(changed, self.cfg, 2))
        train_keys = {(r['device_id'], r['session_id']) for r in self.data if r['split'] == 'train'}
        heldout_keys = {(r['device_id'], r['session_id']) for r in self.data if r['split'] != 'train'}
        self.assertFalse(train_keys & heldout_keys)

    def test_known_synthetic_coefficients_recovered_and_validation_selects_quadratic(self):
        model = fit_devices(self.data, self.cfg, 2)
        truth = load(self.folder / 'generator_provenance.json')['coefficient_truth']
        for device, expected in truth.items():
            np.testing.assert_allclose(model['devices'][device]['coefficients'], expected, rtol=0, atol=.0003)
        validation = [r for r in self.data if r['split'] == 'validation']
        scores = []
        for degree in [0, 1, 2]:
            fitted = fit_devices(self.data, self.cfg, degree)
            corrected = [np.array(r['gyro']) - predict_bias(fitted, r) for r in validation]
            scores.append(error_metrics(validation, corrected)['aggregate_rmse_rad_s'])
        self.assertLess(scores[2], scores[1])
        self.assertLess(scores[1], scores[0])

    def test_rank_unknown_device_and_temperature_extrapolation(self):
        changed = copy.deepcopy(self.data)
        for r in changed:
            r['temperature'] = 25
        with self.assertRaisesRegex(ValueError, 'rank'):
            fit_devices(changed, self.cfg, 2)
        model = fit_devices(self.data, self.cfg, 2)
        row = self.data[0].copy()
        row['device_id'] = 'UNSEEN'
        with self.assertRaisesRegex(ValueError, 'unknown device'):
            predict_bias(model, row)
        row = self.data[0] | {'temperature': 99}
        with self.assertRaisesRegex(ValueError, 'extrapolation'):
            predict_bias(model, row)

    def test_independent_fraction_rne_and_saturation(self):
        for value in list(range(-100, 101)) + [-(1 << 46), (1 << 46) - 1]:
            for shift in [0, 1, 2, 14]:
                self.assertEqual(rne_shift(value, shift), round(Fraction(value, 1 << shift)))
        self.assertEqual(fixed_scalar([100, -200, 300], 8192, 400), (75, 325, 0))
        self.assertEqual(fixed_scalar([-(1 << 31), 0, 0], 0, (1 << 31) - 1), (-(1 << 31), (1 << 31) - 1, 1))
        with self.assertRaises(ValueError):
            fixed_scalar([0, 0, 0], 32768, 0)

    def test_deg_s_conversion_and_stationary_assumption(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            meta = copy.deepcopy(self.meta)
            with (self.folder / 'samples.csv').open(encoding='utf-8', newline='') as f:
                data = list(csv.DictReader(f))
            for r in data:
                for n in ['gx', 'gy', 'gz', 'ref_gx', 'ref_gy', 'ref_gz']:
                    r[n] = str(float(r[n]) * 180 / math.pi)
            write_csv(dest / 'samples.csv', data)
            meta['units']['angular_rate'] = 'deg/s'
            meta['data_sha256'] = sha(dest / 'samples.csv')
            save(dest / 'metadata.json', meta)
            _, converted = read_dataset(dest / 'metadata.json', self.cfg)
            np.testing.assert_allclose([r['gyro'] for r in converted], [r['gyro'] for r in self.data], rtol=1e-14)
            for r in data:
                for n in ['ref_gx', 'ref_gy', 'ref_gz']:
                    r[n] = ''
            write_csv(dest / 'samples.csv', data)
            meta.update(kind='measured', data_sha256=sha(dest / 'samples.csv'))
            meta['reference'] = dict(kind='stationary_zero_assumption', description='Test fixture: explicitly assumed zero while stationary')
            save(dest / 'metadata.json', meta)
            _, converted = read_dataset(dest / 'metadata.json', self.cfg)
            self.assertTrue(all(r['reference'] is None for r in converted if not r['stationary']))
            self.assertTrue(all(r['reference'] == [0., 0., 0.] for r in converted if r['stationary']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
