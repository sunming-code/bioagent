## 案例分析模板

这个模板适用于成功案例和失败案例。

### 基本信息

- `id`:
- `task_type`:
- `difficulty`:
- `question`:
- `baseline/system`:

### Gold 摘要

- Gold genes:
- Gold pathways:
- Gold phenotypes:
- Gold drugs:
- 是否期望存在 bridge:
- Gold supporting relations:

### 系统输出摘要

- Predicted genes:
- Predicted pathways:
- Predicted phenotypes:
- Predicted drugs:
- 是否找到 bridge:
- 最终回答摘要:

### 检索层分析

- 是否命中了正确的 disease / gene / pathway 主实体？
- 是否检索到了正确的关系类型？
- bridge 查询是否真正起作用？
- phenotype / drug 证据是否被合理利用？

### 回答层分析

- 哪些结论是图谱明确支持的？
- 哪些结论是模型的机制推断？
- 回答是否清楚地区分了“图谱事实”和“模型解释”？
- 在症状 / 表型问题上，回答是否忠于图谱？

### 错误类型归因

勾选适用项：

- `graph_sparse`
- `alias_mismatch`
- `wrong_intent`
- `planner_failed`
- `bridge_missing`
- `hallucinated_pathway`
- `hallucinated_symptom`
- `drug_evidence_underused`
- `phenotype_evidence_underused`

### 结论

- 这个案例为什么重要：
- 下一步应该改什么：

## 推荐案例名称

- 成功案例：
  - `breast_carcinoma_mechanism_chain`
  - `lung_cancer_targeted_therapy_bridge`
  - `hepatocellular_carcinoma_symptom_support`
- 失败案例：
  - `schizophrenia_pathway_overgeneralization`
  - `symptom_not_supported_but_hallucinated`
  - `bridge_query_returns_sparse_results`
