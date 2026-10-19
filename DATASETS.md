# 数据获取与 GitHub 上传清单

核查日期：**2026-10-19（Asia/Shanghai）**。依据为当前目录实际文件、已有来源清单与校验和、下载/构建代码，以及官方站点的访问检查。数据审计未删除本地数据或重跑计算；源码发布方式见仓库 README。

当前工作目录磁盘占用约 **226.03 GiB**。按现有 `.gitignore` 模拟收录，代码、小型模型、任务图谱、研究记录和来源说明合计约 **50 MiB**，不存在超过 100 MiB 的待收录文件。这个数值是文件内容总量，不是 Git 仓库压缩后的大小。

**大部分原始输入都有公开来源，可以不上传；GSE159677 的加工产物及剪枝后的 PLINK 面板需要单独安排复现或数据发布。** 公开可访问也不代表可以任意再分发，ANNOVAR 主程序和 dbNSFP 学术分支尤其需要遵守提供方条款。

## 1. 哪些数据不用上传

体积使用 GiB；目录包含索引、解压副本或加工结果时已注明。嵌套目录不能重复相加。精确字节数、732 个本地文件的清单见 [local_inventory.tsv](data_sources/local_inventory.tsv)，已有的固定来源和校验值见 [provenance.json](data_sources/provenance.json)。

| 本地位置 | 内容及版本 | 约占用 | 获取方式与处理结论 |
|---|---|---:|---|
| `1_popgen/data/1000GP/` | 1000 Genomes 高覆盖、3,202 人、GRCh38；`20220422_3202_phased_SNV_INDEL_SV`，本机 chr1–22 | 27.73 | [IGSR 官方发布目录](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/)；排除 VCF 和索引 |
| `1_popgen/data/fastq/` | 诺禾 HG002 WES，`HG002_novogene_wes_18g_rep1_R1/R2.fastq.gz` | 8.59 | 公开示例对象，[R1](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124639/HG002_novogene_wes_18g_rep1_R1.fq.gz)、[R2](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124722/HG002_novogene_wes_18g_rep1_R2.fq.gz)；两者 HEAD 均为 200，大小与来源记录一致；排除原文件，保留来源与 MD5。未确认独立的数据再分发许可 |
| `1_popgen/data/reference/`，扣除 `panel_1000g/` | Broad `hg38/v0/Homo_sapiens_assembly38.fasta`，本地改名 `GRCh38.fa`；含 BWA/FAI/字典 | 8.27 | [Broad 公共对象](https://storage.googleapis.com/gcp-public-data--broad-references/hg38/v0/Homo_sapiens_assembly38.fasta)；下载 FASTA 后重建索引，无需上传 |
| `1_popgen/data/reference/panel_1000g/` | 项目生成的 `ref_1000g_pruned.{bed,bim,fam,pop}`、标签 | 0.235 | 原始 1000G 公开，**这一组剪枝文件没有已确认的公开下载地址**；不放 Git，保留构建脚本、标签、个体顺序和文件哈希，见第 4 节 |
| `1_popgen/data/fastq_partial_1m/` | 两个调试用 FASTQ 子集 | 0.140 | 加工/抽样文件，排除；不是独立的公共数据集，本次未确认其精确抽样记录 |
| `2_egene/data/humandb/` | ANNOVAR 格式 hg38 注释库，详见下一张表 | 74.06 | [ANNOVAR 官方数据库说明](https://annovar.openbioinformatics.org/en/latest/user-guide/download/)，固定 URL、协议、体积和 ETag 在 `2_egene/config/dependencies.lock.json`；排除数据本体 |
| `2_egene/data/reference/` | UCSC `hg38.fa.gz` 解压后的 FASTA 和 FAI | 3.05 | [UCSC 官方文件](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz)，使用现有 `prepare_reference.py` 恢复 |
| `2_egene/data/disease/` | HPO `v2026-09-01`、HGNC `2026-10-06`，及生成的 `disease.sqlite` | 0.124 | `2_egene/config/disease_sources.lock.json` 保存四个源文件的固定 URL 和校验值；数据库由 `setup_disease_data.py` 构建，无需上传 |
| `2_egene/data/omim/mim2gene.txt` | OMIM 基因标识映射，约 1 MB | 0.001 | [官方公开映射端点](https://www.omim.org/static/omim/data/mim2gene.txt)；不是完整 OMIM 数据库。在线文件已更新，与本地快照不一致，见第 4 节 |
| `4_atheromap_data/GSE241346_gsMap/` | GSE241346 两个空间样本、GCST007435 GWAS、gsMap 资源；含解包、H5AD、分析输出 | 4.54 | [GEO sample1](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM7727539)、[sample2](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM7727540)、[GWAS 下载目录](https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics/GCST007001-GCST008000/GCST007435/)、[gsMap 官方资源说明](https://yanglab.westlake.edu.cn/gps_data/website_docs/html/step_by_step.html)；排除大文件，保留准备脚本与清单。gsMap 资源链接本次返回 403 |
| `4_atheromap_data/GSE159677_scDRS/` | 经过人工注释/亚型处理的 H5AD、scDRS 输入、权重、分数和小表 | 1.94 | [原始 GSE159677 公开](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE159677)，**本地加工后的整套文件不能直接从 GEO 下载**；大文件需要独立发布或补齐重建流程；小型人工注释和 marker 表保留 |

`humandb/` 中最大的几类数据如下。体积包含对应索引，均已排除；不能将这些不同历史版本自动替换成最新版后宣称复现相同结果。

| 文件/系列 | 约占用 | 已锁定的版本与说明 |
|---|---:|---|
| `hg38_dbnsfp42a.txt`、`.idx` | 44.80 GiB | dbNSFP 4.2a 学术分支；按历史包及上游分项许可使用，[当前获取说明](https://www.dbnsfp.org/download/)也有注册/许可要求 |
| `hg38_gnomad_genome.txt`、`.idx` | 16.82 GiB | ANNOVAR 的历史 `gnomad_genome` 协议；精确快照按 URL、ETag 和 SHA-256 识别，本次未确认其 gnomAD 上游发布号 |
| `hg38_avsnp147.txt`、`.idx` | 6.72 GiB | avsnp147 |
| `hg38_ALL.sites.2015_08.txt`、`.idx` | 3.28 GiB | 1000g2015aug；与 PopGen 的 3,202 人高覆盖 VCF 是不同资源 |
| 其余注释库 | 约 2.44 GiB | `refGene`/mRNA/版本表、`ensGene`/mRNA、`knownGene`/mRNA、`kgXref`、`esp6500siv2_all`、`clinvar_20210501`、`dbscsnv11`、`rmsk` |

`1_popgen/data/truth/` 目前只有 `.gitkeep`，没有实际 GIAB 金标准文件，不能将旧文档提到的体积算入现有数据。可选的 HG002 GRCh38 v4.2.1 benchmark 在现有 `1_popgen/scripts/fetch_data.sh` 中有官方来源。

## 2. 软件环境、计算产物也无需放 Git

这些内容并非可下载的原始公共数据集，上传时同样排除。排除只影响 Git 收录，不删除本机文件。

| 路径 | 磁盘占用约 GiB | 恢复方式 |
|---|---:|---|
| `1_popgen/.runtime/` | 15.67 | `1_popgen/scripts/setup_runtime.sh` 及 `envs/` |
| `2_egene/.runtime/` | 18.75 | 已有安装脚本；包括工具、下载压缩包和缓存 |
| `3_GDgpt/.runtime/`、`.venv/` | 4.03 | 依赖文件、本地部署说明；Neo4j 数据目录由保留的图谱 CSV 重建 |
| `1_popgen/work/` | 14.05 | Nextflow 中间 BAM/VCF 等，通过流程生成 |
| `runs/` | 41.52 | 多次运行的输出、副本、报告 ZIP 和矩阵，通过流程生成；复现仍依赖本说明列出的输入 |
| `1_popgen/results/`、`2_egene/results/` | 1.88 | 重新执行对应步骤 |
| `2_egene/vendor/` | 1.30 | 固定版本 InterVar 由安装脚本下载；ANNOVAR 主程序由使用者自行注册获取 |

**ANNOVAR 主程序不得随仓库再分发。** [官方注册页](https://www.openbioinformatics.org/annovar/annovar_download_form.php)列明下载及再分发条件。数据库的使用条件按各数据库原条款处理。

## 3. 下载与准备入口

以下命令供新使用者按需要选择执行；本次检查没有实际下载这些大文件。命令从仓库根目录执行，工具环境按各模块说明安装。下载后核对 `data_sources/provenance.json` 中的版本、大小和校验值。

### HG002：使用当前文件的确切来源

旧 `1_popgen/scripts/fetch_data.sh` 下载的是 **SRR2962669**，文件名为 `HG002_exome_R*.fastq.gz`；它不能恢复本机当前的诺禾 WES 文件。恢复当前文件应执行：

```bash
mkdir -p 1_popgen/data/fastq
curl --fail --location --continue-at - \
  'https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124639/HG002_novogene_wes_18g_rep1_R1.fq.gz' \
  -o 1_popgen/data/fastq/HG002_novogene_wes_18g_rep1_R1.fastq.gz
curl --fail --location --continue-at - \
  'https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124722/HG002_novogene_wes_18g_rep1_R2.fq.gz' \
  -o 1_popgen/data/fastq/HG002_novogene_wes_18g_rep1_R2.fastq.gz
printf '%s\n' \
  'e5b9d4718532b901b461d3424b0b215f  1_popgen/data/fastq/HG002_novogene_wes_18g_rep1_R1.fastq.gz' \
  'e46f53a0cf62fd8b9634a6a1493ed667  1_popgen/data/fastq/HG002_novogene_wes_18g_rep1_R2.fastq.gz' \
  | md5sum --check -
```

### PopGen 的 Broad 参考

```bash
mkdir -p 1_popgen/data/reference
curl --fail --location --continue-at - \
  'https://storage.googleapis.com/gcp-public-data--broad-references/hg38/v0/Homo_sapiens_assembly38.fasta' \
  -o 1_popgen/data/reference/GRCh38.fa
printf '%s\n' \
  '7ff134953dcca8c8997453bbb80b6b5e  1_popgen/data/reference/GRCh38.fa' \
  | md5sum --check -
1_popgen/.runtime/envs/popgen/bin/samtools faidx 1_popgen/data/reference/GRCh38.fa
1_popgen/.runtime/envs/popgen/bin/bwa index 1_popgen/data/reference/GRCh38.fa
```

同一 Broad 目录还提供 `Homo_sapiens_assembly38.fasta.fai` 和 `Homo_sapiens_assembly38.dict`；字典保存为 `1_popgen/data/reference/GRCh38.dict`。精确 SHA-256 和来源对象名已保存。

**两个模块的 `GRCh38.fa` 并非同一文件：PopGen 用 Broad，e-Gene 用 UCSC。** 即使都标 GRCh38，完整 contig 集和文件哈希也不同；不要仅凭文件名合并或替换。

### 1000G 原始 VCF 与剪枝面板

```bash
EGENE_1000G_BASE='https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage'
EGENE_1000G_DIR='1_popgen/data/1000GP/20220422_3202_phased_SNV_INDEL_SV'
mkdir -p "$EGENE_1000G_DIR"
for EGENE_CHR in {1..22}; do
  EGENE_VCF="1kGP_high_coverage_Illumina.chr${EGENE_CHR}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
  for EGENE_SUFFIX in '' '.tbi'; do
    curl --fail --location --continue-at - \
      "$EGENE_1000G_BASE/working/20220422_3202_phased_SNV_INDEL_SV/$EGENE_VCF$EGENE_SUFFIX" \
      -o "$EGENE_1000G_DIR/$EGENE_VCF$EGENE_SUFFIX"
  done
done
curl --fail --location \
  "$EGENE_1000G_BASE/20130606_g1k_3202_samples_ped_population.txt" \
  -o 1_popgen/data/1000GP/20130606_g1k_3202_samples_ped_population.txt
```

官方目录还包含 `20220804_manifest.txt`、README 和变更记录，下载时应一并对照。原始 pedigree 文件不是现有脚本直接使用的两列表 `samples.info`，需要按表头解析；本仓库保留了当前实际使用的 [sample_superpop.tsv](data_sources/popgen_panel/sample_superpop.tsv)、`.fam` 和 `.pop`，供核对 3,202 个个体和顺序。

剪枝构建入口是 `bash 1_popgen/scripts/build_1000g_panel.sh 1-22`。GitHub 发布已将实际分析、标签加载及构建/训练脚本改为仓库相对默认路径，可通过 `POPGEN_1000G_VCF_DIR`、`POPGEN_SAMPLES_INFO` 和 `PANEL_TMP` 覆盖；算法和剪枝参数保持原样。`samples.info` 的生成命令见根 README。环境安装器先做软件检查，数据准备后再运行不带 `--software-only` 的完整检查。

### e-Gene 注释、UCSC 参考和疾病库

```bash
# 将占位路径替换为使用者自行获取的授权 ANNOVAR 安装包。
python3 2_egene/scripts/setup_dependencies.py \
  --annovar-archive /绝对路径/annovar.latest.tar.gz --workers 4
python3 2_egene/scripts/setup_input_runtime.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/prepare_reference.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/setup_disease_data.py
```

来源锁分别为 `config/dependencies.lock.json` 和 `config/disease_sources.lock.json`。HPO/HGNC 的四个固定源文件本次 HEAD 均为 200；当前本地已下载快照的 SHA-256 已保存于来源记录。HPO 和 HGNC 的使用条款分别见 [HPO](https://hpo.jax.org/app/license)、[HGNC](https://www.genenames.org/about/license/)。

**当前安装入口有一个已确认的历史快照问题：** `mim2gene.txt` 在线大小为 **990,333** 字节，本地锁定快照为 **990,092** 字节。安装器有 ETag/体积检查，直接重新下载可能拒绝新版；不能保证上述命令现在可逐字节恢复旧安装。需要保留有权使用的旧快照，或显式更新锁并重新验证，不应静默替换。本次没有修改来源锁。

### gsMap：公开原始文件与准备步骤

三个原始下载合计 **848,599,915 字节**，固定 URL、大小和 SHA-256 在 [download_manifest.json](4_atheromap_data/GSE241346_gsMap/download_manifest.json)，下载布局在 [download_plan.json](4_atheromap_data/GSE241346_gsMap/download_plan.json)。

| 文件 | 恢复位置 | 下载地址 |
|---|---|---|
| `GSE241346_RAW.tar` | `data/spatial/` | [NCBI GEO](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE241nnn/GSE241346/suppl/GSE241346_RAW.tar) |
| `GCST007435.tsv.gz` | `data/gwas/` | [EMBL-EBI](https://ftp.ebi.ac.uk/pub/databases/gwas/summary_statistics/GCST007001-GCST008000/GCST007435/GCST007435.tsv.gz) |
| `gsMap_resource.tar.gz` | `resources/` | [gsMap 官方地址](https://yanglab.westlake.edu.cn/data/gsMap/gsMap_resource.tar.gz)；本次本机 HEAD 返回 403，需核实作者提供的可访问入口 |

表中路径相对于 `4_atheromap_data/GSE241346_gsMap/`。下载后在该目录运行 `sha256sum --check SHA256SUMS`。校验值来自 2026-10-18 的实收记录；本次没有重新下载大文件验证内容。

空间矩阵及 GWAS 加工可按保留的 [commands.json](4_atheromap_data/GSE241346_gsMap/preparation/commands.json) 重建：先解包参考资源和空间归档，再执行 `4_atheromap/gsmap/scripts/02_prepare_GSE241346_h5ad_spagcn.py`、gsMap 1.73.8 `format_sumstats`，随后运行 `preparation/audit_reference_alignment.py`、`filter_reference_mismatches.py` 和 `validate_inputs.py`。设置 `ATHEROMAP_GSMAP_WORK_DIR` 为实际工作目录，并将记录中的本机绝对路径替换成新路径。

本地最终 GWAS 比官方 formatter 输出额外排除了 303 个 LD 参考不匹配 rsID。只下载原 GWAS 或只运行 formatter 无法得到当前最终输入；相关代码、排除表及校验记录都保留在 Git 收录范围。GCST007435 的旧 YAML 注释有来源错配，项目的来源复核记录保留在 `preparation/GCST007435_provenance_review.json`。

## 4. 不能仅用公开下载替代的内容

### GSE159677 的项目加工数据

GEO 公开的是原始/作者提供的矩阵及样本说明。当前项目使用的下列文件不等同于 GEO 附件：人工注释后的 H5AD、巨噬细胞/VSMC 亚型 H5AD、协变量、`trait_gene_sets.gs`、scDRS 分数。

官方聚合矩阵可从 [GSE159677 聚合归档](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE159nnn/GSE159677/suppl/GSE159677_AGGREGATEMAPPED-tisCAR6samples_featurebcmatrixfiltered.tar.gz) 获取，HEAD 为 200，约 307.8 MB。但项目尚缺原矩阵到当前 40,563 个细胞对象的完整来源链，`z_score` 基因权重对应的 GWAS/疾病及生成方法也未确认，详见 [KNOWN_GAPS.md](4_atheromap/docs/KNOWN_GAPS.md)。

仓库保留人工复核表、cluster 映射、marker 和小型统计表；大 H5AD、分数、协变量和来源未确认的权重已排除。完整第四阶段的使用者需要另行获取这些加工文件：可把允许发布的文件保存到独立数据存储，提供稳定下载地址及 `4_atheromap/config/GSE159677_scdrs.reference.json` 中对应的 SHA-256；或者补齐从公开输入重建的完整流程。**目前还没有已核实的项目加工数据公共下载地址，不能宣称新 clone 已可完整复现 scDRS。**

### 剪枝面板与冻结模型的匹配

`ref_1000g_pruned.*` 是公开数据的衍生面板，约 241 MiB。重建必须保持 checkpoint 所用的位点和个体顺序。模型代码会检查这些匹配条件；重新运行剪枝不自动保证与现有 `model.pt` 完全相同。

本次已对五个面板文件重新计算 SHA-256，并保留三份小型标签/顺序表。可以用构建脚本重建并验证；若需直接复现当前冻结模型，应提供匹配面板的独立下载地址。当前没有确认这样的公共链接。

### 保留的小型项目资产

| 内容 | 处理 |
|---|---|
| `1_popgen/steps/03_gnn/model.pt`，约 6.32 MiB | 保留；这是项目冻结模型，不是应一概忽略的原始数据 |
| `3_GDgpt/kg_build/task_kg_output/`，节点/边 CSV 合计约 12.53 MiB | 保留，用于重新导入 Neo4j；[PrimeKG 全量上游有公开来源](https://zitniklab.hms.harvard.edu/projects/PrimeKG/)，当前目录没有全量 `kg.csv` 或 `magis_kg_edges.csv` |
| GDgpt 筛选/自制测试集、小型评估结果与 Open Targets/Reactome 查询快照 | 保留，避免丢失论文验证依据；查询快照不是完整上游数据库，当前查询也不保证返回相同内容；具体数据仍遵守原条款 |
| `PcQA_raw.json` | 排除上游原始文件；[上游仓库](https://github.com/yichun10/bioKGQA-KGT)公开，筛选脚本和 `pcqa_100.jsonl` 保留；本次未锁定原始文件的精确上游提交和下载路径 |

## 5. 本次已完成的上传准备与检查范围

根 `.gitignore` 已补齐环境、数据、中间产物和授权软件的排除规则；未使用通配的 `*.csv`、`*.json` 或 `*.pt` 来排除必要资产。也保留了原来各模块的忽略文件。

原先位于被忽略目录中的来源记录已复制到 `data_sources/provenance.json`，标签/顺序小表在 `data_sources/popgen_panel/`。原始数据和原始来源文件均留在本机。

文件选择审计使用临时 Git 元数据目录运行 `git ls-files --others --exclude-standard` 和 `git check-ignore`；GitHub 发布在独立克隆中替换主分支文件并保留旧提交历史，本地含数据的项目目录没有初始化 Git。结果及实际待收录文件见 [git_upload_preview.json](data_sources/git_upload_preview.json) 和 [git_upload_files.tsv](data_sources/git_upload_files.tsv)。

网络检查为 HTTP HEAD/官方页面核实，不是全部数据重新下载，也不是全流程复现验收。当前数据库的完整大文件没有再次计算哈希；清单明确区分历史哈希与本次重算的面板/模型/图谱哈希。当前仍需处理 gsMap 资源 403、OMIM 活动文件变化和加工数据发布缺口；PopGen 实际数据路径迁移已在源码发布时处理。

来源审计和忽略检查不能代替逐项数据再分发许可审查，也没有对所有保留的历史研究文档做完整凭据扫描。
