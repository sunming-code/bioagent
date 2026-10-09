# 独立测试集构建计划

## 📋 背景与目标

### 问题
原测试集 `evaluation_gold_final.jsonl` 的 Gold Standard 直接从 PrimeKG/Neo4j 自动生成，而系统的知识源也是 PrimeKG，构成**循环评测（Circular Evaluation）**。

### 解决方案
从**独立于 PrimeKG 的外部数据源**构建测试集的 Gold Standard，使评测具有真正的验证意义。

```
独立数据源（DisGeNET/Open Targets/Reactome）
    ↓ 定义问题 + Gold 答案
独立测试集
    ↓ 系统使用 PrimeKG 检索
评测 KG 检索能力（有效！）
```

---

## 🎯 数据源选择

| 数据源 | 内容 | 优势 | 获取方式 |
|--------|------|------|----------|
| **Open Targets** | 基因-疾病关联 + 证据评分 | 整合多源证据，评分可靠，免费开放 | GraphQL API / 批量下载 |
| **Reactome** | 基因-通路关联 | 免费开源，质量高 | REST API / 批量下载 |
| **KEGG** | 基因-通路关联 | 经典权威 | REST API |
| **DisGeNET** | 基因-疾病关联 | 数据量大，有置信度评分 | 需注册 API |

### 优先级
1. **Open Targets**（基因-疾病）：完全免费开放，数据质量高
2. **Reactome**（基因-通路）：免费开源
3. **KEGG**（补充通路数据）：API 免费

---

## 📊 测试集设计

### 任务类型（与原系统一致）

| 任务类型 | 问题模板 | Gold 来源 |
|----------|----------|-----------|
| disease-centered | "What genes are associated with {disease}?" | Open Targets |
| gene-centered | "What diseases are associated with gene {gene}?" | Open Targets |
| pathway-centered | "What genes are involved in {pathway}?" | Reactome |
| drug-centered | "What genes does drug {drug} target?" | Open Targets |

### 测试集规模
- **目标**：50-100 条测试数据
- **疾病覆盖**：选择 PrimeKG 中也有的常见疾病（确保 KG 能检索到）
- **分布**：
  - disease-centered: 20 条
  - gene-centered: 20 条
  - pathway-centered: 15 条
  - drug-centered: 10 条

---

## 🛠️ 实现步骤

### Step 1: 从 Open Targets 获取基因-疾病关联
```python
# 使用 GraphQL API 查询高置信度的基因-疾病关联
# 筛选条件：association score > 0.5
```

### Step 2: 从 Reactome 获取基因-通路关联
```python
# 使用 REST API 查询通路中的基因
# https://reactome.org/ContentService/data/pathway/{id}/participants
```

### Step 3: 交叉验证 PrimeKG 覆盖率
```python
# 检查 Open Targets/Reactome 的关联是否也在 PrimeKG 中
# 记录覆盖率，作为评测分析的一部分
```

### Step 4: 生成测试集 JSONL
```python
# 格式与 evaluation_gold_final.jsonl 保持一致
# 添加 source 字段标注数据来源
```

---

## 📁 文件结构

```
evaluation/independent_testset/
├── README.md                           # 本文档
├── scripts/
│   ├── fetch_opentargets.py           # 从 Open Targets 获取数据
│   ├── fetch_reactome.py              # 从 Reactome 获取数据
│   ├── fetch_kegg.py                  # 从 KEGG 获取数据
│   ├── validate_primekg_coverage.py   # 验证 PrimeKG 覆盖率
│   └── generate_testset.py            # 生成最终测试集
├── raw_data/
│   ├── opentargets_associations.json  # Open Targets 原始数据
│   ├── reactome_pathways.json         # Reactome 原始数据
│   └── kegg_pathways.json             # KEGG 原始数据
├── processed/
│   └── coverage_analysis.json         # PrimeKG 覆盖率分析
└── output/
    └── independent_gold_final.jsonl   # 最终独立测试集
```

---

## ⏱️ 时间线

| 阶段 | 任务 | 预计时间 |
|------|------|----------|
| 1 | 编写数据获取脚本 | 1-2 小时 |
| 2 | 获取 Open Targets 数据 | 30 分钟 |
| 3 | 获取 Reactome 数据 | 30 分钟 |
| 4 | 验证 PrimeKG 覆盖率 | 1 小时 |
| 5 | 生成并校验测试集 | 1 小时 |

---

## ✅ 验收标准

1. [ ] 测试集 Gold Standard 100% 来自独立数据源
2. [ ] 测试集中至少 70% 的关联在 PrimeKG 中也存在（确保能测 KG 能力）
3. [ ] 测试集格式与 `evaluation_gold_final.jsonl` 兼容
4. [ ] 每条数据标注来源和置信度
5. [ ] 覆盖率分析报告完成
