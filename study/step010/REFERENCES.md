# 本步参考资料与采用范围

检索日期2026-10-20，使用ic-reference-library。参考文件只读，未执行其中脚本、复制参考RTL或修改原书。以下区分来源内容与本项目实现。

## 本地教材

1. [数字陀螺ASIC与AI计算架构技术教材Markdown源文](D:/学习资料/AI/数字陀螺ASIC与AI计算架构_教材源文与实验/IC_DSP_AI_Technical_Manual.md)：阅读§1.1–1.2和§16.1–16.4。资料强调单位/接口、训练验证测试分工，以及传感器相邻窗口相关、按设备/工况划分。**本项目采用**：受试者隔离，新增标准化和校准只拟合训练数据，冻结模型后再评估测试。本教材没有给出本步的18列、训练结果或RTL周期。
2. [全角陀螺从理论到产品与ASIC设计教材](D:/学习资料/资料/全角陀螺/全角陀螺从理论到产品与ASIC设计教材.md)：阅读§7.3（第284行起）及其验证层级表。资料区分代数、含误差闭环、定点RTL、板级、真器件与转台证据。**本项目采用**：明确活动分类与陀螺校准的目标不同；整数相符和分类准确率不能转述为零偏、噪声、温度补偿或闭环测量性能。

两个Markdown不使用虚构PDF页码；章节和源文件路径可直接定位。文件身份SHA256另存reference_sources.json。

## 数据源与分发

- 数据定义与当前许可页：[UCI HAR](https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones)，DOI [10.24432/C54S4K](https://doi.org/10.24432/C54S4K)。本次查看数据描述、受试者分割、传感器/窗口定义及CC BY 4.0标识。
- 实际下载：[Coursera公开分发ZIP](https://d396qusza40orc.cloudfront.net/getdata%2Fprojectfiles%2FUCI%20HAR%20Dataset.zip)。分发服务器标注Last-Modified 2014-01-15。它是传输副本，不将其视为新的数据作者或已验证等同于UCI当前ZIP。
- 随包README原引用：Davide Anguita, Alessandro Ghio, Luca Oneto, Xavier Parra and Jorge L. Reyes-Ortiz. *Human Activity Recognition on Smartphones using a Multiclass Hardware-Friendly Support Vector Machine*. IWAAL 2012, Vitoria-Gasteiz, Spain, Dec. 2012。
- 旧README保留禁止商业使用与出版引用要求；当前UCI页面另标[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。本地教学使用并保留两种说明，不抹去旧条款或扩大授权。

派生修改为选择18列、保留来源行/受试者、标签改成0起点、说明文本Latin-1转UTF-8；数值列字符串原样保留。没有再分发整个压缩包。字段、来源成员SHA256、派生文件SHA256见data/provenance.json。
