# Bioagent：从基因组数据到可追溯的机制分析报告

**简体中文** | [English](README.en.md)

版本 **1.2.2** · 更新日期 **2026-10-19**

本项目把群体遗传分析、变异注释与 ACMG 判级、基因—疾病机制分析，以及单细胞/空间参考分析连接为一条可恢复的流水线。输入为 **GRCh38 单样本 VCF** 或双端 FASTQ，也可从已完成阶段的清单继续；输出结构化证据、HTML 报告和可离线查看的 ZIP。

## 功能与目录

| 模块 | 主要功能 | 主要输出 |
|---|---|---|
| `1_popgen/` | FASTQ 比对/变异检测；PCA、ADMIXTURE、冻结 GNN 祖源分析；1000G 匹配频率查询 | VCF、祖源和频率表、`evidence_pack.json` |
| `2_egene/` | 输入校验、ANNOVAR 注释、InterVar ACMG2015 判级、HPO 疾病关联排序与报告 | `report_manifest.json`、变异/疾病证据表、HTML |
| `3_GDgpt/` | 七种专家角色结合 Neo4j 任务图谱，生成带工具查询记录的机制解释 | 基因/疾病/通路分析、引用边、逐任务报告 |
| `4_atheromap/` | GSE159677 scDRS 参考背景分析；GSE241346 gsMap 空间结果整合 | 单细胞/空间参考结果及图表 |
| `egene_pipeline/`、`contracts/` | 跨阶段文件契约、校验、失败续接与统一交付 | 状态清单、完整报告和 ZIP |
| `pipeline_ui/` | 本地网页选择起止阶段，实时查看日志与阶段产物 | 浏览器界面及 SSE 进度 |

默认链路为 `PopGen → e-Gene → GDgpt`，增加 `--with-atheromap` 后接入第四阶段。各模块使用独立环境，阶段间传递带大小、SHA-256 和样本标识的文件清单。

## 获取代码

```bash
git clone https://github.com/sunming-code/bioagent.git
cd bioagent
```

本仓库的文件内容约 **50 MiB**，包括源码、文档、约 6.3 MiB 的 GNN 模型、约 12.5 MiB 的任务图谱 CSV，以及小型研究记录。**原始测序数据、参考数据库、Conda/venv 环境、大型运行结果和 ANNOVAR 安装包不在 Git 中**，使用前按下面说明准备。

## 安装与配置

以下命令从仓库根目录执行。环境验收以 **Linux x86_64** 为主；主控制程序/GDgpt 使用 Python 3.11，PopGen 和 AtheroMap 的版本由各自环境文件定义。需要 Git、curl、tar、Perl 和 Python venv 支持；完整 FASTQ 预处理需要 Java，第四阶段安装器需要可用的 Conda。GNN 使用 CPU 即可。

各模块所需数据的来源和准备方式随安装步骤说明。完整下载命令、目录布局、版本和已知缺口见 [DATASETS.md](DATASETS.md)，来源与校验值见 [provenance.json](data_sources/provenance.json)。下载和运行所需空间取决于入口及阶段，应另行预留数据、中间文件和软件环境的空间。

### 1. 安装 PopGen 环境

```bash
bash 1_popgen/scripts/setup_runtime.sh
```

脚本创建 `1_popgen/.runtime/envs/{popgen,popgen_analysis,popgen_gnn}` 并检查软件；数据准备后再运行完整数据检查。支持 `POPGEN_PREFIX`、`POPGEN_ANALYSIS_PREFIX`、`POPGEN_GNN_PREFIX` 覆盖环境路径。

### 2. 准备 PopGen 参考

PopGen 的频率查询使用 **1000G 3,202 人高覆盖 GRCh38 VCF**。从 [IGSR 官方发布目录](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/) 下载 chr1–22 的 VCF 和 `.tbi` 到 `1_popgen/data/1000GP/20220422_3202_phased_SNV_INDEL_SV/`，批量下载命令见 DATASETS.md。PCA、ADMIXTURE 和 GNN 还需要由这些 VCF 构建的 `ref_1000g_pruned.*` 剪枝面板。下面从仓库保留的标签/个体表生成构建所需的 `samples.info`：

```bash
python3 - <<'PYDATA'
import csv
from pathlib import Path
base = Path('data_sources/popgen_panel')
sex = {row[1]: row[4] for row in (line.split() for line in (base / 'ref_1000g_pruned.fam').read_text().splitlines())}
out = Path('1_popgen/data/1000GP/samples.info')
out.parent.mkdir(parents=True, exist_ok=True)
with (base / 'sample_superpop.tsv').open() as source, out.open('w', newline='') as target:
    writer = csv.writer(target, delimiter='\t', lineterminator='\n')
    for row in csv.DictReader(source, delimiter='\t'):
        writer.writerow([row['IID'], row['SUBPOP'], sex.get(row['IID'], '0')])
PYDATA
bash 1_popgen/scripts/build_1000g_panel.sh 1-22
1_popgen/.runtime/envs/popgen_gnn/bin/python 1_popgen/scripts/check_runtime.py
```

默认数据路径相对于当前仓库。可设置 `POPGEN_1000G_VCF_DIR`、`POPGEN_SAMPLES_INFO`、`PANEL_TMP` 指向已有数据和足够大的临时目录。剪枝面板的哈希、个体顺序和冻结模型的训练位点需要一致；重建后按来源清单验证，不能把重新训练的结果当成原冻结模型复现。

从 FASTQ 开始时，另需下载 [Broad GRCh38 FASTA](https://storage.googleapis.com/gcp-public-data--broad-references/hg38/v0/Homo_sapiens_assembly38.fasta)，保存为 `1_popgen/data/reference/GRCh38.fa`，校验后准备 BWA 索引、FAI 和序列字典；具体命令见 DATASETS.md。已有 VCF 的入口不需要下载公开示例 FASTQ。

需要公开双端测序示例时，可使用 HG002 诺禾 WES 的 [R1](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124639/HG002_novogene_wes_18g_rep1_R1.fq.gz) 和 [R2](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124722/HG002_novogene_wes_18g_rep1_R2.fq.gz)，下载到 `1_popgen/data/fastq/`；精确文件名、MD5 和断点续传命令见 DATASETS.md。

### 3. 安装 e-Gene、参考和疾病库

ANNOVAR 主程序由每位使用者从 [官方注册页](https://www.openbioinformatics.org/annovar/annovar_download_form.php) 获取，不能随本仓库再分发。注释与判级所需的 hg38 数据库来自 [ANNOVAR 官方数据库](https://annovar.openbioinformatics.org/en/latest/user-guide/download/)，固定协议、URL 和版本在 `2_egene/config/dependencies.lock.json`；安装器按该清单下载，dbNSFP 等数据库仍按各自使用条款获取。

`prepare_reference.py` 从 [UCSC](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz) 下载 hg38 FASTA 并建立 FAI，用于输入与 REF 校验；`setup_disease_data.py` 按 `2_egene/config/disease_sources.lock.json` 下载固定版本的 HPO/HGNC，并构建表型/疾病关联库。将下面的 ANNOVAR 安装包路径替换为自己的授权文件后执行：

```bash
python3 2_egene/scripts/setup_dependencies.py \
  --annovar-archive /绝对路径/annovar.latest.tar.gz --workers 4
python3 2_egene/scripts/setup_input_runtime.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/prepare_reference.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/setup_disease_data.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/check_dependencies.py
```

安装会创建 `2_egene/.runtime/venv/`、配置文件和数据库清单。**OMIM `mim2gene.txt` 在线文件已更新，与本地锁定快照不同，需要先处理旧快照获取或版本选择**，否则下载器的 ETag/体积检查可能中止；本项目没有为了通过安装而静默改写历史来源锁。e-Gene 的详细安装步骤见 [2_egene/README.md](2_egene/README.md)。

### 4. 安装 GDgpt、配置模型与 Neo4j

```bash
python3 -m venv 3_GDgpt/.venv
3_GDgpt/.venv/bin/python -m pip install -r 3_GDgpt/requirements.lock.txt
cp 3_GDgpt/config.example.json 3_GDgpt/config.json
```

在 `3_GDgpt/config.local.json` 中填写模型和数据库配置；该文件已被 Git 忽略。配置示例：

```json
{
  "api_key": "填写你自己的模型 API Key",
  "base_url": "https://你的模型服务/v1",
  "text_model": "你的模型名称",
  "neo4j_uri": "bolt://127.0.0.1:7687",
  "neo4j_user": "neo4j",
  "neo4j_password": "填写自己的数据库密码",
  "neo4j_database": "neo4j"
}
```

也可通过 `GDGPT_API_KEY`、`GDGPT_BASE_URL`、`GDGPT_TEXT_MODEL` 和 `GDGPT_NEO4J_*` 环境变量覆盖。默认本地向量模型首次使用需要下载模型文件，网络离线时应预先准备缓存。

Neo4j 可使用自己的独立实例。下面以官方 Docker Community 镜像为例，将密码占位符改为与配置一致的值：

```bash
docker run -d --name bioagent-neo4j \
  -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 \
  -v bioagent-neo4j-data:/data \
  -e NEO4J_AUTH=neo4j/REPLACE_WITH_YOUR_PASSWORD \
  neo4j:5.26-community
# 等待数据库就绪后导入仓库自带的任务图谱。
3_GDgpt/.venv/bin/python 3_GDgpt/scripts/import_local_kg.py
```

导入器使用 `config.local.json` 中的数据库配置，核对 **10,133 个节点、87,838 条边**，拒绝混入无关图谱。Docker 设置见 [Neo4j 官方说明](https://neo4j.com/docs/operations-manual/current/docker/introduction/)。`3_GDgpt/scripts/run_local.sh` 是原服务器本地 Neo4j/Java 安装的管理入口，不会在新 clone 中安装被排除的 `.runtime/`；使用 Docker 时不需要该启动器。

### 5. 第四阶段（按需）

```bash
bash 4_atheromap/tools/setup_environments.sh
cp 4_atheromap/config/paths.example.env 4_atheromap/config/paths.local.env
```

编辑本地路径，按 [AtheroMap 环境说明](4_atheromap/docs/ENVIRONMENTS.md) 配置工作目录，并准备两个分支的输入。

scDRS 的原始 GSE159677 聚合矩阵可从 [NCBI GEO](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE159677) 下载。原矩阵不能直接代替项目人工注释后的 H5AD、分数和权重；这些加工文件目前尚无已确认的公共发布地址。参考文件需与 `4_atheromap/config/GSE159677_scdrs.reference.json` 一致，新加工数据需要重新注册；流程与接口见 [scDRS 接口说明](4_atheromap/docs/SCDRS_INTEGRATION.md)。

gsMap 使用 GSE241346 空间数据、GCST007435 GWAS 和 gsMap 官方参考资源，下载地址、文件布局及 SHA-256 见 [固定下载清单](4_atheromap_data/GSE241346_gsMap/download_manifest.json)，转换与准备步骤见 [gsMap 输入说明](4_atheromap/docs/GSMAP_INPUTS.md)。官方资源链接在本机核查时返回 403，需要先确认可访问的获取入口。

根入口还消费**已经验收的 gsMap 输出目录**，应按 [gsMap 验收说明](4_atheromap/docs/GSMAP_VALIDATION_20261018.md) 完成分析与核验后启用。完整四阶段运行需要补齐上述加工数据和验收结果；详细缺口见 [DATASETS.md 第 4 节](DATASETS.md#4-不能仅用公开下载替代的内容)。

## 使用方式

完成所需阶段的环境和数据准备后，从仓库根目录执行。输入为 GRCh38；不会自动执行 GRCh37 liftover。VCF 祖源分析要求足够多的全局位点，少量候选变异不能代替完整样本 VCF。

```bash
# 从单样本 VCF 执行默认三阶段。
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /绝对路径/sample.vcf.gz --outdir runs/sample_analysis

# 从双端 FASTQ 开始。先按 DATASETS.md 准备 Broad FASTA、BWA/FAI 索引和字典。
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --fastq-dir /绝对路径/fastq_directory \
  --reference "$PWD/1_popgen/data/reference/GRCh38.fa" \
  --outdir runs/sample_from_fastq

# 从已经生成的 e-Gene 报告继续机制分析。
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --egene-report /绝对路径/delivery/report_manifest.json \
  --outdir runs/sample_mechanism

# 需要病例表型时增加 --case；模板不包含真实临床资料。
# --case /绝对路径/case.json

# 只运行到 e-Gene，不调用 GDgpt 模型。
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /绝对路径/sample.vcf.gz --end-stage egene --outdir runs/sample_egene

# 第四阶段的数据及已验收 gsMap 结果齐备后启用。
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /绝对路径/sample.vcf.gz --with-atheromap --outdir runs/sample_four_stage
```

病例格式见 [case.template.json](2_egene/examples/case.template.json)，样本 ID 必须匹配 VCF。年龄、表型、家系和病史缺失时保持未知。默认拒绝 REF 不匹配；`--ref-mismatch exclude` 是显式排除并留痕的选择，不是通用默认。

每次运行使用新输出目录。成功后打开 `runs/<任务>/delivery/index.html`，或下载并解压 `delivery.zip` 后离线查看。中间结果、执行参数、哈希、失败状态和重用记录保存在任务目录。模型调用需要自己的服务账户和额度；没有可分析候选时不调用模型。

### 本地网页

```bash
1_popgen/.runtime/envs/popgen_gnn/bin/python -m uvicorn \
  pipeline_ui.app:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，选择起止阶段和服务器可访问的输入路径，运行期间可查看阶段状态、日志和已完成的产物。远程服务器可用 SSH/VS Code 端口转发访问；完整说明见 [pipeline_ui/README.md](pipeline_ui/README.md)。网页复用相同 CLI 和数据库配置。

### 检查安装与运行帮助

```bash
2_egene/.runtime/venv/bin/python run_pipeline.py --help
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v
1_popgen/.runtime/envs/popgen_gnn/bin/python 1_popgen/scripts/check_runtime.py
```

合成回归测试不要求调用付费模型；它验证文件契约、参数传递、恢复/失败语义和报告交付。历史真实数据验收见 [2026-10-16](PIPELINE_VALIDATION_20261016.md)、[2026-10-18](PIPELINE_VALIDATION_20261018.md)，不表示未准备数据的新机器已完成复现。

## 进阶入口与续接

五个 e-Gene 阶段入口与原项目保持一致；另支持完整报告、GDgpt 输入及统一流水线续接。以下入口互斥：

| 入口 | 后续执行 |
|---|---|
| `--vcf` | PopGen 祖源/频率/GNN → e-Gene 全部阶段 → GDgpt → 统一交付 |
| `--fastq-dir` | PopGen FASTQ 预处理，然后执行上述流程；通过 `--reference` 指定参考 FASTA |
| `--popgen-pack` | 从已完成的 PopGen `delivery/evidence_pack.json` 开始 |
| `--prepared-manifest` | 从 e-Gene 输入准备结果继续注释 |
| `--annotation-manifest` | 从注释结果继续 ACMG 判级 |
| `--acmg-manifest` | 从判级结果继续疾病分析，可补充真实病例 |
| `--disease-manifest` | 生成 e-Gene 报告后进入 GDgpt |
| `--egene-report` | 接收 e-Gene `delivery/report_manifest.json`，进行适配和 GDgpt 分析 |
| `--gdgpt-input` | 接收适配后的 `input_manifest.json`，进行 GDgpt 分析；统一交付仍需要原 e-Gene 报告 |
| `--resume-from` | 接收旧任务的 `pipeline_manifest.json`，验证并复用成功阶段，失败阶段在新目录继续 |

例如直接衔接服务器上已有的 PopGen 交付：

```bash
python run_pipeline.py \
  --popgen-pack 1_popgen/results/validation_current/delivery/evidence_pack.json \
  --ref-mismatch exclude \
  --outdir runs/NA18526_from_popgen
```

这里的 `--ref-mismatch exclude` 专门沿用 NA18526 验证数据已经记录的排除策略。新样本默认严格拒绝不匹配；不要将这个参数作为通用质控默认值。该样本来源、质量缺失和参考等位基因限制见 [PopGen 验证记录](1_popgen/VALIDATION_20261016.md)。

## GDgpt 的任务选择

默认对 e-Gene 已保留的**全部疾病候选**逐项生成机制分析任务。`--max-candidates N` 可显式限制数量，未分析的候选数写入报告；不会静默截断。候选数为零时，输出 `no_eligible_candidates` 和上游结论，**不调用模型、不自动提升 background VUS、不生成疾病诊断**。

显式探索指定基因时使用 `--gene`，可重复：

```bash
python run_pipeline.py \
  --egene-report 2_egene/results/NA18526_complete/delivery/report_manifest.json \
  --gene RNF34 \
  --outdir runs/NA18526_RNF34
```

指定基因必须能唯一连接到患者已有的、与基因功能注释区域重叠的变异上下文；intergenic/upstream/downstream 的近邻基因不能直接作为变异靶基因。指定基因任务标记 `explicit_gene_exploration`，保留原始 VUS/良性分类和 background 路由，不改变疾病候选。RNF34 在本例中是 VUS，属于探索性机制解释。

每个模型任务的查询前缀均含基因和疾病假设，以兼容现有 GDgpt 查询规划对前600字符的读取。完整结构化证据存入 `gdgpt_input.json`，包括正/负表型、原始 GT、质量字段、ACMG 证据项、频率权限和排除原因。默认每任务在模型上下文展示20条变异上下文，其余数量明确记录；可通过 `--prompt-variants` 增加。完整证据不会从交付中删除，未展示部分不会声称已被模型逐项审阅。

GDgpt 默认最多 **6轮**，支持 `--max-rounds 1..6`；实际收敛仍由原工作流决定。默认每任务硬超时 **3600秒**，可通过 `--task-timeout` 调整。每任务使用独立子进程，超时或失败即终止本次流水线，成功任务单独保存供续接，不在同一后台线程上重试。

模型使用 `3_GDgpt/config.json` 或已有 `GDGPT_*` 环境变量，不将 API Key 写入统一配置或报告。Neo4j 需要处于运行状态；新机器可使用上文 Docker 配置，原服务器本地安装的管理命令是 `bash 3_GDgpt/scripts/run_local.sh start`。空候选交付不需要模型服务。

## 接入第四阶段 scDRS

已增加可校验的 `3_GDgpt → 4_atheromap` 接口，并连接 `4_atheromap_data/GSE159677_scDRS` 的已复核数据。需要一条命令完成四个阶段时，在入口增加 `--with-atheromap`：

```bash
python run_pipeline.py \
  --egene-report 2_egene/results/NA18526_complete/delivery/report_manifest.json \
  --gene RNF34 --with-atheromap \
  --outdir runs/NA18526_four_stage
```

它会在 `05_atheromap/` 中生成接口清单、scDRS 交付和 gsMap 验收结果，并把第四阶段报告放入 `delivery/atheromap/`。也可在已有三阶段任务上使用 `--resume-from .../pipeline_manifest.json --with-atheromap`，只执行第四阶段。独立续接命令仍可单独运行：

```bash
2_egene/.runtime/venv/bin/python -m egene_pipeline.atheromap_adapter \
  --gdgpt-manifest runs/NA18526_RNF34_pipeline/delivery/gdgpt/gdgpt_manifest.json \
  --scope reference-context \
  --outdir runs/新的任务_atheromap_input

bash 4_atheromap/tools/run_scdrs.sh \
  --input-manifest runs/新的任务_atheromap_input/input_manifest.json \
  --mode reuse --plots all \
  --outdir runs/新的任务_atheromap_scdrs
```

接口完整保留原始变异分类、病例、频率权限与 GDgpt 任务；scDRS 的细胞属于外部参考队列。当前 `z_score` 的真实 GWAS 来源未确认，结果限定为参考背景。`--mode recompute` 可重新计算参考分数并同步亚型导出。输入契约、数据注册、运行方式与输出见 [scDRS 接口说明](4_atheromap/docs/SCDRS_INTEGRATION.md)；四阶段统一运行的参数见 `run_pipeline.py --help`。

## 输出与恢复

```text
runs/任务/
├── 01_popgen/                 从原始数据开始时生成
├── 02_egene/                  注释、判级、疾病分析及原 e-Gene 报告
├── 03_gdgpt_input/            gdgpt_input.json、input_manifest.json
├── 04_gdgpt/                  各任务的问题、原始结果、工具记录、计时和报告
├── 05_atheromap/              scDRS 参考分析、gsMap 验收结果及第四阶段报告（启用 --with-atheromap 时）
├── delivery/
│   ├── index.html            统一报告首页
│   ├── pipeline_report.json  汇总结果、祖源/频率、任务选择和溯源
│   ├── delivery_manifest.json
│   ├── egene/                完整 e-Gene 离线交付
│   └── gdgpt/                完整机制分析交付
├── delivery.zip              解压后打开 delivery/index.html
├── logs/                     每阶段日志
├── pipeline_manifest.json    实际参数、命令、阶段清单哈希和成功/失败记录
└── status.json
```

复用阶段仍在原运行目录，不复制大型生信中间文件；最终离线交付会复制所需报告与完整 TSV。`delivery/provenance` 和 `*.source.json` 中的原始路径用于溯源，不是搬移后可执行的任务入口。报告中的祖源及频率已经由 e-Gene 承接；原始 PopGen VCF、中间数据和模型产物保留在 `01_popgen` 或其原任务目录。

从失败任务继续，必须指定新输出目录：

```bash
python run_pipeline.py \
  --resume-from runs/失败任务/pipeline_manifest.json \
  --outdir runs/继续任务
```

续接会核验成功阶段的清单和文件哈希，检查同一样本；e-Gene 失败时自动寻找其最后一个已完成子阶段。续接未完成的 GDgpt 阶段时，已完成任务只有在输入、模型、图谱 CSV 快照、代码和任务参数一致时才可复用；已完整成功的阶段保留其原始运行配置与结果。可调整 `--threads`、`--task-timeout` 和执行环境路径来恢复执行，不能通过续接改变临床资料或分析策略。若要改变病例、筛选策略或基因选择，应从对应上游清单开始新任务。

运行目录拒绝覆盖，失败不会发布成功 ZIP。最终报告包中的数据文件和本地链接均使用相对路径，SHA-256 可由 `delivery_manifest.json` 校验。四阶段真实续接验收见 [PIPELINE_VALIDATION_20261018.md](PIPELINE_VALIDATION_20261018.md)。

## 参数与环境

`python run_pipeline.py --help` 显示完整参数。PopGen 的 `--skip-cv`、`--skip-gnn` 和 e-Gene 的质量/频率/疾病策略参数显式传递给原入口；默认不跳过这些流程。原入口对复用阶段的策略限制继续生效。

默认 PopGen 控制程序使用 e-Gene 的 Python，生信计算仍由其自身 `runtime.py` 分派到隔离环境。e-Gene 使用 `2_egene/.runtime/venv/bin/python`，GDgpt 使用 `3_GDgpt/.venv/bin/python`。可通过 `--popgen-python`、`--egene-python`、`--gdgpt-python` 覆盖解释器路径，不需要合并依赖环境。

## 检查与分析边界

```bash
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v
```

合成测试明确标记为 synthetic，覆盖完整表读取、分类/频率权限保留、近邻基因拒绝、候选和空候选、样本混用、数据篡改、任务复用、硬超时终止、失败停止和 ZIP 可移植性。真实服务器运行见 [验证记录](PIPELINE_VALIDATION_20261016.md)。

GDgpt 的图谱只有基因、疾病、通路、表型和药物五类节点，没有变异节点。机制解释不能据此确认具体等位基因的致病性、肿瘤驱动作用、药物敏感性或个体患病概率。上游观察和图谱查询记录分别留存；模型文字是待复核结果。e-Gene 的孟德尔疾病候选不自动转为肿瘤治疗证据。
