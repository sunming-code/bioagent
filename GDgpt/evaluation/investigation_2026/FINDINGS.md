# FINDINGS：Gene Recall 提升可行性调研

**调研日期**：2026-09-14  
**调研者**：Claude Code（只读调研，未改任何项目文件）  
**决策问题**：Gene Recall@5 ≈ 0.047，值不值得动核心代码去提升？  
**依赖分支**：`grad`（分析基于此分支的代码和结果文件）

---

## TL;DR（决策结论）

**都不值得做，理由是 W：金标基因绝大多数根本不在 KG 候选池里，改排序是无用功；能用的 Open Targets 分数会构成评测泄漏；KG 内部也不存在任何与金标无关的可靠排序信号。Gene Recall 低是 KG 数据固有结构性限制，诚实写进 limitation 即可。**

---

## 一、三条线索结论

### 线索 1：LLM 重排层（破局2，唯一未试）

**结论：不值得做。**

**Falsifier 结果（LIVE 实测，文件：`candidate_pool_vs_gold.md`）**：

| 指标 | 数值 |
|---|---|
| 15道 disease-centered 题（adapt15_full_raw.jsonl） | |
| 候选池覆盖率 = 0% 的题目 | **11/15（73%）** |
| 平均候选池覆盖率 | **4.7%** |

Falsifier 已跑完，结果推翻了 LLM 重排的有效性假设：

- 当前每次 DiseaseToGene 查询 k=8，跨 3 个角色约取 20-26 个候选基因
- KG 所有边权重 = 0.0，实际按 `gene ASC`（字母序）返回，首先是 ABCA3/ABCA4/ABCB1 等
- 每病有 500-1156 个关联基因，k=8 只取了最靠前的字母
- 金标基因（BRCA2/TP53/APC/KRAS 等）字母位置靠后，73% 的题里根本不在候选池

**代表例**（hereditary breast ovarian cancer syndrome，KG有1156个关联基因）：

| | 内容 |
|---|---|
| KG 返回（k=8） | ABCA3, ABCA4, ABCB1, ABCB10, AKT1, ALOX5, APRT, BRCA1 |
| 金标基因（top-8） | BRCA2, BRCA1, PALB2, TP53, PIK3CA, CHEK2, ATM, RAD51C |
| 重叠 | 仅 AKT1, BRCA1, ERBB2, ESR1（4/20 = 20%） |
| 乳腺癌以外11题 | **0% 重叠** |

即使技术上可行（增大 k 至 50-100 后喂 LLM 重排），有三个根本问题：

1. **重排救不了的题（73%）**：金标根本不在候选池里，重排无法凭空生成候选。
2. **信息来源冲突核心卖点**：LLM 知道"BRCA1 与乳腺癌相关"来自训练数据（参数记忆），不来自 KG 边。重排后该基因的出现无法追溯到任何 KG 边——这直接削弱"KG 可追溯"这个核心卖点。系统会从"KG-grounded 系统"降级为"LLM 用 KG 当候选池"。
3. **成本高、收益低**：需修改 KG 查询（k: 8→100）+ 新增重排 LLM 调用（每题额外 1-2 次 gpt-4o）+ 重跑所有消融实验（≥5组）。预计 4-6 天。即使全成功，Gene Recall@5 对 73% 的题仍然是 0，整体最多从 0.047 升至 0.05-0.10 左右。

**文献核实**（Crossref 核查）：  
LLM 重排（如 RankGPT）在通用 IR 有报告增益，验证了以下论文真实存在：
- "Leveraging Passage Embeddings for Efficient Listwise Reranking with Large Language Models"，ACM Web Conference 2025，DOI: 10.1145/3696410.3714554 [VERIFIED]
- "Self-Calibrated Listwise Reranking with Large Language Models"，ACM Web Conference 2025，DOI: 10.1145/3696410.3714658 [VERIFIED]

但在生物医学 KG 基因检索场景（gene-disease KG，over-connected，边无权重）中**无报告具体增益数字**，文献搜索未找到直接对标研究 [CHECK-DOI]。

---

### 线索 2：Open Targets 边权重导入（是否泄漏）

**结论：是评测泄漏，必须否掉。**

**泄漏判定：是（LIVE 实测）**，依据：

```python
# testset 中 source 字段（evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl）
case["source"] = "Open Targets + PrimeKG cross-validated"  # 乳腺癌、前列腺癌等主要临床病种
case["source"] = "PrimeKG (no OT match)"                   # 部分罕见疾病
```

金标基因本身来自 Open Targets（对于主要癌种），且 KG 边权重（edge weight）的来源也是 Open Targets association score。因此：

**用 Open Targets score 排序 = 用与金标同源的数据排序 = 指标好看但学术上作弊。**

对于 "PrimeKG (no OT match)" 的疾病（11/15 题），Open Targets 没有匹配数据，导入 OT 分数对这些疾病完全无效。

**结论：无论学术诚信还是实际效果，Open Targets 边权重导入均应否掉。**

---

### 线索 3：KG 内部替代排序信号（无需外部金标）

**结论：不存在有效信号。**

以下思路均已穷举：

| 信号 | 状态 | 结论 |
|---|---|---|
| 节点度数（gene node degree） | 可计算 | 反映 KG 整体连接密度而非对特定疾病的相关性；高度数基因（TP53、EGFR）对所有疾病都高，无区分性 |
| PMI / 共现 | 需 PubMed 或外部语料 | 属外部信号，本质等同于再导入一份"答案" |
| Relation type 优先级 | 已隐式做了（ASSOCIATED_WITH > 其他） | 当前查询已只查 ASSOCIATED_WITH，relation-level 已最优化 |
| 子图剪枝（如 disease-gene-pathway 共现） | 已有 DiseaseGenePathwayBridge | Bridge 查询已存在；问题不在子图剪枝，而在基础排序信号缺失 |
| 边属性（source, display_relation, weight） | 代码已包含 `ORDER BY weight DESC` | weight 字段全为 0.0 或缺失（已验证：tools.py 行 196-222 的所有查询） |

**2024-2026 文献搜索结论**：  
针对"过度连接 KG + 边无权重 + 排序改善"场景，检索 Crossref 未找到无监督方法（纯 KG 内部信号）能在此类设置下显著改善 gene-disease 排序的文献 [CHECK-DOI]。现有工作要么引入外部信号（如 Open Targets）、要么使用监督训练（KG embedding 模型）——两者都超出本项目可行范围。

---

## 二、决策表

| 手段 | 预期 Recall 增益 | 成本（人天） | 对核心卖点影响 | 建议 |
|---|---|---|---|---|
| LLM 重排（k 扩至 100） | +0.02~0.05（73%题无效，仅乳腺癌等有微增） | 4-6 天 | **严重削弱**：重排信息来自 LLM 参数记忆，不可追溯到 KG 边 | ❌ 不做 |
| Open Targets 边权重导入 | 高（但数字虚假） | 3-5 天 | 评测泄漏，学术作弊 | ❌ 不做 |
| 节点度/PMI/relation 优先级 | 接近 0 | 2-3 天 | 无 | ❌ 不做 |
| **现状：保持 k=8，如实报告为 limitation** | 0（不改数字） | 0 天 | **保护**：卖点在 Pathway F1/Bridge Hit/Traceability/Abstention，Gene Recall 已有结构性解释 | ✅ 执行 |

---

## 三、Falsifier 状态

**已运行（LIVE 观测）**：

用 `evaluation/results/adapt15_full_raw.jsonl`（15题真实实验结果）逐案检查 KG 候选池与金标基因重叠。

**Falsifier 发现**：假设"LLM 重排值得做"被推翻——11/15（73%）题的金标基因在当前候选池中完全缺失。候选池覆盖率均值 4.7%，乳腺癌题最高也仅 20%。因此，LLM 重排不能帮助绝大多数样本，结论从"可能值得做"反转为"不值得做"。

---

## 四、置信度声明

**线索1（LLM重排）**：置信度 **HIGH**  
- Falsifier 已基于真实结果文件运行，直接观测候选池内容（LIVE）  
- 技术可行性判断（增大 k 可行，但 LLM 参数依赖是结构性问题）是 INFERRED，但逻辑推导清晰无歧义  
- 剩余不确定性：若 k 显著增大（如 200），乳腺癌题的 Recall 上限可超过 20%，但论证不变（LLM 参数知识主导重排）

**线索2（Open Targets 泄漏）**：置信度 **HIGH**  
- source 字段直接从数据文件读取（LIVE），文件路径 `testset_kg_optimized_enriched.jsonl` 明确记录  
- 金标来自 Open Targets 这一事实无歧义

**线索3（内部信号不存在）**：置信度 **MEDIUM**  
- KG 边权重为 0 的观测是 LIVE（tools.py 代码 + 结果文件中 weight=0.0）  
- 文献中"无 unsupervised 有效方法"是 INFERRED（搜索覆盖不完整，可能有遗漏文献）

**整体决策置信度：MEDIUM-HIGH**  
（Falsifier 已跑通支持主要决策，文献搜索未找到颠覆性反例；对线索3的否定保守置信 MEDIUM）

---

## 五、开放问题

1. 若增大 k 至 200 且仅对乳腺癌类题（"Open Targets + PrimeKG cross-validated" source）做重排，Recall 理论上限能到多少？——可通过离线 Cypher 查询统计，但仍面临核心卖点损失问题，因此即便能到 0.3 也不改变决策。

2. 部分金标基因（如 colorectal cancer 的 KRTAP10-8、MIR101-2 等）是否临床上真正重要？若这些基因本身不重要，Gene Recall 指标的效度值得质疑——但改指标而非改系统才是正确方向，与本决策无关。
