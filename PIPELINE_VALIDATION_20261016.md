# 三项目流水线验证记录

版本 **1.0.0** · 日期 **2026-10-16** · 时区 **Asia/Shanghai**

## 集成检查

命令：

```bash
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v
```

**11项通过**。使用明确标记的合成数据验证：完整 TSV 而非报告预览作为证据源；VUS/background、缺失 AF 和频率权限保留；近邻基因不作为变异靶基因；候选分类与原始证据一致；样本混用和文件篡改拒绝；无候选时不调用模型；已完成任务复用；子进程硬超时终止；失败停止；成功清单被修改时拒绝续接；ZIP 解压后的完整性。

## 真实 VCF 全链运行

```bash
python run_pipeline.py \
  --vcf 1_popgen/results/validation_current/patient.vcf.gz \
  --skip-cv --ref-mismatch exclude --threads 4 \
  --outdir runs/NA18526_end_to_end
```

实际阶段记录：`runs/NA18526_end_to_end/pipeline_manifest.json`。运行从原始10,000条记录开始，没有复用旧的 PopGen 或 e-Gene 分析阶段。`--skip-cv` 仅在此次执行检查显式省略无监督 CV；监督祖源、频率和冻结 GNN 正常执行。

此验证数据存在已记录的参考等位基因不匹配和原始质量字段缺失，因此显式排除 REF 不匹配记录。它用于检查执行链、接口与数据一致性，不是独立临床性能评测。其参考样本与训练/参考面板的关系见 [PopGen 验证记录](1_popgen/VALIDATION_20261016.md)。

**实际完成**，总耗时 **733.908秒**，四个统一阶段 `popgen / egene / bridge / gdgpt` 均成功：

| 检查项 | 实际结果 |
|---|---|
| 输入记录 | 10,000 |
| 参考频率精确匹配 | 7,716；其余保留未知 |
| 分析祖源 / GNN | EAS / EAS；GNN 置信分0.999724，仅作祖源补充 |
| REF 不匹配排除 | 1,140 |
| 保留并完成注释/判级的变异 | 2,237 |
| 基因上下文 | 3,418：Benign 3,302，VUS 116，P/LP 0 |
| 疾病候选 | 0 |
| 病例/表型 | 未提供，保持未评估 |
| 默认 GDgpt 分支 | `no_eligible_candidates`，未调用模型，正常生成说明报告 |

完整执行了11个 ANNOVAR 协议、原始及频率证据整合两次 InterVar 运行和疾病分析。新旧结果的全部 `(normalized_id, gene, gene_occurrence)` 上下文集合、原始/整合分类及每项整合 ACMG 证据完全相同。

随后复用完整成功阶段生成最终交付，未重跑生信或模型计算：

```bash
python run_pipeline.py \
  --resume-from runs/NA18526_end_to_end/pipeline_manifest.json \
  --outdir runs/NA18526_pipeline
```

最终入口：[完整流水线报告](runs/NA18526_pipeline/delivery/index.html)，[报告包](runs/NA18526_pipeline/delivery.zip)。根清单和交付清单的文件哈希均校验通过；ZIP 解压后无重名条目，13个本地 HTML 链接均存在。此次验证从 VCF 开始；没有重新执行 FASTQ 比对与变异检测，也不据此声明其测序性能。

## 真实模型分支

```bash
python run_pipeline.py \
  --egene-report 2_egene/results/NA18526_complete/delivery/report_manifest.json \
  --gene RNF34 \
  --outdir runs/NA18526_RNF34_mechanism
```

此分支明确选择患者已有的 RNF34 变异 `GRCh38:chr12:121421374:A:C` 进行基因机制探索。其原始分类为 VUS，原始筛选路由为 background，未变更疾病候选或 ACMG 分类。使用现有模型与 Neo4j，最大轮数采用正式入口默认值6。

逐任务的真实提问、工具调用、原始回答、模型/代码哈希和计时存于 `runs/NA18526_RNF34_mechanism/04_gdgpt/`。

**实际完成**：使用 `kimi-k3`，5个专家角色，首轮收敛；工作流耗时 **332.806秒**。全部模型/专家计时记录均成功，15次已记录图谱查询中14次非空，0次工具错误；共享预取覆盖为 `high / 1.0`。该覆盖值只描述图谱查询是否返回数据，不代表该变异的致病可信度。原始回答保持 VUS 分类，未建立患者诊断或患病概率；模型文本按原样保留，属于待复核结果。

随后使用统一续接入口复用全部成功阶段，生成已核验的最终报告包，**没有新增模型请求**：

```bash
python run_pipeline.py \
  --resume-from runs/NA18526_RNF34_mechanism/pipeline_manifest.json \
  --outdir runs/NA18526_RNF34_pipeline
```

最终入口：[RNF34 机制探索报告](runs/NA18526_RNF34_pipeline/delivery/index.html)，[报告包](runs/NA18526_RNF34_pipeline/delivery.zip)。

根清单及交付清单的 SHA-256、解压后的13个本地 HTML 链接均通过检查；交付中的 `variants.tsv`、`acmg_results.tsv`、`disease_candidates.tsv`、病例和标准化表型与来源 e-Gene 报告逐字节相同。

## 交付规则

原始变异和证据文件来自 e-Gene 完整交付，没有以 `report.json` 的200条预览替代完整 TSV。祖源及其频率权限由 e-Gene 原样承接。没有提供的表型、家系和病史保持未知，未计算个体患病概率。

空候选与显式基因探索属于不同执行分支；空候选不会自动产生候选疾病、调用模型或获得治疗建议。完整报告不等于临床诊断。
