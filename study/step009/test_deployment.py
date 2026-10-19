"""Reject unsupported contracts and prevent stale/partial model reuse."""
import copy
import unittest
from deployment import (BASE, CONTRACT, DeploymentSession, check_package,
                        compile_deployment, descriptor, digest, load)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.desc = descriptor(load(BASE / 'step006/trained_model.json'))
        self.x = [0] * 16

    def uploaded(self, session):
        commands = session.begin()
        for command in commands:
            session.acknowledge(command, True)
        if commands:
            session.finish()
        return commands

    def test_selection_and_determinism(self):
        a = compile_deployment(self.desc)
        b = compile_deployment(copy.deepcopy(self.desc))
        self.assertEqual(digest(a), digest(b))
        self.assertEqual(a['build']['core'], 'step008b_k2o2')
        self.assertEqual(a['expected_compute_cycles'], 79)
        self.desc['execution']['core'] = 'step007_k4o1'
        old = compile_deployment(self.desc)
        self.assertEqual(old['expected_compute_cycles'], 104)
        self.assertNotEqual(a['deployment_id'], old['deployment_id'])

    def test_reject_unsupported_descriptors(self):
        mutations = [
            lambda d: d.update(version=True),
            lambda d: d.update(unknown=0),
            lambda d: d['arithmetic'].update(rounding='truncate'),
            lambda d: d['arithmetic'].update(dot_bits=23),
            lambda d: d['arithmetic'].update(zero_point=False),
            lambda d: d['execution'].update(core='runtime_switch'),
            lambda d: d['execution'].update(ram_mode=True),
            lambda d: d['execution'].update(fused=False),
            lambda d: d['model'].update(version=True),
            lambda d: d['model'].update(shape=[0, 8, 2]),
            lambda d: d['model'].update(shape=[True, 8, 2]),
            lambda d: d['model'].update(shape=[16, 8, 2, 1]),
            lambda d: d['model'].update(zero_point=1),
            lambda d: d['model']['layers'][0].update(relu=1),
            lambda d: d['model']['layers'][0].update(shift=48),
            lambda d: d['model']['layers'][0].update(multiplier=[1] * 8),
            lambda d: d['model']['layers'][0]['weight'][0].__setitem__(0, 128),
            lambda d: d['model']['layers'][0]['bias'].__setitem__(0, 1 << 31),
            lambda d: d['model']['layers'][1].update(relu=True),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                desc = copy.deepcopy(self.desc)
                mutate(desc)
                with self.assertRaises((ValueError, TypeError)):
                    compile_deployment(desc)

    def test_package_payload_and_build_tampering(self):
        for target in ['parameter_commands', 'physical_image', 'build', 'model_id']:
            with self.subTest(target=target):
                package = compile_deployment(self.desc)
                if target == 'parameter_commands':
                    package[target][0] = [0, 1, 0, 999]
                elif target == 'physical_image':
                    package[target]['weights'][0][2] += 1
                elif target == 'build':
                    first = next(iter(package[target]['source_sha256']))
                    package[target]['source_sha256'][first] = '0' * 64
                else:
                    package[target] = '0' * 64
                with self.assertRaises(ValueError):
                    check_package(package)

    def test_acknowledgement_and_recovery(self):
        session = DeploymentSession()
        with self.assertRaises(RuntimeError):
            session.begin()
        session.bind(compile_deployment(self.desc))
        with self.assertRaises(RuntimeError):
            session.inputs(self.x)
        commands = session.begin()
        session.acknowledge(commands[0], False)
        self.assertEqual(session.cache.acknowledged, 0)
        with self.assertRaises(RuntimeError):
            session.acknowledge(commands[1], True)
        session.acknowledge(commands[0], True)
        with self.assertRaises(RuntimeError):
            session.finish()
        with self.assertRaises(RuntimeError):
            session.inputs(self.x)
        with self.assertRaises(RuntimeError):
            session.bind(compile_deployment(self.desc))
        session.invalidate()
        self.assertEqual(len(self.uploaded(session)), 154)
        self.assertEqual(self.uploaded(session), [])
        self.assertEqual(len(session.inputs(self.x)), 16)
        session.invalidate()
        self.assertEqual(len(self.uploaded(session)), 154)
        with self.assertRaises(ValueError):
            session.inputs([128] * 16)

    def test_model_quantizer_build_changes_require_reload(self):
        session = DeploymentSession()
        original = compile_deployment(self.desc)
        session.bind(original)
        self.uploaded(session)
        for field in ['weight', 'bias', 'shift']:
            desc = copy.deepcopy(self.desc)
            layer = desc['model']['layers'][0]
            if field == 'weight':
                layer[field][0][0] += 1
            elif field == 'bias':
                layer[field][0] += 1
            else:
                layer[field] += 1
            package = compile_deployment(desc)
            self.assertNotEqual(package['deployment_id'], original['deployment_id'])
            session.bind(package)
            with self.assertRaises(RuntimeError):
                session.inputs(self.x)
            self.assertEqual(len(self.uploaded(session)), 154)
        for mode, core in [(0, 'step007_k4o1'), (2, 'step008b_k2o2'), (1, 'auto')]:
            desc = copy.deepcopy(self.desc)
            desc['execution'].update(ram_mode=mode, core=core)
            session.bind(compile_deployment(desc))
            with self.assertRaises(RuntimeError):
                session.inputs(self.x)
            self.assertEqual(len(self.uploaded(session)), 154)
        # A legal shape change must also miss residency, even on the same build.
        desc = copy.deepcopy(self.desc)
        desc['model']['shape'][2] = 1
        desc['model']['layers'][1]['weight'] = desc['model']['layers'][1]['weight'][:1]
        desc['model']['layers'][1]['bias'] = desc['model']['layers'][1]['bias'][:1]
        session.bind(compile_deployment(desc))
        with self.assertRaises(RuntimeError):
            session.inputs(self.x)
        self.assertEqual(len(self.uploaded(session)), 145)

    def test_sparse_bank_image_matches_host_address_decoder(self):
        for core in ['step007_k4o1', 'step008b_k2o2']:
            desc = copy.deepcopy(self.desc)
            desc['execution']['core'] = core
            p = compile_deployment(desc)
            actual = {}
            for layer, kind, addr, data in p['parameter_commands']:
                if kind != 1:
                    continue
                if core == 'step007_k4o1':
                    bank = addr & 3
                    word = (layer << 9) | (addr >> 2)
                else:
                    bank = ((addr >> 7) & 2) | (addr & 1)
                    word = (layer << 9) | (((addr >> 9) & 3) << 7) | ((addr >> 1) & 127)
                self.assertNotIn((bank, word), actual)
                actual[bank, word] = data
            self.assertEqual(actual, {(b, a): v for b, a, v in p['physical_image']['weights']})


if __name__ == '__main__':
    unittest.main(verbosity=2)
