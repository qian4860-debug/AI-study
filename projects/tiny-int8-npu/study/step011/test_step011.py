"""Tests for consequential metric, leakage, arithmetic and selection failure modes."""
import unittest
from common import *


class Contracts(unittest.TestCase):
    def test_metrics_imbalance_and_absent_classes(self):
        m = metrics([0] * 9 + [1], [0] * 10)
        self.assertEqual(m['accuracy'], .9)
        self.assertEqual(m['recall'][1], 0)
        self.assertAlmostEqual(m['macro_f1'], (18 / 19) / 6)
        self.assertEqual(sum(m['support']), 10)
        with self.assertRaises(ValueError):
            metrics([], [])

    def test_folds_do_not_split_subjects_or_duplicate_validation_rows(self):
        data = [dict(subject=s) for s in range(9) for _ in range(s + 1)]
        folds = subject_folds(data)
        seen = []
        for fold in folds:
            self.assertFalse(set(fold['fit_subjects']) & set(fold['validation_subjects']))
            self.assertFalse(set(fold['fit_indices']) & set(fold['validation_indices']))
            self.assertEqual(len(fold['fit_indices']) + len(fold['validation_indices']), len(data))
            seen.extend(fold['validation_indices'])
        self.assertEqual(sorted(seen), list(range(len(data))))

    def test_exact_integer_negative_ties_saturation_vs_independent_reference(self):
        rng = np.random.default_rng(12)
        for h in [1, 3, 8]:
            model = dict(version=1, dtype='int8', zero_point=0, shape=[5, h, 6], layers=[
                dict(weight=rng.integers(-128, 128, (h, 5)).tolist(), bias=rng.integers(-100, 100, h).tolist(),
                     relu=True, multiplier=3, shift=7),
                dict(weight=rng.integers(-128, 128, (6, h)).tolist(), bias=[-5, -3, -1, 1, 3, 5],
                     relu=False, multiplier=1, shift=1)])
            x = rng.integers(-128, 128, (80, 5))
            actual, _ = integer(model, x)
            expected = [[q[0] for q in infer(model, a)[1]['quantized']] for a in x.tolist()]
            self.assertEqual(actual.tolist(), expected)

    def test_build_policy_constraints_and_reuse_accounting(self):
        available = profiles()
        for reuse in [1, 16, 1024]:
            c = choose_build([18, 8, 6], reuse, {'RAMB_cells': 4, 'Slice_LUTs': 1600}, available=available)
            self.assertEqual((c['core'], c['ram_mode']), ('step008b_k2o2', 1))
            self.assertEqual(c['total_occupied_edges'], c['cold_occupied'] + (reuse - 1) * c['warm_occupied'])
        with self.assertRaises(ValueError):
            choose_build([18, 8, 6], 1, {'DSP': 0}, available=available)
        with self.assertRaises(ValueError):
            choose_build([18, 8, 6], True, {}, available=available)
        fallback = choose_build([255, 1, 1], 1, {}, available=available)
        self.assertEqual(fallback['core'], 'step007_k4o1')

    def test_preprocessing_does_not_fit_validation_extreme(self):
        from train_compare import fit
        cfg = load(ROOT / 'experiment.json')
        x = np.arange(36, dtype=float).reshape(12, 3)
        y = np.arange(12) % 6
        fitted, _ = fit(x, y, ['a', 'b', 'c'], cfg, 4, 2, 3,
                         (np.ones((6, 3)) * 1e9, np.arange(6)))
        np.testing.assert_allclose(fitted['preprocessing']['mean'], x.mean(axis=0))
        np.testing.assert_allclose(fitted['preprocessing']['std'], x.std(axis=0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
