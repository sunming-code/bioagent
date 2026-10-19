# PRD：GDgpt —— 精准肿瘤学 MTB 辅助系统（Task KG + 多智能体）

> 产品需求文档（Product Requirements Document）
> 适用：毕业设计项目（毕设基线 + 发文章进阶）
> **版本：v2.0（当前主版本）**
> **更新：2026-04-26**
>
> ⚠️ **本文档于 2026-04 发生重大重构**：根据 2026-04-17 导师反馈与 2026-04-20 新场景定位研究（见 `docs/SCENARIO_AND_RESEARCH_PROPOSAL.md`），项目从"通用基因-疾病-通路机制问答"重定位为"**精准肿瘤学 MTB（分子肿瘤委员会）辅助工具**"。
>
> 旧版 v1.x 技术规格作为"附录 A"完整保留，不可删除。

---

## 📋 变更记录 (Changelog)

| 版本 | 日期 | 主要变更 |
| --- | --- | --- |
| **v2.0** | **2026-04-26** | **重大重构**：确立 MTB 主场景；新增用户画像/使用时刻/价值主张/7 角色 → MTB 席位映射；评测指标扩展 Traceability / Hallucination Rate / Clinical Utility；Baseline 升级为 4 档矩阵（GPT-4o / Single-Agent+KG / RAG only / OncoKB 手动）；测试集双轨策略（38 题消融 + 20 题 MTB + 15 题时间分割）；v1.3 技术规格完整保留为附录 A |
| v1.3 | 2026-03-13 | Bridge 查询 + 双知识库技术规格；毕设基线与发文章进阶任务清单 |
| v1.2 及以前 | — | 初版 PRD，基于 MDTeamGPT 改造的基础设计 |

---

## 目录

- [第 0 章：当前定位（MTB 辅助工具）](#第-0-章当前定位mtb-辅助工具)
- [第 1 章：项目背景](#第-1-章项目背景)
- [第 2 章：需求概述](#第-2-章需求概述)
- [第 3 章：系统架构](#第-3-章系统架构)
- [第 4 章：成果物](#第-4-章成果物)
- [第 5 章：测试与评测（v2.0 场景导向）](#第-5-章测试与评测v20-场景导向)
- [第 6 章：依赖与运行](#第-6-章依赖与运行)
- [第 7 章：阶段目标](#第-7-章阶段目标毕设基线-vs-发文章进阶)
- [第 8 章：待确认事项](#第-8-章待确认事项)
- [附录 A：v1.x 历史定位与技术规格存档](#附录-av1x-历史定位与技术规格存档)

---

## 第 0 章：当前定位（MTB 辅助工具）

### 0.1 一句话定义

> **GDgpt 帮助肿瘤科医生在分子肿瘤委员会（MTB, Molecular Tumor Board）准备阶段，快速生成某个癌症患者的"基因—疾病—通路—药物"机制解释报告，所有结论可追溯到知识图谱的具体边，并明确区分"图谱支持的事实" vs "LLM 推测"。**

### 0.2 为什么是 MTB 场景

| 维度 | 匹配情况 |
| --- | --- |
| **现有 KG 数据契合度** | PrimeKG 子图的 20 种疾病几乎全是主流癌症（breast / lung / hepatocellular / ovarian / prostate / pancreatic carcinoma 等） |
| **数据密度** | ASSOCIATED_WITH = 30,854；TARGETS = 18,392；TREATS + OFF_LABEL + CONTRAINDICATED = 574 |
| **Bridge 多跳价值** | MTB 医生天然需要 `disease → gene → pathway → drug` 链式推理 |
| **学术热点 (2025-2026)** | Nature Comm 2026 Knowledge Connector / Cancer Cell 2025 context-LLM / JCO-PO 2024 |
| **对标论文** | DeepRare (Nature 2026) / RareAgents (AAAI-26 Oral) / Knowledge Connector (Nature Commun 2026) |

### 0.3 目标用户画像

**用户 A：肿瘤科住院医生（Oncology Fellow）**

- **使用时刻**：MTB 会议前 1 天，手上 3-5 个复杂病例需要准备
- **传统方案**：手动查 OncoKB → CIViC → PubMed → ClinicalTrials，耗时 1-2 小时/例
- **通用 LLM 替代方案（2025）**：直接问 GPT-4o → 幻觉、来源不可追溯
- **GDgpt 价值**：自动生成机制草稿 + 所有结论可追溯到 KG 边 + 区分"图谱事实" vs "LLM 推测"

**用户 B：分子诊断实验室遗传咨询师**

- **使用时刻**：拿到测序报告后，向医生和患者解释"这个突变意味着什么"
- **需求**：同时解释基因功能、相关通路、疾病关联、可用药物
- **GDgpt 价值**：多角色 Agent 给出"基因视角 + 通路视角 + 药物视角"的完整解释

### 0.4 核心价值主张（对标导师 4 条反馈的直接回应）

| 导师反馈 | GDgpt v2.0 的回应 |
| --- | --- |
| "应用场景不明显，故事讲不好" | ✅ 精准定位 MTB 辅助：用户 = 肿瘤科医生 + 遗传咨询师；使用时刻 = MTB 会前准备 |
| "测试集要面向场景" | ✅ 双轨测试集：38 题 KG 优化集做消融 + 20 题 MTB 场景集做主实验 |
| "要有 baseline" | ✅ 4 档 Baseline：GPT-4o 直答 / 单 Agent+KG / RAG only / OncoKB 手动查 |
| "测系统不是测性能" | ✅ 新增 3 维指标：Traceability / Hallucination Rate / Clinical Utility（医生打分） |

### 0.5 7 个专家角色 → MTB 席位映射

| 系统 Agent 角色 | 对应真实 MTB 席位 |
| --- | --- |
| GeneCurator 基因管理员 | 分子病理学家 |
| DiseaseMechanismAnalyst 疾病机制分析师 | 临床肿瘤学家 |
| PathwayBiologist 通路生物学家 | 转化医学研究员 |
| PhenotypeMapper 表型映射员 | 临床遗传师 |
| DrugMechanismAnalyst 药物机制分析师 | 临床药师 |
| EvidenceReviewer 证据评审员 | 方法学质控 |
| HypothesisIntegrator 假设整合者 | **MTB 主席**（Lead Physician） |

→ 与 **RareAgents (AAAI-26 Oral)** 的多 Agent MDT 架构直接对标。

### 0.6 三层场景架构

| 层级 | 场景 | 论文定位 | 主要对标 |
| --- | --- | --- | --- |
| **主场景** | 精准肿瘤学 MTB 机制解释辅助 | 毕业论文聚焦 + 主实验 | Knowledge Connector, Nature Commun 2026 |
| **次场景** | 药物重定位线索生成 | 论文讨论 + 案例演示 | iKraph (Nature MI 2025), DrugReX (Bioinformatics 2025) |
| **泛化场景** | 罕见遗传病机制解释 | 论文展望 + 可扩展性演示 | DeepRare (Nature 2026), RareAgents (AAAI-26) |

---

## 第 1 章：项目背景

### 1.1 领域与问题

精准肿瘤学的 **分子肿瘤委员会（MTB）** 是整合基因组、病理、临床等多源证据的会诊机制；ESMO 已就转移性癌症的 NGS 使用给出官方推荐（Mosele et al., *Annals of Oncology* 2020, 31:1491–1505，DOI `10.1016/j.annonc.2020.07.014`）。MTB 准备阶段需要医生查阅 OncoKB、CIViC、PubMed 等多个异构来源，平均每例耗时 **1-2 小时**。

现有辅助方案的局限：

- **Knowledge Connector (Nature Commun 2026)**：关注可视化与数据整合，未提供**机制层面的多跳推理**
- **通用 LLM（GPT-4o / Claude-3.7）**：能生成流畅解释文本，但存在**幻觉**和**证据不可追溯**两大关键问题（Cancer Cell 2025）
- **专业数据库（OncoKB / CIViC）直查**：信息分散，需要医生自行整合

GDgpt 的定位是：**基于 PrimeKG 子图的多智能体机制解释系统**，为 MTB 准备阶段提供**可追溯、结构化、多角度**的基因-疾病-通路-药物机制报告。

### 1.2 技术基础

本项目基于 **MDTeamGPT** 多智能体框架进行改造：

- **LangGraph**：工作流编排（分诊 → KG 预取 → 专家会诊 → 安全评审）
- **LLM**：大语言模型负责推理、综合、规划
- **Streamlit**：交互式 Web 界面
- **FAISS**：本地向量库（CorrectKB / ChainKB）作为长期经验记忆
- **Neo4j Task KG**：基于 PrimeKG 构建的任务型子图（10,133 节点 / 87,838 边 / 20 种疾病）

移除原框架的视觉输入能力，聚焦于**纯文本的 MTB 机制解释**。

---

## 第 2 章：需求概述

### 2.1 核心需求（v2.0 场景驱动）

| 需求 ID | 描述 | 优先级 |
| --- | --- | --- |
| **R1** | 集成 Neo4j Task KG（Bolt 连接），支持基因、疾病、通路、表型、药物五类实体 | P0 |
| **R2** | 支持单跳与多跳（Bridge）查询，覆盖 `Disease→Gene→Pathway` / `Gene→Phenotype` / `Drug→Gene→Disease` 路径 | P0 |
| **R3** | 7 角色专家协同：GeneCurator / DiseaseMechanismAnalyst / PathwayBiologist / PhenotypeMapper / DrugMechanismAnalyst / EvidenceReviewer / HypothesisIntegrator | P0 |
| **R4** | 工作流中增加 KG Prefetch：在专家会诊前预取共享 Task KG 证据 | P0 |
| **R5** | 移除视觉输入，仅保留文本问题输入 | P1 |
| **R6** | 提供可复现的评测流程与指标，支持检索层与端到端层评估 | P1 |
| **R7** ✨ | **MTB 场景化输入**：支持输入 `clinical_context`（患者简要描述：年龄/分型/转移状态/变异）并以 MTB 报告格式输出 | P0 |
| **R8** ✨ | **可追溯性**：所有结论必须在输出中标注 KG 证据边（如 `[KG:ASSOCIATED_WITH]`），未被 KG 支持的推测需显式标记为"LLM 推测" | P0 |
| **R9** ✨ | **系统级指标支持**：产出 Traceability Score / Hallucination Rate 所需的结构化字段（evidence 引用、预测来源标签） | P0 |
| **R10** ✨ | **双轨测试集**：同时兼容 38 题 KG 优化集（消融）与 20 题 MTB 场景集（主实验），以及 15 题时间分割泛化集 | P1 |
| **R11** ✨ | **多档 Baseline 兼容**：系统设计需支持通过配置开关运行 GPT-4o 直答 / 单 Agent+KG / RAG only / 完整系统 四档对比 | P1 |

### 2.2 非功能需求

- **可配置**：Neo4j URI/用户/密码、LLM API、模型 ID 可通过 UI / config.json 配置
- **可解释**：UI 展示 triage 理由、专家输出、工具调用及 KG 查询结果
- **可评测**：提供 gold/prediction schema、指标计算脚本、baseline 与消融方案
- **临床可信**：系统输出严格区分"图谱事实 / 文献支持 / LLM 推测"三档可信度

---

## 第 3 章：系统架构

### 3.1 工作流

```
用户输入（问题 + 可选 clinical_context）
    ↓
[Triage] 分诊：选择专家角色（≥3，对应 MTB 席位）
    ↓
[KG Prefetch] 共享 Task KG 预取：LLM 规划 2-3 种 intent 并执行
    ↓
[Consultation] 专家会诊：各角色基于 prefetch + FAISS 上下文独立分析（同轮互盲）
    ↓
[Lead Physician / MTB 主席] 综合各专家意见
    ↓
[Safety Reviewer] 判断是否收敛，输出最终 MTB 报告
    ↓
（未收敛则进入下一轮会诊，最多 max_rounds 轮）
```

### 3.2 专家角色池（MTB 席位映射见 §0.5）

| 角色 | 职责 |
| --- | --- |
| GeneCurator | 基因规范化、别名、基因级证据质量 |
| DiseaseMechanismAnalyst | 疾病-基因机制、因果假设排序 |
| PathwayBiologist | 通路级 bridge 证据、机制级联 |
| PhenotypeMapper | 疾病/基因证据到表型、可观测性状 |
| DrugMechanismAnalyst | 治疗、靶点、禁忌、药物-基因-疾病链接 |
| EvidenceReviewer | 区分图谱支持的事实与弱/推测性主张 |
| HypothesisIntegrator (MTB 主席) | 多跳证据整合为连贯机制链；生成最终 MTB 报告 |

### 3.3 Task KG 查询意图（11 种）

**单跳（8 种）：**

- GeneToDisease, GeneToPathway
- DiseaseToGene, DiseaseToPathway, DiseaseToPhenotype
- DrugToDisease, DiseaseToDrug, GeneToDrug

**多跳 Bridge（3 种）：**

- **DiseaseGenePathwayBridge**：疾病 → 基因 → 通路（MTB 机制解释核心路径）
- **GenePhenotypeBridge**：基因 → 疾病 → 表型
- **DrugTargetDiseaseBridge**：药物 → 靶点基因 → 疾病（药物重定位核心路径）

### 3.4 知识图谱 Schema（Neo4j）

- **节点（5 类）**：Gene, Disease, Pathway, Phenotype, Drug
- **关系**：ASSOCIATED_WITH, INVOLVED_IN, HAS_PHENOTYPE, TREATS, TARGETS, OFF_LABEL_FOR, CONTRAINDICATED_FOR 等
- **数据来源**：PrimeKG → `create3.py` → `task_kg_output` → `import_magis_to_neo4j.py`
- **规模**：10,133 节点 / 87,838 边 / 20 种疾病（主流癌症为主）

### 3.5 技术实现说明与创新定位

#### 3.5.1 Bridge 多跳：实现方式

| 维度 | 说明 |
| --- | --- |
| **实现** | 使用 Neo4j Cypher 的**图模式匹配**，预定义 2 跳路径模板（如 `Disease-[ASSOCIATED_WITH]-Gene-[INVOLVED_IN]-Pathway`） |
| **算法** | 无自定义路径搜索算法，为标准 Cypher `MATCH` 遍历 + `collect` / `ORDER BY` 聚合 |
| **意图选择** | 由 **LLM Query Planning**：根据问题 + clinical_context + 角色，从 11 种 intent 中选 2–3 个执行 |
| **创新定位** | **任务导向的 KG 查询设计** + **LLM 驱动的查询规划**；表述为"设计并实现了基于 Bridge 意图的多跳 KG 查询"，而非"多跳推理算法" |

#### 3.5.2 双知识库（CorrectKB / ChainKB）：自进化机制

| 组件 | 内容 | 写入时机 |
| --- | --- | --- |
| **CorrectKB** | 成功案例：Question、Answer、S4 Summary | 用户填写 Ground Truth 且判定为正确 |
| **ChainKB** | 失败反思：Question、Correct Answer、Error Reflection | 用户填写 Ground Truth 且判定为错误 |

**检索**：`retrieve_context_details(query, k=2)` 对当前问题做向量相似检索，top-2 成功案例 + top-2 失败反思注入专家上下文（`PRIOR KNOWLEDGE FROM DB`）。

**当前局限与效果体现**：参见 [附录 A §A.3.5.2](#a35-技术实现说明与创新定位)。

#### 3.5.3 可追溯性实现（v2.0 新增）

为支持 Traceability Score 计算与 MTB 临床可信度要求：

| 机制 | 说明 |
| --- | --- |
| **KG 引用标签** | 专家输出中强制以 `[KG:<intent>:<src>→<dst>]` 形式标注每条结论的图谱证据边 |
| **LLM 推测标签** | 非 KG 支持的结论需前缀 `[LLM 推测]`，并由 EvidenceReviewer 角色复核 |
| **evidence 字段** | 最终输出的 JSON 结构中，每条 predicted_gene / pathway / drug 附带 `evidence_source` 字段 |

---

## 第 4 章：成果物

### 4.1 可运行系统

| 成果 | 说明 |
| --- | --- |
| Streamlit 应用 | `app.py`：问题输入、配置、事件流展示、KG 结果渲染 |
| 工作流 | `workflow.py`：triage → kg_prefetch → consultation → safety |
| 智能体 | `agents.py`：分诊、专家咨询、综合、安全评审、KG 查询规划 |
| 工具 | `tools.py`：Neo4j_KG（单跳 + Bridge）、可选 Web/PubMed |
| 知识库 | `knowledge_base.py`：FAISS CorrectKB / ChainKB |

### 4.2 评测资源（v2.0 双轨 + 新指标）

| 文件 / 目录 | 用途 |
| --- | --- |
| `evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl` | 轨道 A：**38 题** KG 优化集（内部消融，真实集） |
| `evaluation/evaluation_gold_final.jsonl` | ⚠️ **30 题** legacy 遗留集（非 38 题） |
| `evaluation/independent_testset/output/independent_gold_final.jsonl` | 原独立测试集（53 题，作为泛化参考） |
| `evaluation/mtb_testset_v1.jsonl` ✨ | 轨道 B：**20 题 MTB 场景集（主实验，待建）** |
| `evaluation/timesplit_testset.jsonl` ✨ | 轨道 C：**15 题时间分割泛化集（待建）** |
| `evaluation/compute_metrics.py` | 原检索 + 端到端指标 |
| `evaluation/compute_system_metrics.py` ✨ | **v2.0 新增**：Traceability / Hallucination Rate 自动计算 |
| `evaluation/utility_scoring_form.md` ✨ | **v2.0 新增**：医生打分表（Utility Score 1-5 + Likert 5 项） |
| `evaluation/baselines_and_ablation.md` | Baseline 与消融实验设计 |

---

## 第 5 章：测试与评测（v2.0 场景导向）

### 5.1 新 RQ（v2.0）

**RQ1 场景价值**：GDgpt 在 MTB 场景下，能否生成**比 GPT-4o 直答更可追溯、更低幻觉、更临床可用**的机制报告？

**RQ2 组件必要性**：在 MTB 场景下，Bridge 多跳查询 / 多 Agent 协同 / 双知识库 各自贡献多少？

**RQ3 可泛化性**：系统在时间分割泛化集（KG 覆盖外的新关联）上能否优雅降级？

### 5.2 评测指标（6 类，v2.0）

#### 5.2.1 保留的原指标（正确性）

| 指标 | 含义 | k 值 |
| --- | --- | --- |
| Gene Recall@k / Precision@k | 前 k 个预测基因与 gold 的匹配率 | k=5 |
| Pathway Recall@k / Precision@k | 同上，针对通路 | k=5 |
| Bridge Hit Rate | `bridge_found == gold_bridge` 样本比例 | — |
| Coverage | 四类实体（基因/通路/表型/药物）有预测的比例均值 | — |
| Gene F1 / Pathway F1 / Phenotype F1 | 2×P×R/(P+R) | — |

#### 5.2.2 新增系统级指标 ✨（回应"测系统不测性能"）

| 指标 | 定义 | 计算方式 | 对标 |
| --- | --- | --- | --- |
| **Traceability Score** | 输出中能追溯到 KG 边的结论占比 | 脚本统计 Agent 输出里 `[KG:...]` 标签的比例 / 全部结论句数 | DeepRare "traceable reasoning" |
| **Hallucination Rate** | 不能追溯到 KG / 文献的"编造"比例 | 人工标注 3 类（KG 支持 / 文献支持 / 编造），取"编造"比例 | Cancer Cell 2025 hallucination 评估 |
| **Mechanism Completeness** | 是否给出完整的 Disease → Gene → Pathway → Drug 链 | 0=缺失 / 1=部分 / 2=完整（人工打分） | — |
| **Clinical Utility Score** | 医生觉得这份报告对 MTB 决策有没有用 | 1-5 Likert，请 1-2 位肿瘤科医生打分 | Knowledge Connector 用户调研 |
| **Time-to-insight** | 系统输出 vs 人工准备所用时间 | 记录系统耗时，对比医生估计时间 | — |
| **Usability（5 维问卷）** | 可视化 / 整合度 / 工作流改善 / 效率 / 可信度 | 仿 Knowledge Connector 结构化用户调研 | Knowledge Connector (Nat Commun 2026) |

### 5.3 Baseline 矩阵（4 档，v2.0）

| 档位 | Baseline | 配置 | 能证明什么 |
| --- | --- | --- | --- |
| **Tier A 商业 LLM** | **GPT-4o 直答** | 裸 GPT-4o，无 KG | GPT-4o 很强，但无追溯 + 有幻觉 → 需要 KG |
| | Claude-3.7 直答（可选） | 裸 Claude | 排除模型偏差 |
| | GPT-4o + Web Search（可选） | GPT-4o + Bing | 加搜索仍不如结构化 KG 准确 |
| **Tier B 相关系统** | **单 Agent + KG** | 1 个综合 Agent 用同一 KG | 多 Agent 协同比单 Agent 好 |
| | **RAG only** | KG 查询结果塞给 LLM，不做 Bridge | 多跳 Bridge 比单跳 RAG 好 |
| **Tier C 专业方案** | **OncoKB 手动查询** | 医生手动查 OncoKB | 我们比人工快 + 更全 |
| | Knowledge Connector 风格聚合（可选） | 只做 KG 聚合，不做多跳推理 | 我们比单纯聚合多了机制推理 |

**毕设最低要求**：至少跑完 Tier A GPT-4o 直答 + Tier B 单 Agent+KG + Tier B RAG only 三档。

### 5.4 测试集双轨策略

| 轨道 | 测试集 | 规模 | 用途 | 状态 |
| --- | --- | --- | --- | --- |
| **A 内部消融** | `testset_kg_optimized_enriched.jsonl`（KG 优化集，真实 38 题）；⚠️`evaluation_gold_final.jsonl` 实为 30 题 legacy | 38 题 | 组件消融 / Baseline 自比 | ✅ 已有 |
| **B MTB 场景（主实验）** ✨ | `mtb_testset_v1.jsonl` | 20 题 | 论文主实验，医生打分 | 🔄 待建（Week 1 完成） |
| **C 时间分割（泛化）** ✨ | `timesplit_testset.jsonl` | 15 题 | PrimeKG 2023.07 后新关联 | 🔄 待建（可选） |

**轨道 B 数据来源**：
- OncoKB 2024-2025 新增 Level 1-2 可行动变异
- CIViC 2024+ 新证据条目
- ClinVar 2023.07+ Pathogenic / Likely Pathogenic
- 2024-2025 真实 MTB 案例报告（JCO Precision Oncology / Annals of Oncology）

**标注规范**：见 `evaluation/mtb_annotation_guideline.md`（待建）；由 1-2 位合作医生或遗传咨询师验证 `gold_actionable_genes` / `gold_pathways` / `gold_drugs` / `gold_evidence_source`。

### 5.5 评测流程

```
Step 1. 人工复核 gold 数据，产出 evaluation_gold_final.jsonl / mtb_testset_v1.jsonl
Step 2. 批量运行各档 baseline + 完整系统（run_batch_eval_template.py + 变体）
Step 3. 自动抽取 predicted_* 字段（extract_from_tool_calls.py）
Step 4. 自动计算原指标（compute_metrics.py）
Step 5. 自动计算系统级指标（compute_system_metrics.py：Traceability / Hallucination）
Step 6. 医生打分（utility_scoring_form.md）→ 汇入 results_summary.json
Step 7. 分组分析（analysis_by_coverage.py）+ 画图（plot_results.py）
```

### 5.6 消融实验矩阵

| 实验 ID | 配置 | 目的 |
| --- | --- | --- |
| **Exp-0 Full** | 完整系统（Full Task KG + 7 角色 + Bridge + KB） | 主实验基准 |
| Exp-1 LLM only | 关闭 Neo4j + FAISS | Baseline 1 |
| Exp-2 Single-hop KG | 仅单跳查询 | Baseline 2：验证 Bridge 价值 |
| Exp-3 No prefetch | 跳过 kg_prefetch | 消融：KG 预取价值 |
| Exp-4 No bridge | 仅单跳 intent | 消融：多跳查询价值 |
| Exp-5 Single-role | 单一综合角色 | 消融：多角色协同价值 |
| Exp-6 No KB | 不注入 CorrectKB/ChainKB | 消融：双知识库价值 |
| **Exp-7 GPT-4o** ✨ | Tier A 外部 baseline | 证明 KG 必要性 |
| **Exp-8 RAG only** ✨ | Tier B 外部 baseline | 证明多跳设计价值 |

**所有实验固定**：`max_rounds=6`，`temperature(gen)=0.7`，`temperature(critic)=0.0`，记录 text_model 版本。

### 5.7 论文主表（v2.0 模板）

**表 5-1：主实验（MTB 场景集，20 题）**

| 系统 | Traceability↑ | Halluc Rate↓ | Gene F1 | Pathway F1 | Bridge Hit | Utility (1-5)↑ |
| --- | --- | --- | --- | --- | --- | --- |
| GPT-4o 直答 | — | — | — | — | — | — |
| 单 Agent + KG | — | — | — | — | — | — |
| RAG only | — | — | — | — | — | — |
| **GDgpt Full** | — | — | — | — | — | — |

**表 5-2：组件消融（KG 优化集，38 题）**

| 实验 | Bridge | Prefetch | 多角色 | KB | Gene F1 | Pathway F1 | Bridge Hit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Exp-0 Full | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Exp-3 No prefetch | ✓ | ✗ | ✓ | ✓ | — | — | — |
| Exp-4 No bridge | ✗ | ✓ | ✓ | ✓ | — | — | — |
| Exp-5 Single-role | ✓ | ✓ | ✗ | ✓ | — | — | — |
| Exp-6 No KB | ✓ | ✓ | ✓ | ✗ | — | — | — |

---

## 第 6 章：依赖与运行

### 6.1 环境

- Python 3.8+
- uv 虚拟环境（推荐）
- Neo4j 数据库（Bolt 7687）
- LLM API（如 DashScope/Qwen / OpenAI 兼容接口）

### 6.2 启动

```bash
streamlit run app.py
```

### 6.3 配置项

- API Key、Base URL、Text Model
- Neo4j URI、Username、Password、Database
- Enable Tools（Web/PubMed）
- Max Discussion Rounds（实验建议固定 6）

---

## 第 7 章：阶段目标（毕设基线 vs 发文章进阶）

| 阶段 | 目标 | 核心任务 |
| --- | --- | --- |
| **毕设基线** | 满足答辩要求 | 系统验收 + MTB 测试集构建 + 4 档 baseline 对比 + 2-3 个案例分析 |
| **发文章进阶** | 满足投稿要求 | 方法强化 + 医生打分完整 + 完整消融 + 公开 benchmark 接入 |

### 7.1 毕设基线任务清单（v2.0）

```
[ ] S1–S4 系统验收通过（含 R7-R9 新增需求）
[ ] E1 轨道 A 38 题消融实验完成（Exp-0 / Exp-3 / Exp-4 / Exp-5 / Exp-6）
[ ] E2 ✨ 轨道 B 20 题 MTB 场景测试集构建 + 医生验证
[ ] E3 ✨ Tier A 至少 1 档（GPT-4o 直答）+ Tier B 两档（单 Agent+KG / RAG only）跑通
[ ] E4 ✨ Traceability / Hallucination Rate 自动计算脚本实现
[ ] E5 ✨ 至少 1-2 位医生对 20 题 MTB 输出打 Utility Score
[ ] E6 至少 3 个案例分析（1 成功 + 1 失败 + 1 典型 MTB 病例）
[ ] E7 双知识库效果定性说明
[ ] D1–D5 论文/报告初稿完成（按新叙事结构：MTB 背景 → 用户研究 → 系统 → 场景导向实验 → 案例 → 局限与泛化）
[ ] 答辩 PPT 与演示准备
```

### 7.2 发文章进阶

详见原 v1.3 附录 A §A.7.2；v2.0 新增：

- **M4 ✨ 医生打分完整化**：扩展到 3-5 位医生，计算一致性（Cohen's kappa）
- **M5 ✨ 时间分割泛化实验**：轨道 C 15 题完整跑完 + 统计显著性检验
- **M6 ✨ 外部 Baseline 全覆盖**：补齐 Claude-3.7 / GPT-4o+Web / GraphRAG / OncoKB 手动查

### 7.3 阶段推进建议（2026-04 更新）

| 阶段 | 建议顺序 | 周期 |
| --- | --- | --- |
| **Week 1（4-27 ~ 5-03）** | 构建 20 题 MTB 测试集 + 实现 Traceability / Hallucination 脚本 + 跑 GPT-4o / Single-Agent 两档 baseline | 1 周 |
| **Week 2（5-04 ~ 5-10）** | 在 MTB 测试集上跑全部实验 + 2-3 个案例分析 + 论文草稿 v0.1 | 1 周 |
| **Week 3+（5-11 ~）** | 联系医生打分 + 根据反馈迭代 + 进入发文章进阶阶段 | 可选 |

---

## 第 8 章：待确认事项

以下 5 项来自 `docs/导师汇报文档.md` 第八章，等待导师确认（截至 2026-04-26）：

1. **MTB 作为主场景是否认可？** 若不认可或希望调整方向，请导师指出。
2. **测试集策略是否可行？** 38 题消融 + 20 题 MTB + 15 题泛化的规模与时间投入是否合理？
3. **新增的系统级指标（Traceability / Hallucination / Utility）是否符合预期？** 特别是 Utility Score 需要医生打分，是否有合作医生资源？
4. **Gene Recall = 5.5% 是否需要新方案中重点解决？** 还是通过分层分析（High/Medium/Low coverage）合理解释？
5. **论文投稿目标？** 先满足毕设答辩 vs 同步瞄准期刊/会议？

---

# 附录 A：v1.x 历史定位与技术规格存档

> ⚠️ 以下为 v1.3（2026-03-13）原 PRD 内容，完整保留以供追溯历史演进过程。
> **v2.0 新定位以正文（第 0-8 章）为准；技术规格部分（§3.5 / §5 指标定义）已在正文中同步更新。**

## A.1 原项目名称与定位

**原名**：基于 Task KG 的多智能体基因-疾病-通路机制分析系统

**原定位**：通用生物医学 KGQA，回答「疾病→基因/通路/表型/药物」类多跳机制问题。

## A.2 原需求概述（v1.3）

| 需求 ID | 描述 | 优先级 |
| --- | --- | --- |
| R1 | 集成 Neo4j Task KG（Bolt 连接），支持基因、疾病、通路、表型、药物五类实体 | P0 |
| R2 | 支持单跳与多跳（Bridge）查询 | P0 |
| R3 | 多角色专家协同 | P0 |
| R4 | 工作流中增加 KG Prefetch | P0 |
| R5 | 移除视觉输入，仅保留文本问题输入 | P1 |
| R6 | 提供可复现的评测流程与指标 | P1 |

## A.3 原系统架构技术规格（v1.3）

### A.3.5 技术实现说明与创新定位（原文保留）

#### A.3.5.2 双知识库（CorrectKB / ChainKB）效果体现要求

| 阶段 | 要求 |
| --- | --- |
| **毕设** | 设计说明 + 1–2 个定性案例（有历史 vs 无历史对比），说明历史如何影响回答 |
| **发文章** | 增加「无 KB」消融、KB 预填充实验，报告检索命中率/引用率等 |

**当前局限**：
- 依赖人工 Ground Truth 才写入，批量评测时通常为空
- 冷启动：初始 KB 为空
- 未做「有 KB vs 无 KB」消融，难以量化效果

## A.4 原评测指标（v1.3）

**检索层**：Gene/Pathway Recall@k / Precision@k、Bridge Hit Rate、Coverage
**端到端**：Gene/Pathway/Phenotype F1、Mechanism Completeness、Graph Faithfulness、Utility Score

**v1.3 Baseline（仅 1 档）**：LLM only（关闭 Neo4j + FAISS）

> v2.0 已将 Baseline 升级为 4 档矩阵，详见正文 §5.3。

## A.5 原实验矩阵（v1.3）

| 实验 ID | 配置 | 目的 |
| --- | --- | --- |
| Exp-0 | 完整系统（Full Task KG） | 主实验 |
| Exp-1 | LLM only（关闭 Neo4j + FAISS） | 衡量纯 LLM 能力 |
| Exp-2 | 至少 2 个案例分析 | 定性分析 |

## A.6 原毕设任务清单（v1.3）

```
[ ] S1–S4 系统验收通过
[ ] E1–E7 评测与实验完成（含双知识库定性说明）
[ ] D1–D5 论文/报告初稿完成
[ ] 答辩 PPT 与演示准备
```

## A.7 原发文章进阶（v1.3）

### A.7.2 原发文章进阶任务

| 任务 | 说明 |
| --- | --- |
| M1 | Query Planning 策略 |
| M2 | Bridge 路径发现/排序 |
| M3 | 多智能体协作机制 |
| B1–B4 | 公开 Benchmark 接入（BioASQ / MedQA 等） |
| A1–A5 | 完整消融（含双知识库消融 A5） |
| R1–R3 | 数据与复现公开 |

## A.8 v1.3 待确认事项（已被 v2.0 待确认事项替代）

1. 项目名称：是否采用「基于 Task KG 的多智能体基因-疾病-通路机制分析系统」
2. 创新表述：Bridge + 双知识库表述是否与导师预期一致
3. 毕设基线清单
4. 发文章进阶任务
5. 时间安排

→ **v2.0 已根据 2026-04 导师反馈全面重构，详见正文 §0 与 §8。**

---

*本文档由 2026-04-26 v2.0 重构，历史版本保留为附录 A；后续修改请遵循"Changelog + 版本号 + 更新日期"三件套。*
