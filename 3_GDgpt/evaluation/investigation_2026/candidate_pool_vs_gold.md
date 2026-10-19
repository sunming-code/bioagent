# Falsifier Artifact: KG 候选池 vs 金标基因 对照表

**来源数据**：`evaluation/results/adapt15_full_raw.jsonl`（15题 disease-centered，自适应路由）  
**金标文件**：`evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl`  
**运行日期**：2026-09-14  
**目的**：验证"LLM重排候选池"可行性假设——若金标基因不在候选池里，重排是无用功。

## 汇总统计（LIVE 实测数据）

| 指标 | 值 |
|---|---|
| 总样本数 | 15 |
| 候选池覆盖率 = 0% 的样本 | **11/15 (73%)** |
| 平均候选池覆盖率 | **4.7%** |
| 理论最高 Recall@5（重排后）| 受限于池内覆盖 |

## 逐题明细

| 疾病（disease_focus，截短） | 金标基因数 | KG池大小(k=8×3query) | 重叠数 | 覆盖率 | 金标来源 |
|---|---|---|---|---|---|
| hereditary breast ovarian cancer syndrome | 20 | 21 | 4 | 20% | Open Targets + PrimeKG |
| hereditary breast carcinoma | 20 | 25 | 4 | 20% | Open Targets + PrimeKG |
| breast neoplasm | 20 | 25 | 4 | 20% | Open Targets + PrimeKG |
| squamous cell carcinoma of the corpus uteri | 20 | 25 | **0** | **0%** | PrimeKG (no OT match) |
| undifferentiated carcinoma of the corpus uteri | 20 | 25 | **0** | **0%** | PrimeKG (no OT match) |
| schizophrenia | 20 | 28 | 2 | 10% | PrimeKG (no OT match) |
| colorectal cancer | 20 | 26 | **0** | **0%** | PrimeKG (no OT match) |
| familial prostate carcinoma | 20 | 21 | **0** | **0%** | Open Targets + PrimeKG |
| prostate cancer | 20 | 21 | **0** | **0%** | Open Targets + PrimeKG |
| hepatocellular carcinoma | 20 | 21 | **0** | **0%** | Open Targets + PrimeKG |
| liver cancer | 20 | 21 | **0** | **0%** | PrimeKG (no OT match) |
| lung cancer | 20 | 20 | **0** | **0%** | PrimeKG (no OT match) |
| adenocarcinoma of liver and intrahepatic biliary t... | 20 | 16 | **0** | **0%** | PrimeKG (no OT match) |
| undifferentiated carcinoma of liver and intrahepat... | 20 | 16 | **0** | **0%** | PrimeKG (no OT match) |
| squamous cell carcinoma of liver and intrahepatic... | 20 | 16 | **0** | **0%** | PrimeKG (no OT match) |

## 代表性例子（hereditary breast ovarian cancer syndrome）

**KG 实际返回（DiseaseToGene k=8）**：ABCA3, ABCA4, ABCB1, ABCB10, AKT1, ALOX5, APRT, BRCA1  
（即：权重全0 → 字母序，ABC* 最先返回）

**金标基因（20条）**：BRCA2, BRCA1, PALB2, TP53, PIK3CA, CHEK2, ATM, RAD51C, CDH1, ERBB2...  
**重叠**：AKT1, BRCA1, ERBB2, ESR1（仅4/20 = 20%）

**结论**：即使重排，Recall@5 理论上限 = 4/20 = 0.20；  
而对于其余11道题，理论上限 = 0（金标基因根本不在候选池里）。

## 原因分析（INFERRED）

1. 当前 k=8（DiseaseToGene每次请求），加上3个角色各发2条query，去重后约20-26个候选基因
2. KG中每病有500-1156个关联基因，所有边权重=0.0，实际按 `gene ASC`（字母序）返回
3. 金标基因（BRCA2、TP53、APC、KRAS等）字母位置靠后，被截断在k=8之外
4. 即使 k 增至50-100，对于有1000+关联基因的疾病，BRCA2仍可能在 top-100 以内；但对仅500基因的疾病，仍需验证

## 重排可行性结论

- LLM重排对73%的样本无帮助（金标不在池里 → 重排不能凭空产生候选）
- 对剩余27%（主要是乳腺癌），增大k后LLM可能提升Recall，但信息来源是LLM参数记忆而非KG
- 增大k（8→100）技术上可行，但会显著增加LLM context负担和API成本
