# 导入AI Study与后续版本管理

日期：2026-10-21。项目名Tiny INT8 NPU Lab，目录`projects/tiny-int8-npu`。

## 导入方式与可验证内容

- 原工程HEAD为`9705c66`，采用不压缩历史的Git subtree导入。
- 24个原提交（含NYCU上游历史）原SHA、作者和时间不变，并作为主分支祖先保留。
- 636个原跟踪文件与原提交Git blob字节一致，包含测试、模型、配置和冻结证据；原文件未编辑。新增PROJECT.md和本migration目录作为本次整理。
- 原工作目录部分非封存文件存在CRLF检出转换；本次以原Git提交字节为准，列表记录在source_snapshot.json。已封存验收文件的原始SHA256不变。
- 13个学习里程碑以`tiny-int8-npu/study-*`命名空间重新建立标签，指向相同原提交；原标签对象SHA与映射见source_snapshot.json。新标签创建时间为本次导入时间，没有倒填历史。
- `tiny-int8-npu/import-step010`标记AI Study子目录布局的完成导入版本。
- 本地原`NYCU-Lab3`仓库保留，且课程上游origin未改动。后续以AI-study中的子项目为工作副本，避免误向课程仓库推送。

## 旧版本布局

旧里程碑指向原仓库提交，因此查看`tiny-int8-npu/study-step010`时文件位于根目录：

```powershell
git show tiny-int8-npu/study-step010:study/step010/README.md
```

主分支和新导入标签的路径为`projects/tiny-int8-npu/study/step010/README.md`。为保留原SHA，不重写历史给所有旧提交添加目录前缀。

## 后续开发

在AI-study仓库中的`projects/tiny-int8-npu`内修改、验证，再从AI-study根目录提交；每个已完成逻辑步骤本地提交，里程碑使用`tiny-int8-npu/`前缀标签。推送/发布/合并遵循用户授权范围。此次授权包含本工程导入与对应版本上传，不作为以后所有变更自动发布的授权。

原目录只作为历史副本；若确需继续在那里开发，先明确同步方式，不直接把旧仓库根目录推到AI-study/main。

## 导入核对

在子项目目录运行：

```powershell
python migration/verify_import.py
python study/step009/verify_step009.py --check
python study/step010/verify_har.py --check
```

verify_import.py仅检查原文件字节、原提交祖先关系和标签目标，不执行训练或仿真。原哈希、历史及标签映射为可复核证据，未把导入当作重新做过硬件验收。
