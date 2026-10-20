# 第009步：统一模型部署描述，自动选择与验证计算核心

## 使用入口

仓库根目录PowerShell执行：

```powershell
& ./study/step009/run_all.ps1
```

这条命令依次执行：旧制品哈希检查、部署合同测试、读取固定JSON描述、选择核心、生成主机事务/物理布局/整数参考结果、实际Vivado RTL仿真、核对数值与周期、封存证据。需要Python标准库和Vivado仿真工具；不依赖NumPy或MATLAB。

`run_all.ps1 -Python <python.exe路径>`可指定Python。默认先找本机Codex附带Python，否则用PATH中的python。Vivado默认`D:/vivado/2025.1/Vivado/bin`，可用环境变量`VIVADO_BIN`指定其他安装目录。

## 本步完成范围

同一份部署描述同时决定模型、整数运算合同、RTL构建、参数事务、RAM布局、参考结果与预期周期。描述放在`deployments/`，测试输入放在`inputs/`，当前训练模型的512个测试输入继续引用已冻结的`../step006/test_dataset.json`。运行时不会重新生成或训练这些模型。

支持范围保持为两层全连接：K=1..256、H/O=1..8；第一层ReLU、第二层无激活；两层共享一个FC核心和一个量化器；两层内部融合传递激活。描述中未知字段、不支持的算子/量化合同、错误类型和越界数值均拒绝。

这是主机部署规划与真实RTL仿真的连接入口，尚未实现板卡驱动、AXI/PCIe传输、FPGA重配置或芯片内动态核心切换。4×1与2×2分别编译，源文件列表不会同时包含两个同名`fc_shared`模块。

## 统一描述

| 顶层字段 | 内容与约束 |
|---|---|
| schema / version | `nycu.deployment` / 整数1 |
| model | 完整嵌入两层权重、偏置、尺寸、激活和multiplier/shift；兼容第006步整数模型 |
| arithmetic | INT8输入/权重，INT32偏置，signed24点积，signed33加偏置，nearest-even舍入，INT8饱和，zero point=0，per-tensor |
| execution.core | `auto`、`step007_k4o1`或`step008b_k2o2` |
| execution.ram_mode | 整数0=全BRAM，1=混合，2=全distributed |
| execution.fused | 必须为JSON布尔true |

每层量化计算为`RNE(value * multiplier / 2^shift)`后饱和到[-128,127]；第一层在重定标前做ReLU。multiplier=1..65535，shift=0..47。当前描述表达已确定的整数缩放，不声称包含浮点模型校准、per-channel尺度或真实传感器物理单位。

`auto`沿用第008步已与实际RTL匹配的无停顿融合周期公式，取更快的构建；相同时选4×1。显式指定核心可用于对照。换构建必须先由调用者配置相应硬件，再上传参数。

## 部署包与加载

每次运行在`build/<名称>/`生成：

| 文件 | 用途 |
|---|---|
| package.json | 完整部署描述、实际选择、RTL源码哈希、身份和配置、参数命令、物理镜像及周期 |
| parameters.json | 顶层主机参数事务`[layer,kind,address,data]`；kind=1权重、2偏置 |
| physical_image.json | 稀疏银行镜像，供检查布局；未用位置为未指定状态 |
| vectors.json | 输入事务、输入银行位置、逐层dot/pre/激活/量化值/饱和与tie标志 |
| sources.json | 编译源文件清单与SHA256，路径相对study目录 |
| switched_package.json | 换模型场景使用的完整第二个模型 |
| task_catalog.json / mlp_cases.txt | 主机状态机产生的实际冷热/换模型/中断事务和RTL期望值 |
| scenario_flags.txt / tb_resident.v | 复位与上传中断控制、生成的测试台 |
| mlp_metrics.csv / mlp_events.csv | 实际仿真的逐任务周期与逐输出事件 |
| deployment_metrics.csv / report.json | 加载写入数、冷/热占用边沿和验证摘要 |

主机地址始终是逻辑ABI地址：权重`row*256+j`、偏置`row`、输入`j`。RTL接受写入后自行银行解码，不能把物理银行地址再次作为主机地址发送。

- 4×1权重bank=`j%4`，word=`layer*512+row*64+j//4`。
- 2×2权重bank=`(row%2)*2+j%2`，word=`layer*512+(row//2)*128+j//2`。
- 输入bank=`j%4`，word=`layer*64+j//4`。部署输入仅写第0层，融合隐藏输出由硬件写第1层。
- 偏置位置=`layer*8+row`；两种构建容量仍为4096B权重、512B输入及64B偏置。

镜像是审计旁路，实际仿真使用主机事务写RAM；不会用预装镜像跳过参数加载。

## 身份与驻留规则

`model_id`由完整整数模型计算；`build_id`由ABI、核心、RAM模式、算术合同及RTL源码SHA256计算；`deployment_id`绑定前两者。JSON字段顺序不影响身份，布尔与整数类型不能混同。

部署包在绑定前从内嵌描述重新编译并逐项核对，修改参数命令、镜像、配置、身份或RTL字节都会拒绝。部署会话保存包的副本。更换权重、偏置或量化参数后必须完整上传；换核心、RAM模式或RTL版本时使缓存失效。切换回旧构建也不复用过去的RAM身份。

`begin()`产生参数命令；每个命令只有在真实主机握手接受后才调用`acknowledge(command, True)`，未接受不推进。未完整确认不能`finish()`或发送输入。复位、掉电或上传中断后调用`invalidate()`，重新完整上传。连续同模型推理只写输入。这里的握手确认由仿真事务控制；未来板卡驱动需要接入同一合同。

## 结果与边界

见[验收报告](REPORT.md)、[机器验收结果](results.json)。当前16–8–2训练模型保持第008步的512测试输入和95.3125%准确率；它仍是合成分类任务，不能代表陀螺数据效果。

总占用边沿定义为`实际接受主机写入数 + 1个start边沿 + RTL计算周期`。复位、任务间空隙和额外驱动等待单独存在，未计入该指标；CSV不是实测板端时延。核心RTL未修改，因此本步不重新综合或宣称新的面积/时序改善。

## 自定义模型

以`deployments/trained_auto.json`为模板修改受支持模型与配置，输入JSON为`[{"x":[...]}]`，可选二分类label=0/1。输入必须是INT8且长度等于K。只生成部署包和参考向量：

```powershell
$py='C:/Users/11725/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $py study/step009/deployment.py study/step009/deployments/trained_auto.json --inputs study/step006/test_dataset.json --out study/step009/build/custom_export
```

完成实际选定RTL验证（使用独立输出目录）：

```powershell
& $py study/step009/verify_step009.py --deployment study/step009/deployments/trained_auto.json --inputs study/step006/test_dataset.json --out study/step009/build/custom_run
```

自定义运行保存自己的report；失败会写FAIL，不保留上一次的PASS状态。它不会替代四个固定案例的里程碑验收。

检查交付制品无需运行Vivado：

```powershell
& $py study/step009/verify_step009.py --check
```

代码、部署描述、输入、依赖与冻结证据纳入本地Git；仿真二进制和缓存不跟踪。后续可以在这一入口接入真实数据集，确定浮点与整数精度差异后再决定量化扩展。
