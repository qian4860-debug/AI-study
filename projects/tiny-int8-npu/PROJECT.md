# Tiny INT8 NPU Lab

**从单MAC到可解释、可测量、可修改的INT8神经网络计算核心。**

这是AI Study中的独立子项目，目录为`projects/tiny-int8-npu`。基于NYCU AAML2026 Lab3逐步实现并验证，包含源码、独立参考、训练与部署模型、输入、日志和哈希验收证据。

原课程入口保留在[README.md](README.md)，原版本索引在[VERSIONING.md](VERSIONING.md)。本文件是当前项目总入口。

## 已完成路线

| 阶段 | 内容 | 文档 |
|---|---|---|
| 001–003 | 单MAC、可配置整数点积、同步RAM与流水标签 | [初始学习入口](study/README.md) |
| 004–006 | 四路MAC、全连接/bias/ReLU、两层网络与INT8量化 | [第006步](study/step006/README.md) |
| 007 | 共享四路引擎、混合存储 | [第007步](study/step007/README.md) |
| 008A/B | 参数驻留、2×2 MAC分块及4×1形状回退 | [第008B步](study/step008b/README.md) |
| 009 | 统一模型描述、核心选择、加载数据与RTL一键验证 | [第009步](study/step009/README.md) |
| 010 | 真实IMU特征18–8–6小网络与全部测试输入验证 | [第010步](study/step010/README.md) |

第010步按受试者隔离训练/验证/测试；2947条测试输入、17682个整数输出分数与RTL完全对齐，INT8准确率81.7441%，计算105拍、热占用124拍。性能口径和数据来源边界见[验收报告](study/step010/REPORT.md)。

当前覆盖活动识别与RTL仿真；陀螺零偏/温度补偿、真实主机接口、布局布线和上板仍待完成。OOC综合时序或核心周期不等于板端频率或完整传感器处理时延。

## 使用

先进入本子项目目录，再运行PowerShell：

```powershell
& ./study/step009/run_all.ps1
& ./study/step010/run_all.ps1
```

使用Python、NumPy和Vivado；各步骤README提供具体运行时与`VIVADO_BIN`配置。Git中保留验收所需数据和证据，忽略仿真二进制、安装环境与下载缓存。

## 历史、来源与许可

所有原提交保留，13个旧学习标签已映射为`tiny-int8-npu/study-*`。旧标签对应导入前仓库根目录布局；新主分支使用`projects/tiny-int8-npu`布局。详见[迁移说明](migration/README.md)。

NYCU原文件及署名保持原样；没有给课程源码或第三方材料追加全局开源许可证。数据集、参考材料和本项目代码的适用条件分别保留。尤其HAR课程副本旧README的非商业/引用条款与UCI当前页面许可差异已在[第010步来源说明](study/step010/REFERENCES.md)记录，不推定商业许可。
