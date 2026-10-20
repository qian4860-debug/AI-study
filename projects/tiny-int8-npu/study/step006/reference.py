"""Exact integer contract; no floating point in RTL golden arithmetic."""
import math


def requant(value, multiplier, shift):
    if type(value) is not int or not -(1 << 32) <= value < (1 << 32):
        raise ValueError('signed33 value')
    if type(multiplier) is not int or type(shift) is not int or not 1 <= multiplier <= 65535 or not 0 <= shift <= 47:
        raise ValueError('requant configuration')
    magnitude = abs(value * multiplier)
    base, rem = divmod(magnitude, 1 << shift)
    tie = bool(shift and rem == (1 << (shift - 1)))
    rounded = base + int(2 * rem > (1 << shift) or (tie and base % 2))
    rounded = -rounded if value < 0 else rounded
    return max(-128, min(127, rounded)), int(not -128 <= rounded <= 127), int(tie)


def validate(model):
    """Small typed two-FC graph, deliberately a restricted educational IR."""
    if model['version'] != 1 or model['dtype'] != 'int8' or model['zero_point'] != 0:
        raise ValueError('IR type/version')
    k, h, o = model['shape']
    if any(type(v) is not int for v in (k,h,o)) or not 1 <= k <= 256 or not 1 <= h <= 8 or not 1 <= o <= 8:
        raise ValueError('shape')
    if len(model['layers']) != 2:
        raise ValueError('exactly two FC layers')
    for i, (inputs, outputs) in enumerate([(k, h), (h, o)]):
        layer = model['layers'][i]
        if len(layer['weight']) != outputs or any(len(row) != inputs for row in layer['weight']):
            raise ValueError('weight shape')
        if len(layer['bias']) != outputs or layer['relu'] != (i == 0):
            raise ValueError('bias/activation')
        if any(type(v) is not int or not -128 <= v <= 127 for row in layer['weight'] for v in row):
            raise ValueError('weight INT8')
        if any(type(v) is not int or not -(1 << 31) <= v < (1 << 31) for v in layer['bias']):
            raise ValueError('bias INT32')
        requant(0, layer['multiplier'], layer['shift'])
    return k, h, o


def infer(model, x):
    k, _, _ = validate(model)
    if len(x) != k or any(type(v) is not int or not -128 <= v <= 127 for v in x):
        raise ValueError('input INT8/shape')
    records = []
    for layer in model['layers']:
        dot = [sum(a*b for a, b in zip(x, row)) for row in layer['weight']]
        pre = [a+b for a, b in zip(dot, layer['bias'])]
        active = [max(0, v) if layer['relu'] else v for v in pre]
        quantized = [requant(v, layer['multiplier'], layer['shift']) for v in active]
        records.append(dict(dot=dot, pre=pre, active=active, quantized=quantized))
        x = [q[0] for q in quantized]
    return records


def lower_loads(model, x):
    """Emit the real top-level host transactions (layer,kind,address,data)."""
    validate(model); infer(model, x)
    commands = [(0, 0, j, v) for j, v in enumerate(x)]
    for i, layer in enumerate(model['layers']):
        commands += [(i, 1, row*256+j, v) for row, w in enumerate(layer['weight']) for j, v in enumerate(w)]
        commands += [(i, 2, row, v) for row, v in enumerate(layer['bias'])]
    return commands
