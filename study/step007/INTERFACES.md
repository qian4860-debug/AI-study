# 第007步：共享引擎接口与存储合同

数值合同与第006步相同：INT8输入/权重、signed24点积、INT32偏置、signed33的pre；第一层bias后ReLU，第二层无ReLU；重定标使用正uint16乘数、shift=0..47、RNE ties-to-even，最后饱和到INT8。唯一量化器直接复用第006步已验证的三段流水源码。

## 顶层不改变外部端口

| 接口 | 类型/范围 | 接受条件与行为 |
|---|---|---|
| start/start_ready | 单拍/电平 | reset=0、空闲时接受，K/H/O、量化参数、fused在该边沿快照；忙时忽略start |
| k_cfg/h_cfg/o_cfg | 9/4/4位 | K=1..256，H=1..8，O=1..8；非法配置仅发cfg_error，不启动 |
| mult1/2_cfg | uint16 | 1..65535；不是signed16 |
| shift1/2_cfg | uint6 | 0..47 |
| host_we/host_ready | 单拍/电平 | reset=0时两者为1才写；通常仅空闲且start=0接受 |
| host_layer | 1位 | 0=第一层，1=第二层；两层的存储持久保留，换层不需重新装载权重 |
| host_kind | 2位 | 0=x，1=W，2=bias，3非法 |
| host_addr | 11位 | x地址j<256；W为row*256+j；bias为row<8 |
| host_data | signed32 | x/W取低8位二补码；bias完整32位 |
| fetch_enable | 1位 | 暂停新RAM请求；在途响应、乘积、量化继续排空 |
| hidden_valid/hidden_commit | 1位 | RUN1输出；commit明确指示本边沿接受。host模式受hidden_ready控制；fused模式由内部写口控制 |
| hidden_index/data/saturated/tie | 3/signed8/1/1位 | 0..H−1顺序，标签与数值同停同走 |
| out_valid/out_ready | 1位 | reset=0且两者为1完成输出接收 |
| out_index/data/last/saturated/tie | 3/signed8/1/1/1位 | 0..O−1顺序；last仅最后元素；无softmax |
| busy/done/cfg_error | 1位 | 最终输出接收之前持续busy；done单拍；同步高有效reset优先取消任务 |

reset清空控制、点积与量化valid/tag，保留RAM和bias。不初始化RAM；必须先加载本次任务会读取的全部元素。已输出给外部的前缀不能撤回。

主机桥接模式：全部隐藏输出接受后进入WAIT_HOST；仅接受layer=1、kind=0、addr为下一连续下标的写入。写完H个值后，在host_we=0的边沿接受bridge_done；过早bridge_done或不连续地址被忽略。fused模式不需要该回写过程。

## 共享引擎如何避免覆盖

顶层只有一个 `fc_shared`、一个 `dot_banked_core(LANES=4)`、一个 `requant_i8`。当前层编号在FC启动时锁存；每层最后一个量化输出接受后才换层，绝不让换层信号修改尚在途的乘积或量化参数。

RUN1期间内部隐藏写入始终指向layer1的x区域；点积读取layer0。共享FC内部允许写“非当前层的x”，以保持隐藏产生与计算并行。顶层只把这条例外用于内部隐藏转发，忙时外部主机写入依然被拒绝。同地址读写冲突没有定义为可用操作，测试台断言不会发生。

## 地址映射：四个银行，两层地址区域

设原下标j，lane=j%4，group=j/4；输出行row=0..7，层号L=0/1。

| 存储 | 每银行深度 | 银行内地址 | 四银行总逻辑容量 |
|---|---:|---|---:|
| x | 128×8 | `{L, j[7:2]}`，即L*64+group | 512B |
| W | 1024×8 | `{L,row,j[7:2]}`，即L*512+row*64+group | 4096B |
| bias | 16×32，无银行 | `{L,row}` | 64B |

保留与原双引擎相同的完整逻辑容量和主机地址布局，没有把第二层只能读H≤8的限制用于暗中缩小比较容量。物理上两层共享同一银行的不同地址区域，因此可减少BRAM碎片。

## 存储选择仅为参数

| RAM_MODE | x实现 | W实现 |
|---:|---|---|
| 0 | BRAM | BRAM |
| 1，默认 | 分布式RAM | BRAM |
| 2 | 分布式RAM | 分布式RAM |

三种均为上升沿同步读，rd_en=0时输出保持；无存储复位。它们使用同一份控制、算术和测试输入，改变存储类型不会改变周期合同。
