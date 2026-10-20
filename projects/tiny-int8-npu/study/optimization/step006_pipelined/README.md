# 第006步的三段重定标流水改进

当前推荐入口。数学、训练模型、主机协议和512个测试样本与[功能基线](../../step006/README.md)一致；量化流水从1段改为3段，index/last随数值传递。

实测BRAM版本：**2203 LUT、727 FF、4 DSP、16 RAMB，10ns综合时序估计WNS +1.759ns**。原版为2349 LUT、633 FF、WNS −7.938ns。同一个16–8–2任务，片内转发104拍，主机桥接132拍（测试台D=16）。正WNS不是布局布线或板端验收。

全部624网络任务、6,016个隐藏/输出位置及每层pre值通过；标量流水28,746拍核对ready、数值、舍入/饱和标志、tag、复位与事务守恒。[结果](results.json)、[综合](synthesis_results.json)、[逐任务指标](metrics.csv)、[对照表](comparison.csv)。详细解释见[优化报告](../REPORT.md)。

## 修改位置

- `requant_i8.v`：乘积、移位舍入决策、INT8阈值夹紧三段，每段独立弹性寄存器。
- `mlp2_top.v`：由verify_pipeline.py从原top进行明确替换生成；元数据来自量化器的4位tag。修改调度优先改原top及生成规则，避免下次覆盖手工修改。
- `verify_pipeline.py`：独立流水控制黄金，同步复位取消队列；复用原整数黄金与冻结主机记录，不重新训练或改变测试集。
- `tb_quant_pipeline.v`：逐拍检查数据及tag。网络使用原第006步测试台，避免随优化同时修改黄金合同。

量化器新增 `in_tag[3:0]`/`out_tag[3:0]`，MLP中为 `{last,index}`；三段空流水接受输入后，数值在第三个寄存器边沿成为有效输出。吞吐上限仍为每拍一个量化值；下游不就绪时按容量传播背压，并非强制插入两个空拍。

## 复现

先运行第006步生成冻结测试数据。在仓库根目录：

```powershell
$py='C:/Users/11725/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $py study/optimization/step006_pipelined/verify_pipeline.py
& ./study/optimization/step006_pipelined/run_synthesis.ps1
```

默认实际仿真为BRAM版本。综合同时给出分布式RAM的资源对照；本轮推荐BRAM，因为当前W容量下全分布式版本需要更多LUT。后续混合存储与单引擎分时复用见[下一步通过条件](../../OPTIMIZED_LEARNING_PLAN.md)。
