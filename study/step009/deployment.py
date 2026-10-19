"""Restricted, deterministic deployment IR for the two existing RTL builds.

Logical host addresses are ABI addresses. Physical images are audit sidecars;
the RTL itself performs banking when those host transactions are accepted.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
sys.path.insert(0, str(BASE / 'step006'))
sys.path.insert(0, str(BASE / 'step008a'))
sys.path.insert(0, str(BASE / 'step008b'))
from reference import infer, validate
from resident_model import ResidentModel
from select_variant import recommend

CONTRACT = dict(input_dtype='int8', weight_dtype='int8', bias_dtype='int32',
                dot_bits=24, pre_bits=33, rounding='nearest_even',
                saturation='int8', zero_point=0, quantization='per_tensor')
CORES = {'step007_k4o1': 'k4o1', 'step008b_k2o2': 'k2o2'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8', newline='\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def keys(obj, expected, where):
    if type(obj) is not dict or set(obj) != set(expected):
        raise ValueError(where + ': unknown or missing fields')


def descriptor(model, core='auto', ram_mode=1):
    return dict(schema='nycu.deployment', version=1, model=copy.deepcopy(model),
                arithmetic=copy.deepcopy(CONTRACT),
                execution=dict(core=core, ram_mode=ram_mode, fused=True))


def validate_descriptor(desc):
    keys(desc, ['schema', 'version', 'model', 'arithmetic', 'execution'], 'deployment')
    if desc['schema'] != 'nycu.deployment' or type(desc['version']) is not int or desc['version'] != 1:
        raise ValueError('deployment schema/version')
    # JSON equality alone would accept bool as int. Canonical bytes preserve types.
    if digest(desc['arithmetic']) != digest(CONTRACT):
        raise ValueError('unsupported arithmetic contract')
    m = desc['model']
    keys(m, ['version', 'dtype', 'zero_point', 'shape', 'layers'], 'model')
    if type(m['version']) is not int or type(m['zero_point']) is not int:
        raise ValueError('model integer fields')
    if type(m['shape']) is not list or len(m['shape']) != 3 or type(m['layers']) is not list:
        raise ValueError('model shape/layers')
    for layer in m['layers']:
        keys(layer, ['weight', 'bias', 'relu', 'multiplier', 'shift'], 'layer')
        if type(layer['relu']) is not bool or type(layer['weight']) is not list or type(layer['bias']) is not list:
            raise ValueError('layer types')
        if any(type(row) is not list for row in layer['weight']):
            raise ValueError('weight rows')
    validate(m)
    e = desc['execution']
    keys(e, ['core', 'ram_mode', 'fused'], 'execution')
    if e['core'] not in ['auto', *CORES] or type(e['ram_mode']) is not int or e['ram_mode'] not in [0, 1, 2] or e['fused'] is not True:
        raise ValueError('unsupported execution configuration')


def sources(core):
    if core not in CORES:
        raise ValueError('unknown core')
    dot, fc = (('step004/dot_banked_core.v', 'step007/fc_shared.v')
               if core == 'step007_k4o1' else ('step008b/dot_tile_core.v', 'step008b/fc_shared.v'))
    return [BASE / n for n in [dot, 'optimization/step006_pipelined/requant_i8.v',
                               'step007/sync_ram_style.v', fc, 'step007/mlp2_top.v']]


def physical_image(model, layout):
    weights, biases = [], []
    for layer, net in enumerate(model['layers']):
        for row, values in enumerate(net['weight']):
            for j, value in enumerate(values):
                if layout == 'k4o1':
                    bank, address = j % 4, layer * 512 + row * 64 + j // 4
                elif layout == 'k2o2':
                    bank, address = (row % 2) * 2 + j % 2, layer * 512 + (row // 2) * 128 + j // 2
                else:
                    raise ValueError('layout')
                weights.append([bank, address, value])
        biases.extend([[layer * 8 + row, value] for row, value in enumerate(net['bias'])])
    if len({tuple(w[:2]) for w in weights}) != len(weights):
        raise ValueError('bank address collision')
    return dict(weights=weights, biases=biases, unused='unspecified; never read',
                capacity=dict(weight_banks=4, weight_bank_depth=1024, input_banks=4,
                              input_bank_depth=128, bias_words=16))


def compile_deployment(desc):
    validate_descriptor(desc)
    desc = copy.deepcopy(desc)
    model = desc['model']
    choice = recommend(*model['shape'])
    core = choice['recommended'] if desc['execution']['core'] == 'auto' else desc['execution']['core']
    layout = CORES[core]
    src = {p.relative_to(BASE).as_posix(): sha(p) for p in sources(core)}
    build = dict(abi='mlp2-host-v1', core=core, layout=layout,
                 ram_mode=desc['execution']['ram_mode'], source_sha256=src,
                 arithmetic=desc['arithmetic'])
    session = ResidentModel(layout)
    commands = session.begin_model(model)
    build_id, model_id = digest(build), digest(model)
    a, b = model['layers']
    return dict(schema='nycu.deployment.package', version=1, descriptor=desc,
                build=build, build_id=build_id, model_id=model_id,
                deployment_id=digest(dict(build_id=build_id, model_id=model_id)),
                selection=choice, parameter_commands=commands,
                physical_image=physical_image(model, layout),
                config=dict(K=model['shape'][0], H=model['shape'][1], O=model['shape'][2],
                            mult1=a['multiplier'], shift1=a['shift'], mult2=b['multiplier'],
                            shift2=b['shift'], fused=1),
                expected_compute_cycles=choice['baseline_cycles' if layout == 'k4o1' else 'tile_cycles'])


def check_package(package):
    # Recompile from the descriptor, checking current RTL bytes and every payload.
    if digest(package) != digest(compile_deployment(package['descriptor'])):
        raise ValueError('stale or modified deployment package')


class DeploymentSession:
    """Host upload state; acknowledgements mean real host_ready handshakes.

    Binding another build invalidates RAM residency, including switching back.
    The caller must configure the FPGA/build before sending its commands.
    This class does not implement FPGA reconfiguration or a board driver.
    """
    def __init__(self):
        self.package = None
        self.cache = None

    def bind(self, package):
        check_package(package)
        if self.package is None or self.package['build_id'] != package['build_id']:
            self.cache = ResidentModel(package['build_id'])
        elif self.cache.pending is not None:
            raise RuntimeError('upload pending; invalidate before rebinding')
        self.package = copy.deepcopy(package)

    def invalidate(self):
        if self.cache is not None:
            self.cache.invalidate()

    def begin(self):
        if self.package is None:
            raise RuntimeError('no deployment bound')
        return self.cache.begin_model(self.package['descriptor']['model'])

    def acknowledge(self, command, accepted):
        if self.cache is None:
            raise RuntimeError('no deployment bound')
        return self.cache.acknowledge_write(command, accepted)

    def finish(self):
        if self.cache is None:
            raise RuntimeError('no deployment bound')
        self.cache.finish_model()

    def inputs(self, x):
        if self.package is None:
            raise RuntimeError('no deployment bound')
        return self.cache.input_writes(self.package['descriptor']['model'], x)


def export_package(desc, inputs, dest):
    dest = Path(dest)
    package = compile_deployment(desc)
    save(dest / 'package.json', package)
    save(dest / 'parameters.json', package['parameter_commands'])
    save(dest / 'physical_image.json', package['physical_image'])
    save(dest / 'sources.json', package['build']['source_sha256'])
    vectors = []
    for index, sample in enumerate(inputs):
        x = sample['x']
        records = infer(desc['model'], x)
        vectors.append(dict(index=index, x=x, input_commands=[[0, 0, j, v] for j, v in enumerate(x)],
                            input_bank_image=[[j % 4, j // 4, v] for j, v in enumerate(x)],
                            reference=records, label=sample.get('label')))
    if not vectors:
        raise ValueError('empty input dataset')
    save(dest / 'vectors.json', vectors)
    return package, vectors


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('deployment', type=Path)
    p.add_argument('--inputs', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    args = p.parse_args()
    package, vectors = export_package(load(args.deployment), load(args.inputs), args.out)
    print(json.dumps(dict(core=package['build']['core'], deployment_id=package['deployment_id'],
                          samples=len(vectors), compute_cycles=package['expected_compute_cycles']), indent=2))
