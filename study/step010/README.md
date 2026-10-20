# 第010步：真实IMU特征上的小网络与RTL验证

本步沿第009步交付中的“先接真实数据”方向推进：在已有核心支持范围内，用真实惯性传感器活动识别数据训练18–8–6 ReLU MLP，冻结后完成整数部署与RTL逐项核对。旧路线中的板级实现仍待完成；本步不替代FPGA顶层、约束、布局布线及上板验收。

## 一键复现

仓库根目录PowerShell：

```powershell
& ./study/step010/run_all.ps1
```

默认使用已冻结模型，核对数据哈希、验证受试者隔离与预处理、生成第009步部署包和事务、实际运行全部2947条测试输入，并核对精度、冷热周期和完整制品哈希。需要NumPy和Vivado；本机Codex附带Python/NumPy2.3.5已可用，不需要另装MATLAB或深度学习框架。

从固定实验配置重新训练：

```powershell
& ./study/step010/run_all.ps1 -Retrain
```

可用`-Python <python.exe路径>`指定运行时，Vivado位置由`VIVADO_BIN`控制。重新训练在测试评估前冻结模型和尺度，不能基于测试结果反复调整配置后继续把同一测试集称作未见数据。

## 数据与来源

[UCI HAR数据主页](https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones)，DOI `10.24432/C54S4K`；作者Jorge Reyes-Ortiz、Davide Anguita、Alessandro Ghio、Luca Oneto、Xavier Parra。实际下载采用公开Coursera课程分发包，完整SHA256：

`50dabbc800629611831a85b8b71c87040525ca4af6a152c6ba9360ecee6b92dc`

官方当前压缩包下载过慢，本次没有完成与它的逐字节比较；不把课程副本说成已核验相同的当前官方ZIP。分发URL、原成员SHA256、提取列与派生CSV哈希见[data/provenance.json](data/provenance.json)。下载不执行任何参考代码，62.6MB压缩包仅作为忽略的缓存，复现验收所需的18列数据已纳入Git。

原数据来自30位受试者的手机加速度计/陀螺仪，原采样50Hz、128点窗口、50%重叠。这里直接使用数据集提供的归一化统计特征，而非硬件采原始角速度并在线提特征。上游特征已归一化到[-1,1]，本项目只保证新增标准化和量化校准使用训练受试者；不声称重新审计了上游归一化拟合范围。

选择18列：tBodyAcc、tGravityAcc、tBodyGyro三组，各取mean/std的XYZ。对应原561列中的1–6、41–46、121–126；不把归一化特征解释为rad/s或温度。原行号和受试者保留，标签1..6映射到0..5：行走、上楼、下楼、坐、站、躺。

### 署名与许可记录

UCI当前页面标注CC BY 4.0，但课程压缩包中的2012 README明确要求论文引用且禁止商业使用。两种文字均保留，未改写旧README或为该副本推定商业许可。本项目限本地教学实验，未推送或公开发布。详见[data/README.txt](data/README.txt)与[来源说明](REFERENCES.md)。

## 数据划分与训练

| 划分 | 受试者数 | 窗口数 | 用途 |
|---|---:|---:|---|
| 训练 | 16 | 5619 | 参数拟合、输入mean/std与量化校准 |
| 验证 | 5 | 1733 | 选择800轮中的最佳浮点准确率，平手按交叉熵 |
| 测试 | 9 | 2947 | 冻结后一次评估、全部送RTL |

验证受试者固定为5、11、19、23、30，来自官方训练部分；测试保持官方受试者划分，三者无交集。未随机拆分相邻重叠窗口。固定种子20261020，Adam全批训练、学习率0.01、L2=0.0001；配置见[experiment.json](experiment.json)。

模型输入由训练mean/std标准化、固定裁剪至±127/32，再以1/32尺度作nearest-even整数化。第一层ReLU，第二层输出6个分数；argmax平手选最小类别索引，softmax不进入RTL。

参数与隐藏/输出尺度只从训练数据校准，为2的幂；重定标multiplier=1。signed24点积、INT32偏置、signed33加偏置、逐层RNE/INT8饱和沿用现有合同。主机预处理参数见[preprocessing.json](preprocessing.json)，浮点权重、整数模型和统一部署描述均有独立文件。

## 已测结果

见[验收报告](REPORT.md)及[results.json](results.json)。第009步自动选择2×2混合存储构建，本步核心RTL字节保持不变。

| 指标 | 结果 |
|---|---:|
| 浮点测试准确率 | 2410/2947 = 81.7781% |
| Python INT8与RTL准确率 | 2409/2947 = 81.7441% |
| 浮点与整数预测一致率 | 98.4391% |
| 测试输出整数分数逐项匹配 | 17682/17682 |
| RTL计算周期 | 105 |
| 冷占用边沿 | 330 |
| 参数驻留后的热占用边沿 | 124 |

冷占用=206项权重/偏置写入+18项输入写入+1个start+105拍计算；热占用=18+1+105。它们不包括特征提取、主机标准化/整数化、真实总线和操作系统开销，不能据此声称端到端实时性或板端频率。没有新增综合或功耗结果。

此模型是受试者隔离的真实活动识别基线，81.74%仍有明显分类错误。它验证部署流程和当前小核心；未做陀螺零偏、温度/标度因数补偿、Allan分析或闭环控制。

## 修改与证据入口

| 文件 | 作用 |
|---|---|
| prepare_data.py / data/provenance.json | 数据获取、精确列提取和来源/派生哈希 |
| experiment.json / train_har.py | 固定划分、可调整训练配置与量化校准 |
| split_membership.json / training_history.csv | 每个官方训练行的归属和逐轮验证记录 |
| trained_model.json / deployment.json | 可解释整数网络和第009步部署输入 |
| float_model.json / preprocessing.json | 浮点对照与主机预处理合同 |
| verify_har.py / test_har.py | 多类别评估、真实RTL核对与预处理/划分测试 |
| predictions.csv | 每个测试窗口的真实标签、浮点/整数/RTL预测及6个RTL分数 |
| build/rtl/ | 参数、物理镜像、输入、逐层参考、实际事务、测试台、事件和日志 |
| artifact_manifest.json | 本步制品及旧核心/部署依赖的SHA256 |

为保留旧步骤哈希，本步复用第009步脚本时不修改其文件。多类别标签在本步评估器中核对；送第009步通用数值运行器的是无标签INT8输入。其旧测试台辅助任务编号1000..1004会与2947条主任务冲突，本步只在新生成测试台中改到3047..3051，避免事件混合；硬件和检查断言不变。

本地冻结数据可离线重放。需要重新获取原始分发包时：

```powershell
$py='C:/Users/11725/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $py study/step010/prepare_data.py --download
```

如果分发包哈希改变，脚本拒绝覆盖数据；应先调查来源变化。只检查已交付哈希而不调用Vivado：

```powershell
& $py study/step010/verify_har.py --check
```
