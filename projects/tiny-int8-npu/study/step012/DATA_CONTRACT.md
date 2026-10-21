# 陀螺数据合同 v1

本步接收原始角速度、温度和参考信息，不接受HAR归一化特征冒充物理测量。所有角速度在入口统一转换为rad/s。

## 文件与元数据

同一文件夹放置CSV和metadata.json。元数据结构见[模板](examples/metadata_template.json)，逐字段校验由calibration.py执行：

| 字段 | 合同 |
|---|---|
| schema/version | gyro.calibration.dataset / 整数1；未知顶层字段拒绝 |
| kind/source | synthetic或measured；必须说明采集/生成来源 |
| sample_rate_hz | 正的有限值，各批次同一标称采样率 |
| units | time=s、temperature=degC，angular_rate=rad/s或deg/s；同样适用于ref列 |
| frame | sensor_body，right，轴顺序x/y/z；其他坐标系需显式转换后导入 |
| reference | kind及非空description；必须区分合成真值、独立参考和静止零参考假设 |
| sessions | 每个device_id/session_id唯一，并声明train/validation/test与采集条件 |
| data_file/data_sha256 | CSV同级文件名及实际SHA256，不接收路径跳转 |

每个器件须有互不重名的train、validation、test批次。分批应由真实采集边界、时间段或温度循环确定，不能通过给相邻重叠窗口改名来证明独立性。程序核对声明与行归属，不能证明操作者提供的采集标记正确。

## CSV列（名称与顺序固定）

```text
timestamp_s,device_id,session_id,split,temperature_C,stationary,gx,gy,gz,ref_gx,ref_gy,ref_gz
```

| 列 | 类型/含义 |
|---|---|
| timestamp_s | 有限非负秒；可在不同批次重新从0计时，同批次必须严格递增 |
| device_id/session_id | 非空标识，与元数据声明逐字相同 |
| split | train、validation或test，与批次元数据相同 |
| temperature_C | 有限摄氏度，本入口合理性范围[-100,200]；不是传感器保证工作范围 |
| stationary | 仅0或1，来自实验状态标记，不由误差模型反推 |
| gx/gy/gz | 三轴原始角速度，单位由metadata声明 |
| ref_gx/ref_gy/ref_gz | 独立参考或合成真值；静止假设模式全部留空 |

每批至少2个样本；时间间隔与标称采样率允许5%相对抖动，缺样/跳时拒绝，不静默插值。

`reference.kind`约定：

- synthetic_ground_truth：仅用于kind=synthetic，三轴参考必须完整。
- independent：用于kind=measured，三轴参考必须完整且说明参考设备/方法。静止标记与参考角速度绝对值超过0.001rad/s时拒绝。
- stationary_zero_assumption：用于kind=measured，三轴ref列全部为空。仅stationary=1视为零参考；动态部分仍可补偿，但不计算无真值误差，也不跨缺参考区间积分。该假设不处理地球自转和静止标记错误。

## 拟合、选择与评价

1. 按器件独立拟合，不跨器件迁移系数。
2. 只用train批次的静止样本拟合原始测量减参考的误差。至少100个样本；温度设计矩阵必须满秩且条件数不超过1e6。
3. 常值零偏作为基线；一次、二次温度模型在validation的可评分样本上选择整体三轴RMSE最小者，平手取低阶。
4. 冻结系数和SHA256后评估test，不再重训；报告分轴、分批次与整体误差。
5. 超出训练静止样本温度范围拒绝外推。传感器归一化温度须在±1.5以内，超界拒绝，不能静默裁剪。

采用`z=(T-25)/20`，每轴模型为`bias=c0+c1*z+c2*z²`。低阶模型未用系数为0。

## 定点合同

| 数量 | 表示 |
|---|---|
| raw、c0/c1/c2、bias、corrected | signed32，24小数位；单位rad/s，范围[-128,128) |
| z | signed16，14小数位；模型主机入口限制±1.5，RTL按完整signed16数域验证 |
| 输入编码 | Python nearest-even将物理量乘2的相应小数位次方后取整；超signed32拒绝 |
| 乘积 | 精确signed48 |
| Horner | clip32(RNE(c2*z/2¹⁴)+c1)，再clip32(RNE(上一结果*z/2¹⁴)+c0) |
| 修正输出 | clip32(raw-bias)，任一中间或最终饱和置sticky标记 |

合成传感器样本要求不饱和，浮点bias与定点bias最大绝对差≤2e-6rad/s。边界向量允许并核对饱和。

## RTL接口

| 信号 | 方向 | 合同 |
|---|---|---|
| clk/reset | 输入 | 同步高有效复位，取消在途和未消费输出 |
| start/start_ready | 输入/输出 | 同时为1的时钟沿接受一个标量任务 |
| c0/c1/c2、z、raw、tag | 输入 | 接受任务时原子锁存，忙时变化和start不改变任务 |
| busy | 输出 | 计算在途；未消费输出由out_valid表示 |
| out_valid/out_ready | 输出/输入 | 同时为1的沿消费，背压时全部载荷保持 |
| out_bias/out_corrected | 输出 | signed32 Q24结果 |
| out_saturated/out_tag | 输出 | sticky饱和标记与原样返回的32位tag |

start接受至out_valid为5个时钟间隔；有未消费输出时不接受下一任务。输出被消费的同一沿不同时接收新任务。三轴分别发送；一个共享32×16乘法算子按Horner复用，不代表已映射为一个DSP。

仅实现加性零偏模型；标度因数、轴不正交、温度变化率、完整姿态积分、Allan分析及在线自适应不在当前合同内。
