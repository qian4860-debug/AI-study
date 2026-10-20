# 第008B步接口和流水合同

外部mlp2_top端口及配置合法性完全沿用第007步，直接编译旧top源码：K=1..256，H/O=1..8，uint16 multiplier=1..65535，shift=0..47，zero_point=0。signed24完整dot加INT32 bias扩展signed33；第一层ReLU；RNE ties-to-even和INT8饱和仅在层输出执行。

同步高有效reset优先取消全部控制、点积与量化在途项，保留RAM/bias；已接受的输出前缀不能撤回。busy期间不接受外部写入，仅内部隐藏转发可写非活动层x。host/fused桥接、输出ready/valid及最后握手后done的合同与第007步一致。

## FC tile和scalar边界

channel始终为当前tile第一行0/2/4/6。dot_tile_core启动时快照K和第二行是否有效；四个乘法器各有signed16 product和signed24 partial sum。第0/1部分和归约为第一行dot，第2/3归约为第二行dot。retired_elements使用10位，足以计两个K=256输出合计512个MAC。

FC在LAUNCH快照两行偏置。归约结果先输出第一行；其被唯一量化器接受后才输出第二行。两行可在连续两个边沿送入量化器，受背压时所有数值和index/last保持。奇数M的最后tile只有第一行，不产生填充输出。

最后一个scalar输出已送入量化器时，FC可以空闲，但顶层仍保持RUN1/RUN2直到最后量化值真正接受；因此不能在最后pre产生时提前切层。

## 地址与响应标签

逻辑host仍使用layer、kind和row*256+j，全部容量保持：x512B、W4096B、bias64B。

| 存储 | 物理bank | 银行内index |
|---|---|---|
| x | j%4 | layer*64+j//4 |
| W | (row%2)*2+j%2 | layer*512+(row//2)*128+j//2 |
| bias | 无银行 | layer*8+row |

每个tile同时读W四银行；第二行无效时只读低两个，奇数K末组只读对应K lane。x根据j组奇偶，只启用银行0/1或2/3，并向两输出广播；W的尾mask不能被当成x读取数。

x选择响应时使用`x_pair_q`，与同步RAM读取一起在请求边沿更新。实时rd_addr在接受请求后已指向下一组，直接用它选择返回数据会把银行对错一拍。fetch暂停时RAM数据和响应选择保持，但已在途乘积继续退休。

## 不变量与性能公式

- issued_groups−retired_groups等于rsp_mask非零与mul_mask非零两个有效组标志之和。
- 量化接受−量化输出等于三段valid之和；复位取消尚在途事务。
- 各层有效MAC为K×M，x读取为K×ceil(M/2)，W读取为K×M，发数组为ceil(K/2)×ceil(M/2)。
- no-stall且fused时，每层运行拍为`ceil(M/2)*(ceil(K/2)+5)+M+3`；两层再加2个FC启动状态拍。

这些公式在真实RTL指标上核验，包含当前控制及scalar序列化成本；不包含软件间隙，也不适用于任意外部停顿。

RAM_MODE=0/1/2仍分别为全BRAM/混合/全分布式，读延迟均一拍。编译期模型选择器的k4o1/k2o2是不同物理布局；运行时没有自动切换布局的硬件。
