# 第011步：统一测量与模型对照

保持第001–010步及RTL原始字节，增加分组模型对照、真实RTL计数与带资源约束的主机构建规划。结论见[REPORT.md](REPORT.md)，机器结果见[results.json](results.json)。

本步验收平台和数值一致性。新训练模型在固定回归集上低于第010步准确率，作为实验模型保留；默认基线继续使用第010步，不以测试结果重新调参或另选赢家。

## 一键复现

进入`projects/tiny-int8-npu`后运行：

```powershell
& ./study/step011/run_all.ps1
# 重新训练全部预声明候选，再做RTL测量：
& ./study/step011/run_all.ps1 -Retrain
```

默认复用冻结模型，不训练；两种运行都会执行真实Vivado仿真。需要NumPy和Vivado，Python由脚本定位本机附带运行时或通过`-Python`指定；`VIVADO_BIN`指定Vivado目录。

仅检查离线封存文件：

```powershell
& 'C:/Users/11725/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' ./study/step011/verify_step011.py --check
```

## 实验合同

- 四个候选：18特征或12个body加速度/陀螺特征，隐藏层4或8，输出6；全部属于现有核心支持范围。
- 官方训练集21个受试者按升序轮转分成三折，每折fit/validation受试者不相交；保存确切源行归属。
- 每折的预处理和量化校准只使用fit数据；浮点验证准确率选择epoch，平均折INT8 macro-F1选择候选，周期和候选id作平手规则。
- 最终对全部官方训练数据固定轮数重训，轮数是选中候选的三折best epoch中位数；重训不以官方测试集选epoch。
- 候选和选择文件冻结后才打开官方测试集。该集合已在第010步使用，只作固定回归；CV用于模型选择，不能宣称无偏泛化或统计显著提升。
- 旧模型使用16名训练受试者，新模型使用21名；报告不将结果差异归因于单个架构变化。
- 两个模型×两种核心×三种RAM模式，共12组真实RTL；资源约束选中构建对新模型运行全2947条，其余11组固定前64条，另有协议/复位/驻留补充场景。
- 核心数值使用独立任意精度整数参考核对；矢量评估器还通过负数舍入、奇数形状和饱和的交叉测试。

## 性能与资源合同

RAM读取按实际测试台使能计数；周期和host写次数来自实际任务CSV。容量、逻辑使用量、事务数、字节数分别报告。

`choose_build`从六种已有构建中选择满足LUT/FF/DSP/RAMB上限及OOC WNS下限的方案，以`参数写次数+复用次数×热占用边沿`为目标，平手优先较少LUT、RAMB，再按核心/模式排序。无法满足时拒绝。

面积与时序复用第007/008B步综合结果，先检查其全部源码哈希。它们是同器件、同10ns约束的OOC估计，未新增综合/布局布线、板端时延或能耗结论。

## 制品

| 文件 | 用途 |
|---|---|
| experiment.json / cv_splits.json | 预声明方案及逐行分组 |
| models/ | 12次fit模型、预处理、history、验证预测及指标 |
| selection.json / selected_fit.json | 选择时冻结的依赖哈希和最终模型 |
| selected_deployment.json | 兼容第009步的统一部署描述 |
| quality_metrics.json / subject_metrics.csv | macro-F1、逐类、逐受试者及基线指标 |
| selected_predictions.csv | 每条回归输入的预测与整数分数 |
| hardware_metrics.csv / build_choices.json | 实测核心对照与带约束的规划 |
| evidence/ | 每组实际主机事务、独立参考、生成TB、事件、RAM计数、编译/仿真日志 |
| test_step011.py / unit_tests.log | 指标、分组、算术与资源约束测试 |
| artifact_manifest.json | 全部交付制品与旧步骤依赖的SHA256 |

build/只存可重建仿真产品，验收必需文件复制到evidence/并纳入Git。所有数据沿用第010步的来源与许可边界，不新增下载数据。

## 文献对照与适用范围

以下来自已收集全文的方法章节，项目选择属于工程推断，不代表复现论文完整系统；WoS站内收录仍未核验。

- Sze等，[Efficient Processing of Deep Neural Networks](https://arxiv.org/abs/1703.09039)，本地PDF第13、26–28页：数据移动、存储层次和综合评价指标。本步引入真实RAM读量与分口径对照。
- Chen等，[TVM](https://arxiv.org/abs/1802.04799)，本地USENIX版本PDF第3–4页：计算/调度分离、硬件反馈。本步用有限构建枚举和精确周期公式，不引入学习型cost model或完整TVM运行时。
- Sommer等，[DSP-Packing](https://arxiv.org/abs/2203.11028)，PDF第2–3页：打包的位宽、符号和误差处理。本步不更改已验证INT8算术或套用DSP48E2收益到Artix-7。
- Brossard等，[Denoising IMU Gyroscopes](https://arxiv.org/abs/2002.10718)，PDF第2–4页：校准基线、修正模型与姿态增量。后续先做陀螺数据合同和传统补偿，不将HAR分类解释为陀螺标定。

本地资料索引：`D:/学习资料/资料/AI_Study_文献库/20261021/index.html`。取得与阅读状态分别登记，不将所有候选视作已完整阅读。
