# 第004步：四路 MAC 与存储组织

2026-10-18补充：[分布式RAM的1/2/4路变体](../optimization/step004/)已通过同105,512边沿黄金，另检查全部768种(K,P)银行/尾mask映射。P=4从8个RAMB变为0，LUT从449增至545；[优化报告](../optimization/REPORT.md)分别说明容量、端口及资源取舍。

本步骤在第三步通过验收后继续。没有额外第004步附件，因此按原学习计划开展1、2、4路MAC、分bank存储和计数器实验。

同一套参数化RTL覆盖LANES=1/2/4，数学任务都是同一个INT8点积：把归约维度K按路交错分配，最后合并部分和。每路有独立的x/w读bank，不需要同时读共享单端口RAM。全部方案保存同样的512字节逻辑输入容量。

## 文件入口

| 文件 | 内容 |
|---|---|
| dot_banked_core.v | 1/2/4路乘法、部分和、尾部mask、流水valid/last、最终归约 |
| bank_ram.v | 可综合的同步字节bank，不复位RAM |
| dot_banked_top.v | 标量host装载接口、按j%P和floor(j/P)分bank |
| tb_dot_banked.v | 三配置实际RAM仿真、独立内存/任务模型、逐拍自检 |
| verify_step004.py | 相同输入集、固定种子、三配置周期模型、计数及结果比较 |
| test_step004_reference.m | MATLAB点积参考与1/2/4路bank映射的独立核对 |
| vectors.json | 168组相同工作负载，含128组随机输入 |
| comparison.csv | 504条配置比较：周期、MAC、读取字节、尾部利用率和装载开销 |
| trace_K3_p*.csv | K=3时每种配置的逐拍记录 |
| results.json | 实际验收状态、配置统计、工具与源文件哈希 |
| util_p*.rpt、timing_p*.rpt | 三配置同器件OOC综合与时序估计 |
| REPORT.md | 测量、收益、代价和无收益案例 |

## 为什么要有多个bank

P路MAC每拍最多需要P个x和P个w。映射为：

`bank(j)=j%P`，`bank_addr(j)=floor(j/P)`。

例如P=4时，一拍取x[0..3]/w[0..3]，下一拍取x[4..7]/w[4..7]。每个元素仍只读一次；提升来自同一拍并行读多个bank，而非减少总读取字节。

```mermaid
flowchart LR
    H[标量host写入 j] --> B[按j mod P选择bank]
    B --> R[每路独立x/w同步RAM]
    R --> M[P路乘法寄存器与mask]
    M --> A[P路24位部分和]
    A --> S[最终部分和归约]
    S --> O[24位结果]
```

K不整除P时，最后一拍只使能真实元素对应的bank和MAC。不能依赖未使用RAM位置恰好为0，也不能把旧乘积再累加一次。测试先向全RAM写入非零污染值，再用不同K覆盖真实输入，检查尾部使能。

## 接口与时序

顶层保留第三步的同步高有效reset、start/start_ready、9位k_cfg、fetch_enable、标量host写握手、busy、24位out_data和单拍out_valid/cfg_error。合法K为1～256。LANES是综合时参数，只支持1/2/4，不能在任务中改变。

核心把读使能扩为LANES位mask，所有bank共用组地址；各bank读数据拼成LANES×8位总线。仅有效bank读取。host仍每拍装载一对字节，启动拍和busy期间host_ready=0。RAM复位后保留数据。

读请求→同步RAM响应/mask→乘积/mask→每路部分和→最终归约。最后一组MAC完成后再经过一个归约边沿输出。fetch_enable只停止新组请求，已经发出的所有路继续推进；busy保持到归约输出。

令G=ceil(K/P)，无发读暂停时，从接受启动到新结果是`G+3`周期。若有S个尚未发完请求时的停发周期，则为`G+3+S`。为统一三配置的测量结构，P=1也保留最终输出归约边沿；所以本步P=1延迟K+3，而第三步单MAC是K+2。两种基线不能混写。

数值仍为INT8×INT8，16位乘积显式扩为24位；每路保存对应子序列部分和，最终有符号相加。总范围仍在24位内，无舍入、截位和饱和。P=4的最后归约使用两级加法树，结果在一个边沿寄存；未声明已满足特定板端频率。

## 复现

在NYCU-Lab3仓库根目录：

```powershell
python study/step004/verify_step004.py
```

Python仅依赖标准库。仿真优先Icarus，否则使用VIVADO_BIN或本机Vivado 2025.1。MATLAB独立核对需在step004目录运行：

```powershell
& 'D:/matlab/bin/matlab.exe' -batch "test_step004_reference"
```

回到仓库根目录合并MATLAB结果：

```powershell
python study/step004/verify_step004.py --use-matlab-results
```

三配置综合：

```powershell
& ./study/step004/run_synthesis.ps1
```

本机Vivado与MATLAB按前两步已确认的环境限制在授权的沙箱外执行。综合脚本仅在临时英文目录复制源码并生成报告，结果保存回本目录。缺工具或验证失败会记录FAIL，不能将未执行项目写成PASS。

修改LANES、存储延迟、mask或归约结构后重跑同一回归，比较相同vectors.json；不要只用最大K证明设计取舍。
