# PopGen Agent

一个完整的临床群体遗传流水线 agent：病人测序数据进 → 预处理成 VCF → 群体分析（祖先+频率）→ GNN 决策增强 → 汇总成 `evidence_pack.json` → 交给 e-Gene 做 ACMG 致病性分级。

> 团队平台中的定位：**数据入口 + 宏观维度提供者**（Yin Wang / PopGen Agent）。
> 下游对接：**e-Gene Agent**（Ming Sun，ACMG 变异分级）。

## 架构：一个 agent，三步隔离环境

```
控制层 orchestrator.py  (只做机械编排 + 汇总，不装工具)
        │            │              │
   步骤1 预处理   步骤2 群体分析   步骤3 GNN决策
   env: popgen   env: popgen_     env: popgen_gnn
   FASTQ→VCF     analysis          祖先判定+置信度
   (bwa/gatk/    (smartpca/        (torch/pyg/
    plink2/nf)    admixture/        scikit-allel)
                  treemix)
        └────────────┴──────────────┘
                     ▼
        evidence_pack.json ──► e-Gene
```

每一步用 `conda run -n <env>` 拉起自己的环境，跑完即退，步骤间只通过文件（vcf/json）传递，互不冲突。

## 目录结构

```
popgen_agent/
├── orchestrator.py              # 控制层：按序调度各步 + 汇总 evidence_pack
├── envs/                        # 三个环境的可复现定义 (conda env export --from-history)
│   ├── preprocess.yml           # → 环境 popgen
│   ├── analysis.yml             # → 环境 popgen_analysis
│   └── gnn.yml                  # → 环境 popgen_gnn
├── steps/
│   ├── 01_preprocess/main.nf    # FASTQ→VCF (Nextflow)
│   ├── 02_analysis/popgen_agent.py  # 祖先/频率
│   └── 03_gnn/decide.py         # GNN 祖先决策
├── contracts/
│   └── evidence_pack.schema.json  # 给 e-Gene 的接口契约
├── data/  results/              # 大文件不入库，见 LOCAL_DATA.md
└── LOCAL_DATA.md                # 留在本机的数据：绝对路径、内容、作用
```

## 三个 conda 环境

| 环境 | 步骤 | 关键工具 |
|---|---|---|
| `popgen` | 预处理 | nextflow, bwa, gatk, samtools, bcftools, plink2, fastqc, snpEff |
| `popgen_analysis` | 群体分析 | plink, plink2, bcftools, smartpca(eigensoft), admixture, treemix |
| `popgen_gnn` | GNN 决策 | torch 2.1+CUDA, torch_geometric, scikit-allel, sklearn, xgboost |

## 参考数据（只读）

- 1000G 高覆盖面板（GRCh38, 3202 人, 26 群）：`/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV/`
- 样本标签：`/data/public/1000GP/samples.info`

## 运行

```bash
# 已有 VCF：分析 + GNN + 汇总（跳过预处理）
python orchestrator.py --vcf results/patient.vcf.gz --outdir results/

# 已有分析结果：只跑 GNN + 汇总
python orchestrator.py --vcf results/patient.vcf.gz --outdir results/ --skip-analysis

# 只汇总已有 JSON（不重跑 1/2/3）
python orchestrator.py --pack-only --outdir results/

# 已完成任务可视化 UI（不重跑分析）
bash scripts/run_ui.sh
# 本机 http://127.0.0.1:8008  ；其它电脑 http://<服务器IP>:8008
```

## 待办（2026-09-14）

已完成（文件层闭环）：

- [x] 步骤 1：GIAB HG002 FASTQ→VCF，GRCh38
- [x] 步骤 2：去掉 demo 桩，真实 1000G 面板投影
- [x] 步骤 3 原型：decide.py + train.py，混血/细分/低质量 CV 打赢 PCA/ADMIXTURE
- [x] 契约草稿：`evidence_pack.schema.json` 含 `gnn_based`；查表仍以 `analysis_based` 为准
- [x] 整合：orchestrator 串联 + schema 1.0 校验 + `results/delivery/`

下一阶段（见 `OPERATION.md`）：

- [x] 完善 GNN 模块（冻结 checkpoint 推理；GNN 不得覆盖查表人群）
- [ ] 与 e-Gene **最终确定**交付字段：GRCh38 patient VCF + 模式校验的 `evidence_pack.json`（祖先比例、匹配人群频率、随后锁定的 GNN 置信分）
- [ ] 磁盘上的 JSON/VCF/TSV 升级为互相锁定的 API 合约
- [ ] 作为数据层嵌入 Docker / Streamlit 集成平台，自动化 VCF 处理与证据包，并馈送 e-Gene
```
