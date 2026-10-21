# 第012步：陀螺数据合同与传统补偿基线

**用户目前没有原始测量数据。本步交付可复现的合成验证与真实数据导入入口，实物标定仍待完成。**

新增常值零偏、一次/二次温度模型、Q24/Q14独立整数参考和一个共享乘法算子的标量RTL核心。它是传感器补偿实验分支，保留既有INT8分类NPU及其所有冻结文件。

## 复现

进入`projects/tiny-int8-npu`后运行：

```powershell
& ./study/step012/run_all.ps1
# 由固定种子重新生成明确标注的合成数据，再执行全流程：
& ./study/step012/run_all.ps1 -Regenerate
```

需要Python、NumPy与Vivado。使用`-Python`指定解释器，`VIVADO_BIN`指定工具目录；默认定位现有本机运行时和Vivado2025.1。运行包括旧依赖哈希、8项失败路径/算术/数据隔离/已知系数恢复测试、基线拟合、验证集选阶、固定模型test评价、真实RTL、报告及哈希封存。

仅离线检查：

```powershell
$py='C:/Users/11725/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $py ./study/step012/verify_step012.py --check
```

结论见[验收报告](REPORT.md)，单位、字段、坐标系、划分与RTL握手见[数据合同](DATA_CONTRACT.md)。

## 真实数据入口

按[元数据模板](examples/metadata_template.json)准备CSV和metadata.json，填写实际SHA256。MAT文件需要先根据字段含义、单位与坐标系显式转为合同CSV，本步不猜测MAT变量意义。

```powershell
# metadata.json与samples.csv位于你指定的数据目录；输出放入独立实验目录。
& $py ./study/step012/calibration.py --metadata 'D:/your-data/metadata.json' --out 'D:/your-run/calibrated'
# 将该实验生成的全部定点轴向量送入同一个RTL核心：
& $py ./study/step012/verify_step012.py --rtl-vectors 'D:/your-run/calibrated/sensor_vectors.csv' --out 'D:/your-run/rtl'
```

没有温度时不能运行温度补偿入口；没有动态真值时只能评价明确标记的静止样本。没有独立设备温度循环时，不宣称跨批次或跨设备泛化。

## 数据与证据

- data/：7200条合成样本、来源与生成器哈希；两个虚拟器件各6个独立批次，100Hz、每批600点。温度被故意快速扫描，不模拟真实热时间常数。
- calibrated/：逐器件模型、选阶与哈希、校正后test输出、定点向量及误差报告。
- evidence/：实际RTL全部向量与事件、边界向量、编译/展开/仿真日志和工具命令；内部build/仅保留可重建工具产品并被忽略。
- gyro_bias_core.v / tb_gyro_bias.v：单标量Horner核心及握手/背压/复位测试。
- artifact_manifest.json：源码、配置、模型、数据、测试、参考、原始日志及旧步骤依赖SHA256。

软件补偿结果不等于实物标定验收。实际RTL周期不等于采样到输出时延。本步未综合或上板，不报告面积、DSP数、功耗或板端频率。积分角速度误差不等同于一般SO(3)姿态误差。

## 文献来源与工程取舍

本地参考来自已建立资料库，本步只复用概念，不复制论文源码或全文：

- [An Adaptive Compensation Algorithm...Strong Tracking Kalman Filter](https://doi.org/10.3390/s150511222)，本地`D:/学习资料/资料/AI_Study_文献库/20261021/pdf/AI-20261021-017_kalman.pdf`，PDF第4–5页：区分真实角速度、慢变误差与随机噪声，并建模温度/温度变化率。本步采用较简单的离线温度多项式对照，没有复现STKF、磁罗盘辅助或在线参数估计。
- [Denoising IMU Gyroscopes with Deep Learning](https://arxiv.org/abs/2002.10718)，本地`D:/学习资料/资料/AI_Study_文献库/20261021/pdf/AI-20261021-014_denoise.pdf`，PDF第2–4页：校准基线、神经网络修正与姿态增量评价。本步先做可解释传统基线，不以HAR分类成绩代替陀螺补偿效果。

现有WoS收录仍未核验。本步算法形式、数值格式和合成误差参数属于工程设计，不代表原论文的设备参数或测量结果。
