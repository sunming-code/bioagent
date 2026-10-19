# e-Gene：从 PopGen 交付包到变异、疾病关联与完整报告

本目录实现完整的六步命令行流程：依赖安装、PopGen 输入适配、ANNOVAR 全量注释与候选初筛、InterVar ACMG2015 判级及 PopGen 频率证据整合、结合基因型和 HPO 表型的疾病关联排序，以及统一编排和最终报告。不包含网页和独立评测项目。

依赖安装完成后，统一入口为 `bash scripts/run_pipeline.sh`（或 `.runtime/venv/bin/python run.py`）。从 PopGen 交付包运行第二至第六步，也可从已完成步骤的清单继续；具体命令和交付文件见下文“第六步”。

## 固定配置

- 参考版本：GRCh38 / ANNOVAR `hg38`。
- InterVar：`2.2.2 20210727`，提交 `4801682d37982bb3e99b50392790878a568b42cd`。
- Python：`.runtime/venv/`，不修改服务器基础环境。
- 注释组合：沿用该版本源码内置的 ANNOVAR 协议，详见 `config/dependencies.lock.json`。这些是历史兼容数据，不代表最新版临床知识或后续全部 ClinGen 规范。
- OMIM `mim2gene.txt` 从官方公开端点下载；这是基因标识映射，不是基因—疾病关联表。其他 InterVar 辅助表保持上游原始快照，不冒充最新 OMIM 数据。
- `disorder_cutoff=0.005` 与固定源码的默认值一致，仅为 InterVar 兼容配置，不作为所有疾病通用的临床阈值。

## 安装

在 `2_egene/` 中执行：

```bash
python scripts/setup_dependencies.py
```

安装程序下载公开数据库，支持断点续传，保留压缩包并对解压后的文件计算 SHA-256。ANNOVAR 官方 hg38 目录快照保存在 `config/hg38_avdblist.snapshot.txt`，实收文件的来源、体积和校验值保存在 `data/dependency_manifest.json`。目录部分条目的体积和更新时间已落后于实际文件，因此锁文件分别保存目录信息和官方 HTTP HEAD 的实际体积、ETag、Last-Modified；下载使用实际快照核验，来源改变时拒绝继续混合下载。所有配置路径均自动生成为当前安装的绝对路径。

1000G 压缩包中的原始文件名是 `hg38_ALL.sites.2015_08.txt` 及其 `.idx`。安装保留该名称；ANNOVAR 的 `1000g2015aug_all` 协议会自动映射到它，InterVar 的数据库存在性检查则使用 `1000g2015aug` 组合名称。协议名与磁盘文件名不能混用。

ANNOVAR 主程序需从用户已获授权的来源安装。官方注册页面：
https://www.openbioinformatics.org/annovar/annovar_download_form.php

已有授权安装目录时：

```bash
python scripts/setup_dependencies.py --annovar-dir /绝对路径/annovar --skip-download
```

已有官方安装包时：

```bash
python scripts/setup_dependencies.py --annovar-archive /绝对路径/annovar.latest.tar.gz --skip-download
```

`--skip-download` 只跳过数据库下载，仍检查整体是否安装完整。提供目录时建立本地符号链接，不修改该目录；提供安装包时解压到 `vendor/annovar/`。不从第三方镜像获取主程序，不代填身份或提交注册表单。`vendor/` 和 `data/` 均不纳入版本管理。

## 安装检查

```bash
.runtime/venv/bin/python scripts/check_dependencies.py
bash scripts/intervar.sh --version
```

检查包括固定源码、Python/Perl、ANNOVAR Perl 语法、所有必需数据库、hg38 配置和真实辅助表加载。缺失时退出码为 `2`，完整时为 `0`；完整状态记录在 `.runtime/dependency_status.json`。需要重新核验全部数据库校验值时使用 `--verify-hashes`。

本机已安装用户提供的官方 ANNOVAR `2025-03-02` 安装包，压缩包 SHA-256 为 `d32e18747eb3eafdc4889397483fbd9d15ac8aeefda14ef17442ae54dd192f57`。各个 Perl 脚本的版本日期和 SHA-256 单独记录在 `data/software_manifest.json`；其脚本日期可能早于整包日期，这是官方包本身的情况。

较大的公共数据库使用已安装的 aria2 进行分段续传，继承现有网络代理配置。可用 `bash scripts/download_databases.sh` 执行带互斥锁和失败重试的完整下载；日志位于 `.runtime/logs/setup.log`，该次下载进程 PID 保存在 `.runtime/database_download.pid`，结束时写入 `.runtime/database_download.exitcode`。退出码 `0` 表示数据库及运行依赖检查全部通过，不能以进程已启动代替安装完成。

`scripts/intervar.sh` 在实际运行前检查依赖，禁止从该入口切换到 hg19 或另一份配置。正式样本输入和输出前缀需要由后续步骤提供；当前配置不默认运行上游 hg19 示例。

## 目录

```text
config/dependencies.lock.json       固定来源、版本、压缩体积和协议
config/intervar.hg38.ini            本机 InterVar 配置（自动生成）
config/runtime.json                本机运行环境路径（自动生成）
vendor/InterVar/                    固定的上游原始源码及辅助表
vendor/annovar/                     用户授权的主程序
data/humandb/                      hg38 ANNOVAR 注释数据库
data/omim/mim2gene.txt              官方公开基因标识映射
data/dependency_manifest.json       已下载数据的来源和 SHA-256
.runtime/downloads/                下载缓存及可续传的 .part 文件
.runtime/logs/                     安装日志
.runtime/dependency_status.json    实际依赖状态
```

## 第二步：PopGen 输入准备

新增依赖仅安装到已有的独立 Python venv，bcftools 复用本机 PopGen 环境，不修改其内容：

```bash
python scripts/setup_input_runtime.py
.runtime/venv/bin/python scripts/prepare_reference.py
```

安装程序将 bcftools 路径写入 `config/input.runtime.json`，实际 Python 版本和依赖版本写入 `envs/input.runtime.lock.json`。也可用 `setup_input_runtime.py --bcftools /绝对路径/bcftools` 显式指定工具。

参考准备程序从 UCSC 下载完整 `hg38.fa.gz`，校验官方发布的 MD5 `1c9dcaddfa41027f17cd8f7a82c7293b`，解压为 `data/reference/GRCh38.fa` 并建立 FAI。来源、FASTA SHA-256 和各 contig 长度记录在 `data/reference/reference_manifest.json`；压缩文件支持断点续传。已有参考时，可在输入准备命令中使用 `--reference /绝对路径/GRCh38.fa`，该文件需要现成的 `.fai`，contig 使用 `chr1` 等命名。

对参考等位基因正确的新交付包，默认严格模式会在 REF 不符时停止。当前 NA18526 验证包由 PLINK 导出，含临时参考等位基因标记，其中 1,140 条携带记录与真实 GRCh38 REF 不符。对这份验证包，显式排除这些记录后运行：

```bash
bash scripts/prepare_input.sh \
  --popgen-pack ../1_popgen/results/validation_current/delivery/evidence_pack.json \
  --ref-mismatch exclude \
  --outdir results/你的新任务目录
```

程序根据证据包的相对路径读取原始 VCF、频率表及已声明的索引和输入元数据，不猜测其他任务的文件。旧的 `1_popgen/results/delivery/` 若缺少配套 VCF/频率表，会报错。每次指定新输出目录，已有目录拒绝覆盖。

### 处理与筛选规则

- 校验 PopGen schema 1.0、样本 ID、记录数、参考版本及频率查表人群；频率表有重复键、孤立行或数量不符时拒绝继续。
- 只保留 GT 明确携带的 ALT；`0/0`、未携带 ALT、完整或部分缺失 GT、非单倍体/二倍体、未通过 FILTER/FT 的记录均在映射表记录排除原因。
- 默认保留有明确基因型但缺少 DP/GQ/AD/QUAL 的记录，并明确标记质量信息缺失；FILTER 为 `.` 表示未评估。不会自动设置临床质量阈值。
- 如显式设置 `--min-dp 20 --min-gq 20 --min-qual 30`，低于对应阈值或缺少对应字段的变异会被排除。这些数值仅展示参数用法，不是统一的临床标准。`--include-filtered` 可显式保留 FILTER/FT 失败记录，原始标记仍保留。
- 当前准备范围为常规染色体、性染色体和线粒体中有明确 A/C/G/T 序列的变异；符号 SV、星号等位基因、gVCF 占位符和其他 contig 记录在映射表中单列，不送入这一 ANNOVAR 输入。
- 先逐条核对携带记录的 REF，再使用 bcftools 严格核验、左对齐及多等位拆分。默认 `--ref-mismatch error` 会在核验后停止并给出完整错误列表；显式 `--ref-mismatch exclude` 将这些记录单列排除，原始 GT 和频率均保留在审计表，不自动交换 REF/ALT。标准化到同一位点的重复变异拒绝任意合并，需先处理原始重复记录。
- PopGen 频率先按原始 `CHROM+POS+REF+ALT` 连接，再通过映射转移到标准化坐标；缺失行标记 `no_row`，有行但匹配人群频率为空标记 `missing`，真正的 `0.0` 标记 `available`。空值均保留为空。
- `use_for_acmg_ba1_bs1` 和 `analysis_based.af_population` 原样传递；GNN 结果只保存为辅助祖源信息，不覆盖人群或改变频率使用权限。此步骤不产生 ACMG 证据或分类。
- 多等位拆分后的 GT 只表示单个 ALT 的剂量，其他 ALT 会映射为 0；原始 GT、相位、PS、FORMAT、SAMPLE 和质量字段保存在侧表中，后续家系判断必须读取原始信息。

### 输出契约

后续步骤从 `input_manifest.json` 读取结果，不重新解析工作目录：

| 文件 | 内容 |
|---|---|
| `normalized.vcf.gz`、`.tbi` | 已排序、参考核验和标准化的携带变异 |
| `patient.avinput` | 使用已安装的官方 `convert2annovar.pl` 生成，前 5 列为 ANNOVAR 坐标，后接 zygosity/QUAL/depth |
| `source_records.tsv` | 所有原始记录的 GT、完整 FORMAT/SAMPLE、QUAL/FILTER/INFO、DP/GQ/AD 和相位信息 |
| `variant_mapping.tsv` | 每个原始 ALT 的原始键、标准化键、ANNOVAR 键、是否保留及原因 |
| `patient_variants.tsv` | 保留变异的完整映射、原始质量、拆分后 AD 和 PopGen 频率 |
| `allele_freq.tsv` | 保留变异的标准化坐标、频率缺失状态及原始 BA1/BS1 使用权限 |
| `input_qc.json` | 输入、筛选和缺失字段计数、质量策略和数据限制 |
| `reference_mismatches.tsv` | 携带记录的 VCF REF 与真实 FASTA REF 不匹配明细 |
| `input_manifest.json` | schema 1.0、输入与输出 SHA-256、工具和参考版本、祖源与使用权限 |
| `status.json`、`logs/` | 执行完成或失败状态及工具日志 |

`variant_mapping.tsv` 用 `record_id + alt_index` 对应原始记录，`normalized_id` 对应标准化变异，`ANNOVAR_CHROM/START/END/REF/ALT` 用于连接下一步注释结果。插入/缺失的 ANNOVAR START 和 REF/ALT 不等同于原始 VCF POS 和锚定等位基因。

`popgen_evidence_pack.json` 仅为原始交付包快照，其内部路径仍属于原交付目录；应通过 `input_manifest.json` 的 `inputs` 获取原文件位置，不能把快照当成另一份独立 PopGen 交付包。

`contracts/popgen_evidence_pack.schema.json` 是本次接入冻结的上游 `1_popgen/contracts/evidence_pack.schema.json` 原样快照；准备结果按 `contracts/prepared_input.schema.json` 校验。输入文件处理中发生变化、外部工具失败或转换丢失变异时不会产生成功状态；失败目录和日志保留供排查。成功后删除工作文件，可用 `--keep-work` 保留。

没有保留变异时仍输出完整空表和可读的 VCF/索引，`input_qc.json` 中 `ready_for_annotation=false`。不能把空候选集合解释为排除了遗传病。

针对适配逻辑的本地检查（不构成临床性能评测）：

```bash
.runtime/venv/bin/python -m unittest discover -s tests -v
```

本机已对 `1_popgen/results/validation_current/delivery/evidence_pack.json` 完成输入准备，结果位于 `results/NA18526_prepared_ref_checked/`：10,000 条原始记录中，6,623 条未携带 ALT，显式排除 1,140 条 REF 不符记录后保留 2,237 个变异，均通过真实 GRCh38 REF 核验及官方 ANNOVAR 格式转换。所有原始质量字段缺失的事实仍明确保留。该运行只验证第二步输入适配，不代表临床判级性能。

## 第三步：ANNOVAR 批量注释和候选初筛

第三步仅使用已经安装的依赖，从第二步清单读取输入，不重新上传 VCF、不执行 InterVar 分类，也不调用 LLM：

```bash
bash scripts/annotate_variants.sh \
  --prepared-manifest results/NA18526_prepared_ref_checked/input_manifest.json \
  --outdir results/你的新注释任务目录 \
  --threads 4
```

程序先验证第二步成功状态及全部产物的 SHA-256，再运行固定的 11 个 ANNOVAR 协议：`refGene`、`esp6500siv2_all`、`1000g2015aug_all`、`avsnp147`、`dbnsfp42a`、`clinvar_20210501`、`gnomad_genome`、`dbscsnv11`、`rmsk`、`ensGene`、`knownGene`。保留三套基因模型的全部转录本结果，不使用 `-onetranscript`。ANNOVAR 的 `Chr/Start/End/Ref/Alt` 与第二步映射唯一连接，同时校验 zygosity/QUAL/depth 没有被替换。

### 筛选含义

`config/annotation_triage.json` 定义可追溯的初筛策略，可通过 `--policy` 传入同格式配置。本策略只决定后续分析优先级，所有记录的 `acmg_classification` 均为 `not_evaluated`。

默认频率筛选值为 `0.01`，用于把常见背景位点移出重点清单，不是统一的疾病阈值，也不构成 BA1/BS1/PM2：

- ClinVar 有致病/可能致病提交的变异保留，仍需核对审核状态、疾病和原始证据。
- ClinVar 分类冲突、固定 InterVar hg38 频率例外表中的位点，以及高影响/剪接注释与常见频率或可靠良性提交并存的位点，单列复核，不因频率直接排除。
- 风险因子、药物反应、低外显率等特定背景的 ClinVar 注释单列复核，不把这些标签当成普通孟德尔疾病的致病结论。
- 无冲突的 ClinVar 良性/可能良性且审核状态至少 2 星时降低优先级；高影响矛盾和例外位点优先保留。
- 其余位点结合独立 ANNOVAR 频率与功能注释分流：频率低于筛选值或频率未知、且有蛋白改变/剪接注释的位点进入候选；功能注释不完整的位点在频率未达到筛选值时进入复核。
- 非编码变异若有已知致病、分类冲突或例外证据仍保留；其余位点只降低初筛优先级，原始注释仍全部保存，后续可按病例重新检索。
- 频率使用 `gnomAD_genome_ALL`、`esp6500siv2_all`、`1000g2015aug_all` 的可用值；仅当第二步权限为 true 时加入 `matched_pop_AF`。不使用 GNN 改换人群，也不以 PopGen 全球 AF 绕过权限限制。多个来源不会被当成多条独立 ACMG 证据。
- 频率为空保持未知，预测分数为空保持缺失，不据此产生 PM2 或良性判断。

ClinVar 审核状态按[NCBI 官方定义](https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/)转换；频率例外表来自固定的 InterVar 上游快照，不能视为完整或最新的致病白名单。当前数据库仍为第一步锁定的历史兼容组合，特别是 ClinVar `20210501`，并非最新临床数据库。

### 输出文件

| 文件 | 内容 |
|---|---|
| `raw/annovar.hg38_multianno.txt` | 原始完整 ANNOVAR 表，保留兼容后续 InterVar 的字段 |
| `all_variants.tsv` | 全部变异的患者字段、完整 ANNOVAR 注释、筛选分流及理由 |
| `annotated_variants.jsonl` | 按患者数据、注释、筛选结果分别组织的结构化全量记录 |
| `candidate_variants.tsv` | 后续候选与需复核项，不是致病位点清单 |
| `priority_variants.tsv` | 已知致病提交、冲突、例外和高影响等优先复核子集，不强行凑固定数量 |
| `review_variants.tsv` | 分类冲突、特殊临床背景、注释矛盾或缺失等需复核记录 |
| `candidate.avinput` | 候选对应的 ANNOVAR 输入，保留原始 zygosity/QUAL/depth |
| `candidate.hg38_multianno.txt` | 候选对应的 ANNOVAR 注释，供后续 InterVar 复用 |
| `annotation_summary.json` | 各层数量、功能分布、ClinVar 分布、数据缺失及上游限制 |
| `annotation_manifest.json` | 输入、输出、数据库、工具和筛选策略的版本及校验信息 |
| `database_snapshot.json`、`triage_policy.json` | 本次实际使用的数据库和策略快照 |
| `status.json`、`execution.json`、`logs/annovar.log` | 状态、实际命令和工具日志 |

`candidate_variants.tsv` 包含 `triage_route=candidate` 和 `review`，`review_variants.tsv` 与其重叠，`priority_variants.tsv` 为优先复核子集；这些数量不应直接相加。所有降低优先级的变异仍位于全量表。候选数量允许为零，初筛不排除疾病。

后续从 `annotation_manifest.json` 读取结果并核验校验和。原始 ANNOVAR 表和候选 ANNOVAR 表都保留与固定 InterVar 版本兼容的原始列，第四步可直接复用，避免重复注释。基因型、相位及原始质量仍以患者侧表字段为准。

### 运行约束

- 每次使用新输出目录；缺失行、多余行、重复变异、表头不完整、患者映射或 Otherinfo 不一致均报错，不能以不完整结果标记成功。
- 默认核验 ANNOVAR 程序 SHA-256 和数据库文件体积，并记录安装时的数据库 SHA-256、本次文件时间和来源。需要重新读取约 75 GB 数据核验完整校验值时，添加 `--verify-database-hashes`。
- ANNOVAR 内部会执行 shell 命令。运行器在私有临时目录通过固定相对路径调用软件和数据库，输入及输出目录可含空格，用户路径不会被拼入其内部命令。
- 成功后清理临时文件；`--keep-work` 可保留。失败时保留日志和 `execution.json` 中记录的临时目录，不复制数据库。
- 空输入不启动 ANNOVAR，仍生成完整空表与成功清单。当前步骤未评估病例表型、遗传模式或疾病机制。

### 本机实际运行结果

`results/NA18526_annotated/` 已完成 2,237 个变异的全部 11 个协议注释，原始基因型、相位、质量与 PopGen 频率映射保持一致：

- 2,234 条因频率达到初筛值而降低优先级，另 2 条根据无冲突且满足审核状态要求的 ClinVar 良性提交降低优先级，共 2,236 条背景记录。
- 后续候选/复核表保留 1 条特殊背景记录：`GRIK4` 的 `rs1954787`，固定 ClinVar 快照标签为 `drug_response`。这是药物反应背景，不是本系统给出的致病结论。
- `priority_variants.tsv` 当前无数据行。当前没有满足本策略优先复核条件的记录；这不是排除疾病的结论，也没有执行 ACMG 判级。
- 这批数据由祖源剪枝面板抽样得到，主要是常见 SNP，且原始测序质量字段缺失；这些限制在 `annotation_summary.json` 中继续保留。不能由这份验证包推断真实患者的疾病候选分布。

原有输入适配与新增注释/筛选检查共 29 项通过，另对真实运行结果核对了 2,237 个原始记录到注释结果的逐字段映射、输出完整性、候选子集及所有产物校验和。工具给出的转录本 ORF 等警告保留在 `logs/annovar.log`，数据库来源和固定快照详见 `database_snapshot.json`。

## 第四步：InterVar 判级与 PopGen 频率证据整合

从第三步清单运行，直接复用已完成的 ANNOVAR 注释，不再注释或下载数据库：

```bash
bash scripts/classify_variants.sh \
  --annotation-manifest results/NA18526_annotated/annotation_manifest.json \
  --outdir results/你的新判级任务目录
```

默认 `--scope all` 对全部标准化携带变异执行 InterVar，避免把第三步的优先级筛选当成最终判级。添加 `--scope candidates` 时，仅处理第三步 `candidate + review` 集合；选择集合及数量写入输出清单。每次必须使用新的输出目录。空输入或空候选集正常输出空表，并明确 `classification_performed=false`。

### 运行与证据语义

- 入口核验第二、三步成功状态、样本、全部产物 SHA-256、患者侧表、ANNOVAR 坐标、完整注释和 Otherinfo 映射。固定 InterVar 提交及上游辅助表保持原样，运行前后记录并核验代码、配置和辅助表校验值。
- 原始运行使用未添加 PopGen 证据的 InterVar ACMG-AMP 2015；整合运行使用相同注释及生成的 `evidence_overrides.tsv`。两个运行都使用 `AVinput + --skip_annovar`，不经过会丢失患者质量信息的 VCF 转换路径。
- InterVar 2.2.2 的 `assign()` 把 BA1/PVS1 覆盖值保留成字符串，而 `classfy()` 进行整数比较，会导致 `BA1=1` 等覆盖虽然出现在文本中，却未参与分类。`egene/intervar_worker.py` 仅在 `classfy` 边界转成整数；不修改 vendor 文件、证据选择或组合规则。原始运行没有覆盖值时不受影响。结果解析后再次逐条检查覆盖值确实生效。
- 原始 InterVar 的独立频率来源仍按其历史规则运行，包括其 `disorder_cutoff=0.005`。这不是疾病专用阈值。PopGen 权限为 false 只阻止这份 PopGen 频率新增 BA1/BS1，不清除其他独立来源的原始证据；GNN、Q 最大档和全球 AF 均不用于改变查表人群或生成覆盖项。
- 默认 `config/acmg_frequency.json` 不设统一 PopGen BA1/BS1 阈值。因此上游权限为 true、频率非空，也不会自动新增这两项证据。缺少阈值、样本量依据或例外审核时，保留频率信息和具体未采用原因。
- 当全部独立外部频率列均为缺失值时，原始 InterVar 可能自动置 PM2=1；整合层以 `PM2=0` 撤回这项缺少覆盖依据的证据，审计状态是 `insufficient_coverage_evidence`，不表示已证明该变异不稀有。实际 AF=0 与缺失值分别保存，PopGen 未命中不会生成 PM2。
- 已有充分依据的 PopGen BA1/BS1 生效时，同时撤回同一变异背景下相矛盾的 PM2。固定 hg38 历史频率例外表优先，策略不能重新启用其中的 PopGen BA1/BS1。
- InterVar 会把一个位点按 `Gene.refGene` 拆成多个记录。ANNOVAR 的 `NONE,NONE` 或同一侧翼基因重复出现也保留，使用 `normalized_id + gene + gene_occurrence` 唯一标识。邻近基因标记并不证明疾病关联；不据此合并或选择一个疾病解释。
- 原始 GT、相位、质量字段、ClinVar 原始标签和第三步筛选结果继续保留。药物反应、风险及分类冲突保留复核标记，即使历史 InterVar 给出 Benign 也不删除相应背景。

### 提供有依据的 PopGen 频率阈值

通过 `--frequency-policy /绝对路径/策略.json` 提供策略。键必须是第二步标准化后的完整 `normalized_id`，不是 ANNOVAR indel 坐标或 rsID。每条策略需要明确的疾病/解释背景、阈值依据、参考人群适用性和有效样本量核对、例外审核记录。当前 PopGen AF 表没有 AC/AN，程序不会代替使用者确认这些依据。

以下仅展示文件格式；示例变异和阈值用于说明接口，不构成临床建议。确认开关为 false 时不会新增证据：

```json
{
  "schema_version": "1.0",
  "variants": {
    "GRCh38:chr1:123:A:G": {
      "context": "具体疾病标识和解释背景",
      "basis": "阈值规范、有效样本量及例外审核的可追溯依据",
      "population_adequacy_confirmed": false,
      "exceptions_reviewed": false,
      "ba1_threshold": 0.05,
      "bs1_threshold": 0.005
    }
  }
}
```

仅在上下游权限一致、匹配 AF 可用、确认开关均为 true、未命中历史例外时评估新增证据。BA1 使用严格 `AF > threshold`，BS1 使用 `AF >= threshold`。低于阈值不会删除来自其他数据库的原始证据。策略中不存在的变异键、非法频率、BS1 高于 BA1 的阈值以及不完整字段会报错。可只配置其中一项阈值。当前接口每个变异对应一个显式频率解释背景；疾病特异性多背景判级和家系证据留给后续疾病解释步骤。

### 第四步输出

| 文件 | 内容 |
|---|---|
| `acmg_results.tsv` | 患者 GT/质量/频率、基因上下文、原始分类、整合分类、28 个证据项及变化理由 |
| `acmg_results.jsonl` | 每条基因上下文的完整患者侧表、注释、筛选、两套证据、频率决策和数据标记 |
| `frequency_evidence.jsonl` | 每个选中变异的频率可用性、权限、阈值、采用/未采用原因和覆盖项 |
| `evidence_overrides.tsv` | 实际传入 InterVar 的五列证据文件；位置和等位基因采用 ANNOVAR 映射 |
| `raw/raw.intervar`、`raw/integrated.intervar` | 两次实际 InterVar 输出，未用自写组合算法代替 |
| `raw/*.ini`、`raw/*_worker.json` | 实际配置与 BA1/PVS1 类型修正次数 |
| `frequency_policy.json`、`intervar_snapshot.json` | 显式频率策略、InterVar/适配代码和辅助表版本与校验值 |
| `database_snapshot.json` | 第三步已使用的完整注释数据库快照 |
| `acmg_summary.json` | 变异数、基因上下文数、两套分类分布、证据变化和输入限制 |
| `acmg_manifest.json` | 后续步骤入口，包含本次输入、输出 SHA-256 和分类器版本 |
| `status.json`、`execution.json`、`logs/*.log` | 成功/失败状态、实际命令与工具日志 |

InterVar 自身有部分失败路径会以退出码 0 结束；封装层会检查实际输出文件、完整变异与基因上下文集合、证据格式和覆盖采用情况，失败时不写成功清单。临时路径与用户路径分离；失败保留日志和临时目录，成功清理工作文件，`--keep-work` 可保留。

本机 `results/NA18526_acmg/` 已对 2,237 个携带变异运行两次实际 InterVar，共 3,418 条基因上下文记录：3,302 条 Benign、116 条 Uncertain significance。38 个变异的所有独立外部频率注释均缺失，整合层撤回其 PM2（涉及 67 条基因上下文记录）；分类未因此改变。没有提供疾病专用 PopGen 阈值，未额外启用 PopGen BA1/BS1。GRIK4/rs1954787 的药物反应背景继续保留为复核信息。以上仅为历史规则在这份祖源面板验证数据上的实际输出，未进行疾病诊断或患病概率计算。

第四步运行时的本地封装版本为 `0.3.0`。第四步新增 18 项功能检查，连同输入准备和注释检查共 47 项通过；包含实际固定 InterVar 的 BA1/PVS1 覆盖类型修正、合法阈值生效、权限阻断、未知频率、indel 坐标、重复基因上下文、质量/相位保留、空集合及输入篡改拒绝。这些是实现正确性检查，不是独立临床性能评测。

## 第五步：疾病关联、遗传相容性与 HPO 表型排序

本步骤从第四步成功的 `acmg_manifest.json` 读取实际整合分类、患者侧表、基因上下文和原始注释，不重跑 ANNOVAR/InterVar，也不修改已有 ACMG 证据或分类。程序核验第四步文件校验和及所引用的第二、三步交付链。

### 疾病数据准备

```bash
.runtime/venv/bin/python scripts/setup_disease_data.py
```

本机已完成安装，不需要再下载。固定来源见 `config/disease_sources.lock.json`：

- HPO 发布包 `v2026-09-01` 的 `hp-international.obo`、`genes_to_disease.txt`、`phenotype.hpoa`；最后一个文件的内部注释版本为 `2026-09-02`，其 SHA-256 与固定发布资产一致。
- HGNC `2026-10-06` 季度归档，包含批准符号、旧符号、别名和 NCBI Gene 标识。
- 资源的官方地址、许可链接、体积和校验值保存在锁文件及 `data/disease/disease_database_manifest.json`。原始文件不修改，派生索引为同目录 `disease.sqlite`。
- 实际索引包含 20,482 个 HPO 条目、45,233 个 HGNC 基因、16,099 条基因—疾病关联和 286,651 条疾病注释；覆盖的 14,871 个疾病标识中有些仅有基因关联，没有表型注释。

下载使用发布资产 SHA-256；HGNC 归档同时核验固定 MD5 和体积并记录实收 SHA-256。重复安装核验已存在资源并复用索引；不同下载进程通过文件锁互斥。数据变更需要显式更新锁文件，不从滚动 `latest` 端点混合下载。

HPO 的基因—疾病映射包含 `MENDELIAN`、`POLYGENIC` 和 `UNKNOWN` 类型，其来源逐条保留。它不代表 ClinGen 临床有效性分级或完整的疾病致病机制审定。OMIM、ORPHA 标识保持独立，不凭名称合并；同一种临床疾病可能以不同来源标识出现。使用和再分发时遵守 [HPO 许可](https://hpo.jax.org/app/license)和 [HGNC 许可](https://www.genenames.org/about/license/)。

This analysis uses the Human Phenotype Ontology (HPO v2026-09-01) and HGNC (2026-10-06); source versions and attribution are retained in each run.

### 命令行运行

没有病例表型或家系资料时，直接运行：

```bash
bash scripts/prioritize_diseases.sh \
  --acmg-manifest results/NA18526_acmg/acmg_manifest.json \
  --outdir results/你的新疾病分析目录
```

有真实病例资料时，在同一命令中增加 `--case /绝对路径/case.json`。病例样本 ID 必须与第四步完全一致；每次使用新的输出目录，已有目录拒绝覆盖。

`examples/case.template.json` 是空模板，复制后填写真实样本 ID。以下仅展示字段格式，其中症状不是 NA18526 的真实资料：

```json
{
  "schema_version": "1.0",
  "sample_id": "REPLACE_WITH_ACTUAL_SAMPLE_ID",
  "sex": "unknown",
  "age_years": null,
  "onset_age_years": null,
  "clinical_description": "",
  "phenotypes": [
    {"id": "HP:0001250", "observed": true, "source_text": "实际病历中的原文"},
    {"label": "听力障碍", "observed": false}
  ],
  "family": {"relationships_confirmed": false, "genotypes": [], "phase": []}
}
```

`phenotypes` 必须明确提供 `observed`。支持 HPO ID、精确标签/EXACT 同义词及 `config/phenotype_aliases.json` 中的中文术语；自定义词典通过 `--phenotype-aliases` 指定。无唯一匹配的标签保留在 `unresolved_entries`，不会自动猜测。废弃 ID 仅在存在唯一替代时转换；未知 ID、肯定表型与其否定上位概念冲突时拒绝分析。原始条目和转换依据始终保存。

`clinical_description` 保留原文，当前不调用 LLM 从自由病历中猜测症状；否定、年龄和家族史需要结构化输入。年龄和发病时间保留供复核，不以未经校准的年龄阈值排除疾病。没有可解析的阳性表型时 `phenotype_score=null`，不会填 0 或伪造匹配率。

### 家系和相位资料

家系证据以已核验、同一 GRCh38 标准化等位基因的结构化观察输入；当前入口不直接导入父母原始 VCF。`family.genotypes` 的元素格式如下，坐标和内容仅为格式示例，实际必须引用第四步已处理的变异：

```json
{
  "normalized_id": "GRCh38:chr1:123:A:G",
  "mother": {"gt": "0/0", "callable": true, "basis": "填写真实的位点可判读核验依据", "dp": 35, "gq": 99},
  "father": {"gt": "0/1", "callable": true, "basis": "填写真实的位点可判读核验依据", "dp": 40, "gq": 99}
}
```

父母 `gt` 为这个标准化 REF/ALT 的基因型，`0` 是 REF，`1` 是该 ALT。`callable=true` 必须同时填写非空 `basis`；字段表示提交者已核验该位点可判读，不会仅凭文件中没有记录就生成 `0/0`。缺少一方、`callable=false` 或缺失调用均保留未知。普通杂合新发观察与纯合子/父母参考调用的不相容情况分开记录，不自动赋予 PS2/PM6 等 ACMG 项。

可在 `family.phase` 中补充已核验的相位，每项包含 `variant_ids`（两个不同标准化 ID）、`relation`（`cis` 或 `trans`）和非空 `basis`。程序同时读取原始 GT、ALT 序号、相位标记和 PS；只有同一相位块才比较不同记录的单倍型。同一原始 `1/2` 记录拆出的两个 ALT 可以识别为反式。亲缘已确认且父母位点均可判读时，可使用双亲来源辅助判断。相位声明冲突会报错。

### 候选形成与排序含义

- 所有第四步基因上下文均连接 HGNC/HPO 并写入关联审计表；旧符号只在别名映射唯一时更新，歧义别名不猜测。
- 候选要求变异与该基因有重叠的功能注释。ANNOVAR 的 intergenic/upstream/downstream 邻近基因信息仅作关联审计，不直接解释为该变异影响该基因。
- Benign/Likely benign、药物反应或其他特殊临床背景及非孟德尔映射不进入本步骤的孟德尔疾病候选。它们仍完整保留在关联表中。
- Pathogenic/Likely pathogenic 会重新检查疾病关联，不因第三步 background 路由丢弃。VUS 默认沿用第三步 candidate/review 筛选；可显式添加 `--include-background-vus` 探索重叠基因的 background VUS，结果标记探索来源并继续保留 VUS 身份。
- 单个基因—疾病组合只按标准化 ID 计数变异，不将重复基因上下文或多个转录本算成多个等位基因。
- 常染色体隐性疾病区分纯合、已知反式、相位未知、仅顺式和单个杂合等情况。只发现一个 P/LP 等位基因时输出携带者可能性或第二等位基因未检出，不能建立隐性疾病诊断。
- 显性和 X/Y 连锁模型检查相应染色体/倍性及必要的性别信息；X 染色体 PAR 区域保留专用背景待复核，边界采用 [Ensembl GRCh38 PAR 定义](https://jun2026.archive.ensembl.org/info/genome/genebuild/human_PARS.html)。线粒体、印记、寡基因、嵌合等复杂背景明确要求进一步核验，不套用普通单基因模型。
- 优先级先看 `priority_band`：0 为 P/LP 与完整相容基因型，1 为 P/LP 隐性组合相位未知，2 为相容基因型中仍含 VUS，3 为含 VUS 且隐性相位未知，4 为单个隐性等位基因/仅顺式，5 为遗传资料未知或复杂背景。同一档按表型相似度、变异支持和稳定标识排序。
- 有阳性表型时，使用 HPO is_a 层次、疾病语料信息量与 Lin 对称 best-match average 计算相似度；遗传模式条目不混入症状匹配。显式否定表型及疾病排除注释产生可追溯的冲突项，默认按策略中的 0.25 系数降低相似度；未填写症状不会被当成阴性。
- `variant_support` 采用固定 P=1、LP=0.85、VUS=0.2；隐性组合按所需等位基因中较弱者计算。这些值和表型相似度均是复核排序指标，不是个体患病概率，也不改变 ACMG 分类。机制、外显率及原始测序质量仍需要复核。

### 第五步输出

| 文件 | 内容 |
|---|---|
| `variant_disease_links.jsonl`、`.tsv` | 全部变异—基因上下文的符号解析、疾病关联、来源、进入/排除候选的原因 |
| `disease_candidates.json`、`.jsonl` | 每个基因—疾病候选的变异、原始分类、遗传相容性、相位/家系观察、表型匹配与冲突 |
| `disease_candidates.tsv` | 可直接查看的候选排序和支持变异摘要 |
| `carrier_findings.tsv` | 具有携带者可能性的候选视图，为主候选表子集，数量不相加 |
| `case.json`、`phenotypes.normalized.json` | 实际病例快照、HPO 标准化、否定及无法解析的条目 |
| `disease_policy.json`、`disease_database_snapshot.json` | 实际筛选排序策略和数据库来源/版本 |
| `disease_summary.json` | 计数、关联/筛选状态、上游质量限制及本步骤限制 |
| `disease_manifest.json` | 第五步交付入口，记录输入/输出 SHA-256、模块版本及病例/策略来源 |
| `status.json` | 本步骤的成功/失败状态 |

本机 `results/NA18526_diseases/` 已承接第四步的 2,237 个变异和 3,418 条基因上下文。697 条上下文有疾病关联，共保留 2,162 条基因—疾病来源记录。默认候选为 0：第四步没有 P/LP，116 条 VUS 上下文均为第三步 background，唯一特殊临床背景为药物反应。没有提供真实表型，表型状态明确为未评估；这不排除疾病。

## 第六步：统一命令行与完整报告交付

### 从 PopGen 一条命令运行

本机依赖和疾病数据库已安装。对新的、参考等位基因正确的 PopGen 交付包：

```bash
cd /hpc2hdd/home/msun663/e-gene/2_egene
bash scripts/run_pipeline.sh \
  --popgen-pack /绝对路径/delivery/evidence_pack.json \
  --outdir results/你的新任务目录
```

当前 NA18526 验证包存在已知 REF 不匹配记录，沿用前面已经采用的显式排除策略：

```bash
bash scripts/run_pipeline.sh \
  --popgen-pack ../1_popgen/results/validation_current/delivery/evidence_pack.json \
  --ref-mismatch exclude \
  --threads 4 \
  --outdir results/新的完整分析目录
```

有真实病例资料时增加 `--case /绝对路径/case.json`，格式仍使用 `examples/case.template.json`。默认严格核验 REF、使用全部保留变异进行 InterVar 判级，未知信息保持未知；不会自动改变前面各步的筛选含义。

### 从已完成步骤继续

五个入口参数互斥，根据指定清单仅运行其后的步骤：

| 入口 | 后续执行 |
|---|---|
| `--popgen-pack` | 输入准备 → 注释 → 判级 → 疾病分析 → 报告 |
| `--prepared-manifest` | 注释 → 判级 → 疾病分析 → 报告 |
| `--annotation-manifest` | 判级 → 疾病分析 → 报告 |
| `--acmg-manifest` | 疾病分析 → 报告 |
| `--disease-manifest` | 报告 |

例如，直接把已有第五步结果转成可读报告：

```bash
bash scripts/run_pipeline.sh \
  --disease-manifest results/NA18526_diseases/disease_manifest.json \
  --outdir results/新的报告交付目录
```

若要给已判级样本补充真实表型并重新排序，应从第四步继续：

```bash
bash scripts/run_pipeline.sh \
  --acmg-manifest results/NA18526_acmg/acmg_manifest.json \
  --case /绝对路径/case.json \
  --outdir results/新的病例报告目录
```

复用下游结果时不允许静默改变已完成步骤的策略。改变质量/参考策略需从 PopGen 开始；改变注释初筛策略需从准备清单开始；改变判级范围/频率策略需从注释清单开始；改变病例、表型词典或疾病策略需从 ACMG 清单开始。入口及其上游清单都核验样本、完成状态和产物 SHA-256。

支持的传递参数包括 `--reference`、`--bcftools`、`--convert2annovar`、`--perl`、`--min-dp`、`--min-gq`、`--min-qual`、`--include-filtered`、`--ref-mismatch`、`--threads`、`--annotation-policy`、`--verify-database-hashes`、`--acmg-scope`、`--frequency-policy`、`--disease-database`、`--disease-policy`、`--phenotype-aliases`、`--include-background-vus`、`--preview-limit` 和 `--keep-work`。`--help` 显示完整参数。传入相对路径时，以调用命令的目录为基准解析。

### 运行目录、状态与失败恢复

从 PopGen 启动时，目录如下；复用已完成清单时不复制或重跑已经完成的阶段：

```text
任务目录/
├── 02_input/                 输入准备与映射
├── 03_annotation/            ANNOVAR 注释和初筛
├── 04_acmg/                  InterVar 原始/整合分类
├── 05_diseases/              疾病关联、遗传相容性与表型排序
├── delivery/                 可独立查看和分享的报告文件
├── delivery.zip              同一 delivery 目录的压缩包
├── logs/                     各阶段入口的标准输出和错误
├── pipeline_config.json      实际传入参数
├── pipeline_manifest.json    入口、已执行/复用阶段、命令、版本与校验值
└── status.json               当前阶段及完整成功/失败状态
```

统一入口逐步运行，每个阶段先校验真实输出再进入下一步。失败立即停止，根目录和失败阶段都保留状态与日志，不产生成功标记或完成的报告包。原始工具的细节日志仍在各阶段子目录中，例如 `03_annotation/logs/annovar.log`。已有输出目录拒绝覆盖；恢复时选择最后一个成功清单，指定新的输出目录继续。

### 报告文件

| 文件 | 内容 |
|---|---|
| `delivery/report.html` | 独立中文 HTML 报告，可离线打开、筛选变异预览及打印/保存 PDF |
| `delivery/report.json` | 样本、结论、分析覆盖、质量、祖源、频率权限、完整疾病候选和版本信息 |
| `delivery/variants.tsv` | 全部保留变异、原始 GT/质量/频率、三套基因注释摘要、转录本改变和逐基因 ACMG 上下文 |
| `delivery/acmg_results.tsv` | 第四步完整原始交付表，分类、证据和覆盖记录原样保留 |
| `delivery/disease_candidates.tsv` | 第五步完整候选排序摘要 |
| `delivery/carrier_findings.tsv` | 携带者可能性子集 |
| `delivery/variant_disease_links.tsv` | 第五步全部关联和排除原因，包含未进入候选的背景记录 |
| `delivery/case.json`、`phenotypes.normalized.json` | 实际病例和表型解释快照 |
| `delivery/provenance/` | 第二至第五步清单、数据库、筛选策略、质量和 InterVar 依据快照 |
| `delivery/report_manifest.json` | 报告文件 SHA-256、输入疾病清单及生成模块版本 |
| `delivery/status.json` | 报告生成状态 |
| `delivery.zip` | 上述整个报告目录，解压后可直接打开 HTML |

HTML 和下载文件均使用本地相对路径，预览不依赖在线脚本或外部样式。`provenance/*manifest.source.json` 是原运行快照，其内部绝对路径用于追溯，不作为独立可重跑任务入口。完整流程的所有阶段清单保留在任务目录或原始运行位置。

报告按“变异数”“基因上下文数”“基因—疾病候选数”分别计数。一个变异可同时包含不同基因上下文的 P、VUS 或 B 标签；报告中用于预览排序的 `display_priority_classification` 只是显示优先级，不创造或覆盖分类。未被选中进行判级的变异明确标记 `not_evaluated`，不会变成 VUS 或良性。

默认 HTML 预览 200 个按复核优先级排序的变异，可通过 `--preview-limit` 改为 1–1000；疾病预览最多 100 项。预览上限只影响展示，完整 TSV 包含全部结果，`report.json` 包含全部疾病候选。表型为空时显示未评估，个体患病概率为空并标记未估计；不会将模型置信度或表型相似度转成风险百分比。

也可以只调用报告生成器而不建立统一任务目录或 ZIP：

```bash
bash scripts/generate_report.sh \
  --disease-manifest results/NA18526_diseases/disease_manifest.json \
  --outdir results/新的独立报告目录
```

### 功能检查

```bash
.runtime/venv/bin/python -m unittest discover -s tests -v
```

目前共 83 项功能检查通过，第六步新增 11 项，覆盖变异/基因上下文计数、候选解释、未判级/空结果、HTML 转义、本地下载完整性、证据文件保真、文件篡改拒绝、复用调用、失败停止及 ZIP 可移植性。这些检查验证工程行为，不是独立临床性能评测。

本机已通过统一入口从原始 PopGen 验证包完整执行第二至第六步，结果位于 `results/NA18526_complete/`。10,000 条原始记录经同一显式 REF 排除策略保留 2,237 个变异，完成全部 11 个注释协议、两次实际 InterVar 运行和疾病关联分析。最终报告包含 3,418 条判级上下文，默认疾病候选为 0，未提供表型的事实继续保留。新判级上下文集合、原始/整合分类和所有证据项均与此前第四步一致；ANNOVAR 的一条 RepeatMasker 多值注释内部顺序不同（MER5A/MER5B），保留本次工具原始输出，不影响判级。全部报告文件、ZIP 内容和本地下载链接已核验；离线 HTML 已在浏览器中检查显示。入口为 `results/NA18526_complete/delivery/report.html`，可分享压缩包为 `results/NA18526_complete/delivery.zip`。

### 变更记录

- `1.0.0`（2026-10-16）：完成第六步，新增统一入口、已完成清单续接、完整变异导出、离线中文 HTML/JSON 报告、原始证据与版本快照、校验清单及 ZIP 交付。
- `0.4.0`（2026-10-16）：新增第五步、固定 HPO/HGNC 数据索引、基因旧名映射、表型匹配、遗传/相位/家系观察、候选与关联审计输出及病例数据契约；保持第四步分类结果不变。
