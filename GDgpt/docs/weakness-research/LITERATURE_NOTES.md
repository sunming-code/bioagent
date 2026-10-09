# 文献笔记（每条引用已验证）

验证方式：DOI 走 `https://api.crossref.org/works/<doi>`；arXiv 走 `https://export.arxiv.org/api/query?id_list=<id>`；
Zenodo 走记录页。下表 **VERIFIED = 本次实际拿到标题/期刊/年份并与用途吻合**。

## 已验证可用

| 引用 | 标识 | 核实到的标题 / 出处 | 用途（对应弱点） |
|---|---|---|---|
| HippoRAG | arXiv **2405.14831** (v3, 2024-05-23) | *HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models* | ✅ VERIFIED。用 Personalized PageRank 在 KG 上做检索排序的代表作，是"查询时用图信号排序、不改图"的直接方法论依据 → 弱点 1 |
| Open Targets Platform | DOI **10.1093/nar/gkac1046** (NAR, 2022-11-18) | *The next-generation Open Targets Platform: reimagined, redesigned, rebuilt* | ✅ VERIFIED。证据加权 gene–disease association score 的权威来源；可作为外部边权注入候选 → 弱点 1 |
| DisGeNET | DOI **10.1093/nar/gkz1021** (NAR, 2019-11-04) | *The DisGeNET knowledge platform for disease genomics: 2019 update* | ✅ VERIFIED。另一套 gene–disease 证据分数（GDA score），可做 Open Targets 的交叉校验 → 弱点 1 |
| PrimeKG | DOI **10.1038/s41597-023-01960-3** (Sci Data, 2023-02-02) | *Building a knowledge graph to enable precision medicine* | ✅ VERIFIED。本系统 KG 的源头，引用 KG 本身的属性论证时必用 |
| Selective classification | arXiv **1705.08500** (v2, 2017-05-23) | *Selective Classification for Deep Neural Networks* (Geifman & El-Yaniv) | ✅ VERIFIED。risk–coverage 曲线与 selective risk 的标准定义来源；弃权实验从"8/8 百分比"升级为 risk–coverage / AURC 曲线的依据 → 弱点 3、5 |
| ALCE | DOI **10.18653/v1/2023.emnlp-main.398** (EMNLP 2023) | *Enabling Large Language Models to Generate Text with Citations* | ✅ VERIFIED。citation precision / recall 的标准定义；把 Traceability 从 Likert 分升级成可计算指标 → 弱点 2、5 |
| MTBBench | arXiv **2511.20490** (v1, 2025-11-25) | *MTBBench: A Multimodal Sequential Clinical Decision-Making Benchmark in Oncology* | ✅ VERIFIED。MTB 场景外部 benchmark，可取纵向文本子集扩 N → 弱点 3 |
| PrimeKGQA | DOI **10.5281/zenodo.13829395** (Zenodo, v2 2024-10-02, Univ. Hamburg) | *PrimeKGQA … Bridging the Gap: Generating a Comprehensive Biomedical KGQA Dataset*；83,999 QA + SPARQL；CC-BY-4.0；code github.com/xixi019/primeKGQG | ✅ VERIFIED。**与本系统同源 KG（PrimeKG）**，筛子集即可把 N 从 15 提到数百，且 gold 天然在 KG 内 → 弱点 3（性价比最高的扩 N 途径） |
| BioASQ | DOI **10.1186/s12859-015-0564-6** (BMC Bioinformatics, 2015-04-30) | *An overview of the BIOASQ large-scale biomedical semantic indexing and question answering competition* | ✅ VERIFIED。但领域是通用生物医学 QA，不是 MTB/基因-疾病机制，**与场景不匹配，建议不用** |

## 已拒绝（核实不通过或不适配）

| 候选 | 为什么拒 |
|---|---|
| `10.1186/1471-2105-16-138` 作为 BioASQ 的 DOI | Crossref 返回 `Resource not found`。正确的是 `10.1186/s12859-015-0564-6`。**不要用前者** |
| `10.1093/nar/gkae1067` 作为 Open Targets 2025 update | 实际解析到 *The Natural Products Magnetic Resonance Database (NP-MRD) for 2025*，**与 Open Targets 无关**。用 `10.1093/nar/gkac1046` |
| MedHop | 多跳阅读理解，语料是 MEDLINE 摘要而非 KG 三元组；与"KG 边级可追溯"的贡献对不上，扩 N 但不增强论点 |
| BioASQ（见上） | 已验证但场景不匹配，收益低于 PrimeKGQA |

## 方法要点摘录

**HippoRAG / PPR 检索（弱点 1 的核心方法）**
在 KG 上以查询中的实体为 seed 跑 Personalized PageRank，用 PPR 得分而不是边权排序邻居。
对本项目的意义：GDgpt 的边权全为空（`task_kg_edges.csv` 中 Drug–Disease 边 weight 全 `''`），
但 **图结构本身携带信号**——度数、共享通路数、source 数据库条数都可在查询时算出来，
不需要改 KG，也不需要 GDS 插件（纯 Cypher 的 degree / 共享邻居计数即可）。

**证据加权（弱点 1 的替代/互补路径）**
Open Targets 与 DisGeNET 都给出 (gene, disease) 的证据分数。把分数做成一张查询时读取的本地
lookup 表（而不是写回 Neo4j 边属性），即可在不动 KG 的前提下排序。注意：若 gold 本身部分来自
Open Targets（本项目 15 题里有 4 题标注 `Open Targets + PrimeKG`），用 Open Targets 分数排序
对这几题构成信息泄漏，**必须按 gold 来源分层报告**，否则是变相的 metric shopping。

**selective prediction（弱点 3、5）**
把当前"8/8 弃权 = 100%"换成 risk–coverage 曲线：横轴 coverage（回答比例），纵轴 selective risk
（在回答的那部分里的错误率），汇总成 AURC。好处：N=8 的二值结果升级为一条曲线，
并且可以把 GPT-4o 画在同一张图上（它的 coverage 恒为 1.0），对比更强且完全诚实。

**attribution precision / recall（弱点 2、5）**
ALCE 的做法：逐句判断该句是否被所引证据支持。本项目已经有 `cited_edges` 与
`expected_kg_edges` 两个字段，可直接算 citation precision（引用的边有多少真在 KG 里）
与 recall（KG 里该有的边有多少被引用），把 D3 从"评委 Likert 分"换成确定性数字——
这是对 LLM-judge 争议最彻底的回应。
