# 两条分析流程

本文根据收到的源码整理运行关系，不代表本次已经重跑。以下路径均相对于 `atheromap/`，先在对应环境中运行 `source config/paths.local.env`。数据和输出位于配置的工作目录，不放在 Git 仓库中。

## GSE159677 · scDRS

使用本模块已配置的环境。以下原始命令需要先激活 scDRS 环境；也可以在每条分析命令前加 `bash tools/run_in_env.sh scdrs`：

```bash
source config/paths.local.env
conda activate "$ATHEROMAP_ENV_ROOT/atheromap_scdrs"
```

预处理通过 `ATHEROMAP_RSCRIPT` 调用独立 R 环境。安装及合成数据验证见 [ENVIRONMENTS.md](ENVIRONMENTS.md)。

### 输入与研究设置

原预处理脚本读取已聚合的 `matrix.mtx.gz`、`features.tsv.gz`、`barcodes.tsv.gz`。barcode 末尾的 1–6 被固定映射为 P1/P2/P3 及 H/D 条件；这不是任意六个样本都适用的通用规则。必须确认聚合过程和后缀映射与原数据一致。上传包没有聚合脚本或原始矩阵。

原脚本包含红细胞识别 / 去除、scDblFinder 双细胞检测、QC、scran size factor、acosh 变换、Harmony 及聚类。保留的 QC 常量为 counts 400–55000、genes 350–4000、线粒体比例阈值 0.10；具体边界判断以代码为准。这些是本项目设置，不是通用推荐阈值。

### 操作顺序

1. 原始矩阵准备好并核对样本后缀后，运行预处理脚本：

   ```bash
   python scdrs/scripts/overall_analysis/run_GSE159677_pre_scdrs_harmony.py
   ```

2. 将原来使用的 marker 表准备为 `$ATHEROMAP_SCDRS_WORK_DIR/metadata/final_report_marker_manual.tsv`，再运行注释建议脚本：

   ```bash
   python scdrs/scripts/overall_analysis/run_GSE159677_annotate_from_marker_tsv.py
   ```

3. 打开工作目录 `merged/GSE159677_annotation_review_table.csv`，人工复核每个 cluster，填写 `final_high_level_celltype_10`。脚本默认不以建议值替代空白最终注释。复核后执行：

   ```bash
   python scdrs/scripts/overall_analysis/run_GSE159677_finalize_annotation.py
   python scdrs/scripts/overall_analysis/run_GSE159677_prepare_scdrs.py
   ```

4. 准备与 GWAS 来源、基因映射及权重一致的 `.gs` 文件。本版没有包含该文件，也没有包含它的生成流程。默认位置 `scdrs_input/trait_gene_sets.gs`。运行前检查：

   ```bash
   python tools/check_inputs.py --stage scdrs-score
   scdrs compute-score --help
   scdrs perform-downstream --help
   ```

5. 在 scDRS 环境中计算分数和分组分析：

   ```bash
   bash scdrs/scripts/overall_analysis/run_GSE159677_scdrs_cli.sh \
     z_score "$ATHEROMAP_SCDRS_WORK_DIR/scdrs_input/trait_gene_sets.gs"
   python scdrs/scripts/overall_analysis/run_GSE159677_merge_scdrs_and_downstream.py --trait z_score
   ```

   **`z_score` 是原文件中使用的 trait 标签，不是已经核实的疾病名称。** 若实际 `.gs` 使用其他标签，要相应修改参数。若 `.gs` 包含多个 trait，评分可能为多个 trait 生成文件，Shell 的后续分组分析只选择传入的一个。

### 输入、输出与方法边界

| 步骤 | 主要输入 | 主要输出 |
| --- | --- | --- |
| 预处理 | 聚合的 10x 格式矩阵及固定样本映射 | `merged/GSE159677_filtered_batch_corrected.h5ad` |
| 注释 | 上一步 H5AD、人工 marker 表 | 自动建议 H5AD、review CSV、marker JSON |
| 人工复核落盘 | review CSV、自动建议 H5AD | `merged/GSE159677_harmony_highlevel_annotated_final.h5ad` |
| scDRS 准备 | 最终注释 H5AD 的 raw counts 和元信息 | `merged/GSE159677_for_scdrs_rawcount.h5ad`、covariates TSV |
| scDRS 计算 | raw-count H5AD、covariates、`.gs` | `scdrs_out/<trait>.score.gz`、`.full_score.gz`、分组结果 |
| 汇总 | 评分文件和细胞注释 | 合并 H5AD、统计 CSV、图 |

准备脚本按 gene symbol 合并重复基因，以 raw counts 作为 X；构建的协变量为 const、log1p(n_counts)、mt_frac。邻居图使用 `X_harmony`。该邻居图不能被描述为“scDRS 控制分数归一化本身采用 Harmony KNN”；评分校准与某些下游基于图的分析是不同步骤。

Shell 保留 `n_ctrl=1000`、输入不再过滤、使用 raw counts 的计算设置。`perform-downstream` 的三个路径已改成官方文档中的具名参数；其他参数保持原脚本行为。运行时仍应核对实际安装版本的帮助信息。

### 亚型与绘图

巨噬细胞和 VSMC 各目录包含 formal analysis、intermediate inspection、finalize labels、dotplot、violin 和 final panels。先查看其 `--help`（需要科学计算环境），再逐步运行；finalize 脚本中的 cluster 重命名是针对原运行的规则，重跑后 cluster 编号可能改变，必须复核。

多数 Python 下游默认读取工作目录的 `merged/` 平铺文件；两个 R 绘图脚本却读取 `merged/macrophage_subtype_analysis/` 或 `merged/vsmc_subtype_analysis/` 中的额外 CSV。收到的源码未包含 `*_celllevel_scores.csv` 的导出脚本，因此 R 绘图保留作可选脚本，不能直接串接成保证成功的一键流程。

细胞级 violin 检验和图上的星号不是患者级重复验证，也不能证明疾病因果性。本次仅整理代码，未重新审核统计推断。

## GSE241346 · gsMap

切换到 gsMap / SpaGCN 环境后再运行本节命令；也可以在每条分析命令前加 `bash tools/run_in_env.sh gsmap`：

```bash
source config/paths.local.env
conda activate "$ATHEROMAP_ENV_ROOT/atheromap_gsmap"
```

### 准备与运行

原脚本处理 `GSM7727539`（sample1）和 `GSM7727540`（sample2）。原始文件放到工作目录 `data/spatial/GSE241346/raw/`。如果只有 GEO 原始 tar 包，先把它放到 `data/spatial/GSE241346_RAW.tar`，再运行解包脚本；已经解包则跳过。

```bash
bash gsmap/scripts/01_unpack_GSE241346.sh
python tools/check_inputs.py --stage gsmap-prepare
python gsmap/scripts/02_prepare_GSE241346_h5ad_spagcn.py
```

准备脚本要求每个样本的 matrix、features、barcodes、tissue_positions_list、scalefactors_json、hires image 压缩文件。输出 H5AD 中保留 `layers['count']`、`obsm['spatial']` 和 `obs['annotation']`。

原代码设置 `histology=False`，SpaGCN 分区没有把组织图像像素作为模型输入；组织图像仍可用于后续展示。原目标分区数为 7，图上 domain 编号不能直接当成确定的解剖区域。

保留原参数：spot counts ≥100、spot genes ≥50、每基因至少 3 个 spots；SpaGCN p=0.5、lr=0.05、最大 200 epochs、tol=0.005、随机种子均为 100。实际分区数以输出为准。

准备格式化 GWAS `data/gwas/GCST007435_gsmap.sumstats.gz` 和 `resources/gsMap_resource/` 下的参考资源后：

```bash
python tools/check_inputs.py --stage gsmap-run
gsmap quick_mode --help
bash gsmap/scripts/03_gsmap_quick_mode_sample2.sh
bash gsmap/scripts/04_gsmap_quick_mode_sample1.sh
```

两个脚本各处理一个样本，原并行进程数为 10。本机已用 gsMap 官方 formatter 转换 GCST007435，保留 GRCh37 坐标和逐位点 N，完成等位基因、重复位点及原始数据对应检查；命令及准备好的工作目录见 [gsMap 输入说明](GSMAP_INPUTS.md)。

主要结果保存在 `results/gsmap_quick_mode/GSE241346/<sample>/`：latent H5AD、gene marker score、spot LDSC、Cauchy 分组结果以及 HTML report。

### 可选的结果检查

| 脚本 | 额外输入或注意点 |
| --- | --- |
| `review/plotting_code.py` | 使用原图、分区 H5AD 和 spot LDSC 绘图；不重新做主分析 |
| `review/check_spatial_markers.py` | 检查空间 marker 表达；依赖已准备的数据及图像 |
| `review/summarize_domains.py` | 还需两个样本的 cell2location posterior mean abundance CSV；本版未包含该上游流程 |
| `annotate_tissue_regions.py` | 手工设定位置的推测性组织区域示意，不能称为模型验证过的病理注释 |

review 脚本现在将结果写入工作目录下 `results/carotid_gsmap_validation/*_atheromap/`，不会写进 Git 源码目录。`summarize_domains.py` 会搜索同级 triptych 文件夹以复制已有图片，若保留多次历史输出，需要检查实际选中的来源。

## 数据入口与工具说明

- [GSE159677 数据入口](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE159677)
- [GSE241346 数据入口](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE241346)
- [GCST007435 数据入口](https://www.ebi.ac.uk/gwas/studies/GCST007435)
- [scDRS 官方 CLI 文档](https://github.com/martinjzhang/scDRS/blob/master/docs/reference_cli.rst)
- [scDRS 官方 CLI 源码](https://github.com/martinjzhang/scDRS/blob/master/bin/scdrs)

数据链接用于定位原始来源；本机已下载并核对 GSE241346、GCST007435 和 gsMap 资源，准备记录见 [gsMap 输入说明](GSMAP_INPUTS.md)；两个真实样本的完整 gsMap 关联、分组统计和 HTML 报告已验收，见 [真实数据验收](GSMAP_VALIDATION_20261018.md)。以上 workflow 以用户提交的脚本为依据，官方 CLI 文档用于核对参数写法，不代表与原服务器安装版本完全一致。
