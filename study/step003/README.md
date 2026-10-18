# 第003步：同步存储读取与流水有效标记

2026-10-18补充：[同步分布式RAM变体](../optimization/step003/)已通过同39,592边沿逐拍黄金；综合对照见[优化报告](../optimization/REPORT.md)。原同步读延迟和暂停排空合同保持，原版保留对照。

第二步已经验收。本步骤按其“下一步”定义继续，在工作区没有发现额外的第003步外部规格。本目录明确采用固定一拍同步读 RAM 和一拍乘法寄存器，再做单拍反馈累加；接口合同见 [教学规格](003_同步存储器读取与流水有效标记_项目式学习.md)。

## 文件入口

| 文件 | 内容 |
|---|---|
| dot_serial_mem.v | 配置快照、读地址、请求计数、流水标签、乘法寄存器、24位累加 |
| sync_byte_ram.v | 256×8同步RAM，不复位存储和读数据寄存器 |
| dot_mem_top.v | 两块RAM与核心连接；空闲时通过host端口装入x/w |
| tb_dot_mem.v | 实际RAM连接、独立内存/任务黄金模型、逐拍标签与计数检查 |
| verify_step003.py | 固定种子激励、Python周期模型与28字段逐拍对齐 |
| test_step003_reference.m | 用第二步已验证的MATLAB函数独立核对完整点积 |
| vectors.json | 完成任务的完整输入、数学期望、任务延迟和发读暂停数 |
| results.json | 最新验证汇总、工具版本、源文件哈希 |
| trace_K*.csv | K=1、K=3无停顿与K=3暂停排空的简短时序记录 |
| simulation.log、matlab_console.log | RTL与MATLAB实际执行日志 |
| synthesis_*.rpt、synthesis_results.json | 包含两块RAM的顶层综合与时序报告 |
| REPORT.md | 验收、测量、首次失败和当前边界 |
| build/rtl_trace.csv | 全部RTL逐拍记录，其他build文件可再生成 |

## 数据如何逐拍流动

```mermaid
flowchart LR
    A[读地址与使能] --> B[同步RAM响应及rsp_valid/rsp_last]
    B --> C[乘法寄存器及mul_valid/mul_last]
    C --> D[24位部分和]
    D --> E[末项sum_next写输出]
    F[fetch_enable] --> A
```

fetch_enable只决定是否继续发读，不冻结已发出的数据。即使发读暂停或全部请求已经发完，rsp与mul两个阶段仍逐拍推进。最后一个乘积在mul_last=1的有效累加边沿进入sum_next，再产生out_valid并清busy。

RAM在发读上升沿后更新输出；乘法寄存器在下一上升沿读取该数据；累加器在再下一个上升沿读取乘积。因此K=3无停顿任务：C0启动，C1～C3发读，C2～C4登记乘积，C3～C5累加，C5产生结果。启动到完成为K+2个周期。

## 复现

在NYCU-Lab3仓库根目录运行：

```powershell
python study/step003/verify_step003.py
```

Python只需标准库。优先使用PATH中的iverilog/vvp，否则使用`VIVADO_BIN`或本机`D:\vivado\2025.1\Vivado\bin`。本机沙箱内的Vivado生成C文件编译失败，经授权在沙箱外运行通过。脚本缺工具或失败会退出非零并记录FAIL。

同时调用MATLAB：

```powershell
python study/step003/verify_step003.py --matlab D:/matlab/bin/matlab.exe
```

若MATLAB需要单独在沙箱外运行，在本目录执行：

```powershell
& 'D:/matlab/bin/matlab.exe' -batch "test_step003_reference"
```

再回到仓库根目录合并新鲜结果：

```powershell
python study/step003/verify_step003.py --use-matlab-results
```

重新综合（脚本在系统临时英文目录工作，将报告保存回本目录）：

```powershell
& ./study/step003/run_synthesis.ps1
```

综合对象是dot_mem_top，包含两块RAM。输入向量/参考源码变化后需重跑MATLAB；DUT/综合脚本变化后需重跑综合。报告中的时钟约束用于综合网表估计，不能据此声称板端频率收敛。
