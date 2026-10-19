# gsMap 本机输入准备

工作目录为 `/hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap`。本文记录空间输入准备和 GWAS 质控转换；两个真实样本的完整 gsMap quick mode、空间 LDSC、Cauchy 和 HTML 报告也已完成验收，见 [真实数据验收](GSMAP_VALIDATION_20261018.md)。

## 空间数据和参考资源

`data/spatial/GSE241346_RAW.tar` 已解包到 `data/spatial/GSE241346/raw/`；`resources/gsMap_resource.tar.gz` 已解包到 `resources/gsMap_resource/`。原始归档保留，下载来源、版本和校验和见工作目录内的 `download_manifest.json`，解包清单见 `preparation/extraction.json`。

使用现有 `gsmap/scripts/02_prepare_GSE241346_h5ad_spagcn.py` 和固定环境 `atheromap_gsmap` 准备两份输入：

| 样本 | H5AD 文件名 | 保留点位 | 保留基因 | 修正后区域数 | 与参考矩阵共有基因 |
| --- | --- | ---: | ---: | ---: | ---: |
| GSM7727539 / sample1 | `GSE241346_sample1_gsmap_spagcn.h5ad` | 1,804 | 13,036 | 6 | 11,988 |
| GSM7727540 / sample2 | `GSE241346_sample2_gsmap_spagcn.h5ad` | 1,039 | 12,738 | 7 | 11,890 |

文件位于 `data/spatial/GSE241346/h5ad/`。`.X` 和 `layers["count"]` 保存原始整数计数；重复基因 symbol 按计数求和，QC、坐标和计数均与源文件独立核对。`obsm["spatial"]` 为原始 full-resolution 像素列、行；`obs["annotation"]` 为 SpaGCN 邻域修正后的区域编号，尚不代表人工病理区域或细胞类型。注释表和 QC 表位于 `data/spatial/GSE241346/metadata/`，示意图位于 `plots/GSE241346_spagcn/`。

原脚本设定为 spot 至少 100 counts、50 genes，基因至少在 3 个 spot 表达；SpaGCN 使用 histology=False、目标 7 类和随机种子 100。sample1 初始训练得到 7 类，原有 refine 步骤合并为 6 类，按实际输出保留。

## GWAS

原始文件为 `data/gwas/GCST007435.tsv.gz`；转换文件为 `data/gwas/GCST007435_gsmap.sumstats.gz`。使用 gsMap 1.73.8 官方 `format_sumstats`，输出 `SNP A1 A2 Z N Chr Pos`，保留 GRCh37 / 1-based 坐标及逐位点原始 N。Z 按官方规则由 P 值和 beta 符号计算，写出保留三位小数。完整参数保存在 `preparation/commands.json`。

原始 7,928,717 个位点，去除 1,228,753 个非 SNP 或方向不明确的组合、562,393 个 N < 32,290 的位点，官方转换保留 6,137,571 个位点；再按 LD panel 的坐标和等位基因一致性核对，剔除 303 个无匹配记录的 rsID（其中 4 个位于回归交集），最终保留 6,137,268 个位点。缺失值、非法 P 值、重复 rsID 和官方 MAF 过滤各删除 0 个。MAF 按官方实现 `min(FRQ, 1-FRQ) > 0.01` 的浮点计算执行。逐位点 N 不用整项研究样本数替换。官方转换结果另存为 `GCST007435_gsmap.official.sumstats.gz`，剔除明细和命令保存在 `preparation/`；最终文件与 LD panel 的共有 rsID 不再有坐标或等位基因不一致。

[GWAS Catalog 新版官方 API](https://www.ebi.ac.uk/gwas/rest/api/v2/studies/GCST007435) 和官方研究目录导出共同确认：性状为 Carotid plaque，Franceschini 等，2018，PMID 30510157，报告最多 21,540 例病例和 26,894 例对照。API 和目录匹配行保存在 `download_metadata/`。官方原始 YAML 的 `author_notes` 错配了一篇 2024 年人乳寡糖研究及其 QC；原文件原样保留，以 `preparation/GCST007435_provenance_review.json` 中的核实记录为准。

## 使用与核对

从项目根目录选择该工作目录，再运行现有环境入口；该环境变量须在后续 shell 中重新设置，或写入自己的本地配置：

```bash
export ATHEROMAP_GSMAP_WORK_DIR=/hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap
python 4_atheromap/tools/check_inputs.py --stage gsmap-run
```

本次不修改默认的旧工作目录配置。输入内容核对脚本为工作目录中的 `preparation/validate_inputs.py`，在 `atheromap_gsmap` 环境中运行，`--stage spatial` 核对空间源矩阵，`--stage gwas` 核对全量 GWAS 及 22 条染色体的 LD/baseline/weights/SNP-gene 资源。最终验收、运行环境、精确命令、SHA-256 和状态见该工作目录的 `preparation/`，入口为该目录的 `README.md`。

GRCh37 用于外部 GWAS 和匹配的 LD/GTF 资源；空间坐标为像素坐标。这一步不涉及患者 GRCh38 变异的坐标转换。两个样本的 gsMap 完整分析及报告验收已完成；根调度器接入尚待处理。
