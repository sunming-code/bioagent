# PopGen Agent 施工手册

这份文档回答两个问题：
1. **两周前的三步施工做到哪了**（步骤 1 / 2 / 3 + orchestrator）。
2. **现在往哪走**：完善 GNN 模块、与 e-Gene 锁死交付字段、把磁盘文件升级为互相锁定的 API，并作为数据层嵌入 Docker / Streamlit 平台。

---

## 现状快照（2026-09-14 更新）

两周前的策略是「步骤 2 先做真 → 步骤 1 接真数据 → 步骤 3 GNN 新实现 → orchestrator 串起来」。  
**步骤 0 / 1 / 2 与文件型交付包已经闭环；步骤 3 已改为冻结 checkpoint 推理。平台侧仍是本机文件 + 只读 UI，没有锁死的跨代理 API。**

### 已完成

| 块 | 状态 | 证据 |
|---|---|---|
| 步骤 0 公共准备 | 完成 | GRCh38 参考 + 索引；1000G plink 底库 `data/reference/panel_1000g/ref_1000g_pruned` |
| 步骤 1 FASTQ→VCF | 完成 | GIAB HG002，`results/patient.vcf(.gz)`，GRCh38，913,922 变异；高置信区 SNP precision ≈ 0.90 |
| 步骤 2 群体分析 | 完成 | `mode=Real_Pipeline`；demo 桩已关；监督 K=5 祖先比例 + 匹配人群 AF（`allele_freq.tsv` 844,704 行） |
| 编排 + schema 校验 | 完成（文件层） | `orchestrator.py` → `pack.py` → `contracts/evidence_pack.schema.json`（schema 1.0） |
| 本机可视化 | 完成（只读） | FastAPI UI `scripts/run_ui.sh`，端口 8008；**不重跑** 步骤 1/2/3 |

HG002 当前分析结论（给 e-Gene 的权威口径）：

- 查表人群：`EUR`（`AF_EUR`）
- `assignment=admixed`，`use_for_acmg_ba1_bs1=false`
- PCA 最近档 EUR，监督 ADMIXTURE 最大档 AFR → **最大 Q 不是祖先结论**
- 交付目录：`results/delivery/`（`evidence_pack.json` + `INTERFACE.md` + `allele_freq.tsv`）

### 未完成 / 未锁死

| 块 | 现状 | 缺口 |
|---|---|---|
| **GNN 模块** | 冻结 `model.pt` 归纳推理（2026-10-08）：温度 1.3122，不再转导重训 | HG002：训练位点只交上 2766/30000，GNN=`AMR`（0.382）与 PCA3=`EUR` 不一致，`usable_for_lookup=false`；查表仍是 EUR。四个大陆留一全部命中标签 |
| **e-Gene 交付字段** | schema 1.0 草稿 + `INTERFACE.md` 已存在 | **双方尚未最终签字**；字段名、VCF 文件名、GNN 置信分是否入包，都要以这次对齐为准 |
| **跨代理接口** | JSON / VCF / TSV **落在磁盘**；UI 仅提供下载 | 还不是互相锁定的 API 合约（无版本协商、无 schema 互检、无服务发现） |
| **平台嵌入** | 本机 conda + FastAPI 只读页 | 尚未作为数据层模块进入 **Docker / Streamlit 集成基因研究平台** |

贯穿约束仍然有效：基因组版本 **GRCh38**；每步只在自己的 conda 环境跑；步骤间目前仍以文件传递。

---

## 下一阶段（当前优先级）

> 目标一句话：把 popgen 从「本机跑通的三步流水线」收成平台里的 **数据层模块**——自动产出 GRCh38 VCF + 模式校验过的 evidence pack，并按锁死字段同时喂给 e-Gene。

### A. 完善 GNN 模块（先做）

现有实现是 `AncestryGAT`（`gnn_core.py`），不是拓扑形状分类器，也还不是可插拔的 GGNN 层。完善范围：

1. **推理形态**：从「每次把病人节点塞进 3202 人图再转导重训」收到可复现的推理路径（固定 checkpoint、固定温度、可关闭“与 PCA 不一致就抬 T”的临时规则）。
2. **置信度语义**：`ancestry.confidence` / `gnn_based.qmax` 必须可解释（校准 ECE、与 `concordant_with_pca3` 的关系、何时视为 `null`）。
3. **临床硬规则保持**：GNN **不得**覆盖 `analysis_based.af_population`；不一致时只作补充证据。
4. **HG002 不一致要给结论**：当前 `pca3_EUR_gnn_AMR_discordant` 是已知事实，完善模块时必须写明：这是模型问题、样本问题，还是「混血就应输出低置信 / 禁止锁定」。
5. **通过标准（相对两周前）**：仍要求混血 / 细分 / 低质量切片打赢 PCA/ADMIXTURE；**另外**要求：病人推理可复现、置信度进契约后 e-Gene 能无歧义消费。

命令不变：

```bash
conda run -n popgen_gnn python steps/03_gnn/train.py --out steps/03_gnn/model.pt
conda run -n popgen_gnn python steps/03_gnn/decide.py --vcf <patient.vcf> --outdir results/
```

### B. 与 e-Gene 最终确定交付字段

**直接交付给 e-Gene 的只有两样**（其余 TSV 为附属，按契约引用，不塞进 JSON）：

| 对象 | 约定 | 现状 → 目标 |
|---|---|---|
| GRCh38 病人 VCF | 基因组版本 GRCh38，`chr*` contig | 现文件名 `patient.vcf` / `patient.vcf.gz` → 契约中明确为 **GRCh38 patient VCF**（可保留现名，或加别名 `GRCh38patient.vcf`，双方选一个写死） |
| `evidence_pack.json` | 必须通过 `contracts/evidence_pack.schema.json` | 已能校验 schema 1.0 → **升到双方锁定的 schema 1.1**（字段冻结） |

包内 **必须** 含：

- 祖先比例（`ancestry.analysis_based.q` + `assignment` / `af_population` / `use_for_acmg_ba1_bs1`）
- 匹配人群频率（`allele_frequency` → `allele_freq.tsv`，join key `CHROM+POS+REF+ALT`）
- **GNN 置信分数**：schema 已预留 `ancestry.confidence` 与 `ancestry.gnn_based`；当前 HG002 包已填写，但 e-Gene 侧视为 **待最终确认后才必读**。模块完善前允许 `gnn_based=null`。

硬规则（对齐前不得改口径）：

- 查表人群与 BA1 以 `ancestry.analysis_based` 为准。
- `gnn_based` 只作补充，不得覆盖 `af_population`。
- 频率表不嵌进 JSON。

对齐产出：一份双方签字的字段表（可写在 `results/delivery/INTERFACE.md` + schema），作为 API 合约的唯一来源。

### C. 磁盘文件 → 互相锁定的 API 合约

当前：`results/delivery/` 里的 JSON / VCF / TSV，e-Gene 靠读目录消费。

升级目标：

- **同一份 schema** 同时约束：落盘文件、HTTP/RPC 响应、平台内消息。
- popgen 提供只读契约，例如：
  - `GET /v1/samples/{id}/vcf` → GRCh38 patient VCF
  - `GET /v1/samples/{id}/evidence_pack` → 校验后的 `evidence_pack.json`
  - `GET /v1/samples/{id}/allele_freq` → TSV（或按变异查询）
- 响应带 `schema_version`；双方 CI 用同一份 `evidence_pack.schema.json` 互检。
- 在 API 落地前，磁盘布局保持现状，避免双轨字段漂移。

### D. 作为数据层嵌入 Docker / Streamlit 平台

整体基因研究平台里，**popgen 代理 = 数据层模块**，不是独立演示站。

职责：

1. 自动化 VCF 处理（已有 Nextflow 步骤 1，收入平台镜像）。
2. 产出人群频率证据包（步骤 2 + pack，schema 校验后才出站）。
3. 经约定接口 **同时馈送 e-Gene**（VCF + evidence_pack；GNN 字段按 B 的锁定结果带上或为 null）。

落地形态：

- 三个 conda 环境打进平台 Docker（或三服务：preprocess / analysis / gnn），orchestrator 只做编排。
- Streamlit（或现有 FastAPI UI 迁过去）作为平台壳：上传/选样本、看祖先与 AF、把同一包推给 e-Gene。
- 本仓库现有 `ui/app.py` 是只读看板；`prototype/UI` 的 Streamlit 与 `docs/legacy_docker_pipeline` 是旧链路，**不要当新平台实现**，只作参考。

---

## 已完成施工记录（两周前计划，步骤 0–2）

顺序当时按「最快闭环」排：步骤 2 → 步骤 1 → 步骤 3 → orchestrator。  
三条硬约束未改：GRCh38；每步独立 conda；先去 demo 桩。

### 步骤 0 · 公共准备 — 已完成

- 参考基因组 GRCh38 + bwa / samtools / GATK 字典。
- 1000G 面板（只读）：`/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV/` + `samples.info`。
- 测试样本走了方案 B：GIAB HG002 真实 FASTQ；步骤 2/3 另有 1000G 留一（YRI/CEU/CHB/ITU）自测。

### 步骤 2 · 群体分析（env: `popgen_analysis`）— 已完成

原计划 4 处改造均已落地：`--outdir`、`partial_evidence.json`、关闭 demo、真实 1000G plink、CV 选 K、从 `.evec`/`.Q` 反解析祖先。

```bash
conda run -n popgen_analysis python steps/02_analysis/popgen_agent.py \
  --vcf <patient.vcf> --outdir results/
```

通过标准已满足：`mode=Real_Pipeline`；HG002 给出 EUR/admixed 口径，而不是写死的 EAS demo。

### 步骤 1 · 预处理 FASTQ→VCF（env: `popgen`）— 已完成

参数、GRCh38、真 VCF、`patient.vcf` 发布名、snpEff 关闭（QC 记为 `off`）已对齐 orchestrator。

```bash
conda run -n popgen bash -c '
cd popgen_agent/steps/01_preprocess
nextflow run main.nf --fastq_dir <fastq目录> --ref ../../data/reference/GRCh38.fa --outdir ../../results
'
```

通过标准已满足：`patient.vcf` 存在且变异 ≫ 1 万。Concordance 见 `results/concordance/summary.md`（外显子 vs 全基因组 truth，recall 低是预期，不以 recall 卡关）。

---

## 步骤 3 · GNN 祖先决策（env: `popgen_gnn`）— 冻结推理已完成

`decide.py` 加载 `model.pt` 的权重、训练位点和交叉验证温度，只做一次前向。参考个体之间的 kNN 保持训练图；病人只连到 20 个最近参考个体。

2026-10-08 HG002：观测 2766/30000 个训练位点，`predicted=AMR`，`confidence=0.382`，`temperature=1.3122`，PCA3=`EUR`，`usable_for_lookup=false`。同一 VCF 连跑两次 JSON 一致。四个大陆留一（`results/gnn/inductive_loo.tsv`）预测与标签一致。查表人群仍由步骤 2 决定。

e-Gene 是否把 `confidence` 定为必读，仍属下一阶段 B。

---

## 整合 · orchestrator + 当前文件交付

```bash
# 端到端（给 FASTQ）
conda run -n base python popgen_agent/orchestrator.py \
  --fastq-dir <dir> --ref data/reference/GRCh38.fa --outdir results/

# 跳过预处理，直接给 VCF
python popgen_agent/orchestrator.py --vcf <patient.vcf> --outdir results/

# 只按已有 JSON 重打包并做 schema 校验
python popgen_agent/orchestrator.py --pack-only --outdir results/
```

**当前（磁盘）交付物**：`results/delivery/evidence_pack.json`（schema 1.0 校验通过），旁路 `allele_freq.tsv`，病人 VCF 在 `results/patient.vcf.gz`。  
**目标交付物**：同一内容经锁定 API 给出；GNN 置信分在字段对齐后成为包内正式字段。

---

## 里程碑对照

| 步骤 | 对应 Milestone | 交付 | 2026-09-14 |
|---|---|---|---|
| 步骤 1 | M1 自动化 VCF 生成 | 真实 FASTQ→VCF 跑通 | **已完成**（HG002 / GRCh38） |
| 步骤 2 | M2 群体频率报告 | 祖先匹配的等位基因频率 | **已完成**（文件包 + schema 1.0） |
| 步骤 3 | M3 前半：GNN | 可复现推理 + 校准置信度 | **已完成**（冻结推理；HG002 不锁定查表） |
| 整合 | M3 对接 e-Gene | 锁死字段的 `evidence_pack` + VCF | **文件层已通，API / 字段终稿未锁** |
| 平台 | 集成基因研究平台 | Docker / Streamlit 数据层 | **未开始**（仅本机只读 UI） |

## 施工优先级 checklist

- [x] 步骤 0：GRCh38 参考 + 三套索引
- [x] 步骤 2：去 demo 桩 + 建 1000G plink 底库 + 跑通真分析
- [x] 步骤 1：接 GIAB/真实 FASTQ 跑通，发布 `patient.vcf`
- [x] 文件型整合：orchestrator + schema 1.0 校验 + `results/delivery/`
- [x] **完善 GNN 模块**（冻结推理、固定温度、HG002 `usable_for_lookup=false`）
- [ ] **与 e-Gene 最终确定交付字段**（GRCh38 VCF + 校验过的 `evidence_pack.json`；祖先比例、匹配 AF、GNN 置信分）
- [ ] **磁盘 JSON/VCF/TSV → 互相锁定的 API 合约**
- [ ] **popgen 作为数据层嵌入 Docker / Streamlit 平台**，自动化 VCF + 证据包并馈送 e-Gene
