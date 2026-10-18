# NYCU Lab3 接口与数值合同

依据：`lab3-1/RTL/TPU.v`、`global_buffer.v`、`TESTBENCH/PATTERN.v`、`data_generator.py`，以及 `lab3-2/BOARD/reference/rtl/{TPU,board_bram,TPU_top}.v`、`HOST/uart_test.py`。上游版本见 results.json。

## 顶层端口（方向均相对于 TPU）

| 端口 | 方向 | Lab3-1 位宽 | Lab3-2 位宽 | 合同 |
|---|---|---:|---:|---|
| clk | 输入 | 1 | 1 | TPU 在上升沿更新状态 |
| rst_n | 输入 | 1 | 1 | 异步低有效，清空控制与部分和；RAM 不复位 |
| in_valid | 输入 | 1 | 1 | 空闲时一个周期的启动脉冲；该拍锁存维度 |
| M | 输入 | 8 | 8 | 卷积输入边长 / GEMV 行数 |
| N | 输入 | 8 | 8 | 卷积核边长 / GEMV 固定为 1 |
| K | 输入 | 无 | 8 | GEMV 归约长度 |
| busy | 输出 | 1 | 1 | 接受启动后拉高，全部 C 写完后拉低 |
| A_ram_en、B_ram_en | 输出 | 各 1 | 各 1 | 只读访问使能；空闲为 0 |
| A_index、B_index | 输出 | 各 16 | 各 16 | 地址含义见下表 |
| A_data_out、B_data_out | 输入 | 各 32 | 各 32 | RAM 输出到 TPU；名字中的 out 相对于 RAM |
| A_wr_en、B_wr_en | 输出 | 无 | 各 1 | GEMV 固定为 0 |
| A_data_in、B_data_in | 输出 | 无 | 各 32 | GEMV 未使用，固定为 0 |
| C_ram_en、C_wr_en | 输出 | 各 1 | 各 1 | 写结果时同时为 1；空闲均为 0 |
| C_index | 输出 | 16 | 16 | 128 位字地址 |
| C_data_in | 输出 | 128 | 128 | TPU 写入 C 的四个 32 位槽 |
| C_data_out | 输入 | 无 | 128 | 本实现不用 |

原接口参数默认 A_WIDTH=B_WIDTH=8、PSUM_WIDTH=32。本学习版本仅验证该配置。没有 ready、输出背压、运行中抢占或非法维度错误端口；调用方须在空闲启动，并在复位后重新装载/清理任务所需 RAM。

## 运算与存储

| 项目 | Lab3-1 卷积 | Lab3-2 GEMV |
|---|---|---|
| 运算 | 二维互相关，核不翻转，stride=1、padding=0 | C[r]=Σ A[r,k] B[k] |
| 数据 | UINT8 × UINT8 → UINT32 | INT8 × INT8 → INT32 |
| 范围 | 1≤N≤M≤254，L=M−N+1 | 1≤M,K≤254，N=1 |
| A 地址 | 字节起点 c·(M+3)+r；每列附加 3 个零字节 | floor(r/4)·K+k |
| A 槽位 | 起点起四个连续字节放在 [31:24]、[23:16]、[15:8]、[7:0]，窗口彼此重叠 | 相邻四行的元素依次放在 [7:0]、[15:8]、[23:16]、[31:24] |
| B 地址 | floor(r/4)·N+c；核每列取四个相邻行，尾部补零 | k；B[k] 放在 [7:0]，高位为零 |
| B 槽位 | 第一行在最高字节 | 有符号数先截取低字节，再符号扩展 |
| C 地址 | y·ceil(L/4)+floor(x/4) | r |
| C 槽位 | 相邻四列结果从 [127:96] 开始，末组补零 | C[r] 放 [31:0]，高 96 位清零 |
| RAM 边沿 | 下降沿读写，数据在该边沿后更新 | 上升沿同步读写，数据在该边沿后更新 |
| 板端容量 | 不适用该 GEMV 板端约束 | ceil(M/4)·K≤1024；B、C 均≤1024 字 |

不能在同一上升沿同时发出 GEMV 读请求并使用该请求的新数据。单 MAC 采用 READ→MAC 两拍安排。C 写入发生在 WRITE 上升沿，之后经过 DRAIN 才清 busy。

UINT8 卷积最坏和为 254²×255²=4,195,152,900，小于 UINT32 上限。GEMV 最大正和为 254×(−128)²=4,161,536，INT32 安全。两者均无偏置、无重定标、无饱和、无中间截断；Python 使用任意精度整数，RTL 使用 16 位有符号乘积并符号扩展到 32 位。以后引入任意 INT32 偏置时，必须重新证明累加范围。

## 本版单 MAC 的边沿定义

启动上升沿记 t0：锁存 M/K 并置 busy。随后每行依次 READ、MAC，重复 K 次，再 WRITE。最后一行 WRITE 后 DRAIN 一拍。按 t0 之后到 busy 拉低的上升沿计数：

`cycles = M·(2K+1)+1`，`MAC = MK`，`A_reads = B_reads = MK`，`C_writes = M`。

PE 本身 valid 连续时每拍接受一次乘加；系统因单拍同步 RAM 读安排，稳态每两拍执行一次 MAC。不能把 PE 的 II=1 当作整个 GEMV 的吞吐。每次 READ 从两个 32 位端口读取，共 8 字节；每次 WRITE 写 16 字节。此处统计 BRAM 端口流量，不是 UART、DDR 流量或功耗。

PE 的 first 在 valid=1 时覆盖旧部分和，last 使 done 在该边沿后有效一周期；valid=0 保持 sum、清 done。控制器仅在 MAC 状态给 valid，行间在首个 MAC 边沿替换旧和。异步复位会丢弃在途任务，已写入 RAM 的内容不会撤销。

官方说明：<https://nycu-caslab.github.io/AAML2026/labs/lab_3.html>。
