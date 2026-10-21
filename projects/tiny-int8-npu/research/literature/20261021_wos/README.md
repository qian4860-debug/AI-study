# AI Study文献专题：2026-10-21

## 完成范围与未完成项

已根据项目关键词定位20条系统、电路、量化、部署、IMU与陀螺文献候选，取得其中可公开获取的作者稿/出版社PDF，复用已有本地全文，生成CSV、RIS、BibTeX及离线分类索引，并接入现有资料库和ic-reference-library目录。实际数量见[collection_result.json](collection_result.json)。

**Web of Science站内检索尚未完成。** 用户指定的smart-search页面直接请求返回HTTP403；本轮工具集中没有computer-use所需的node_repl或浏览器自动化接口。已记录8组待执行检索式，但没有取得已登录WoS结果、命中数量或WoS收录证明。所有候选明确标注WoS未核验，不将出版社网页或Crossref记录当作WoS检索结果。

本次是首批定向收集，不是穷尽检索或系统综述。覆盖经典方法与直接相关应用，不能据此认定最新、被引最高或WoS全部收录。

## 本地资料库入口

- 主文献专题：`D:/学习资料/资料/AI_Study_文献库/20261021/index.html`。
- 既有资料库：`C:/Users/11725/Documents/ChatGPT/设计规范/reference_library/index.html`，已加入本专题并保留原285条记录。
- 既有库专题入口：`C:/Users/11725/Documents/ChatGPT/设计规范/reference_library/ai_study_20261021/index.html`。
- PDF位于主文献专题的`pdf/`；已有两篇陀螺论文保留原位置，仅登记路径和SHA256，不重复搬运。
- `references.ris`和`references.bib`可导入常见文献管理软件；它们是本项目生成的引用文件，不是WoS导出。

首页支持题名/作者/DOI搜索和方向筛选。主索引中的全文状态、版本、WoS状态与阅读状态分别保存。

## 分类与阅读顺序

| 方向 | 候选入口 | 对应项目问题 |
|---|---|---|
| 系统/架构 | Sze综述、Eyeriss/Eyeriss v2、Roofline、MCUNet | 数据移动、形状利用率、存储与计算约束 |
| 电路/FPGA | DSP-Packing、FINN、FINN-R、DP-VSA | 精确乘加、DSP映射、折叠、流水与资源 |
| 量化 | Jacob整数推理、HAWQ | 尺度、偏置、舍入、饱和和混合精度 |
| 编译/部署 | TVM、hls4ml、Hessian-aware codesign | 模型/布局/调度/硬件后端边界 |
| IMU | UCI HAR原始论文 | 真实数据和受试者划分 |
| 陀螺 | DenoiseIMU、Huang校准、温度补偿、STKF、Transformer补偿 | 传统基线、动态模型、单位、真值与独立轨迹 |

建议先读综述、Jacob、DSP-Packing、hls4ml和传统温度补偿，再与本项目具体计数/数值合同对照。FINN的二值网络、Eyeriss的CNN和Transformer时序补偿都不等同于当前两层INT8 MLP，应记录适用范围后再迁移方法。

本轮仅做PDF完整性、页数和首页题名核对，并查看少量首页预览；**未精读全部论文，也未复现实验或运行参考代码**。项目阅读问题是后续研究建议，不是资料对当前设计的背书。

## 书目与版本规则

- DOI题名通过Crossref出版社登记记录匹配；其主标题/副标题分字段时合并核对，避免将FINN等缩写误判为另一篇论文。
- arXiv作者稿、出版社公开PDF和已有本地文件分别标注。取得arXiv稿不等于取得正式出版版。
- 保留来源公开日期/卷期日期字段；例如Transformer论文的在线年与卷期年可能不同，不仅依据本地文件名判断年份。
- Roofline可能只能取得相关技术报告稿，若收录须标明技术报告与2009期刊论文题名/版本差异；不能无说明替换。
- 没有取得全文的项目保留“仅书目”，不把HTML错误页或不完整PDF计为全文。
- 本地PDF仅用于用户资料库；没有把第三方全文上传GitHub。公开可下载不等于获得任意再分发或商业使用许可。

## WoS后续核验

[queries.json](queries.json)保存8组TS检索式。可在WoS核心合集的高级检索/查询构建器运行；本轮未操作或验证当前smart-search页面的输入模式。

用户从已登录WoS导出RIS或“完整记录”纯文本后，可执行：

```powershell
python import_wos.py <WoS导出文件路径>
```

导入器以DOI优先、严格题名匹配辅助，要求存在`WOS:`入藏号。没有入藏号的普通RIS不会被标成WoS已核验。输出`wos_export_matches.json`供核对，保留原始403记录，不自动把整批候选都改成WoS命中。BibTeX文件可后续另行解析核对，当前导入器只支持RIS与WoS字段纯文本。

## 维护与复现

在本目录使用本机可用Python（含pypdf）：

```powershell
python collect.py                  # 按seeds.json收集公开来源
python collect.py --retry-missing  # 只补缺失全文，保留已取得记录
python build_library.py            # 重建引用/索引并注册到既有资料库
python verify_library.py           # 文件哈希、引用条数、资料库登记与导出匹配规则
```

作者/出版社网络可能改变；下载失败须保留原因，不关闭TLS证书验证、不绕过WoS认证/验证码/付费限制。Windows系统HTTPS客户端补取得的文件也记录客户端与来源。根目录`catalog.json`、`collection_result.json`保存本轮实际结果。

代码、检索式、公开书目、引用文件、来源及PDF哈希随AI-study本地Git管理并同步GitHub；PDF、分发方网页全文、登录信息与用户原始WoS批量导出不上传。
