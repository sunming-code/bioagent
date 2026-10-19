## Baseline 与消融设计

### 核心 baseline

1. `LLM only`
   - 关闭 Neo4j 和 FAISS。
   - 保持问题集和提示词风格不变。
   - 目的：衡量模型纯靠参数知识时能回答到什么程度。

2. `LLM + single-hop KG`
   - 每题只允许一次 Task KG 查询。
   - 推荐只保留：
     - `DiseaseToGene`
     - `GeneToPathway`
     - `DiseaseToPhenotype`
   - 目的：衡量“图谱 grounding”本身的价值，但不使用多跳规划。

3. `LLM + Task KG multi-hop`
   - 使用当前完整系统：
     - query planning
     - `kg_prefetch`
     - bridge intents
     - 多角色综合

### 可选 baseline

4. `LLM + Web/PubMed`
   - 保留外部检索工具，关闭 Neo4j。
   - 目的：比较开放式检索与结构化 KG 检索的差异。

5. `LLM + FAISS memory`
   - 保留长期经验向量库，关闭 Neo4j。
   - 目的：比较结构化图谱与非结构化长期经验的增益差异。

## 推荐消融实验

1. 去掉 `kg_prefetch`
   - 让专家在没有共享 Task KG 证据的情况下直接开始分析。

2. 去掉 bridge intents
   - 禁用：
     - `DiseaseGenePathwayBridge`
     - `GenePhenotypeBridge`
     - `DrugTargetDiseaseBridge`
   - 仅保留单跳查询。

3. 去掉多角色设置
   - 把多个 specialist 简化为一个综合机制分析角色。

4. 去掉 phenotype/drug 扩展角色
   - 仅保留：
     - `GeneCurator`
     - `DiseaseMechanismAnalyst`
     - `PathwayBiologist`
     - `EvidenceReviewer`
     - `HypothesisIntegrator`

## 每组实验都建议报告的指标

- 检索层：
  - Recall@k
  - Precision@k
  - Bridge Hit Rate
  - Coverage
- 端到端层：
  - Gene F1
  - Pathway F1
  - Phenotype F1
  - Mechanism Completeness
  - Graph Faithfulness
  - Utility Score

## 最小实验矩阵

| 实验 | Neo4j | Bridge | 多角色 | KG Prefetch |
|---|---|---|---|---|
| LLM only | 否 | 否 | 可选 | 否 |
| Single-hop KG | 是 | 否 | 可选 | 否 |
| Full Task KG | 是 | 是 | 是 | 是 |
| No prefetch ablation | 是 | 是 | 是 | 否 |
| No bridge ablation | 是 | 否 | 是 | 是 |
| Single-role ablation | 是 | 是 | 否 | 是 |

## 运行日志建议

每次实验至少保存：

- `id`
- 完整回答文本
- `predicted_genes / pathways / phenotypes / drugs`
- 是否找到 bridge
- 所有工具调用和工具输出
- 模型名称
- 当前 baseline / ablation 标签

这样后面写案例分析和错误归因会容易很多。
