# GDgpt → AtheroMap scDRS 接口与运行

版本 1.1.0，2026-10-18。以下命令从 `/hpc2hdd/home/msun663/e-gene` 执行。

本机真实数据的运行命令、检查结果及报告链接见 [接入验收记录](SCDRS_VALIDATION_20261018.md)。

## 已连接的输入

第三阶段交付的 `gdgpt_manifest.json` 是唯一的患者任务入口。适配器接收已完成的 GDgpt 任务，核验状态、文件大小、SHA-256、样本 ID、GRCh38、逐任务结果及原输入摘要，再生成第四阶段输入。生成接口不调用模型。

参考数据已注册在 [GSE159677_scdrs.reference.json](../config/GSE159677_scdrs.reference.json)，原始数据根目录为 `4_atheromap_data/GSE159677_scDRS`。注册清单记录 25 个必需文件的角色、相对路径、大小、SHA-256 和注释验收结果。工作入口使用独立副本把编号文件映射为原脚本所需的长文件名；原始数据保持不变。

数据中 40,563 个细胞、23 个总体 cluster 的复核表、映射表、最终 H5AD、scDRS 输入一致。巨噬细胞 7,498 → 7,055（移除 cluster 7 的 443 个细胞），VSMC 5,112 → 4,935（移除 cluster 7 的 177 个细胞）。亚型人工映射与现有 finalize 代码一致。总体 cluster 17 的 710 个细胞保留明确的 `Unknown` 标签。

这批细胞属于外部 GSE159677 队列。患者任务的 `sample_id` 与参考队列的 donor / `patient` 列分别保留，不做患者与细胞的对应。表达矩阵的原参考版本未知，登记为 `null`；患者变异仍为 GRCh38。

## 第三到第四的契约

契约由 [输入 schema](../../contracts/atheromap_input.schema.json) 与 [参考数据 schema](../../contracts/atheromap_reference.schema.json) 定义，`schema_version` 均为 `1.0`。

| 字段 | 含义及约束 |
| --- | --- |
| `sample_id`, `assembly` | 原患者 ID、GRCh38；与 GDgpt 清单和快照一致 |
| `source_gdgpt_manifest`, `source_reference_manifest` | 来源清单的位置、大小与 SHA-256 |
| `sample`, `case`, `phenotypes` | 保留原病例和正负表型；未知资料不补写 |
| `ancestry`, `frequency_policy`, `upstream_summary` | 保留祖源、频率使用权限、缺失语义和上游结论 |
| `tasks[].source_task_id`, `gene`, `kind`, `candidate` | 按原任务传递基因、疾病假设或指定基因探索；不添加疾病候选 |
| `tasks[].variant_evidence` | 完整原变异证据，包括原始分类、GT、频率、质量与排除原因 |
| `tasks[].gdgpt_result` | 对应任务的结构化机制结果；检查任务和输入摘要 |
| `reference` | 外部队列、组织、物种、trait 标签及来源状态 |
| `tasks[].applicability` | 只有已确认来源且疾病标识精确匹配时才为 `trait_matched` |
| `selection`, `analysis_scope` | 记录全部输入、所选任务和排除原因；拒绝静默丢失或提升任务 |
| `classification_labels_modified`, `diagnosis_established`, `risk_probability` | 固定为 `false`、`false`、`null` |

接口目录包含 `atheromap_input.json`、GDgpt 输入/报告快照、参考快照、`input_manifest.json` 和 `status.json`。消费入口重新验证这些文件与原始参考数据。空候选任务可以生成参考背景汇总；不会从 background VUS 自动制造新任务。

当前基因集有 1,000 个带权重基因，但 `z_score` 仅是交付文件的性状标签，真实疾病、GWAS 来源、权重生成方法尚未确认。因此默认使用 `--scope reference-context`，结果标为 `reference_context_only`。GDgpt 的回答不会被转换成 scDRS 权重。

未来补齐真实来源后，可在新的参考清单中填写 `provenance_status=verified`、`disease_name`、`gwas_study_id`、`source_records`，并人工审核 `mapped_disease_ids`。`--scope matched-trait` 仅接收疾病 ID 精确匹配的任务；无匹配即报错，排除项写入接口。不要仅凭 `z_score` 或数据集组织名称认定疾病匹配。

## 执行命令

本服务器的参考清单已生成，无须重复注册。新数据位置或新版文件需要在新路径注册，注册程序要求实际矩阵、复核表、分数、协变量及亚型导出一致：

```bash
bash 4_atheromap/tools/register_scdrs_reference.sh \
  --data-root 4_atheromap_data/GSE159677_scDRS \
  --out /绝对路径/新的参考清单.json
```

从第三阶段生成第四阶段输入；将上游清单替换成实际任务：

```bash
2_egene/.runtime/venv/bin/python -m egene_pipeline.atheromap_adapter \
  --gdgpt-manifest runs/NA18526_RNF34_pipeline/delivery/gdgpt/gdgpt_manifest.json \
  --reference 4_atheromap/config/GSE159677_scdrs.reference.json \
  --scope reference-context \
  --outdir runs/新的任务_atheromap_input
```

复用已经验收的 scDRS 分数，运行总体、亚型统计及全部 Python/R 图：

```bash
bash 4_atheromap/tools/run_scdrs.sh \
  --input-manifest runs/新的任务_atheromap_input/input_manifest.json \
  --mode reuse --plots all \
  --outdir runs/新的任务_atheromap_scdrs
```

需要重新评分时改用 `--mode recompute`。它调用原 scDRS CLI，保留 `n_ctrl=1000`，重新生成四种分组分析，将新分数写入工作副本的两类最终亚型 H5AD，再生成细胞级 CSV、汇总和图。重新评分的每个新任务会计算相同参考队列，不会把患者变异作为细胞基因型输入。

`--plots all` 为默认值，额外执行完整 Python 和 R 绘图；`--plots python` 跳过两个 R 图；`--plots none` 只保留原 merge 步骤附带的基础图和结构化汇总，不执行额外面板。单个外部 CLI / R 步骤默认超时 7,200 秒，可用 `--timeout` 调整。运行目录必须不存在且位于参考数据之外，失败记录保留在该目录的 `status.json` 与 `logs/`；修复后用新目录重跑。

启动器使用 `atheromap_scdrs` 和独立 `atheromap_r`，不合并前三个项目的环境。环境中新增的 `jsonschema==4.23.0` 用于接口校验，完整依赖记录见 `environments/locks/scdrs.pip.txt`。环境重建见 [ENVIRONMENTS.md](ENVIRONMENTS.md)。

## 文件格式兼容

现有总体注释及两类最终亚型 H5AD 含 `uns/pca/params/mask_var` 的新版 `null` 编码。AnnData 0.10.8 无法读取该编码；工作副本按旧版对 `None` 的表示方式省略这一元数据键，原值 `null` 和操作路径记录于 `input_compatibility.json`、运行清单的 `input_aliases`。转换限制在 `uns` 元数据，拒绝转换矩阵、obs、var 等数据位置的 null。表达矩阵、分层矩阵、细胞标签与嵌入均不参与转换；原数据文件通过哈希复查。

## 交付

```text
运行目录/
├── delivery/
│   ├── report.html                    报告和相对文件链接
│   ├── report.json                    队列规模、模式、范围、基因映射与限制
│   ├── atheromap_input.json           本次实际任务
│   ├── target_gene_context.json       原证据及参考表达映射
│   ├── target_gene_expression.tsv      目标基因在总体细胞类及两类亚型的表达
│   ├── celltype_condition_summary.tsv
│   ├── reference_donor_summary.tsv
│   ├── macrophage_celllevel_scores.tsv
│   ├── vsmc_celllevel_scores.tsv
│   ├── *_condition_summary.tsv
│   ├── statistics/                    原脚本统计与 scDRS 分组结果
│   └── plots/                         PNG / PDF
├── work/                             独立工作副本、评分文件及合并 H5AD
├── logs/                             每步骤日志
├── annotation_validation.json
├── input_compatibility.json
├── atheromap_manifest.json            输入校验、文件映射、步骤、版本与交付哈希
└── status.json
```

目标基因按 `var.gene_name` 做不区分大小写的唯一符号匹配；缺失或多义匹配明确记录，不补造表达值。表达取原注释对象的 `acosh` 层，给出均值和表达细胞比例；不声称患者细胞表达。亚型 R 输入 CSV 自动从最终 H5AD 与本次分数导出，另外保留含 reference cell ID 的 TSV。

单细胞检验的 P 值沿用原研究脚本，多个细胞来自同一 donor，不能把细胞级差异直接解释为患者诊断或个体风险。

本次交付范围是第三到第四的接口与 scDRS 参考数据入口。根目录 `run_pipeline.py --with-atheromap` 已可在 GDgpt 完成后自动生成接口、运行 scDRS，并挂接已验收的 GSE241346 gsMap 空间结果；独立命令仍可用于单独复核。完整四阶段交付的第四阶段位于 `05_atheromap/` 和 `delivery/atheromap/`。
