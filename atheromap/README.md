# AtheroMap · 颈动脉斑块分析

本模块整理颈动脉斑块的单细胞疾病相关性分析与空间遗传关联分析，用于团队代码交接及后续 bioagent 集成。

**当前为已有研究脚本的第一版整理包，尚未接入 Agent 工具调用，也未完成跨机器端到端复现。** 本版只包括 GSE159677 的 scDRS 和 GSE241346 的 gsMap；不包括冠状动脉、scPagwas 或其他疾病分析。

## 本版包含什么

| 目录 | 内容 |
| --- | --- |
| `scdrs/scripts/overall_analysis/` | 单细胞预处理、Harmony、人工复核注释、scDRS 输入准备、评分、统计与绘图 |
| `scdrs/scripts/macrophage_subtype_analysis/` | 巨噬细胞亚型分析及绘图 |
| `scdrs/scripts/vsmc_subtype_analysis/` | 血管平滑肌细胞亚型分析及绘图 |
| `gsmap/scripts/` | GSE241346 数据解包、SpaGCN 分区、两个样本的 gsMap quick mode |
| `gsmap/scripts/review/` | 空间图、marker 检查、区域汇总；区域汇总另需 cell2location 结果 |
| `config/` | 工作目录配置示例 |
| `tools/` | 只读的输入文件检查程序 |
| `docs/` | 工作流、文件映射、来源记录、已知缺口、上传步骤和验证记录 |

源码包中整理了 **34 个 Python / Shell / R 脚本**。没有附带表达矩阵、GWAS 原始数据、LD 参考资源、实际结果表或结果图。`docs/server_inventory.tsv` 仅记录服务器上的文件位置和大小，不能当作数据本身。

## 从哪里开始

1. 仅上传代码：阅读 [上传步骤](docs/UPLOAD.md)，将整个 `atheromap` 文件夹放到 `bioagent/agents/` 下。
2. 想运行分析：先阅读 [工作流](docs/WORKFLOWS.md) 和 [缺失文件与限制](docs/KNOWN_GAPS.md)。
3. 想接着使用旧结果：先核对 [文件对应表](docs/FILE_MAP.md)，不要直接把编号文件当成脚本所需的原文件名。

从 `atheromap/` 目录配置一个新的工作目录：

```bash
cp config/paths.example.env config/paths.local.env
# 编辑 config/paths.local.env 后再执行下一行
source config/paths.local.env
python tools/check_inputs.py --stage scdrs-score
python tools/check_inputs.py --stage gsmap-run
```

检查程序只报告文件是否存在，不运行分析、不修改文件，也不验证矩阵内容或科学结论。全新目录报告缺失是正常的，需要先准备输入。

分析结果写入配置中的工作目录。请为新运行使用单独目录；同一目录重复运行原脚本可能覆盖其中同名结果。

## 环境与可复现性

本次没有收到原服务器的环境锁定文件，因此没有编造依赖版本。依赖分组及环境导出方法见 [环境说明](docs/ENVIRONMENTS.md)。新机器需先确认 scDRS、gsMap、Scanpy、Harmony、SpaGCN、R / Bioconductor 之间的版本兼容性。

目录整理保留原有分析函数、QC 阈值及模型参数；修改了工作目录配置、gsMap 绘图输出位置和 Shell 运行接口。完整逐文件来源及 SHA256 见 [source_manifest.tsv](docs/source_manifest.tsv)。验证范围见 [验证记录](docs/VALIDATION.md)。

## 后续与 Agent 的接口

本版提供研究代码，不宣称已经形成自动分析 Agent。后续可在输入格式、参数、环境和复现结果稳定后，增加任务提交、进度查询、结果读取等工具函数。涉及人工注释的步骤需保留人工确认，不能直接当作全自动流程。

第三方软件应引用其原项目并遵守对应许可。本次整理未为团队代码擅自指定新的开源许可证。
