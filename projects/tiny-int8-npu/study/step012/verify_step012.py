"""Synthetic calibration, independent exact oracle, real RTL, immutable evidence."""
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from calibration import *


def old_dependencies():
    base = ROOT.parent
    manifest_path = base / 'step011/artifact_manifest.json'
    manifest = load(manifest_path)
    assert manifest['status'] == 'PASS'
    deps = {'step011/' + n: h for n, h in manifest['sha256'].items()}
    deps.update(manifest['dependency_sha256'])
    deps['step011/artifact_manifest.json'] = sha(manifest_path)
    for n, h in deps.items():
        assert sha(base / n) == h, n
    print('PASS previous frozen dependencies', len(deps), flush=True)
    return deps


def fraction_reference(coeff, z, raw):
    # Independent arithmetic path: Fraction + Python built-in nearest-even round.
    flag = False
    def clip(v):
        nonlocal flag
        flag |= not -(1 << 31) <= v < 1 << 31
        return min((1 << 31) - 1, max(-(1 << 31), v))
    first = clip(round(Fraction(coeff[2] * z, 16384)) + coeff[1])
    bias = clip(round(Fraction(first * z, 16384)) + coeff[0])
    return bias, clip(raw - bias), int(flag)


def stress_vectors(start, cfg):
    cases = []
    patterns = [[0, 0, 0], [100, -200, 300], [1, -3, -5],
                [2147483647, 2147483647, 2147483647], [-2147483648, -2147483648, -2147483648]]
    for c in patterns:
        for z in [-32768, -24576, -8192, 0, 8192, 24576, 32767]:
            for raw in [-2147483648, -1, 0, 1, 2147483647]:
                cases.append((c, z, raw))
    rng = np.random.default_rng(cfg['seed'] + 12)
    for _ in range(cfg['boundary_random_cases']):
        cases.append((rng.integers(-(1 << 31), 1 << 31, 3, dtype=np.int64).tolist(),
                      int(rng.integers(-32768, 32768)), int(rng.integers(-(1 << 31), 1 << 31))))
    vectors = []
    for coeff, z, raw in cases:
        result = fraction_reference(coeff, z, raw)
        assert result == fixed_scalar(coeff, z, raw)
        vectors.append(dict(tag=start + len(vectors), source_index=-1, axis=-1,
                            c0=coeff[0], c1=coeff[1], c2=coeff[2], z=z, raw=raw,
                            bias=result[0], corrected=result[1], saturated=result[2]))
    return vectors


def run_command(args, dest, name):
    process = subprocess.run([str(a) for a in args], cwd=dest, capture_output=True,
                             text=True, encoding='utf-8', errors='replace')
    log = process.stdout + process.stderr
    (dest / name).write_text(log, encoding='utf-8', newline='\n')
    if process.returncode or 'Fatal:' in log:
        raise RuntimeError(name + '\n' + log[-3000:])
    return log


def _run_rtl(sensor_vector_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cfg = load(ROOT / 'experiment.json')
    with Path(sensor_vector_path).open(encoding='utf-8', newline='') as f:
        vectors = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(f)]
    if not vectors or [v['tag'] for v in vectors] != list(range(len(vectors))):
        raise ValueError('nonempty contiguous sensor vector tags required')
    for v in vectors:
        coeff = [v['c0'], v['c1'], v['c2']]
        oracle = fraction_reference(coeff, v['z'], v['raw'])
        assert oracle == fixed_scalar(coeff, v['z'], v['raw']) == (v['bias'], v['corrected'], v['saturated'])
    extra = stress_vectors(len(vectors), cfg)
    write_csv(output / 'stress_vectors.csv', extra)
    all_vectors = vectors + extra
    build = output / 'build'
    build.mkdir(parents=True, exist_ok=True)
    fields = ['tag', 'c0', 'c1', 'c2', 'z', 'raw', 'bias', 'corrected', 'saturated']
    (build / 'vectors.txt').write_text(''.join(' '.join(str(v[n]) for n in fields) + '\n' for v in all_vectors),
                                      encoding='utf-8', newline='\n')
    import os
    binary = Path(os.environ.get('VIVADO_BIN', 'D:/vivado/2025.1/Vivado/bin'))
    commands = [[binary / 'xvlog.bat', '--sv', ROOT / 'gyro_bias_core.v', ROOT / 'tb_gyro_bias.v'],
                [binary / 'xelab.bat', 'tb_gyro_bias', '--timescale', '1ns/1ps', '-s', 'gyro_sim'],
                [binary / 'xsim.bat', 'gyro_sim', '-runall']]
    logs = []
    for command, name in zip(commands, ['compile.log', 'elaborate.log', 'simulation.log']):
        logs.append(run_command(command, build, name))
    assert f'PASS GYRO completed={len(all_vectors)} reset_scenarios=6 latency=5' in logs[-1]
    with (build / 'rtl_events.csv').open(encoding='utf-8', newline='') as f:
        actual = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(f)]
    assert len(actual) == len(all_vectors)
    for event, expected in zip(actual, all_vectors):
        assert all(event[n] == expected[n] for n in ['tag', 'bias', 'corrected', 'saturated']), (event, expected)
        assert event['compute_cycles'] == 5 and event['stall_cycles'] == expected['tag'] % 4
    for n in ['compile.log', 'elaborate.log', 'simulation.log', 'vectors.txt', 'rtl_events.csv']:
        shutil.copyfile(build / n, output / n)
    save(output / 'commands.json', [[str(v) for v in command] for command in commands])
    result = dict(status='PASS', sensor_cases=len(vectors), stress_cases=len(extra), total_cases=len(all_vectors),
                  exact_scalar_matches=len(actual), reset_cancel_restart_scenarios=6, compute_cycles=5,
                  stalled_output_cases=sum(v['stall_cycles'] != 0 for v in actual),
                  saturated_stress_cases=sum(v['saturated'] != 0 for v in extra),
                  sensor_vectors_sha256=sha(sensor_vector_path),
                  rtl_source_sha256={n: sha(ROOT / n) for n in ['gyro_bias_core.v', 'tb_gyro_bias.v']},
                  scope='Actual Vivado RTL simulation of new scalar Q24/Q14 polynomial kernel. One multiply operator, not a measured one-DSP claim; no synthesis or board result.')
    save(output / 'rtl_results.json', result)
    print('PASS GYRO RTL', len(actual), 'exact scalar cases', flush=True)
    return result


def run_rtl(sensor_vector_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    save(output / 'rtl_results.json', dict(status='RUNNING'))
    try:
        return _run_rtl(sensor_vector_path, output)
    except Exception as e:
        save(output / 'rtl_results.json', dict(status='FAIL', error=str(e)))
        raise


def report():
    r = load(ROOT / 'results.json')
    c = load(ROOT / 'calibrated/results.json')
    lines = ['# 第012步验收报告', '', '**本步完成数据合同、合成数据基线与RTL验证；真实陀螺标定尚未完成。**', '',
             '## 数据与算法', '',
             f"使用两个明确标注SYNTH的虚拟器件，12个不跨划分的采集批次。划分样本数：{c['split_counts']}。所有数据由已保存种子和生成器产生，没有实测温度/角速度数据。",
             '', f"按器件独立拟合常值零偏及温度多项式，只使用train批次中的静止样本；按validation三轴整体RMSE选定{c['selected_degree']}阶，再冻结模型并评估test；不合并验证集重训。",
             '', '| 方法 | 合成test三轴整体RMSE (rad/s) |', '|---|---:|']
    for name, metric in c['test_methods'].items():
        lines.append(f"| {name} | {metric['aggregate_rmse_rad_s']:.9f} |")
    lines += ['', '逐轴RMSE、平均误差、最大误差和分器件/批次的积分误差见calibrated/results.json；积分采用相邻样本梯形积分，时间跨度由真实时间戳差计算，只是分轴角速度误差的积分，不等价于一般三维姿态误差。', '',
              '合成误差含二次温度项、未建模的微小三次项/升降温项、批次偏移和白噪声；温度变化被人为加速，不验证真实热动态或真实噪声模型。温度补偿有效是实现自检，不是实物性能结论。', '',
              '## 定点合同与RTL', '',
              '新标量核心使用signed32、24小数位表示rad/s及系数，signed16、14小数位表示归一化温度z=(T-25)/20。Horner两次乘法共享一个32×16乘法算子，每次乘积按nearest-even右移14位，再加系数并饱和到signed32；最终raw-bias也饱和。任一步饱和置sticky标记。', '',
              f"合成传感器范围内最大浮点/定点bias差为{c['fixed_float_max_bias_error_rad_s']:.10g} rad/s，门槛2e-6 rad/s；传感器验证饱和数{c['fixed_saturations']}。",
              '', f"真实Vivado仿真核对{r['rtl']['sensor_cases']}个传感器轴样本和{r['rtl']['stress_cases']}个边界/随机样本，共{r['rtl']['total_cases']}次标量运算，所有bias、corrected、saturated、tag逐项一致。",
              '', '每次接受start至out_valid为5个时钟间隔。输出背压期间载荷稳定；忙时start及输入改变不影响已锁存任务；6种复位位置覆盖在途各阶段和未消费输出，取消后不泄漏输出并能重启。单轴串行运行，三轴需分别发送；5拍不包括上游量化、系数输送、输出握手及传感器接口。', '',
              '独立参考使用Fraction和Python内置round构造精确有理数舍入，与工程整数参考及RTL三方核对。未复用INT8分类核心：本步为精细角速度分辨率采用单独Q24合同，未修改前述NPU或声称单个DSP实现。没有新综合、布局布线、面积、功耗或板端频率结论。', '',
              '## 导入边界', '',
              '数据入口验证SHA256、CSV字段、有限数值、单位、右手坐标系、批次划分、时间戳单调性和采样间隔。deg/s显式转rad/s；不猜测LSB量程、坐标变换或时间单位。', '',
              '逐器件拟合，无标定的器件拒绝；超出训练温度范围拒绝外推；温度设计矩阵秩亏/病态拒绝。无独立参考时必须显式声明stationary_zero_assumption，只有人工标记静止的样本采用零参考，动态样本不报告误差。该假设不自动校正地球自转或静止标记错误。', '',
              '用户已确认暂时没有原始数据，因此不将合成PASS视为真实标定完成。收到数据后先按DATA_CONTRACT.md导入，再复用基线、定点和RTL验证入口。', '',
              '## 验收', '',
              f"{r['unit_tests']}项合同测试通过；原第011步及其全部依赖哈希保持。完整数据、模型、选择记录、参考向量、实际RTL事件与工具日志纳入Git，仿真产品留在忽略的build目录。", '']
    (ROOT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')


def seal(check=False):
    path = ROOT / 'artifact_manifest.json'
    if check:
        m = load(path)
        assert m['status'] == 'PASS'
        for n, h in m['sha256'].items():
            assert sha(ROOT / n) == h, n
        for n, h in m['dependency_sha256'].items():
            assert sha(ROOT.parent / n) == h, n
        print('PASS STEP012 sealed files', len(m['sha256']))
        return
    assert load(ROOT / 'results.json')['status'] == 'PASS'
    files = [p for p in ROOT.rglob('*') if p.is_file() and p != path and
             not any(v in p.relative_to(ROOT).parts for v in ['build', '__pycache__'])]
    save(path, dict(status='PASS', sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)},
                    dependency_sha256=old_dependencies()))


def main(regenerate=False):
    save(ROOT / 'artifact_manifest.json', dict(status='RUNNING'))
    save(ROOT / 'results.json', dict(status='RUNNING'))
    try:
        old_dependencies()
        if regenerate:
            from generate_synthetic import generate
            generate(ROOT / 'data')
        p = subprocess.run([sys.executable, str(ROOT / 'test_calibration.py')], capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
        (ROOT / 'unit_tests.log').write_text(p.stdout + p.stderr, encoding='utf-8', newline='\n')
        if p.returncode:
            raise RuntimeError(p.stdout + p.stderr)
        tests = re.search(r'Ran (\d+) tests', p.stdout + p.stderr)
        assert tests, 'unit test count missing'
        result = calibrate(ROOT / 'data/metadata.json', ROOT / 'calibrated')
        assert result['dataset_kind'] == 'synthetic' and result['physical_calibration_complete'] is False
        rtl = run_rtl(ROOT / 'calibrated/sensor_vectors.csv', ROOT / 'evidence')
        save(ROOT / 'results.json', dict(status='PASS', dataset_kind='synthetic', physical_calibration_complete=False,
             software_result_sha256=sha(ROOT / 'calibrated/results.json'), rtl=rtl, unit_tests=int(tests[1]),
             stage='Data contract + synthetic traditional baselines + scalar fixed-point RTL',
             next='Import actual sensor measurements; do not claim physical calibration from synthetic results'))
        report()
        seal()
        seal(True)
    except Exception as e:
        save(ROOT / 'results.json', dict(status='FAIL', error=str(e)))
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true')
    p.add_argument('--regenerate', action='store_true')
    p.add_argument('--rtl-vectors')
    p.add_argument('--out')
    a = p.parse_args()
    if a.check:
        seal(True)
    elif a.rtl_vectors:
        if not a.out:
            p.error('--rtl-vectors requires --out')
        run_rtl(a.rtl_vectors, Path(a.out))
    else:
        main(a.regenerate)
