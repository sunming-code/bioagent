# 不进入 Git 仓库的本地数据

本文件随 popgen agent 代码一起提交，说明哪些大文件留在本机、绝对路径是什么、以及它们在流水线里做什么。

仓库根目录在本机是符号链接：

`/home/wangy/RBM_popgen` → `/scratch/wangy/RBM_popgen`

下文一律写 `/scratch/wangy/RBM_popgen/...`。两边是同一份文件。

这些数据不上传，是因为体积超过 GitHub 单文件或仓库的合理范围，而且参考基因组、测序数据和 VCF 不应进公共代码库。代码通过下面的路径在运行时读取它们。换机器时按同名目录准备，或改脚本里的路径，不要把文件本体提交进去。

## 输入数据

| 绝对路径 | 是什么 | 在项目中的作用 |
|---|---|---|
| `/scratch/wangy/RBM_popgen/popgen_agent/data/fastq/HG002_exome_R1.fastq.gz` | GIAB HG002 外显子双端测序，read 1（约 12GB，与 R2 合计） | 步骤 1 的输入。Nextflow `main.nf` 把它比对到 GRCh38，得到 `patient.vcf` |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/fastq/HG002_exome_R2.fastq.gz` | 同上，read 2 | 与 R1 成对，供 BWA 比对 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa` | 人类参考基因组 GRCh38 主序列（约 3.1GB） | 步骤 1 的比对和变异检测参考。全流程坐标都对齐这一版本 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.fai` | samtools 序列索引 | 按区间取参考序列 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.dict` | GATK 序列字典 | HaplotypeCaller 要求与 fasta 同名的字典 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.amb` | BWA 索引 | 步骤 1 比对时 BWA 读取 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.ann` | BWA 索引 | 同上 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.bwt` | BWA 索引（约 3.0GB） | 同上 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.pac` | BWA 索引（约 766MB） | 同上 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/GRCh38.fa.sa` | BWA 索引（约 1.5GB） | 同上 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/ref_1000g_pruned.bed` | 1000 Genomes 3202 人、LD 剪枝后的 PLINK 基因型（约 229MB） | 步骤 2 的 PCA / ADMIXTURE 底库；步骤 3 按 checkpoint 位点从这里取参考基因型 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/ref_1000g_pruned.bim` | 上述底库的变异表（染色体、位置、REF/ALT） | 把病人 VCF 对齐到训练位点和频率位点 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/ref_1000g_pruned.fam` | 上述底库的个体表（3202 人） | 与人群标签对齐 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/ref_1000g_pruned.pop` | 每个个体的超群标签，供监督 ADMIXTURE | 步骤 2 把 K=5 固定成 AFR/EUR/EAS/SAS/AMR |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/sample_superpop.tsv` | 样本 ID 到亚群、超群的对照表 | 步骤 2 和步骤 3 给参考个体贴标签 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/backup_chr19/` | 早期只含 19 号染色体的底库备份 | 已被全基因组剪枝底库替换，只留作对照，当前推理不读它 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/reference/panel_1000g/tmp/` | 建底库时的临时文件 | 无后续用途 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/truth/HG002_GRCh38_v4.2.1_benchmark.vcf.gz` | GIAB HG002 在 GRCh38 上的 v4.2.1 金标准变异（约 162MB，含索引） | 步骤 1 的一致性评估：用 `bcftools isec` 计算精确率 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/truth/HG002_GRCh38_v4.2.1_benchmark.vcf.gz.tbi` | 金标准 VCF 的 tabix 索引 | 按区间读取金标准 |
| `/scratch/wangy/RBM_popgen/popgen_agent/data/truth/HG002_GRCh38_v4.2.1_benchmark.bed` | GIAB 高置信区间 | 一致性只在这个 BED 与常染色体的交集里计算 |

底库由 `/data/public/1000GP/` 生成，生成脚本是 `scripts/build_1000g_panel.sh`。脚本会把中间文件写到 `/scratch/wangy/RBM_popgen/panel_1000g_tmp`（约 605MB），该目录同样不上传。

## 集群上的公共参考（只读，不属于本仓库）

| 绝对路径 | 是什么 | 在项目中的作用 |
|---|---|---|
| `/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV/` | 1000 Genomes 高覆盖、已分相的 GRCh38 变异，3202 人、26 个亚群 | 构建 `ref_1000g_pruned` 的原始 VCF。分析阶段不再直接扫这套全量 VCF |
| `/data/public/1000GP/samples.info` | 样本 ID、亚群、性别 | 映射成 `sample_superpop.tsv` 和 `.pop`。`gnn_core.py` 在缺少本地标签表时会读这里 |

## 运行产物

| 绝对路径 | 是什么 | 在项目中的作用 |
|---|---|---|
| `/scratch/wangy/RBM_popgen/popgen_agent/work/` | Nextflow 工作目录（约 19GB） | 步骤 1 的中间 BAM：比对后的 `patient.sorted.bam`、去重后的 `patient.dedup.bam`，以及 calling 产生的 VCF。正式结果已复制到 `results/`，重跑比对质量时才需要回到这里 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/patient.vcf` | HG002 外显子调用得到的未压缩 VCF（约 140MB，913,922 个变异，GRCh38，contig 为 `chr*`） | 步骤 2 和步骤 3 的病人输入。交付给 e-Gene 的是它的压缩版 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/patient.vcf.gz` | 上一文件的 bgzip 压缩（约 22MB） | 证据包 `files.patient_vcf` 指向的病人 VCF |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/patient.vcf.gz.tbi` | 该 VCF 的 tabix 索引 | 按位点查询病人基因型 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/allele_freq.tsv` | 病人 VCF 里每个变异的匹配人群等位基因频率和全球频率（约 34MB，844,704 行） | 证据包的频率表。e-Gene 用 `CHROM+POS+REF+ALT` 与变异连接。查表人群是 EUR |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/delivery/allele_freq.tsv` | 上一文件在交付目录中的硬链接 | 与 `evidence_pack.json` 放在同一目录，供下游按相对路径读取 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/loo/` | 四个 1000G 个体的留一分析目录（约 2.2GB） | 步骤 2 自测：把 YRI/CEU/CHB/ITU 各一人从底库拿掉再投影，核对 PCA 和 ADMIXTURE 是否回到已知超群 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/concordance/` | HG002 调用结果与 GIAB 金标准的交集文件（约 5.8GB） | 步骤 1 的质量记录。文字结论在 `summary.md`（该 md 可以单独提交） |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/round1_chr19/` | 第一轮只做 19 号染色体时的分析和临时文件（约 147MB） | 早期调试，当前交付不使用 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/hg002_after_refhom/` | 用 BAM 把参考纯合位点补进 VCF 之后的一次分析（约 34MB） | 试验「频率表是否包含 0/0」。当前交付的频率表不含这些补点 |
| `/scratch/wangy/RBM_popgen/popgen_agent/results/gnn_tmp/` | 冻结推理时从病人 VCF 抽出的训练位点基因型（约 500KB） | `decide.py` 的临时目录，可随时重跑生成 |
| `/scratch/wangy/RBM_popgen/loo/` | `scripts/leave_one_out.sh` 的临时目录（约 1GB） | 留一过程中导出的单样本 VCF 和去掉该人的 plink 底库 |
| `/scratch/wangy/RBM_popgen/hg002_step2/` | 步骤 2 早期输出 | 已被 `popgen_agent/results/` 里的正式结果替代 |
| `/scratch/wangy/RBM_popgen/hg002_refhom/` | 补参考纯合之前的中间 VCF（约 38MB） | 仅用于和 `hg002_after_refhom` 对比 |
| `/scratch/wangy/RBM_popgen/hg002_after_refhom/` | 仓库根上的一份补点结果副本（约 297MB） | 与 `popgen_agent/results/hg002_after_refhom/` 同类，当前流水线不读 |

`results/` 里体积小的结论文件会单独提交，用来让 e-Gene 对字段，不替代上表里的 VCF 和频率表。它们是：`results/delivery/evidence_pack.json`、`results/delivery/INTERFACE.md`、`results/gnn_decision.json`、`results/gnn/cv_metrics.json`、`results/gnn/inductive_loo.tsv`、`results/concordance/summary.md`。

## 不进入本次 agent 合并的其它目录

| 绝对路径 | 是什么 | 在项目中的作用 |
|---|---|---|
| `/scratch/wangy/RBM_popgen/prototype/` | 早期原型（约 22GB），含旧的 Streamlit、Nextflow demo 和 MAGMA 示例 | 平台壳和旧链路的参考。当前 popgen agent 不调用它 |
| `/scratch/wangy/RBM_popgen/docs/legacy_docker_pipeline/` | 更早的 Docker 流水线说明和 Dockerfile | 记录旧部署方式。新的平台镜像还未从这里生成 |
| `/scratch/wangy/RBM_popgen/docs/00_previous_fsc_attempt.md` | 之前用 fastsimcoal2 估计连续人口参数的失败记录 | 研究背景，不是 agent 运行依赖 |
| `/scratch/wangy/RBM_popgen/docs/01_roadmap.md` | 2026-07-26 的人口史形状分类路线图 | 研究背景。已实现的步骤 3 是祖先分类，不是这份路线图里的拓扑分类 |
| `/scratch/wangy/RBM_popgen/docs/02_topology_shapes.md` | 候选人口史形状的说明 | 同上，agent 运行不读 |
