# 第006步接口与数值合同

所有事件发生在上升沿。reset是同步高有效，优先取消任务及量化寄存器；RAM内容保留。复位边沿不发生主机、隐藏或输出接收。已接收的输出前缀无法撤回。

## 任务与主机

| 信号 | 位宽/类型 | 合同 |
|---|---|---|
| start/start_ready | 1/1 | reset=0且IDLE时接受start；忙时start忽略；配置在接受边沿快照 |
| k_cfg,h_cfg,o_cfg | 9/4/4，无符号 | 合法K=1..256,H=1..8,O=1..8 |
| mult1_cfg,mult2_cfg | 各16，无符号 | 1..65535；不是有符号INT16 |
| shift1_cfg,shift2_cfg | 各6，无符号 | 0..47 |
| fused_cfg | 1 | 1：片内隐藏值写FC2输入；0：主机回写隐藏值 |
| cfg_error | 1，单拍 | IDLE接受非法配置时置位；不启动、不产生输出 |
| fetch_enable | 1 | 仅暂停新RAM请求，已在途乘积必须排空 |
| host_we/host_ready | 1/1 | reset=0且两者为1时写入；通常仅IDLE且start=0可写 |
| host_layer | 1 | 0=FC1，1=FC2 |
| host_kind | 2 | 0=x，1=权重，2=偏置；3非法 |
| host_addr | 11 | x按j；W按row*256+j；bias按row |
| host_data | signed32 | x/W只取低8位二补码；bias完整INT32 |

IDLE主机可装载保留容量内的数据（x256、W8×256、bias8），本次任务只读取配置形状内数据。未初始化RAM没有默认零，使用者须先加载所有会读的元素。主机转存模式下，WAIT_HOST只接受layer=1、kind=0、addr为下一连续下标的隐藏回写；H个完成之后，bridge_done=1且host_we=0才启动FC2。bridge_done过早忽略。片内模式无需主机重写。

## 流接口与状态

| 信号 | 位宽 | 合同 |
|---|---:|---|
| hidden_valid/hidden_commit | 各1 | hidden_commit明确指示隐藏值在本边沿接受。host模式由hidden_ready决定；fused模式由FC2写口决定，hidden_ready无效 |
| hidden_index/data | 3/signed8 | 0..H−1按序；饱和/tie标志对应同一元素 |
| out_valid/out_ready | 各1 | reset=0时两者为1完成输出接收 |
| out_index/data/last | 3/signed8/1 | 0..O−1按序，last仅O−1；不是softmax概率 |
| out_saturated/out_tie | 各1 | 对应最终缩位前舍入结果与半整数事件 |
| busy/done | 各1 | 从启动至最后输出接收保持busy；最后接收后done脉冲1拍 |

valid=1且消费者未就绪时，数据、index、last、饱和和tie保持。量化输出有一个弹性寄存器，允许同拍消费旧值、接受新值；非法量化输入消耗输入握手并发cfg_error，无输出。网络顶层已筛除非法配置，子模块错误在测试台中断言不出现。

## 位宽

INT8×INT8乘积signed16；K≤256的完整dot为signed24，范围[−4,161,536,4,194,304]；加INT32偏置使用signed33，理论范围[−2,151,645,184,2,151,677,951]。重定标模块接受完整signed33范围[−2^32,2^32−1]，乘正17位零扩展乘数，乘积signed50，恢复符号使用signed51临时值。只在层输出处饱和为INT8。

实数解释为 `real = scale*q`，本版zero_point固定0。bias的scale是输入scale×权重scale；重定标ratio近似或等于该乘积scale/输出scale。本次训练导出使用2的幂尺度，multiplier=1、shift1=8、shift2=7，无乘数近似误差；一般模块仍测试完整16位乘数。没有实现per-channel scale、非零zero_point、softmax、QAT或原生TVM/LLVM运行时。
