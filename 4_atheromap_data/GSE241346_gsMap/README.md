# gsMap 输入准备与真实样本验收（已完成）

工作目录：`/hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap`。空间输入准备与 GWAS 质控转换均已完成，独立内容校验通过；两个真实样本的完整 gsMap 分析、分组统计和 HTML 报告也已验收，见 [验收说明与报告入口](validation/gsmap_real_samples/README.md)。

| 样本 | 保留点位 | 保留基因 | SpaGCN 修正后区域数 |
| --- | ---: | ---: | ---: |
| sample1 / GSM7727539 | 1,804 | 13,036 | 6 |
| sample2 / GSM7727540 | 1,039 | 12,738 | 7 |

## 已准备的文件

- [sample1 H5AD](data/spatial/GSE241346/h5ad/GSE241346_sample1_gsmap_spagcn.h5ad)
- [sample2 H5AD](data/spatial/GSE241346/h5ad/GSE241346_sample2_gsmap_spagcn.h5ad)
- [格式化 GWAS](data/gwas/GCST007435_gsmap.sumstats.gz)
- [官方转换结果备份（剔除参考不一致位点之前）](data/gwas/GCST007435_gsmap.official.sumstats.gz)
- [解包后的 gsMap 参考资源](resources/gsMap_resource/)
- [完整输入清单与验收记录](preparation/inputs_manifest.json)、[文件 SHA-256 清单](preparation/prepared_files.json)、[校验和文本](preparation/PREPARED_SHA256SUMS)
- [精确运行命令](preparation/commands.json)、[运行环境](preparation/environment.json)
- [空间内容校验](preparation/validation_spatial.json)、[GWAS 与参考资源校验](preparation/validation_gwas.json)
- [LD 差异是否进入回归的核查](preparation/reference_alignment_audit.json)、[差异明细表](preparation/GCST007435_ld_reference_mismatches.tsv)
- [参考不一致位点剔除记录](preparation/reference_exclusions.json)、[被剔除的 GWAS 记录](preparation/GCST007435_excluded_from_final_sumstats.tsv)
- [GWAS 来源及元数据冲突说明](preparation/GCST007435_provenance_review.json)

空间 H5AD 的 `.X` 和 `layers["count"]` 为整数原始计数，`obsm["spatial"]` 为原始像素坐标，`obs["annotation"]` 为 SpaGCN 区域编号。逐项核对了原始 MTX、基因合并、QC 成员、barcode、坐标和计数值。注释/QC 表位于 `data/spatial/GSE241346/metadata/`，图位于 `plots/GSE241346_spagcn/`。原脚本 QC 和模型参数保留。

## GWAS 转换与参考匹配

原始 7,928,717 个位点，官方 formatter 保留 6,137,571 个，再剔除 303 个参考不一致位点，最终保留 6,137,268 个，输出列为 `SNP A1 A2 Z N Chr Pos`。按 gsMap 1.73.8 官方规则去除非 SNP/方向不明确的组合及 N < 32,290 的位点；没有缺失值、非法 P 值或重复 rsID。保留位点的 GRCh37 / 1-based 坐标、效应等位基因和逐位点 N 均与源文件一致。Z 由 P 和 beta 符号生成，按官方格式保留三位小数，最大核对误差 0.000499956。官方 gsMap 读取函数往返检查通过。

保留位点的 N 范围 32290–48435，中位数 47862，共 7,447 种取值。GWAS 与 baseline/weights 共有 1,045,692 个 rsID；22 条染色体参考文件均已核对。与 LD panel 共有 5,879,885 条记录，其中坐标不一致 0 条，考虑互换/互补后的等位基因不一致 0 条。

## 来源说明

原始归档和 GWAS 源文件保留，三个原始文件共 848,599,915 字节（约 0.85 GB），下载来源、原始 SHA-256 和完整性结果见 [download_manifest.json](download_manifest.json)。解包和准备后的文件（含官方转换备份）另占约 3.75 GB，合计约 4.60 GB，未计 Conda 环境。

注意事项：

- 官方 YAML 的 author_notes 错配了无关研究；已通过官方研究 API 和目录导出确认性状为 Carotid plaque，Franceschini 等，2018，PMID 30510157。原 YAML 保留。
- SpaGCN 注释为区域编号。原脚本邻域修正后 sample1 为 6 个区域，sample2 为 7 个区域。
- 官方整项研究样本数为 48,434，原始逐位点 N 最高为 48435；保留原始逐位点值，不按整项研究样本数改写。
- 已剔除 303 个无法与 LD panel 坐标和等位基因同时匹配的 rsID，其中 4 个位于回归交集。最终输入与 LD panel 的共有 rsID 没有坐标或等位基因不一致；官方转换备份和剔除明细均保留。

官方 API 和研究目录匹配行保存在 `download_metadata/`，确认 GCST007435 为 Carotid plaque，Franceschini 等，2018，PMID 30510157。

## 后续使用

从项目根目录设置工作目录；当前默认本地配置仍指向原先的空工作目录，因此使用本批输入时必须设置该变量：

```bash
export ATHEROMAP_GSMAP_WORK_DIR=/hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap
python 4_atheromap/tools/check_inputs.py --stage gsmap-run
```

两个真实样本的完整 gsMap quick mode 已运行并验收：空间点位分别完整覆盖 1,804 / 1,039 个，Cauchy 分组统计和 HTML 浏览器检查均通过。报告、完整 ZIP、数值验收和文件校验和见 [真实样本验收目录](validation/gsmap_real_samples/README.md)。根统一调度器接入尚待处理。
