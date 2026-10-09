# 独立测试集 Output 目录

## 📁 文件说明

### 推荐使用的测试集

| 文件 | 题数 | 用途 | 说明 |
|------|:----:|------|------|
| **`testset_quick.jsonl`** | 30 | 🚀 快速验证 | 调试代码、验证流程 |
| **`testset_full.jsonl`** | 80 | 📊 正式实验 | 论文数据、完整评测 |

### 其他文件（可忽略）

| 文件 | 说明 |
|------|------|
| `independent_gold_final.jsonl` | 旧版测试集 (53题) |
| `testset_high_quality.jsonl` | 实验性生成 |
| `testset_combined.jsonl` | 实验性生成 |
| `testset_all_tiers.jsonl` | 实验性生成 |

---

## 📊 测试集对比

### Quick (快速版) - 30 题

```
┌─────────────────────┬──────┬────────────────┐
│ 类型                │ 数量 │ 数据来源       │
├─────────────────────┼──────┼────────────────┤
│ disease-centered    │  10  │ Open Targets   │
│ gene-centered       │  12  │ Open Targets   │
│ pathway-centered    │   8  │ Reactome       │
├─────────────────────┼──────┼────────────────┤
│ 总计                │  30  │                │
└─────────────────────┴──────┴────────────────┘
```

**使用场景**：
- ✅ 开发调试
- ✅ 快速验证改动
- ✅ CI/CD 流程

---

### Full (完整版) - 80 题

```
┌─────────────────────┬──────┬────────────────┐
│ 类型                │ 数量 │ 数据来源       │
├─────────────────────┼──────┼────────────────┤
│ disease-centered    │  18  │ Open Targets   │
│ gene-centered       │  30  │ Open Targets   │
│ pathway-centered    │  32  │ Reactome       │
├─────────────────────┼──────┼────────────────┤
│ 总计                │  80  │                │
└─────────────────────┴──────┴────────────────┘
```

**使用场景**：
- ✅ 正式实验
- ✅ 论文评测
- ✅ 消融实验
- ✅ 统计显著性分析

---

## 🔧 使用方法

### 在评测脚本中指定测试集

```bash
# 快速验证
python evaluation/run_batch_eval_template.py \
  --testset evaluation/independent_testset/output/testset_quick.jsonl

# 正式实验
python evaluation/run_batch_eval_template.py \
  --testset evaluation/independent_testset/output/testset_full.jsonl
```

### Python 代码加载

```python
import json

# 快速版
with open("evaluation/independent_testset/output/testset_quick.jsonl") as f:
    quick_data = [json.loads(line) for line in f]

# 完整版
with open("evaluation/independent_testset/output/testset_full.jsonl") as f:
    full_data = [json.loads(line) for line in f]
```

---

## 📋 数据格式

每条测试数据包含以下字段：

```json
{
  "id": "ind_dc_xxx",
  "task_type": "disease-centered | gene-centered | pathway-centered",
  "question": "问题文本",
  "disease_focus": "疾病名称 (disease-centered)",
  "gene_focus": "基因名称 (gene-centered)",
  "pathway_focus": "通路名称 (pathway-centered)",
  "gold_genes": ["基因1", "基因2", ...],
  "gold_diseases": ["疾病1", "疾病2", ...],
  "confidence_scores": {"实体": 置信度分数},
  "source": "Open Targets Platform | Reactome",
  "annotation_status": "independent_source"
}
```

---

## 📅 生成日期

- Quick: 2026-03-31
- Full: 2026-03-31

## 📚 数据来源

- **Open Targets Platform**: https://platform.opentargets.org/
- **Reactome**: https://reactome.org/
