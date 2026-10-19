# AtheroMap · 颈动脉斑块分析

本模块整理颈动脉斑块的单细胞疾病相关性分析与空间遗传关联分析，用于团队代码交接及后续 bioagent 集成。

本模块包括 GSE159677 的 scDRS 和 GSE241346 的 gsMap。已补充独立依赖环境、安装与检查工具，并增加第三阶段 GDgpt 到 scDRS 的独立接口，接入本机已复核的 GSE159677 数据。本机 gsMap 空间 H5AD、格式化 GWAS 和参考资源已准备，并完成两个真实样本的空间关联、分组统计和 HTML 报告验收，见 [gsMap 输入说明](docs/GSMAP_INPUTS.md) 与 [真实数据验收](docs/GSMAP_VALIDATION_20261018.md)。跨机器复现及根调度器接入仍需单独处理。不包括冠状动脉、scPagwas 或其他疾病分析。

## GDgpt 续接与本机 scDRS 数据

本机数据位于 `../4_atheromap_data/GSE159677_scDRS`，注册记录见 [参考清单](config/GSE159677_scdrs.reference.json)。从项目根目录使用 `egene_pipeline.atheromap_adapter` 生成输入，再使用 `bash 4_atheromap/tools/run_scdrs.sh` 运行评分复用/重算及 Python/R 绘图。完整命令、契约及结果目录见 [SCDRS_INTEGRATION.md](docs/SCDRS_INTEGRATION.md)。

保留已完成的人工注释，使用独立副本适配编号文件和 AnnData 空值元数据，并自动导出 R 所需细胞级 CSV。当前 `z_score` 的疾病/GWAS 来源未确认，输出范围为外部队列参考背景，不修改患者原始变异分类。

## 本版包含什么

| 目录 | 内容 |
| --- | --- |
| `scdrs/scripts/overall_analysis/` | 单细胞预处理、Harmony、人工复核注释、scDRS 输入准备、评分、统计与绘图 |
| `scdrs/scripts/macrophage_subtype_analysis/` | 巨噬细胞亚型分析及绘图 |
| `scdrs/scripts/vsmc_subtype_analysis/` | 血管平滑肌细胞亚型分析及绘图 |
| `gsmap/scripts/` | GSE241346 数据解包、SpaGCN 分区、两个样本的 gsMap quick mode |
| `gsmap/scripts/review/` | 空间图、marker 检查、区域汇总；区域汇总另需 cell2location 结果 |
| `config/` | 工作目录配置示例 |
| `tools/` | 输入检查、环境管理、参考注册和 scDRS 运行入口 |
| `docs/` | 工作流、文件映射、来源记录、已知缺口、上传步骤和验证记录 |

原源码包中整理了 **34 个 Python / Shell / R 分析脚本**。表达矩阵与已有结果通过上述外部数据目录及校验清单引用，不随源码复制；GWAS 原始数据、转换结果及 LD 参考资源位于 `../4_atheromap_data/GSE241346_gsMap`，来源、命令和校验结果随数据保存。`docs/server_inventory.tsv` 是历史位置清单，当前 scDRS 使用注册清单。

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

依赖分为 `atheromap_scdrs`、`atheromap_gsmap`、`atheromap_r` 三个独立环境。环境定义、锁定文件、安装步骤和启动方式见 [环境说明](docs/ENVIRONMENTS.md)。在当前服务器已有环境时，直接检查及使用；在新机器上先安装：

```bash
# 新机器首次安装；已有环境时跳过这一行
bash tools/setup_environments.sh
python tools/check_environments.py --smoke
bash tools/run_in_env.sh scdrs scdrs compute-score --help
bash tools/run_in_env.sh gsmap gsmap quick_mode --help
```

Shell 和配置文件统一使用 LF 换行。环境验证使用合成数据，不替代真实数据的完整复现；原服务器历史环境仍未提供。

目录整理保留原有分析函数、QC 阈值及模型参数；修改了工作目录配置、gsMap 绘图输出位置和 Shell 运行接口。完整逐文件来源及 SHA256 见 [source_manifest.tsv](docs/source_manifest.tsv)。验证范围见 [验证记录](docs/VALIDATION.md)。

## 后续与 Agent 的接口

已有独立 scDRS 命令行与可校验输入输出清单，并已通过根目录 `run_pipeline.py --with-atheromap` 接入四阶段统一调度。当前入口消费已完成复核的数据；若重做预处理/聚类，仍须重新审核人工注释，不能直接套用旧 cluster 编号映射。根入口接入说明见 [项目统一说明](../README.md)。

第三方软件应引用其原项目并遵守对应许可。本次整理未为团队代码擅自指定新的开源许可证。
