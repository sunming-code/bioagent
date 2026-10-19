## Breast Carcinoma 案例分析

### 基本信息

- `id`: `eval-001`
- `task_type`: `disease_centered`
- `difficulty`: `medium`
- `question`: `我怀疑我有 breast carcinoma，把他相关的基因/通路给我解释一下，以及他有什么症状呢？`
- `system`: `Full Task KG multi-hop`

### Gold 摘要

- Gold genes:
  - `AKT1`
  - `PIK3CA`
  - `EGFR`
  - `ERBB4`
  - `FGFR1`
  - `STAT3`
  - `FOXA1`
  - `MTOR`
- Gold pathways:
  - `PI3K/AKT/mTOR signaling`
  - `RAF/MAP kinase cascade`
  - `Estrogen-dependent gene expression`
  - `Interleukin-4 and Interleukin-13 signaling`
- Gold phenotypes:
  - 如果图谱没有明确支持，可以为空
- Gold drugs:
  - `Paclitaxel`
  - `Docetaxel`
  - `Everolimus`
- 是否期望存在 bridge:
  - 是
- Gold supporting relations:
  - `ASSOCIATED_WITH`
  - `INVOLVED_IN`
  - `TREATS`

### 一个强回答应该做到什么

- 明确识别 `breast carcinoma` 是主疾病实体。
- 返回一组核心 disease-gene，而不是只抓一个 marker。
- 至少给出一条清晰的 `Disease -> Gene -> Pathway` 机制桥接。
- 如果图谱里没有症状/表型支持，要明确说明“图谱未支持”，而不是乱编。
- 最好能补充治疗相关证据，但不要喧宾夺主。

### 应重点关注的优点

- 是否正确提到了 `PIK3CA`、`AKT1`、`MTOR`、`EGFR`、`ERBB4` 等关键基因。
- 是否把这些基因和 `PI3K/AKT/mTOR` 或 `RAF/MAP kinase cascade` 明确连起来。
- 是否把“图谱事实”和“模型解释”分开写清楚。
- 对症状是否足够谨慎，例如：
  - `No graph-supported phenotype/symptom chain was found.`

### 常见失败模式

- 只返回 1 个基因，然后剩下内容全靠脑补。
- 只会说“癌症相关通路很多”，却没有 bridge 证据。
- 混淆 disease subtype、syndrome、phenotype。
- 在图谱没有症状支持时仍然编造症状。

### 为什么这个案例重要

这个题能同时考察系统最关键的几层能力：

- disease 检索
- 多跳 bridge 检索
- pathway 机制解释
- symptom / phenotype 忠实度
- 可选的药物 grounding
