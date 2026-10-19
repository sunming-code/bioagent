# 📋 GDgpt 实验方案

> **项目**：GDgpt —— 精准肿瘤学 MTB 辅助系统（Task KG + 多智能体）
> **当前版本**：**v2.0（场景导向评测）**
> **更新日期**：**2026-04-26**
>
> ⚠️ **本文档于 2026-04 发生重大重构**。根据 2026-04-17 导师反馈（"应用场景不明显 / 测试集要面向场景 / 要有 baseline / 测系统不测性能"），实验方案从"性能导向（P/R/F1 对比 LLM only）"升级为"**场景导向（MTB 可追溯/低幻觉/临床效用）**"。
>
> **Part I（正文）= v2.0 新方案**；**Part II（文末）= v1.0 原方案存档**，保留可追溯。

---

## 📋 变更记录 (Changelog)

| 版本 | 日期 | 主要变更 |
| --- | --- | --- |
| **v2.1** | **2026-04-26（晚间增量）** | **测试集策略升级为"3 轨混搭 70 题"**：B1 PrimeKGQA 癌症子集 40 题（Zenodo 13829395）+ B2 MTBBench 纵向文本子集 20 题（arXiv 2511.20490）+ B3 自制 MTB 补充集 10 题。放弃原"纯自造 20 题"方案，改为"站在外部权威 benchmark 肩膀上"。见 `docs/DECISION_LOG.md` D-2026-04-26-03/04。 |
| **v2.0** | **2026-04-26** | **场景导向重构**：新 RQ（可追溯/低幻觉/临床效用）；3 个新指标（Traceability / Hallucination Rate / Clinical Utility）；4 档外部 Baseline（GPT-4o / 单 Agent+KG / RAG only / OncoKB 手动）；双轨测试集（38 题消融 + 20 题 MTB 主实验 + 15 题时间分割泛化） |
| v1.0 | 2026-03-31 | 初版：分层分析策略（High/Medium/Low coverage）；80 题独立测试集；Exp-0 / Exp-1 / Exp-2 主实验 + 4 个消融实验 |

---

## 目录（Part I：v2.0 主方案）

1. [实验方案的"破题思路"](#1-实验方案的破题思路回应导师反馈)
2. [Part I — 新 RQ（v2.0）](#part-i--新-rqv20)
3. [Part I — 评测指标体系（v2.0）](#part-i--评测指标体系v20)
4. [Part I — Baseline 4 档矩阵](#part-i--baseline-4-档矩阵)
5. [Part I — 测试集双轨策略](#part-i--测试集双轨策略)
6. [Part I — 实验矩阵与流程](#part-i--实验矩阵与流程)
7. [Part I — 两周执行计划](#part-i--两周执行计划)
8. [Part II — v1.0 原方案存档](#part-ii--v10-原方案存档)

---

## 1. 实验方案的"破题思路"（回应导师反馈）

### 1.1 导师反馈原句 → 翻译成研究语言 → 破题方向

| 导师原话 | 翻译成研究语言 | v2.0 破题方向 |
| --- | --- | --- |
| "应用场景不明显，故事讲不好" | 你没说清给谁用、解决什么真实痛点 | 明确**用户角色（MTB 肿瘤医生） + 使用时刻（MTB 会前） + 可替代方案** |
| "测试集要面向场景" | Gold 标签不能只来自 KG 本身（循环评测） | **以真实临床任务为出发点反向设计测试集**（OncoKB / CIViC / MTB 案例报告） |
| "测系统不是测性能" | F1 = 0.05 体现不出"系统能不能用" | 新增**可用性 / 可追溯性 / 幻觉率 / 临床效用** 4 维度 |
| "要有 baseline" | 不能只跟"LLM Only 全零"比，这是无效对比 | 跟**医生真正会用的替代方案**比（GPT-4o / RAG only / OncoKB 手动） |

### 1.2 一句话总结 v2.0 方案

> **不再追求"KG 一定比 LLM F1 高"，而是回答：GDgpt 在 MTB 场景下，能否给医生一份 GPT-4o 给不了的"可追溯、低幻觉、临床可用"的机制报告？**

---

# Part I — 新 RQ（v2.0）

## 2. 研究问题重构

**RQ1 场景价值（核心）**：GDgpt 在 MTB 场景下，能否生成**比 GPT-4o 直答更可追溯、更低幻觉、更临床可用**的机制报告？

**RQ2 组件必要性**：在 MTB 场景下，Bridge 多跳查询 / 多 Agent 协同 / 双知识库 三个组件各自贡献多少？

**RQ3 可泛化性**：系统在时间分割泛化集（KG 覆盖外的新关联）上能否优雅降级？

> v1.0 的旧 RQ（"KG 能否提升 F1 / 在何种条件下最有效 / KG 不足如何降级"）仍部分有效，但**不再作为主论点**。见 [Part II](#part-ii--v10-原方案存档)。

---

# Part I — 评测指标体系（v2.0）

## 3. 六类指标（保留 + 新增）

### 3.1 保留的原指标（正确性维度）

| 指标 | 公式 / 含义 | k 值 |
| --- | --- | --- |
| Gene Recall@k / Precision@k | 前 k 个预测基因中命中 gold 的比例 | k=5 |
| Pathway Recall@k / Precision@k | 同上，针对通路 | k=5 |
| Bridge Hit Rate | `bridge_found == gold_bridge` 样本比例 | — |
| Coverage | 四类实体（基因/通路/表型/药物）有预测的比例均值 | — |
| Gene F1 / Pathway F1 / Phenotype F1 | 2×P×R / (P+R) | — |

### 3.2 新增系统级指标 ✨（回应"测系统不测性能"）

| 指标 | 定义 | 计算方式 | 对标 |
| --- | --- | --- | --- |
| **Traceability Score** | 输出中能追溯到 KG 边的结论占比 | 自动脚本统计 `[KG:...]` 标签的句数 / 全部结论句数 | DeepRare (Nature 2026) "traceable reasoning" |
| **Hallucination Rate** | 不能追溯到 KG / 文献的"编造"比例 | 人工标注 3 类（KG 支持 / 文献支持 / 编造），取"编造"比例 | Cancer Cell 2025 hallucination 评估 |
| **Mechanism Completeness** | 是否给出完整的 Disease → Gene → Pathway → Drug 链 | 0=缺失 / 1=部分 / 2=完整（人工打分） | — |
| **Clinical Utility Score** | 医生觉得这份报告对 MTB 决策有没有用 | 1-5 Likert，请 1-2 位肿瘤科医生打分 | Knowledge Connector (Nature Commun 2026) 用户调研 |
| **Time-to-insight** | 系统输出 vs 人工准备所用时间 | 记录系统耗时，对比医生估计时间 | — |
| **Usability 5 维问卷** | 可视化 / 整合度 / 工作流改善 / 效率 / 可信度 | 仿 Knowledge Connector 结构化问卷 | Knowledge Connector |

### 3.3 指标计算与人工标注实施

| 指标类别 | 实施方式 | 脚本 / 表单 |
| --- | --- | --- |
| 自动指标（原 P/R/F1 + Traceability） | 脚本一键跑 | `evaluation/compute_metrics.py` + `evaluation/compute_system_metrics.py` ✨ |
| 半自动（Hallucination Rate） | 脚本初筛 + 人工复核 | `evaluation/hallucination_annotation.jsonl` ✨ |
| 纯人工（Mechanism / Utility） | 医生打分表 | `evaluation/utility_scoring_form.md` ✨ |

---

# Part I — Baseline 4 档矩阵

## 4. Baseline 设计

相比 v1.0 只有"LLM only"一档（且检索层全零，对比无信息量），v2.0 引入 **4 档** Baseline，覆盖"商业 LLM / 相关系统 / 专业方案"三个层次。

### 4.1 Tier A：商业最强 LLM（证明 KG 的必要性）

| Baseline | 配置 | 能证明什么 |
| --- | --- | --- |
| **GPT-4o 直答** | 裸 GPT-4o，无 KG、无工具 | GPT-4o 很强，但**无可追溯 + 有幻觉** → 需要 KG |
| Claude-3.7 直答（可选） | 裸 Claude | 排除模型偏差 |
| GPT-4o + Web Search（可选） | GPT-4o + Bing | 加搜索仍不如结构化 KG 准确 |

### 4.2 Tier B：相关系统（证明我们的架构）

| Baseline | 配置 | 能证明什么 |
| --- | --- | --- |
| **单 Agent + KG** | 1 个综合 Agent 用同一 KG | 多 Agent 协同比单 Agent 好 |
| **RAG only** | KG 查询结果塞给 LLM，不做 Bridge | 多跳 Bridge 比单跳 RAG 好 |
| GraphRAG（可选） | 微软 GraphRAG | 我们的 Bridge 设计比通用 GraphRAG 好 |

### 4.3 Tier C：专业方案（证明临床价值）

| Baseline | 配置 | 能证明什么 |
| --- | --- | --- |
| **OncoKB 手动查询** | 医生手动查 OncoKB | 我们比人工快 X 倍，信息更全 |
| Knowledge Connector 风格聚合（可选） | 只做 KG 聚合，不做多跳推理 | 我们比单纯聚合多了机制推理 |

### 4.4 毕设最低要求

| 必做 | 档位 | 实验 ID |
| --- | --- | --- |
| ✅ | Tier A GPT-4o 直答 | Exp-7 |
| ✅ | Tier B 单 Agent + KG | 由 Exp-5 Single-role 复用 |
| ✅ | Tier B RAG only | Exp-8 |
| 建议 | Tier C OncoKB 手动（5 题抽样对比） | Exp-9 |

---

# Part I — 测试集双轨策略

## 5. 三轨混搭测试集设计（v2.1 升级）

> **v2.1 重大更新（2026-04-26 晚间）**：在完成外部 benchmark 调研后，**放弃"纯自造 20 题"方案**，改为"**外部权威 benchmark + 自制特色补充**"混搭策略。这直接化解 reviewer 两个常见质疑：(1) 循环评测 (2) 测试集有偏。

### 5.1 总览

```
┌─────────────────────────────────────────────────────────────┐
│           GDgpt v2.1 测试集架构（2026-04-26 更新）           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  轨道 A：组件消融（内部基准，已有）                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 38 题 KG 优化集（testset_kg_optimized_enriched.jsonl）│   │
│  │ · 用途：Bridge / 多 Agent / KB 组件消融             │   │
│  │ · 不作为论文主实验                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  轨道 B：主实验（3 档混搭，共 70 题）                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ B1. PrimeKGQA 癌症子集（40 题）✨                    │   │
│  │     · 来源：Zenodo 13829395（2024-10, Hamburg）     │   │
│  │     · 用途：KG 推理能力基准                           │   │
│  │     · 金标：SPARQL 查询结果（外部可验）              │   │
│  │     · 文件：evaluation/external_benchmarks/         │   │
│  │              b1_primekgqa_cancer40.jsonl             │   │
│  │                                                     │   │
│  │ B2. MTBBench 纵向文本子集（20 题）✨                │   │
│  │     · 来源：arXiv 2511.20490（2025-11, ETH+EPFL+HUG）│   │
│  │     · 用途：真实 MTB 场景基准                        │   │
│  │     · 金标：原 benchmark 多选题已标注                 │   │
│  │     · 文件：evaluation/external_benchmarks/         │   │
│  │              b2_mtbbench_text20.jsonl                │   │
│  │     · 限制：只取纵向文本轨（我们不支持多模态图像）    │   │
│  │                                                     │   │
│  │ B3. 自制 MTB 补充集（10 题）✨                      │   │
│  │     · 来源：OncoKB 2024-2025 Level 1-2 + 真实案例  │   │
│  │     · 用途：展示 Bridge 多跳 + 多角色协同特色         │   │
│  │     · 标注：作者验证（若有合作医生则 clinician 复核）│   │
│  │     · 文件：evaluation/mtb_supp_v1.jsonl             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  轨道 C：时间分割泛化（可选）                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 15 题时间分割集（Open Targets 2023.07+ 新关联）     │   │
│  │ · 目的：测试 KG 覆盖外的优雅降级能力                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 B1: PrimeKGQA 癌症子集（40 题）

**数据集原貌**：
- 规模：83,999 个 QA + SPARQL（train/val/test 三分）
- 许可：CC BY 4.0（商用可改写）
- 下载：`wget https://zenodo.org/records/13829395/files/test_call_bioLLM.json`

**筛选策略**（Day 1-2 任务）：
```python
# 伪代码：筛 test 集里与癌症相关的条目
cancer_keywords = ["carcinoma", "cancer", "tumor", "neoplasm", "leukemia", ...]
for q in primekgqa_test:
    if any(kw in q.text.lower() for kw in cancer_keywords):
        if involves_entity_type(q, ["Disease", "Gene", "Drug"]):
            candidates.append(q)
# 从候选中按多跳/单跳均衡分层采样 40 题
```

**格式对齐**：需将 PrimeKGQA 的 (question, answer, SPARQL) 三元组改写为我们的 schema，SPARQL 答案作为 `gold_entities`。

### 5.3 B2: MTBBench 纵向文本子集（20 题）

**数据集原貌**：
- 规模：多模态轨 390 题 + 纵向轨 183 题 = 573 题
- 数据源：HANCOCK（头颈癌多模态）+ MSK-CHORD（基因组+临床时间线）
- 格式：多选题（6 选项）+ 判断题
- 开源：GitHub bunnelab/MTBBench + HuggingFace EeshaanJain/MTBBench

**筛选策略**：
```python
from datasets import load_dataset
ds = load_dataset("EeshaanJain/MTBBench", split="longitudinal")
# 只取纯文本题（无图像依赖）
text_only = ds.filter(lambda x: not x.get("requires_image", False))
# 按任务类型分层采样：治疗映射 8 + 结果预测 6 + 进展预测 6
```

### 5.4 B3: 自制 MTB 补充集（10 题）

**题目格式（完整示例）**：

```json
{
  "id": "MTB_supp_001",
  "question": "58yo F with HER2+ breast cancer, liver metastasis, post-trastuzumab progression. What actionable alterations and mechanism-based therapies are available?",
  "clinical_context": {
    "age": 58, "sex": "F",
    "histology": "Invasive ductal carcinoma, HER2 IHC 3+",
    "stage": "IV (hepatic metastasis)",
    "prior_therapy": ["Trastuzumab 14 months → PD"],
    "biomarkers": ["HER2 amp", "PIK3CA H1047R"]
  },
  "gold_actionable_genes": ["ERBB2", "PIK3CA"],
  "gold_pathways": ["ERBB signaling", "PI3K/AKT/mTOR"],
  "gold_drugs": [
    {"name": "T-DXd", "level": "OncoKB-1", "evidence": "DESTINY-Breast03 NEJM 2022"},
    {"name": "Alpelisib", "level": "OncoKB-1", "evidence": "SOLAR-1 NEJM 2019"},
    {"name": "Tucatinib", "level": "OncoKB-1", "evidence": "HER2CLIMB NEJM 2020"}
  ],
  "gold_mechanism_sentence": "HER2 amplification drives PI3K/AKT and MAPK; post-trastuzumab resistance often involves PI3K bypass (here supported by PIK3CA H1047R). Options: HER2-ADC (T-DXd), HER2-TKI (Tucatinib), or PI3Kα inhibitor (Alpelisib).",
  "expected_kg_edges": [
    {"from": "ERBB2", "to": "breast carcinoma", "type": "ASSOCIATED_WITH"},
    {"from": "Trastuzumab-deruxtecan", "to": "ERBB2", "type": "TARGETS"},
    {"from": "Alpelisib", "to": "PIK3CA", "type": "TARGETS"},
    {"from": "ERBB2", "to": "PI3K/AKT/mTOR", "type": "INVOLVED_IN"}
  ],
  "expected_bridge_intents": ["DiseaseGenePathwayBridge", "DrugTargetDiseaseBridge"],
  "cancer_type": "breast carcinoma",
  "task_type": "targeted_therapy_resistance",
  "difficulty": "medium",
  "annotation_status": "author_verified",
  "evidence_source": "OncoKB 2024-11; DESTINY-Breast03; SOLAR-1"
}
```

**10 题分布**（聚焦 Bridge 多跳能力的 5 癌种×2 场景类型）：

| 癌症 | 机制解释 | 耐药分析 | 小计 |
|---|:---:|:---:|:---:|
| breast carcinoma | 1 | 1 | 2 |
| lung carcinoma | 1 | 1 | 2 |
| hepatocellular carcinoma | 1 | 1 | 2 |
| ovarian carcinoma | 1 | 1 | 2 |
| pancreatic carcinoma | 1 | 1 | 2 |
| **合计** | 5 | 5 | **10** |

### 5.5 历史测试集的处置

| v1.0 测试集 | v2.1 定位 | 文件路径 |
| --- | --- | --- |
| 30 题原 gold（从 PrimeKG 自动生成） | ⚠️ **废弃**（循环评测） | 已删除 |
| 38 题 KG 优化集 | ✅ 轨道 A（消融，真实集） | `evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl` |
| 30 题 legacy 集 | ⚠️ 非 38 题，历史遗留 | `evaluation/evaluation_gold_final.jsonl` |
| 53/80 题 independent testset | ℹ️ 仅历史参考 | `evaluation/independent_testset/output/` |
| **20 题 mtb_testset_v1**（v2.0 方案） | ❌ **放弃**（v2.1 改为 B1+B2+B3 混搭） | — |
| **B1 PrimeKGQA 癌症 40 题** ✨ | 🔄 待建 | `evaluation/external_benchmarks/b1_primekgqa_cancer40.jsonl` |
| **B2 MTBBench 纵向 20 题** ✨ | 🔄 待建 | `evaluation/external_benchmarks/b2_mtbbench_text20.jsonl` |
| **B3 自制 MTB 补充 10 题** ✨ | 🔄 待建 | `evaluation/mtb_supp_v1.jsonl` |
| **15 题时间分割集** ✨ | 🔄 可选 | `evaluation/timesplit_testset.jsonl` |

### 5.6 论文 Experimental Setup 写法范例

> We evaluate on **three benchmarks** to ensure robust and unbiased assessment:
> (1) **PrimeKGQA cancer subset** (N=40), filtered from the PrimeKGQA test split [Wessling et al. 2024] for evaluating KG reasoning capability;
> (2) **MTBBench longitudinal subset** (N=20), text-only questions drawn from [Jain et al. 2025] for real-world MTB scenario evaluation;
> (3) our **curated MTB supplementary set** (N=10), constructed from OncoKB 2024-2025 Level 1-2 variants and published MTB case reports, focused on multi-hop reasoning and role-collaboration capability.
>
> Component ablations are conducted on the **38-question KG optimization set** (internal benchmark). All external-benchmark questions use their original gold annotations to avoid author-introduced bias.

---

# Part I — 实验矩阵与流程

## 6. 实验矩阵（v2.0）

### 6.1 主实验（必做，在轨道 B 20 题 MTB 场景集上跑）

| 实验 ID | 配置 | 目的 | 优先级 |
| --- | --- | --- | :---: |
| **Exp-0 Full** | 完整系统（Full Task KG + 7 角色 + Bridge + KB） | 主实验基准 | P0 |
| **Exp-7 GPT-4o** ✨ | Tier A 裸 GPT-4o 直答 | 证明 KG 必要性 | P0 |
| **Exp-5 Single-role** | 单一综合 Agent + KG（复用为 Tier B） | 证明多角色协同价值 | P0 |
| **Exp-8 RAG only** ✨ | KG 查询塞给 LLM，不做 Bridge（Tier B） | 证明多跳 Bridge 价值 | P0 |

### 6.2 组件消融（在轨道 A 38 题 KG 优化集上跑）

| 实验 ID | 配置 | 目的 | 优先级 |
| --- | --- | --- | :---: |
| Exp-0 Full（基准） | 完整系统 | — | P0 |
| Exp-1 LLM only | 关闭 Neo4j + FAISS | v1.0 遗留，仅作参考 | P1 |
| Exp-2 Single-hop KG | 仅单跳查询 | 消融：Bridge 价值 | P1 |
| Exp-3 No prefetch | 跳过 kg_prefetch | 消融：KG 预取价值 | P1 |
| Exp-4 No bridge | 仅单跳 intent | 消融：多跳查询价值 | P1 |
| Exp-6 No KB | 不注入 CorrectKB / ChainKB | 消融：双知识库价值 | P2 |

### 6.3 泛化实验（在轨道 C 15 题时间分割集上跑，可选）

| 实验 ID | 配置 | 目的 |
| --- | --- | --- |
| Exp-0 Full（泛化） | 完整系统 | 测试 KG 覆盖外的优雅降级 |
| Exp-7 GPT-4o（泛化） | Tier A | 对照：LLM 在新关联上的表现 |

### 6.4 评测流程（7 步）

```
Step 1. 人工复核 gold 数据
   - 轨道 A：evaluation_gold_final.jsonl（已完成）
   - 轨道 B：mtb_testset_v1.jsonl（Week 1 完成，请医生验证）

Step 2. 批量运行各档 baseline + 完整系统
   python evaluation/run_batch_eval_template.py \
     --gold evaluation/mtb_testset_v1.jsonl \
     --out evaluation/results/exp0_mtb.jsonl \
     --experiment full --max-rounds 6

Step 3. 自动抽取 predicted_* 字段
   python evaluation/extract_from_tool_calls.py \
     --pred evaluation/results/exp0_mtb.jsonl \
     --out evaluation/results/exp0_mtb_extracted.jsonl

Step 4. 自动计算原指标
   python evaluation/compute_metrics.py \
     --gold evaluation/mtb_testset_v1.jsonl \
     --pred evaluation/results/exp0_mtb_extracted.jsonl --k 5

Step 5. ✨ 自动计算系统级指标（Traceability / Hallucination 初筛）
   python evaluation/compute_system_metrics.py \
     --pred evaluation/results/exp0_mtb_extracted.jsonl

Step 6. ✨ 医生打分（Utility + Mechanism Completeness）
   - 医生填写 evaluation/utility_scoring_form.md
   - 结果汇入 evaluation/results/utility_scores.json

Step 7. 分组分析 + 画图
   python evaluation/analysis_by_coverage.py
   python evaluation/plot_results.py \
     --input evaluation/results/results_summary.json
```

### 6.5 可复现性要求

| 项 | 说明 |
| --- | --- |
| **max_rounds** | 固定 6，所有实验一致；运行日志记录 |
| **随机种子** | LLM 若涉及采样固定 seed（或 `temperature=0`） |
| **模型版本** | 记录 text_model、embedding 模型及版本号 |
| **数据版本** | 记录 gold 文件 hash 或 git commit ID |
| **运行日志** | 每次实验保存 `id / answer_text / predicted_* / tool_calls / experiment_id / max_rounds / traceability_raw` |

### 6.6 v2.0 论文主表模板

**表 6-1：主实验（MTB 场景集，20 题）**

| 系统 | Traceability↑ | Halluc Rate↓ | Gene F1 | Pathway F1 | Bridge Hit | Utility (1-5)↑ | Mech Comp↑ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GPT-4o 直答 | — | — | — | — | — | — | — |
| 单 Agent + KG | — | — | — | — | — | — | — |
| RAG only | — | — | — | — | — | — | — |
| **GDgpt Full** | — | — | — | — | — | — | — |

**表 6-2：组件消融（KG 优化集，38 题）**

| 实验 | Bridge | Prefetch | 多角色 | KB | Gene F1 | Pathway F1 | Bridge Hit |
| --- | :---: | :---: | :---: | :---: | --- | --- | --- |
| Exp-0 Full | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Exp-2 Single-hop | ✗ | ✗ | ✓ | ✓ | — | — | — |
| Exp-3 No prefetch | ✓ | ✗ | ✓ | ✓ | — | — | — |
| Exp-4 No bridge | ✗ | ✓ | ✓ | ✓ | — | — | — |
| Exp-5 Single-role | ✓ | ✓ | ✗ | ✓ | — | — | — |
| Exp-6 No KB | ✓ | ✓ | ✓ | ✗ | — | — | — |

---

# Part I — 两周执行计划

## 7. Week 1（2026-04-27 ~ 05-03）：场景落地 + 测试集构建

| 天 | 任务 | 产出 |
| --- | --- | --- |
| Day 1-2 | 构建 20 题 MTB 场景测试集（OncoKB + CIViC + MTB 案例） | `evaluation/mtb_testset_v1.jsonl` |
| Day 3 | 实现 Traceability / Hallucination 计算脚本 | `evaluation/compute_system_metrics.py` |
| Day 4-5 | 实现 GPT-4o / 单 Agent+KG / RAG only 三档 Baseline | 3 套预测文件 |

## 8. Week 2（2026-05-04 ~ 05-10）：主实验 + 分析

| 天 | 任务 | 产出 |
| --- | --- | --- |
| Day 1-2 | 在 MTB 测试集上跑完全部实验（Exp-0/5/7/8） | 完整结果表格 |
| Day 3 | 做 2-3 个案例分析（1 成功 + 1 失败 + 1 典型 MTB 病例） | `evaluation/case_studies/*.md` |
| Day 4 | 整理数据、画图、写实验章节（论文 v0.1） | 论文草稿 v0.1 |
| Day 5 | 准备下次导师汇报材料 | 汇报 PPT |

## 9. 可选高 ROI 改进（如果时间允许）

| 改进 | 预期效果 | 耗时 |
| --- | --- | --- |
| KG 查询改证据加权排序（替代字母序） | Gene Recall 从 0.05 → ~0.20 | 1 天 |
| 提高 DiseaseToGene 的 k 从 8 → 20 | 召回翻倍 | 0.5 天 |
| 补充 `kg_gene_count` 元数据 | 指标更准确 | 0.5 天 |

## 10. 预期结果与论文叙事

### 10.1 预期定量结果（v2.0）

> 🔴 **2026-07-06 诚信提示**：下表为**预期/目标值，非实测结果**（主实验尚未在 MTB 场景集上跑）。加粗数字是希望达到的目标，不能作为已得结论汇报。真实数字见主实验产出。

| 指标 | GPT-4o 直答 | GDgpt Full | 预期差距 |
| --- | --- | --- | --- |
| Traceability | 0% | **> 80%** | 压倒性优势 |
| Hallucination Rate | 15-25% | **< 5%** | 大幅降低 |
| Gene F1 | 低 | 高 | KG 有帮助 |
| Utility Score | 3.0-3.5 | **> 4.0** | 医生认可度高 |

### 10.2 论文叙事公式

```
具体场景（MTB 会前准备）
  + 明确用户（肿瘤科医生 + 遗传咨询师）
  + 真实痛点（1-2 小时/例，GPT-4o 会幻觉）
  + 现有方案不足（Knowledge Connector 只聚合不推理）
  + 我们的系统（Bridge 多跳 + 多 Agent MDT 映射）
  + 外部 Baseline（GPT-4o / RAG only / OncoKB 手动）
  + 专家验证（3 位肿瘤医生打 Traceability / Utility / Hallucination）
```

### 10.3 论文 Intro 草稿（参考）

> 精准肿瘤学依赖多组学检测指导治疗，ESMO 已就转移性癌症的 NGS 使用给出官方推荐 [Mosele et al., Ann Oncol 2020]；分子肿瘤委员会（MTB）作为整合基因组、病理、临床等多源证据的会诊机制，其准备阶段需要医生查阅 OncoKB、CIViC、PubMed 等多个异构来源 [Nature Rev Clin Oncol 2023]，平均每例耗时 1-2 小时。近期研究 [Knowledge Connector, Nature Commun 2026] 尝试用 AI 辅助聚合多源证据，但主要关注可视化与数据整合，未提供**机制层面的多跳推理**。同时，通用大语言模型（GPT-4o）虽能生成流畅解释 [JCO PO 2024]，但存在**幻觉**和**证据不可追溯**两个关键问题 [Cancer Cell 2025]。
>
> 🔴 **2026-07-06 诚信提示**：下段 Intro 结尾的定量结论是**目标/占位，主实验尚未跑**，投稿前须用真实数字替换。切勿在拿到数据前作为已完成结果引用。
>
> 本文提出 GDgpt，一个基于 PrimeKG 子图的多智能体机制解释系统，为 MTB 准备阶段提供**可追溯、结构化、多角度**的基因-疾病-通路-药物机制报告。在基于 OncoKB 2024+ 新增证据和真实 MTB 案例报告构建的场景导向测试集上，GDgpt 相比 GPT-4o 直答在可追溯性上提升 `<待实验>` 倍，幻觉率降至 `<待实验>`，获得 `<待实验>` 位肿瘤医生 `<待实验>`/5 的临床效用评分。

---

---

# Part II — v1.0 原方案存档

> ⚠️ 以下为 2026-03-31 的 v1.0 实验方案原文，完整保留以供追溯历史演进。
> **v2.0 已全面重构；v1.0 中的组件消融矩阵（Exp-3/4/5/6）和 80 题 independent testset 的部分内容被 v2.0 吸收并修订**，见正文。

## A1. 原研究问题（v1.0）

- **RQ1**: 知识图谱辅助能否提升 LLM 在生物医学问答任务上的表现？
- **RQ2**: 在何种条件下，KG 辅助最为有效？
- **RQ3**: KG 覆盖不足时，系统应如何优雅降级？

## A2. 原发现的关键问题（v1.0）

### A2.1 PrimeKG 疾病覆盖有限

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| PrimeKG 疾病总数 | **20 种** | 覆盖极为有限 |
| 测试集疾病匹配率 | **44.4%** | 18 种疾病中仅 8 种匹配 |
| 基因覆盖率 | 56.6% | 中等 |
| 通路覆盖率 | 100% | 完全覆盖 |

→ **v2.0 重新诠释**：20 种疾病几乎都是癌症，恰好是精准肿瘤学 MTB 场景的天然匹配，不再视为"覆盖不足"。

### A2.2 原实验结果（30 题 KG 优化集）

| 指标 | Full Task KG | LLM only | 说明 |
| --- | :---: | :---: | --- |
| Gene F1 | **0.060** | 0.000 | KG 有优势 |
| Pathway F1 | **0.316** | 0.000 | KG 有显著优势 |
| Phenotype F1 | 0.438 | **0.633** | ⚠️ LLM 更好 |
| Bridge Hit Rate | **1.000** | 0.000 | 多跳查询有效 |

## A3. 原实验方案设计（v1.0）

### A3.1 核心策略：**按 KG 覆盖率分层分析**

不再追求"KG 一定优于 LLM"，而是研究"KG 辅助在何种条件下有效"。

#### 分层设计（原文）

```
测试问题分层：
├── Tier 1: High Coverage (KG 完全支持)
│   ├── Pathway-centered 问题 (100% 覆盖)
│   └── Disease-centered 问题 (PrimeKG 中存在的疾病)
│   → 预期：KG 辅助显著提升性能
├── Tier 2: Medium Coverage (KG 部分支持)
│   └── Gene-centered 问题 (56.6% 基因覆盖)
│   → 预期：KG 有部分帮助
└── Tier 3: Low Coverage (KG 无法支持)
    └── Disease-centered 问题 (不在 PrimeKG 中的疾病)
    → 预期：系统退化为 LLM-only，展示优雅降级
```

→ **v2.0 定位**：此分层策略仍是轨道 A 消融分析的有效方法，但不再是主实验论点。

### A3.2 原实验矩阵（v1.0）

#### 主实验（必做）

| 实验 ID | 配置 | 目的 | 优先级 |
| --- | --- | --- | :---: |
| Exp-0 | Full Task KG | 完整系统基准 | P0 |
| Exp-1 | LLM only | 纯 LLM baseline | P0 |
| Exp-2 | Single-hop KG | 仅单跳查询，无 Bridge | P0 |

#### 消融实验（选做）

| 实验 ID | 消融项 | 验证目标 | 优先级 |
| --- | --- | --- | :---: |
| Exp-3 | No KG Prefetch | KG 预取机制的价值 | P1 |
| Exp-4 | No Bridge | 多跳查询的价值 | P1 |
| Exp-5 | Single Role | 多角色协同的价值 | P2 |
| Exp-6 | No CorrectKB/ChainKB | 双知识库的价值 | P2 |

### A3.3 原评测指标（v1.0）

**检索层**：Gene/Pathway Recall@k、Precision@k、Bridge Hit Rate、Coverage
**端到端**：Gene/Pathway/Phenotype F1、Mechanism Completeness（0-2）、Graph Faithfulness（0-2）
**分层对比**：High / Medium / Low Coverage Group、Coverage-Performance Correlation

## A4. 原测试集配置（v1.0）

### A4.1 两个版本（80 题独立测试集）

| 版本 | 文件 | 题数 | 用途 |
| --- | --- | :---: | --- |
| Quick | `testset_quick.jsonl` | 30 | 🚀 快速验证流程、调试代码 |
| Full | `testset_full.jsonl` | 80 | 📊 正式实验、论文数据 |

### A4.2 Full 版本构成（80 题）

| 任务类型 | 数量 | PrimeKG 覆盖率 | 说明 |
| --- | :---: | :---: | --- |
| disease-centered | 18 | 39%（7 题覆盖） | 部分疾病不在 PrimeKG |
| gene-centered | 30 | 100% | 热门基因完全覆盖 |
| pathway-centered | 32 | 100% | Reactome 通路完全覆盖 |
| **总计** | **80** | **86.2%** | — |

### A4.3 数据来源可信度

| 数据源 | 权威性 | 学术引用 |
| --- | :---: | --- |
| Open Targets Platform | ⭐⭐⭐⭐⭐ | Nucleic Acids Research（EMBL-EBI） |
| Reactome | ⭐⭐⭐⭐⭐ | Nucleic Acids Research（手工筛选+同行评审） |
| PrimeKG | ⭐⭐⭐⭐ | Nature Sci Data 2023（哈佛/MIT）⚠️2026-07-06更正：原写ICLR2022有误 |

→ **v2.0 定位**：80 题 independent testset **不再主用**（循环评测残留 + 场景泛化），仅作为历史参考。主实验切到 20 题 MTB 场景集。

## A5. 原实验执行计划（v1.0）

### A5.1 Phase 1: Quick 快速验证（0.5 天）
### A5.2 Phase 2: Full 正式实验（2-3 天）
### A5.3 Phase 3: 分层分析（1 天）
### A5.4 Phase 4: 消融实验（可选，2-3 天）
### A5.5 Phase 5: 论文撰写（持续）

→ **v2.0 执行计划** 见 Part I §7-§9，已替代此计划。

## A6. 原预期结果与论文叙事（v1.0）

### A6.1 v1.0 论文叙事

> "KG augmentation provides substantial benefits when knowledge coverage is high, and gracefully degrades to LLM-only performance otherwise. This reveals that **KG coverage is the critical factor** determining augmentation effectiveness."

→ **v2.0 已替换**：新叙事聚焦 MTB 场景下的可追溯性与幻觉率优势。

## A7. 原时间安排（v1.0）

原定 2026-04 完成主实验 + 分层分析 + 消融实验。

→ **v2.0 执行计划已重排**，见 Part I §7-§9。

---

*本文档 v2.0 由 2026-04-26 重构；v1.0 完整存档见 Part II；后续修改请遵循"Changelog + 版本号 + 更新日期"三件套。*
