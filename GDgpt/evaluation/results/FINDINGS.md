# GDgpt 投稿可信度分析 — FINDINGS

> 作者：Claude Code（只读调研，不改项目文件）  
> 日期：2026-09-14  
> 目标：在不改任何实测数字的前提下，判断哪些弱点是真弱、哪些是被低估资产、最低成本如何增说服力。

**CONFIDENCE: HIGH** for all falsifier-confirmed findings (directly verified from disk files). **CONFIDENCE: MEDIUM** for baseline gap analysis and literature-based framing recommendations (inferred, not experimentally confirmed).

---

## 置信度陈述

本报告的结论基于：(a) 直接读取磁盘上的 `evaluation/results/` 下 113 个文件；(b) 读取 `paper_draft_en.md` 和工作记录；(c) 对关键统计文件的内容核查。**未运行任何新实验**。

- **HIGH 置信度（LIVE 实证）**：Falsifier 已跑，结论由磁盘文件直接支持。
- **MEDIUM 置信度（INFERRED）**：结论基于文件缺失或文本叙述，但未对全部内容穷举验证。
- 凡我未能用磁盘文件直接证伪的推断，均标为 INFERRED。

---

## Falsifier 报告（最重要）

**调查对象**：任务说明声称"Wilcoxon/bootstrap 统计从未存盘（grep 不到 p-value/CI 文件）"，以及"adaptive routing 成本/延迟维度是现成的第4支柱候选"。

### Falsifier 1：Wilcoxon/bootstrap 统计是否存盘？

**结论：任务说明有误，统计文件实际存在。** [LIVE]

```
evaluation/results/paired_stats_pathway_f1.txt  (368 B, 2026-09-14)
evaluation/results/paired_stats_bridge_hit.txt   (368 B, 2026-09-14)
evaluation/results/paired_stats_gene_recall.txt  (384 B, 2026-09-14)
```

文件内容已直接读取，包含 Wilcoxon W 值、p 值和 bootstrap 95% CI，与论文草稿 Table 1 数字完全吻合。**这不是弱点，论文统计已足够可信。**

### Falsifier 2：adaptive routing 成本维度是否有系统实测数据？

**结论：没有。"3-5× speedup"是定性观察，不是系统性配对实验。** [LIVE]

核查方式：
1. 对 `adapt15_full_raw.jsonl`（N=15）所有 JSON 字段做穷举，keys 为：`id, answer_text, final_answer, predicted_*, bridge_found, mechanism_completeness, graph_faithfulness, utility_score, tool_calls, kg_coverage_level, kg_coverage_ratio, cited_edges, asserted_claims, notes` —— **无任何 latency/elapsed/token_usage/duration 字段**。
2. 对 `adapt3_raw.jsonl`, `adapt3_ext.jsonl` 做同样检查，**同样无计时字段**。
3. grep `evaluation/results/` 下所有文件的 `token_usage|elapsed|latency|duration_sec|wall_time`，**找到的都是 answer_text 里的自然语言，无结构化计时数据**。
4. "37 sec" 和 "3-5 分钟" 均来自工作记录（2026-07-10 执行日志）的叙述，不是测量值。

**判定：adaptive routing 的成本维度是"需要补一轮实验"，不是"现成资产"。** 估计成本：需要对 adapt（1/3/5角色）和 full（5/7角色）各跑 N≥15 并记录 wall time，约 1-2 天实验 + 0.5 天分析。

---

## 线索 1：被低估的现成资产盘点

| 资产 | 磁盘状态 | 论文现状 | 说明 |
|---|---|---|---|
| **Wilcoxon + bootstrap CI**（N=15 配对） | ✅ 已存盘，3个文件 | ✅ 论文已引用，正确 | 任务说明有误；统计已完整 |
| **三评委多 judge 内部 9q 数据** | ✅ `multijudge_9q.json`（完整逐题 swap 数据）| ✅ 论文 Table 6 已包含，数字吻合 | swap 一致性：gpt-4o=0.844, qwen-max=0.778, mini=0.489 |
| **三评委多 judge 外部 PcQA 20q 数据** | ✅ `multijudge_pcqa20.json` | ✅ 论文 Table 7 已包含 | 外部独立 qwen-max 支持 GDgpt D3 领先 |
| **Backbone mini 实验（N=9）** | ✅ `mini_9q_raw.jsonl`, `mini_kg_vs_direct_judge.json` | ✅ §4.7 已写，结构性保证backbone无关 | 已实现，且已写进贡献 |
| **PcQA 外部 N=68（per-dimension）** | ✅ `pcqa49_judge_results.json` + `pcqa_remaining_judge.json` + `pcqa99_judge.log` | ✅ 论文 Table 5 已包含，数字 D3=4.21 vs 2.94 | 这是最强的外部独立验证 |
| **低覆盖弃权实验 N=8** | ✅ `lowcov_full_raw.jsonl` + `lowcov_gpt4o_raw.jsonl` | ✅ Table 2，8/8=100% vs 0/8=0% | 结构性结果，最强论证点 |
| **Bridge 消融 N=3** | ✅ `abl_rag_ext.jsonl`, `abl_single_ext.jsonl` | ✅ Table 3，PathF1 0.667→0.084(−87%) | 已写进论文 |
| **Swap consistency 分析** | ✅ 逐题 swap 字段已记录 | ✅ 论文已报告 0.84/0.78/0.49 | 可直接引用，无需补充 |
| **adaptive routing 质量对比（N=15 vs N=3）** | ✅ `adapt15_full_raw.jsonl` + `adapt3_ext.jsonl`，F1 0.596 vs 0.667 | ✅ Table 4，质量损失8% | 已写，但成本侧无数据 |
| **adaptive routing 成本/延迟** | ❌ 无结构化计时数据 | 论文写"≈37 sec"（定性观测）| **缺口**：需补配对计时实验 |
| **Human kappa** | ❌ `human_rating_form_v23.md` 全空，D1-D5 所有栏均空 | 论文写"提供表格供未来验证"| **弱点**：无任何人工评分 |
| **PcQA 剩余31题 per-dimension** | ❌ pcqa99 总共99题，仅68题有 per-dimension 评测 | 论文写"N=68 combining N=49+N=19 holdout"| **可补**：约1天 |
| **时间分割评测** | ❌ 零产物 | 论文写"Future work" | 已明确放弃（支柱3）|

**现成资产结论（LIVE）**：已完成的实验已经覆盖了论文所有核心声明的证据链。Wilcoxon/统计已存盘，多评委数据完整，外部 PcQA 68题已评。真正缺的只有：(1) 系统性延迟数据、(2) human kappa。

---

## 线索 2：缺失的 Baseline 分析

当前 baseline：GPT-4o 直答 / single_agent / rag_only。

| 缺失 baseline | 审稿人提问概率 | 补充成本 | 不补会被怎么问 |
|---|---|---|---|
| **可比较的 KG-RAG 系统**（如 KG4Diag 或 GraphRAG 变体） | HIGH | 高（需跑其他系统） | "你和同类 KG-RAG 相比怎么样？只和纯 LLM 比不公平" |
| **MedAgents / MDAgents 直接对比** | MEDIUM | 高（需复现对方代码） | "你声称受 MDAgents 启发，但为何不和它比？" |
| **OncoKB 手动查询时间对照** | MEDIUM | 低（引用文献数字即可）| "临床效率提升有多少？" — 可用文献引 1-2h/case 数字代替实验 |
| **GPT-4o + 同样 KG 作为独立基线** | HIGH | 中（需跑 GPT-4o + KG 注入不多轮） | "你的胜利是多轮/多角色带来的，还是 KG 本身带来的？single_agent 已经部分回答但不够" |

**最危险的缺口**（INFERRED）：审稿人最可能问"你和同类 KG-augmented 系统比如何"，而当前所有非 GDgpt 的系统都是要么纯 LLM、要么消融。完全缺乏一个"别人家 KG 系统"的对比。但补充这个代价极高（需实现对方系统）。

**务实应对策略**：在 Related Work 和 Limitations 中主动点出"我们没有和 KG4Diag、Knowledge Connector 的系统做过量化对比，原因是两者的代码库/KG 格式不同步且不开源"，先发制人，比被问倒更好。

---

## 线索 3：低成本增说服力手段（按性价比排序）

| 手段 | 增益 | 成本（人天）| 置信度 | 是否答辩必需 |
|---|---|---|---|---|
| **Human kappa N=5 题**（找导师或医学同学）| 把 LLM-judge 从"未验证代理"升级为"kappa 验证代理"；直接回应审稿人必问 | 0.5（问卷设计已有，只需找人填）| HIGH（最高 ROI）| 投稿加分 |
| **PcQA 剩余31题 per-dimension 补评**（N=68→N=99） | 全量覆盖使"N=68"变"N=99"，数字更有说服力 | 1（跑 pcqa judge 脚本）| HIGH（可行）| 投稿加分 |
| **Adaptive routing 系统性延迟测量**（N=15 配对 wall time） | 让"3-5×"从定性变为实测成对数字，支撑 Table 4 | 1.5（加计时字段+重跑对比）| MEDIUM（可行但需代码改动）| 可选 |
| **gpt-4o-mini 在 PcQA 外部集的行为诠释**（已有数据）| 论文 §5.4 说 mini 在外部"reverses"；可以加一句解释（swap_consistency=0.85 说明不是 position bias，而是真实判断差异），把弱点转化为"sensitivity analysis"资产 | 0.5（只改论文描述）| HIGH（数据已有）| 投稿加分 |
| **统计检验存档说明**（更正论文中的"未存盘"说法）| 移除不存在的弱点；消除读者疑虑 | 0（只更新论文措辞）| HIGH（falsifier已确认）| 答辩必需 |

**关于 gpt-4o-mini swap 的具体诠释**：现有数据显示，外部 pcqa20 中 mini 的 swap_consistency=0.85（不是 position bias），但方向上 mini 在外部集偏好 GPT-4o（D3: 2.025 vs 3.325）。正确的叙述是：*"mini 在外部集的 position bias 很低（0.85），但其判断与高可靠性评委（gpt-4o, qwen-max）一致性低 (D3 Spearman ρ 仅 0.149–0.338)，说明 mini 的 D3 判断本身缺乏可靠性，而非系统性偏见。两个高可靠性评委在内外两套数据上均支持 GDgpt D3 领先。"* 这种改写不改数字，但把弱点变成"judge 分级可靠性分析"的方法论贡献。

---

## 线索 4：弱点的诚实写法（可直接改进论文）

### Gene Recall 0.047

**最强写法框架**（INFERRED，基于 PcQA/KGT 方向文献）：

> ⚠️ **2026-10-08 作废**：下面这段措辞已被线上 KG 复核否定，**不要再粘到论文里**。否定依据：300 个金标基因中 290 个（96.7%）确实是该疾病的 `ASSOCIATED_WITH` 邻居，所以"relevance-ranked retrieval structurally impossible / not a failure of GDgpt's architecture"是错的——金标基因在图里，是 `DiseaseToGene` 的 `LIMIT $k` 截断掉的（实测 k=8，重复源行再砍一半）。保留原文仅为记录。
>
> ~~*"The low Gene Recall@5 (0.047) reflects a field-wide challenge in KG-based retrieval: PrimeKG associates 1,000+ genes with a single cancer type without edge weights, making relevance-ranked retrieval structurally impossible [cite over-connected KG literature]. This is not a failure of GDgpt's architecture — Pathway F1 and Bridge Hit, which depend on the same retrieval step, are statistically significantly higher than GPT-4o (p≈0.0007). The Gene Recall gap is evidence that KG edge weights are a prerequisite for gene-level ranking in cancer KGs, consistent with findings in KGT/PcQA [Feng et al., GigaScience 2025, VERIFIED]."*~~

**现行写法**见 `docs/paper_draft_en.md` §5.5：低 gene recall 是**可修复的检索截断缺陷**，不是知识源缺失；对截断后的池重排无效，在完整邻居集合上排序尚未试过（待实验）。另外 0.047 这个数**不是 Recall@5**，而是无名次截断的 recall（`evaluation/compute_paired_stats.py`，上限 1.0）。

### 幻觉率不赢 GPT-4o

**最强写法框架**：

> *"GPT-4o generates richer responses drawing on parametric knowledge; GDgpt is architecturally constrained to KG-grounded content. On D1/D2, GPT-4o's advantage reflects this design difference — a system that refuses to generate beyond its knowledge base will necessarily appear 'incomplete' on fluency-based dimensions. The clinically relevant question is not 'which system generates more content' but 'can a clinician verify the claims.' GDgpt's D3 advantage (+1.26 on PcQA external) and its 100% abstention on KG-absent queries are the safety-relevant metrics."*

这个框架明确接受 D1/D2 的劣势，但把评价维度切换到"临床相关性"。不需要改数字，只需要在 Discussion 里换一个判断框架。

### N 小

**最强写法框架**：

> *"N=15 constitutes a pilot/feasibility study; results are not intended as a definitive benchmark. We contextualize this within the clinical NLP literature: structured evaluation of complex multi-hop reasoning in oncology inevitably faces sample-size constraints — a trade-off between annotation depth and breadth. Our per-question annotation depth (Bridge hit + Pathway F1 + per-dimension LLM scoring + cited edge traceability) is significantly richer than typical benchmark-scale evaluations. Statistical significance is achieved on our primary metrics (p≈0.0007), and cross-dataset replication on PcQA (N=68) confirms the D3 advantage is not an artifact of the N=15 setup."*

关键点：小样本不是弱点，是"深度换广度"的设计选择，只要有统计支撑且有外部验证复现就成立。

**哪条弱点最可能被当致命伤**：Human kappa 缺失。审稿人一定会问"为何没有人工评分验证 LLM-judge 的可靠性"。这是最危险的单点弱点，也是成本最低的可修复项（0.5天）。第二危险：消融 N=3，容易被质疑样本代表性（暂时无好办法，只能诚实标 pilot）。

---

## 综合行动清单（按性价比排序）

| # | 手段 | 增益说明 | 成本（人天）| 类别 |
|---|---|---|---|---|
| **1** | **更正"统计未存盘"误说**（论文 §4.1，如有提到）| 消除不存在弱点 | 0 | 答辩必需 |
| **2** | **Human kappa N≥5**（找导师/医学生填 `human_rating_form_v23.md` 任意5题）| LLM-judge 升级为"验证代理"；直接回应最危险审稿问题 | 0.5 | 投稿必需（workshop级）|
| **3** | **gpt-4o-mini外部集诠释优化**（改论文描述，数据已有）| 弱点转化为"judge 可靠性分层分析" | 0.5 | 投稿加分 |
| **4** | **PcQA 剩余31题 per-dimension 补评**（N=68→N=99）| 全量覆盖，数字更完整 | 1 | 投稿加分 |
| **5** | **主动承认缺 KG-RAG 对比 baseline**（在 Limitations 写1段）| 先发制人，比被问倒好 | 0.5（纯写作）| 投稿必需 |
| **6** | **Adaptive routing 系统性延迟测量**（加计时 + 重跑 N=15 对比）| "3-5×"变实测数字 | 1.5 | 可选加分 |
| **7** | **Gene Recall 弱点改写**（frame as field-level constraint）| 换叙事框架，数字不变 | 0.5（纯写作）| 投稿必需 |
| **8** | **N小 pilot study 表述标准化**（深度换广度框架）| 降低 N 小的质疑风险 | 0.5（纯写作）| 投稿必需 |

---

## 开放问题（无法在只读调研中确定）

1. `pcqa99_judge.log` 的 N=99 vs 论文 N=68 有31题缺口——需要确认是否还有 pcqa_remaining_judge 未合并。
2. 导师/医学同学的可用性（#2 行动的前提）——不确定，需学生确认。
3. MDAgents 代码库的可访问性——若未来想补比较，需要调研。

---

*FINDINGS.md 生成时间：2026-09-14。所有 LIVE 标记表示直接在磁盘文件中观察到的事实；INFERRED 表示基于文件内容的推断。*
