# 服务器现有文件与脚本默认输入

只改工作目录不足以使用所有旧结果：服务器现有文件已经被编号并分组，原脚本仍使用平铺的长文件名。

下表的“服务器现有位置”以用户提供的 `GSE159677_scDRS/` 为根；“脚本默认位置”以配置的 `ATHEROMAP_SCDRS_WORK_DIR` 为根。2026-10-18 已读取总体注释、scDRS 输入、分数、两类最终亚型及复核/映射/细胞级 CSV，完成内容验收。当前实际消费的文件及哈希以 [参考清单](../config/GSE159677_scdrs.reference.json) 为准，执行时的映射写入 `atheromap_manifest.json` 的 `input_aliases`。下表中的预处理等非消费文件仍是历史路径提示。

| 服务器现有位置 | 脚本默认位置 |
| --- | --- |
| `merged/overall_analysis/06_filtered_batch_corrected.h5ad` | `merged/GSE159677_filtered_batch_corrected.h5ad` |
| `merged/overall_analysis/09_harmony_highlevel_auto_annotated.h5ad` | `merged/GSE159677_harmony_highlevel_auto_annotated.h5ad` |
| `merged/overall_analysis/10_annotation_review_table.csv` | `merged/GSE159677_annotation_review_table.csv` |
| `merged/overall_analysis/12_harmony_highlevel_annotated_final.h5ad` | `merged/GSE159677_harmony_highlevel_annotated_final.h5ad` |
| `merged/overall_analysis/14_for_scdrs_rawcount.h5ad` | `merged/GSE159677_for_scdrs_rawcount.h5ad` |
| `merged/overall_analysis/15_scdrs_z_score_merged.h5ad` | `merged/GSE159677_scdrs_z_score_merged.h5ad` |
| `metadata/final_report_marker_manual.tsv` | 同名相对路径 |
| `metadata/GSE159677_paper10_highlevel_markers.json` | 同名相对路径 |
| `metadata/GSE159677_scdrs_covariates.tsv` | 同名相对路径 |
| `scdrs_input/trait_gene_sets.gs` | 同名相对路径 |
| `scdrs_out/z_score.full_score.gz` | 同名相对路径 |
| `merged/macrophage_subtype_analysis/11_macrophage_subtyped_final.h5ad` | `merged/GSE159677_macrophage_subtyped_final_z_score.h5ad` |
| `merged/vsmc_subtype_analysis/09_vsmc_subtyped_final.h5ad` | `merged/GSE159677_vsmc_subtyped_final_z_score.h5ad` |
| `merged/macrophage_subtype_analysis/03_macrophage_leiden_wilcoxon_dge.csv` | `merged/GSE159677_macrophage_leiden_wilcoxon_dge_z_score.csv` |
| `merged/vsmc_subtype_analysis/05_vsmc_intermediate_top_markers.csv` | `merged/GSE159677_vsmc_intermediate_top_markers_z_score.csv` |

当前推荐通过 [scDRS 独立入口](SCDRS_INTEGRATION.md) 创建新工作目录，由入口复制已注册文件、处理格式兼容，并自动生成 R 所需 CSV 和统计路径。新版本数据仍须先确认细胞、基因、注释、trait 和 score 列，再创建新的注册清单；不应覆盖原始编号结果。

gsMap 的数据相对路径保留原结构，例如：

- `data/spatial/GSE241346/h5ad/GSE241346_sample1_gsmap_spagcn.h5ad`
- `data/spatial/GSE241346/h5ad/GSE241346_sample2_gsmap_spagcn.h5ad`
- `data/gwas/GCST007435_gsmap.sumstats.gz`
- `results/gsmap_quick_mode/GSE241346/`

因此 gsMap 从已有结果开始时主要需核对工作根目录、参考资源和数据来源。使用新的 gsMap 工作目录时，应自行准备所需输入；本包不会自动从旧服务器复制数据。

`server_inventory.tsv` 中的 `scdrs_existing/` 和 `gsmap_existing/` 是两个原数据根目录的占位名称，不是随包附带的文件夹。
