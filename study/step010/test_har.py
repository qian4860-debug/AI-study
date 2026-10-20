"""Check subject isolation, preprocessing semantics and deterministic class ties."""
import unittest
from prepare_data import ROOT, FEATURES, check_data, load, read_rows
from train_har import np, transform, quantize


class HarTests(unittest.TestCase):
    def test_subject_isolation(self):
        check_data()
        cfg = load(ROOT / 'experiment.json')
        train = read_rows(ROOT / 'data/train.csv')
        test = read_rows(ROOT / 'data/test.csv')
        train_ids = {int(r['subject']) for r in train}
        test_ids = {int(r['subject']) for r in test}
        val_ids = set(cfg['validation_subjects'])
        self.assertFalse(train_ids & test_ids)
        self.assertTrue(val_ids < train_ids)
        self.assertEqual(len(train_ids | test_ids), 30)
        self.assertEqual([len(train), len(test)], [7352, 2947])
        self.assertEqual(len(FEATURES), 18)

    def test_train_only_statistics(self):
        pre = load(ROOT / 'preprocessing.json')
        membership = load(ROOT / 'split_membership.json')
        rows = read_rows(ROOT / 'data/train.csv')
        selected = [r for r in rows if int(r['subject']) in membership['train_subjects']]
        x = np.array([[float(r[n]) for n in FEATURES] for r in selected])
        np.testing.assert_array_equal(x.mean(axis=0), pre['mean'])
        np.testing.assert_array_equal(np.maximum(x.std(axis=0), 1e-6), pre['std'])
        self.assertEqual([int(r['source_row']) for r in selected], membership['train_rows'])

    def test_clipping_rounding_and_class_ties(self):
        pre = dict(mean=[1., 2.], std=[2., 4.], clip_abs=127 / 32)
        z = transform(np.array([[1., 2.], [1000., -1000.]]), pre)
        np.testing.assert_array_equal(z, [[0., 0.], [127 / 32, -127 / 32]])
        # np.rint must match the hardware's nearest-even at host quantization.
        np.testing.assert_array_equal(quantize(np.array([.5, 1.5, 2.5, -.5, -1.5]), 1), [0, 2, 2, 0, -2])
        logits = [5, 5, 1, 0, -1, -5]
        self.assertEqual(max(range(6), key=lambda i: logits[i]), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
