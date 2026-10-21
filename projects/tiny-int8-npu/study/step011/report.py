"""Generate human-readable measurements from retained machine evidence."""
from common import *


def main():
    result, quality = load(ROOT / 'results.json'), load(ROOT / 'quality_metrics.json')
    assert result['status'] == 'PASS'
    selection = load(ROOT / 'selection.json')
    cfg = load(ROOT / 'experiment.json')
    lines = ['# 第011步验收报告', '', '## 结论', '',
             f"已完成{result['cv_fits']}次按受试者划分的训练、12组真实RTL构建对照。选中`{result['candidate']}`，形状{result['selected_shape']}，在全部21个官方训练受试者上固定训练{selection['refit_epochs']}轮。",
             '', '**本步PASS表示测量平台与数值验证通过，不表示新模型精度提升。新模型保持实验身份，第010步冻结模型继续作为默认基线。**',
             '', '选中模型的2947条固定回归输入、17682个最终整数分数全部与独立Python整数参考和RTL一致。其余11组构建各使用固定前64条输入；每组还验证7个换模型/驻留/复位/上传中断任务及深层补充场景。', '',
             '## 模型对照：仅官方训练数据的三折分组验证', '',
             '| 候选 | 形状 | 平均INT8 macro-F1 | 折间标准差 | 平均INT8准确率 | 预测auto周期 |',
             '|---|---|---:|---:|---:|---:|']
    for s in selection['candidate_summaries']:
        lines.append(f"| {s['candidate']} | {s['shape']} | {s['mean_int8_macro_f1']:.6f} | {s['std_fold_macro_f1']:.6f} | {s['mean_int8_accuracy']:.6f} | {s['auto_compute_cycles']} |")
    lines += ['', '候选、种子、800轮上限和选择规则先写入experiment.json；标准化统计量和量化尺度只用各折fit受试者。每折按验证浮点准确率、再按交叉熵选epoch，候选按平均INT8 macro-F1选择。最终在全部官方训练数据上重训，轮数取选中候选三个best epoch的中位数。', '',
              '**三折既用于选择epoch，也用于选择候选，因此上述分数属于模型选择统计，不是无偏泛化估计；折间标准差不是置信区间。**', '',
              '## 固定测试集回归', '',
              '| 模型 | 浮点准确率 | INT8准确率 | INT8 macro-F1 |', '|---|---:|---:|---:|']
    old = load(BASE / 'step010/results.json')
    for name, fa, m in [('step010冻结基线', old['test_float_accuracy'], quality['baseline_step010']['integer']),
                        ('step011选中模型', result['selected_float_accuracy'], quality['selected']['integer'])]:
        lines.append(f"| {name} | {fa:.6%} | {m['accuracy']:.6%} | {m['macro_f1']:.6f} |")
    names = ['行走', '上楼', '下楼', '坐', '站', '躺']
    lines += ['', '| 类别 | 基线召回率 | 新模型召回率 | 基线F1 | 新模型F1 |', '|---|---:|---:|---:|---:|']
    a, b = quality['baseline_step010']['integer'], quality['selected']['integer']
    for i, name in enumerate(names):
        lines.append(f"| {name} | {a['recall'][i]:.6f} | {b['recall'][i]:.6f} | {a['f1'][i]:.6f} | {b['f1'][i]:.6f} |")
    lines += ['', '逐受试者结果见subject_metrics.csv；完整混淆矩阵、precision/recall/F1及零除约定见quality_metrics.json。macro-F1固定对六类取平均，零分母按0处理。', '',
              '官方测试集在第010步已经使用。本步在选择文件冻结后才打开测试输入和标签，但仍只称固定回归集，不称新的未见测试；不按其结果重选方案。新模型使用21人重训、旧模型使用16人训练，不能把差异单独归因于网络结构。', '',
              '## 核心与存储实测', '',
              '| 模型 | 核心 | RAM模式 | 样本 | 预测/实测周期 | 冷/热占用边沿 | x/W读取B | LUT/FF/DSP/RAMB |',
              '|---|---|---:|---:|---|---|---|---|']
    for r in rows(ROOT / 'hardware_metrics.csv'):
        lines.append(f"| {r['model']} | {r['core']} | {r['ram_mode']} | {r['samples']} | {r['predicted_compute']}/{r['measured_compute']} | {r['cold_occupied']}/{r['warm_occupied']} | {r['measured_x_read_bytes']}/{r['measured_w_read_bytes']} | {r['LUT']}/{r['FF']}/{r['DSP']}/{r['RAMB']} |")
    lines += ['', 'RAM模式0=全BRAM，1=混合，2=全distributed。RAM读计数来自新生成测试台observe接受边沿上的实际rd_mask/x_rd_mask；只统计计算阶段有效8位操作数读取，排除host写、bias读和流水内部寄存器。每个任务独立核对计数与形状推导。融合隐藏写另计H字节。', '',
              '占用边沿=接受的主机写次数+1个start边沿+计算周期；冷加载含模型参数，热推理仅写输入。未包含总线等待、软件开销及任务间空隙。逻辑权重/偏置字节数、固定物理容量和主机事务数分别列出；一个INT32 bias写入是一个事务而不是一个字节。', '',
              'LUT/FF/DSP/RAMB和WNS复用第007/008B步同器件xc7a100tcsg324-1的OOC综合记录，源哈希逐项检查；本步未修改RTL、未重新综合、未布局布线。正WNS不等于板端100MHz，RAM读量不用于推导功耗。', '',
              '## 资源约束选择', '',
              f"本次限制：`{cfg['resource_limits']}`，OOC WNS≥{cfg['minimum_synthesis_wns_ns']}ns。不满足限制时明确拒绝，不自动放宽。",
              '', '| 同模型连续推理次数 | 核心 | RAM模式 | 预计总占用边沿 |', '|---:|---|---:|---:|']
    for p in load(ROOT / 'build_choices.json'):
        c = p['choice']
        lines.append(f"| {p['reuse']} | {c['core']} | {c['ram_mode']} | {c['total_occupied_edges']} |")
    lines += ['', '总占用=参数写入数+N×热占用；N=1/16/1024为无总线等待的规划预测，未运行1024次专门计时。当前两个核心参数装载量相同，因此增加N不会改变排序；不声称重用次数一定引起核心切换。资源配置的选择是主机构建规划，不是芯片内动态切换。', '',
              '## 端到端测量边界', '',
              'UCI HAR原始50Hz、128点窗口，对应2.56秒窗口跨度，50%重叠对应1.28秒步进。本工程直接使用预计算统计特征，没有在线滤波/特征提取和传输实测；上述跨度不能直接与核心周期相加形成已测端到端时延。', '',
              '本步没有增加per-channel、QAT、DSP打包或TCN。下一步应建立带单位、温度、时间戳及独立参考真值的陀螺数据合同，先做静态零偏/温度补偿基线。', '',
              '## 验收与复现', '',
              'run_all.ps1默认重放已冻结模型、运行12组RTL并重新封存；-Retrain重跑预声明的CV与重训。--check离线验证源码、数据、所有模型/划分/预测/事务/日志/CSV及旧依赖哈希。原步骤文件不改写。', '']
    (ROOT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
