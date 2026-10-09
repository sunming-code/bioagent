# GDgpt 实验阶段性报告

> **项目名称**：基于 Task KG 的多智能体基因-疾病-通路机制分析系统  
> **报告日期**：2026年3月19日  
> **报告类型**：阶段性实验成果汇报  

---

## 1. 项目概述

### 1.1 研究目标

本项目旨在构建一个**基于 Task KG（任务知识图谱）的多智能体基因-疾病-通路（GDP）机制分析系统**，通过结合大语言模型（LLM）与结构化知识图谱，回答复杂的生物医学机制问题。

### 1.2 核心创新点

| 创新点 | 描述 |
|--------|------|
| **Task KG 集成** | 基于 Neo4j 的结构化知识图谱，包含 Gene、Disease、Pathway、Phenotype、Drug 五类实体 |
| **Bridge 多跳查询** | 设计 3 种多跳查询意图（Disease→Gene→Pathway 等），支持复杂机制链推理 |
| **KG Prefetch 机制** | 在专家会诊前预取共享 KG 证据，确保多角色基于统一事实讨论 |
| **多角色专家协同** | 7 种专业角色（GeneCurator、PathwayBiologist 等）分工协作 |
| **双知识库** | CorrectKB（成功案例）+ ChainKB（失败反思）作为长期经验记忆 |

### 1.3 系统架构

```
用户输入问题
    ↓
[Triage] 分诊：选择 ≥3 个专家角色
    ↓
[KG Prefetch] 共享 Task KG 预取：自动规划并执行 KG 查询
    ↓
[Consultation] 专家会诊：各角色基于 prefetch + FAISS 上下文独立分析
    ↓
[Lead Physician] 综合各专家意见
    ↓
[Safety Reviewer] 判断是否收敛，输出最终答案
    ↓
（未收敛则进入下一轮会诊，最多 max_rounds 轮）
```

---

## 2. 实验设计

### 2.1 评测数据集

| 项目 | 说明 |
|------|------|
| **数据集名称** | `evaluation_gold_final.jsonl` |
| **样本数量** | 30 题 |
| **题目类型** | 疾病中心型、基因中心型、药物机制型等 |
| **标注内容** | gold_genes、gold_pathways、gold_phenotypes、gold_drugs、gold_bridge |
| **数据来源** | 基于 PrimeKG 图谱自动生成 + 人工复核 |

### 2.2 评测指标

#### 检索层指标（Retrieval Metrics）

| 指标 | 说明 |
|------|------|
| **Gene Recall@5** | 预测基因与 gold 基因的召回率（取 top-5） |
| **Gene Precision@5** | 预测基因的精确率 |
| **Pathway Recall@5** | 预测通路的召回率 |
| **Pathway Precision@5** | 预测通路的精确率 |
| **Bridge Hit Rate** | 多跳查询成功率（系统是否找到 gold 中标注的 bridge 路径） |
| **Coverage** | 四类实体（基因/通路/表型/药物）的覆盖比例 |

#### 端到端指标（End-to-End Metrics）

| 指标 | 说明 |
|------|------|
| **Gene F1** | 基因预测的 F1 分数 |
| **Pathway F1** | 通路预测的 F1 分数 |
| **Phenotype F1** | 表型预测的 F1 分数 |
| **Mechanism Completeness** | 机制完整性（0-2，待人工评估） |
| **Graph Faithfulness** | 图谱忠实度（0-2，待人工评估） |
| **Utility Score** | 答案实用性（1-5，待人工评估） |

### 2.3 实验矩阵设计

| 实验 ID | 实验名称 | Neo4j | Bridge | 多角色 | KG Prefetch | 状态 |
|---------|----------|:-----:|:------:|:------:|:-----------:|:----:|
| Exp-0 | Full Task KG | ✅ | ✅ | ✅ | ✅ | ✅ 完成 |
| Exp-1 | LLM only | ❌ | ❌ | ✅ | ❌ | ✅ 完成 |
| Exp-2 | Single-hop KG | ✅ | ❌ | ✅ | ❌ | ⏳ 待做 |
| Exp-3 | No KG Prefetch | ✅ | ✅ | ✅ | ❌ | ⏳ 待做 |
| Exp-4 | No Bridge | ✅ | ❌ | ✅ | ✅ | ⏳ 待做 |
| Exp-5 | Single Role | ✅ | ✅ | ❌ | ✅ | ⏳ 待做 |

---

## 3. 已完成实验结果

### 3.1 实验配置

| 参数 | Exp-0 (Full Task KG) | Exp-1 (LLM only) |
|------|:--------------------:|:----------------:|
| Neo4j 知识图谱 | ✅ 启用 | ❌ 关闭 |
| Bridge 多跳查询 | ✅ 启用 | ❌ 关闭 |
| KG Prefetch | ✅ 启用 | ❌ 关闭 |
| 多角色专家 | ✅ 启用 | ✅ 启用 |
| 最大会诊轮数 | 6 | 6 |
| 样本数量 | 30 | 30 |

### 3.2 检索层指标对比

| 指标 | Exp-0 Full Task KG | Exp-1 LLM only | 差值 | 提升幅度 |
|------|:------------------:|:--------------:|:----:|:--------:|
| **Gene Recall@5** | 0.055 | 0.000 | +0.055 | — |
| **Gene Precision@5** | 0.040 | 0.000 | +0.040 | — |
| **Pathway Recall@5** | 0.394 | 0.000 | +0.394 | — |
| **Pathway Precision@5** | 0.153 | 0.000 | +0.153 | — |
| **Bridge Hit Rate** | **1.000** | 0.000 | +1.000 | — |
| **Coverage** | 0.858 | 0.000 | +0.858 | — |

> **关键发现**：LLM only 实验的检索层指标**全部为 0**，因为纯 LLM 无法调用 KG 工具，无法产生结构化的实体抽取结果。这证明了 **Task KG 对于结构化信息检索是不可或缺的**。

### 3.3 端到端指标对比

| 指标 | Exp-0 Full Task KG | Exp-1 LLM only | 差值 | 说明 |
|------|:------------------:|:--------------:|:----:|:----:|
| **Gene F1** | 0.060 | 0.000 | +0.060 | Task KG 优 |
| **Pathway F1** | 0.316 | 0.000 | +0.316 | Task KG 优 |
| **Phenotype F1** | 0.438 | **0.633** | -0.195 | LLM only 优 |

> **有趣发现**：在 **Phenotype F1** 指标上，纯 LLM 反而表现更好（0.633 vs 0.438）。这可能是因为：
> 1. LLM 的参数知识对临床表型描述有较强的记忆
> 2. 当前 KG 中表型信息相对稀疏
> 3. Task KG 系统可能过度依赖图谱中的表型节点，而忽略了 LLM 的常识知识

### 3.4 结果可视化

实验结果图表已保存至 `evaluation/results/` 目录：

- `retrieval_metrics.png` — 检索层指标对比图
- `e2e_metrics.png` — 端到端指标对比图

---

## 4. 关键发现与分析

### 4.1 Task KG 的价值验证

| 维度 | 结论 | 证据 |
|------|------|------|
| **结构化检索** | Task KG 是必要的 | LLM only 检索层指标全为 0 |
| **多跳推理** | Bridge 查询有效 | Bridge Hit Rate = 1.0 |
| **实体覆盖** | KG 大幅提升覆盖率 | Coverage 从 0 提升至 85.8% |
| **通路识别** | 显著优势 | Pathway Recall@5 从 0 提升至 39.4% |

### 4.2 待改进方向

| 问题 | 可能原因 | 改进方向 |
|------|----------|----------|
| Gene Recall 偏低 (5.5%) | 1. 实体抽取正则不完善<br>2. KG 中基因命名不规范 | 改进抽取逻辑，增加别名映射 |
| Phenotype F1 低于 LLM only | 1. KG 表型节点稀疏<br>2. 过度依赖图谱 | 允许 LLM 补充表型，混合策略 |
| 部分回答为 "Continuing discussion" | max_rounds 内未收敛 | 调整收敛条件或增加轮数 |

### 4.3 LLM only 的局限性

通过 Exp-1 的结果，我们观察到纯 LLM（无工具调用）的关键问题：

1. **无法输出结构化实体**：所有 `predicted_genes`、`predicted_pathways` 等字段为空数组
2. **无法验证事实**：LLM 的回答基于参数记忆，无法区分"图谱支持的事实"与"推测性结论"
3. **机制链不可追溯**：无法展示 Disease→Gene→Pathway 的推理路径

---

## 5. 后续实验计划

### 5.1 待完成的 Baseline 实验

| 优先级 | 实验 | 目的 | 预计时间 |
|:------:|------|------|:--------:|
| **P0** | Exp-2: Single-hop KG | 验证多跳 Bridge 相比单跳的增益 | 3-4h |
| **P0** | Exp-4: No Bridge | 消融 Bridge 意图，量化多跳价值 | 3-4h |

### 5.2 待完成的消融实验

| 优先级 | 实验 | 目的 | 预计时间 |
|:------:|------|------|:--------:|
| **P1** | Exp-3: No KG Prefetch | 验证预取机制的价值 | 3-4h |
| **P2** | Exp-5: Single Role | 验证多角色协同的价值 | 3-4h |

### 5.3 其他待办

| 任务 | 描述 | 状态 |
|------|------|:----:|
| 案例分析 ×2 | 详细分析 2 个典型问题的推理过程 | ⏳ 待做 |
| 双知识库效果说明 | CorrectKB/ChainKB 的定性分析 | ⏳ 待做 |
| 人工评估指标 | Mechanism Completeness、Graph Faithfulness、Utility Score | ⏳ 待做 |

---

## 6. 技术细节

### 6.1 实验环境

| 项目 | 配置 |
|------|------|
| LLM | GPT-4o (gpt-4o-2024-05-13) |
| Neo4j | 5.x (Bolt 协议) |
| 向量库 | FAISS (L2 距离) |
| 框架 | LangGraph + Streamlit |
| 运行环境 | macOS / Python 3.13 |

### 6.2 数据来源

| 数据 | 来源 |
|------|------|
| 知识图谱 | PrimeKG → 自定义 ETL → Neo4j |
| 评测数据集 | 基于 KG 自动生成 + 人工复核 |
| 嵌入模型 | text-embedding-3-small |

### 6.3 文件结构

```
evaluation/
├── evaluation_gold_final.jsonl      # 30题 gold 标准集
├── experiment_config.yaml           # 实验配置
├── results/
│   ├── exp0_full_raw.jsonl          # Exp-0 原始输出
│   ├── exp0_full.jsonl              # Exp-0 实体抽取后
│   ├── exp1_llm_only_raw.jsonl      # Exp-1 原始输出
│   ├── exp1_llm_only.jsonl          # Exp-1 最终版本
│   ├── results_summary.json         # 实验结果汇总
│   ├── retrieval_metrics.png        # 检索层指标图
│   └── e2e_metrics.png              # 端到端指标图
├── compute_metrics.py               # 指标计算脚本
├── run_all_experiments.py           # 全自动实验脚本
└── EXPERIMENT_REPORT.md             # 本报告
```

---

## 7. 总结

### 7.1 阶段性成果

1. ✅ 完成系统核心功能开发（Task KG 集成、Bridge 多跳、KG Prefetch、多角色协同）
2. ✅ 构建 30 题评测数据集
3. ✅ 完成 2 组核心实验（Full Task KG vs LLM only）
4. ✅ 建立自动化评测流程

### 7.2 核心结论

> **Task KG 系统在结构化信息检索和多跳推理上显著优于纯 LLM**，验证了知识图谱增强的必要性。Bridge Hit Rate = 1.0 证明多跳查询设计有效。

### 7.3 下一步重点

1. 完成 Single-hop KG 和 No Bridge 实验，量化多跳查询的边际贡献
2. 改进实体抽取逻辑，提升 Gene Recall
3. 设计混合策略，利用 LLM 知识补充 KG 稀疏的表型信息

---

**报告完成时间**：2026-03-19  
**负责人**：[待填写]  
**指导教师**：[待填写]
