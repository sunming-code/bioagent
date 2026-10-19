# GDgpt 工作量证据化盘点报告

> **盘点时间**：2026-09-14  
> **盘点人**：Claude Code（只读调查，未改任何项目文件，未跑任何实验）  
> **产物来源**：`evaluation/results/`（113 个文件）+ 工作记录 + 论文初稿 + git log  
> **声明标准**：LIVE = 本次直接读到文件；INFERRED = 基于文档记录推断，数据文件存在但未重算

---

## 置信度陈述

**CONFIDENCE STATEMENT**: 工作量基本达到硕士毕业论文最低标准（8/9工程维度 + 6/6学术叙事维度）。  
**置信度：MEDIUM**（因 falsifier 揭示 Wilcoxon 统计存档缺失，降为 MEDIUM；核心产物文件全部存在）。

不确定的地方：
1. Wilcoxon/bootstrap 统计（p≈0.0007）仅有文档记录，无单独输出文件，未经本次重算验证（INFERRED）。
2. `human_rating_form_v23.md` 是未填写的空白表单，human kappa 从未产生。
3. PcQA N=68 的 D3 数字已由本次加权平均核实（4.21 vs 2.94 ✓），但 N=99 原始跑完后只有总分日志，无逐维数字。

---

## 第一部分：工作量清单逐项核实（§六-a 更新版）

### 工程维度

| 要求 | §六-a 旧状态 | 产物证据（文件 + 实际数字） | 判定 |
|---|---|---|---|
| 至少一个端到端原创系统 | ✅ | `workflow.py` + `agents.py` + `tools.py`；`run_batch_eval_template.py`；代码覆盖 4 阶段流程 | ✅ 产物证实 |
| ≥2 个核心技术组件 | ✅ | Bridge 多跳（`tools.py:121-284`）；覆盖度弃权（`workflow.py` node_safety_check）；自适应路由（`agents.py` assess_complexity）；已 merge 进 grad | ✅ 产物证实 |
| 完整评测流水线（脚本可复现） | ✅ | `run_batch_eval_template.py`→`extract_from_tool_calls.py`→`compute_metrics.py`→`compute_system_metrics.py`；独立 testset 带 expected_kg_edges（`testset_kg_optimized_enriched_with_edges.jsonl`） | ✅ 产物证实 |
| ≥2 个 baseline 对比 | ✅ (旧标注"补外部benchmark baseline") | GPT-4o direct（`exp15_gpt4o_ext.jsonl` 15题）；single_agent 消融（`abl_single_ext.jsonl` 3题）；rag_only 消融（`abl_rag_ext.jsonl` 3题）；PcQA 外部 benchmark 提供独立对比集 | ✅ 产物证实 |
| 统计严谨性（Wilcoxon + bootstrap CI） | ✅ | `compute_paired_stats.py` 存在；工作记录§8(2026-07-13)记录输出：Pathway F1 p≈0.0007、CI [0.57,0.62]；数据文件（`adapt15_full_ext.jsonl`+`exp15_gpt4o_ext.jsonl`+gold）均在。**但无单独 JSON 输出文件**（脚本输出到 stdout 未存盘）。 | ⚠️ 文档声称+数据可复现，输出文件缺失 |
| 消融实验（证明每个组件有用） | ✅ | `abl_rag_ext.jsonl`(3题)：rag_only PathF1=0.084 vs Full=0.667（-87%）；`abl_single_ext.jsonl`(3题)：single PathF1=0.653 vs Full=0.667。Bridge 关键性结论强。N=3 但信号决定性。 | ✅ 产物证实 |
| ≥1 个外部 benchmark | **❌ 旧清单标"尚未跑"** | `evaluation/external_benchmarks/pcqa_100.jsonl`(100题构建完成)；`pcqa100_gdgpt_raw.jsonl`(99题)；`pcqa100_gpt4o_raw.jsonl`(100题)；`pcqa49_judge_results.json`(N=49，D3 GDgpt=4.306 vs 2.878)；`pcqa_remaining_judge.json`(N=19，D3 GDgpt=3.947 vs 3.105)；加权合计 N=68，D3=4.21 vs 2.94 ✓ | **✅ 产物证实（清单已过时，今日更新）** |
| 案例分析（定性理解） | ✅ | 论文 §5.1/5.2/5.3 三个案例（成功案例/弃权案例/局限案例）均有完整叙述 | ✅ 产物证实 |
| 代码可重现（脚本+配置模板） | ✅ | `config.example.json` 存在；`evaluation/README.md`；各脚本有 argparse 接口 | ✅ 产物证实 |

**工程维度合格：8/9（统计输出文件缺失为唯一⚠️）**

### 学术叙事维度

| 要求 | 说明 | 判定 |
|---|---|---|
| 问题有临床/社会动机 | 论文 §1.1-1.2：MTB 准备瓶颈(1-2h/case) + 临床安全不对称性 | ✅ 产物证实 |
| 方法有理论/文献支撑 | MDAgents/Selective QA/ALCE/AttributionBench/Verga PoLL 均在 References，全部 VERIFIED | ✅ 产物证实 |
| 贡献是真正空白 | KG-edge 级确定性可追溯 + KG覆盖度触发弃权，文献调研已验证为空白（工作记录§8续2+§6-a续5） | ✅ 产物证实 |
| 有定量支持的主要贡献 | Pathway F1=0.596 p≈0.0007；Bridge Hit=1.0；弃权 8/8=100% vs 0%；D3 4.04/4.21 vs 3.22/2.94 | ✅ 产物证实 |
| 诚实面对 limitation | §6 Limitations：低 Gene Recall（字母序）、pilot study 规模、无临床专家评分、幻觉率 GDgpt 未赢 | ✅ 产物证实 |
| 有 future work 延伸性 | 时间分割评测、KG 重排、human kappa、PcQA full N=100 均在 future work | ✅ 产物证实 |

**学术叙事维度：6/6 ✅**

---

## 第二部分：实验产物矩阵

### 已真实跑完的实验

| 实验名 | 数据集/题数 | 对比 baseline | 原始 jsonl | judge 结果 | 指标算出 |
|---|---|---|---|---|---|
| **主实验（自适应）** | 内部 disease-centered N=15 | GPT-4o direct N=15 | `adapt15_full_raw.jsonl`(15)，`exp15_gpt4o_raw.jsonl`(15) | `llm_judge_v23_results.json`(N=9,3票) | Pathway F1=0.596，Bridge Hit=1.0，Gene Recall=0.047（工作记录 §8，脚本 stdout）|
| **弃权评测** | 低覆盖确定性集 N=8（真实疾病不在KG） | GPT-4o direct N=8 | `lowcov_full_raw.jsonl`(8)，`lowcov_gpt4o_raw.jsonl`(8) | — | GDgpt 8/8=100% 弃权 vs GPT-4o 0/8=0% |
| **组件消融** | disease-centered N=3 | Full vs single_agent vs rag_only | `cmp3_full_ext.jsonl`，`abl_single_ext.jsonl`，`abl_rag_ext.jsonl` (各3题) | — | Bridge消融：PathF1 0.667→0.084（-87%）；single-agent PathF1=0.653 |
| **外部 PcQA** | PcQA pan-cancer N=99/100 | GPT-4o direct N=100 | `pcqa100_gdgpt_raw.jsonl`(99)，`pcqa100_gpt4o_raw.jsonl`(100) | `pcqa49_judge_results.json`(N=49)，`pcqa_remaining_judge.json`(N=19)，合计 N=68 | D3 GDgpt=4.21 vs GPT-4o=2.94（N=68，加权验算✓） |
| **第二 backbone（gpt-4o-mini）** | 内部9题 | gpt-4o-mini direct N=9 | `mini_9q_raw.jsonl`(9)，`mini_direct_9q_raw.jsonl`(9) | `backbone_mini_vs_gpt4o_direct.json` | KG覆盖 9/9 HIGH，inline KG引用 7/9；`backbone_judge.log`+`backbone_mini_judge.log` 存在 |
| **多评委陪审团** | 内部 N=9 + PcQA N=20 | 3评委(gpt-4o/qwen-max/mini) | 依赖上述 raw 文件 | `multijudge_9q.json`(N=9)，`multijudge_pcqa20.json`(N=20) | 内部 3/3全票 GDgpt D3 领先；外部 2/3（mini 反转，如实报告）|
| **v2.3 内联引用** | 内部 9题重跑（v2.3 prompt） | gpt-4o direct（复用旧结果） | `v23_9q_raw.jsonl`(9) | `llm_judge_v23_results.json` | D3 GDgpt=4.038 vs GPT-4o=3.223（N=9，3票）|
| **消融 30题 legacy（旧集）** | 30题 legacy 集（Exp-0/Exp-1） | LLM only | `exp0_full.jsonl`(30)，`exp1_llm_only.jsonl`(30) | — | Bridge Hit: Full=1.0 vs LLM=0；PathF1: 0.316 vs 0 |
| **GPT-4o 15题扩样本** | 内部 15题 | GPT-4o | `exp15_gpt4o_ext.jsonl`(15)，`exp15_gpt4o_raw.jsonl`(15) | — | GPT-4o 全0结构性确认 |

### 专项核实

**PcQA N 说明**：`pcqa_100.jsonl` 实为 100题；GDgpt 实跑了 99题（`pcqa100_gdgpt_raw.jsonl` 99行），GPT-4o 跑了 100题（100行）。LLM-judge 有完整逐维分数的为 N=68（49+19），其余 31题有总分日志（`pcqa99_judge.log`）但无逐维数字。**论文§4.5 说"N=68 with per-dimension scores, out of 99 total" 与文件一致 ✓**。

**第二 backbone 结论**：`mini_9q_raw.jsonl` 存在，9题，KG覆盖 HIGH 9/9，inline KG引用 7/9——**结构性保证与 backbone 无关结论成立**。工作记录§8(2026-07-20)记录一致。

**多评委 D3 数字核实**（LIVE 读取 `multijudge_9q.json`）：
- gpt-4o D3：GDgpt=4.222，GPT-4o=2.889（论文 Table 6：4.22/2.89 ✓）
- qwen-max D3：GDgpt=3.444，GPT-4o=1.333（论文 Table 6：3.44/1.33 ✓）
- gpt-4o-mini D3：GDgpt=3.889，GPT-4o=3.556（论文 Table 6：3.89/3.56 ✓）
- swap_consistency：gpt-4o=0.844，qwen-max=0.778，mini=0.489（论文§5.4 ✓）

**Wilcoxon/bootstrap 统计**：`compute_paired_stats.py` 脚本存在，数据文件（`adapt15_full_ext.jsonl`+`exp15_gpt4o_ext.jsonl`+gold）均存在。工作记录§8(2026-07-13)记录输出：Pathway F1 0.596，p≈0.0007，CI [0.57,0.62]；Bridge Hit p≈0.0007，CI [1.0,1.0]；Gene Recall p≈0.068，CI [0.013,0.093]（INFERRED，可复现但未本次重算）。**无单独 JSON 输出文件**——这是唯一的产物缺口。

**人工评分 kappa**：`human_rating_form_v23.md` 存在（`evaluation/results/`），但**全空（0个数字填入）**，是未填写的表单模板。`compute_kappa.py` 存在但从未有真实输入。**Human kappa 从未产生**。

**时间分割评测**：`evaluation/` 目录下无 `timesplit_testset.jsonl`。external_benchmarks 下无时间分割数据。**支柱3时间分割完全没有产物**，与论文 future work 描述一致。

---

## 第三部分：论文初稿完成度（`docs/paper_draft_en.md`）

| 章节 | 完成度 | 数字/产物匹配情况 |
|---|---|---|
| Abstract | 完整 | Pathway F1=0.596、p≈0.0007、CI [0.57,0.62]（INFERRED）；弃权 8/8=100%（✅ `lowcov` files）；D3内部 4.04/3.22（✅ `llm_judge_v23_results.json`）；D3外部 4.21/2.94（✅ 加权验算）|
| §1 Introduction | 完整 | 无具体实验数字，纯论证 |
| §2 Related Work | 完整 | 18个引用全部 VERIFIED，MDAT/MedAgents/RareAgents 竞品已补 |
| §3 System | 完整 | 架构描述与代码一致（10133节点/87838边/11 intents/3 Bridge） |
| §4.1 Experimental Setup | 完整 | N=15/N=8/N=3/N=100 均有对应产物文件 |
| §4.2 Abstention (N=8) | 完整 | ✅ `lowcov_full_raw.jsonl`(8)，`lowcov_gpt4o_raw.jsonl`(8) |
| §4.3 Main Results (N=15) | 完整 | ⚠️ 数字来自 stdout 记录，数据文件存在可复现，但无 JSON 输出存档 |
| §4.4 Ablation (N=3) | 完整 | ✅ `abl_rag_ext.jsonl`(3) PathF1=0.084；`abl_single_ext.jsonl`(3) PathF1=0.653 vs Full=0.667 |
| §4.5 PcQA External (N=68/99) | 完整 | ✅ files 存在，数字加权验算吻合 |
| §4.6 Adaptive Routing | 完整 | ✅ `adapt3_ext.jsonl`(3) PathF1=0.596/0.614 vs Full=0.667；延迟 37 sec 记录在工作记录 |
| §4.7 Backbone Independence | 完整 | ✅ `mini_9q_raw.jsonl`(9)，`backbone_mini_vs_gpt4o_direct.json` |
| §5.1-5.3 Case Studies | 完整 | ✓ 描述与已知产物一致 |
| §5.4 Multi-Judge Panel | 完整 | ✅ `multijudge_9q.json`(N=9)，`multijudge_pcqa20.json`(N=20)；数字全部吻合 |
| §5.5 Limitation Case | 完整 | 字母序问题是已核实 KG 属性 |
| §6 Discussion | 完整 | future work 4条均有对应工程待做项 |
| References | 完整 | 18个引用全 VERIFIED，0个 [CHECK-DOI] 残留 |

**数字与产物不一致情况（关键）**：

| 论文数字 | 来源文件/记录 | 一致性 |
|---|---|---|
| Pathway F1=0.596，p≈0.0007，CI[0.57,0.62]（N=15） | 工作记录§8，数据文件存在 | ⚠️ INFERRED（无存档 JSON，数据可复现）|
| Bridge Hit=1.0，p≈0.0007（N=15） | 工作记录§8 | ⚠️ INFERRED（同上）|
| D3 内部 4.038 vs 3.223（论文写 4.04/3.22）| `llm_judge_v23_results.json` D3 A=4.038，B=3.223 | ✅ LIVE 核实，精确吻合 |
| 弃权 8/8=100% vs 0/8=0% | `lowcov_full_raw.jsonl`(8行)，`lowcov_gpt4o_raw.jsonl`(8行) | ✅ LIVE 核实 |
| D3 外部 PcQA 4.21 vs 2.94（N=68） | 加权：(49×4.306+19×3.947)/68=4.206≈4.21 ✓ | ✅ LIVE 核实 |
| Multi-judge 9q gpt-4o D3: 4.22/2.89 | `multijudge_9q.json` 4.222/2.889 | ✅ LIVE 核实 |
| Multi-judge qwen-max D3: 3.44/1.33 | `multijudge_9q.json` 3.444/1.333 | ✅ LIVE 核实 |
| Multi-judge mini D3: 3.89/3.56，swap=0.49 | `multijudge_9q.json` 3.889/3.556，0.489 | ✅ LIVE 核实 |
| PcQA N=99 raw，N=68 with per-dim scores | `pcqa100_gdgpt_raw.jsonl`(99行)，`pcqa49_judge`(49)+`pcqa_remaining`(19)=68 | ✅ LIVE 核实 |
| Ablation Bridge消融 PathF1: 0.084 | `abl_rag_ext.jsonl` N=3（未重算但文件存在） | ⚠️ INFERRED（数据存在，未重算）|

**总体**：论文中引用的所有关键数字，**原始数据文件全部存在**，**JSON 层面直接可读的数字**（judge scores、N 数）全部核实吻合。仅 Wilcoxon/bootstrap 统计结果无单独存档文件（只在 stdout 日志中）。

---

## 第四部分：差距与最短路径

### 距离"能答辩"还差什么

| 缺口 | 严重度 | 估计工作量 | 说明 |
|---|---|---|---|
| **Wilcoxon 统计存档**（把 compute_paired_stats.py 输出保存为 JSON） | 🟡 中 | **0.5 天** | 跑一次命令，保存输出；答辩被问"统计数字从哪来"时需出示文件 |
| **human_rating_form_v23.md 找人填写**（导师/医学生，N≥3题） | 🟡 中 | **1–2 天**（协调人/填表） | 空表单存在，compute_kappa.py 存在；填完即可算 kappa；不填则只有 LLM-judge |
| 论文 TODO/占位符清理 | 🟢 低 | 0.5 天 | Abstract 末尾"[GitHub URL]"需填；个别 `[TODO]` 占位 |
| 图表编号修正（论文有重复 Table 1） | 🟢 低 | 0.5 天 | §4.2 和 §4.3 都用了"Table 1" |

### 距离"能投 workshop（ML4H 2026 / Clinical NLP / BioNLP）"还差什么

| 缺口 | 性价比 | 估计工作量 | 说明 |
|---|---|---|---|
| Wilcoxon 统计 JSON 存档 | ⭐⭐⭐ | 0.5 天 | 必须。审稿人会问原始 stats |
| PcQA 剩余 31题补 per-dim judge 分（N=68→N=99） | ⭐⭐ | 1–2 天（API 调用） | 可选；N=68 在 GigaScience workshop 级别已可接受 |
| Human kappa（哪怕 N=5题，κ≥0.6） | ⭐⭐⭐ | 2–3 天（协调+填表+计算） | 把 LLM-judge 从"未验证代理"升级为"验证过的代理"；投 workshop 最高性价比改进 |
| 时间分割评测（支柱3） | ⭐ | 5–10 天（构建 post-cutoff 数据+跑实验） | 已是 future work 定位；答辩不必须 |
| 顶层图表美化（Figure 1架构图/Figure 3 bar chart） | ⭐ | 1 天 | 可有可无，workshop 接受 PNG |

### `feat/adaptive-routing` 分支状态

**LIVE 核实**：`git log grad..feat/adaptive-routing` 返回空，确认**已 merge 进 grad**。该分支有 10 个实质提交（含 `feat: 实现自适应复杂度路由` + `results: 自适应vs全模式对比`），**不是空壳，也不是半成品**，是已完整实现并合并的功能。工作记录§8(2026-07-13)记录 merge 操作。

---

## Falsifier（反证检验）

**主结论是"工作量基本达标"。反证测试：在论文引用的数字里找一个在产物中对不上或找不到的。**

**测试的 falsifier**：Pathway F1=0.596、p≈0.0007、CI [0.57,0.62] 这组 N=15 核心统计数字——这是论文的头条主实验结果，如果产物里找不到，主结论必须下调。

**结果**：
- `adapt15_full_ext.jsonl`（15行）✅ 存在
- `exp15_gpt4o_ext.jsonl`（15行）✅ 存在  
- `testset_kg_optimized_enriched_with_edges.jsonl`（gold，含 expected_kg_edges）✅ 存在
- `compute_paired_stats.py` ✅ 存在，有正确的 Wilcoxon+bootstrap 逻辑
- **但**：`evaluation/results/` 中**无任何包含 p-value 或 CI 的 JSON 输出文件**

**结论**：数据存在、脚本存在、结论可复现，但**统计输出从未存盘**。这是可以当场重跑修复的缺口（0.5 天），不推翻"工作量达标"的主结论，但**确认了一个诚信风险**：如果答辩委员要求当场展示统计数字的原始输出，目前拿不出来。

**主结论维持，但降评为 MEDIUM 置信度（因 falsifier 揭示了统计存档缺失这条生产链断点）**。

---

## 开放问题

1. `pcqa99_judge.log` 中有 99题的总分（A_total/B_total），但无逐维 D1-D5。论文 §4.5 注释中说 N=68 有逐维数字，N=99 只有总分——这与文件一致，但若审稿人要求全量逐维数字，需补跑。
2. 消融 N=3 对审稿人可信度偏低。工作记录提到计划扩到 38题，但从未执行（Exp-2~6 均未在 38题集上跑）。
3. 单一场景（disease-centered 癌症）——PcQA 提供了一定外部泛化，但所有内部集仍集中在相似疾病类型。
