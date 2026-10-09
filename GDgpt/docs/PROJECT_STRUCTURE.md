# 📁 GDgpt 项目文档结构

> 最后更新：2026年3月31日

---

## 一、项目整体结构

```
GDgpt/
│
├── 📄 核心代码文件
│   ├── app.py                    # Flask Web 应用入口
│   ├── agents.py                 # 多智能体定义（分诊、专家）
│   ├── workflow.py               # 多智能体工作流程
│   ├── tools.py                  # KG 查询工具（11 种意图）
│   ├── knowledge_base.py         # 知识库管理
│   └── utils.py                  # 工具函数
│
├── 📋 配置文件
│   ├── config.json               # 运行配置（API Key 等）
│   ├── config.example.json       # 配置模板
│   └── requirements.txt          # Python 依赖
│
├── 📚 文档目录 (docs/)
│   ├── REPORT_TO_ADVISOR.md      # ⭐ 给老师的汇报总结
│   ├── PROJECT_STRUCTURE.md      # 本文档 - 项目结构说明
│   └── (其他文档将迁移至此)
│
├── 📊 评测目录 (evaluation/)
│   ├── 测试集文件
│   ├── 实验脚本
│   ├── 结果输出
│   └── 独立测试集构建
│
└── 📝 根目录文档
    ├── README.md                 # 项目总体说明
    ├── PRD.md                    # 产品需求文档
    ├── PROGRESS_REPORT.md        # 进度报告
    └── EXPERIMENT_PROPOSAL.md    # 实验方案
```

---

## 二、文档归类

### 2.1 核心文档（根目录）

| 文件 | 用途 | 读者 |
|------|------|------|
| `README.md` | 项目快速入门 | 所有人 |
| `PRD.md` | 产品需求文档 | 开发者 |
| `EXPERIMENT_PROPOSAL.md` | **完整实验方案** | 老师 |
| `PROGRESS_REPORT.md` | 开发进度记录 | 自己 |

### 2.2 汇报文档 (docs/)

| 文件 | 用途 | 说明 |
|------|------|------|
| `REPORT_TO_ADVISOR.md` | **给老师的精简汇报** | ⭐ 汇报时用这个 |
| `PROJECT_STRUCTURE.md` | 项目结构说明 | 理解项目布局 |

### 2.3 评测文档 (evaluation/)

| 文件 | 用途 |
|------|------|
| `README.md` | 评测模块说明 |
| `EXPERIMENT_REPORT.md` | 实验结果报告 |
| `baselines_and_ablation.md` | 基线与消融实验说明 |
| `breast_carcinoma_case_study.md` | 案例分析示例 |
| `case_study_template.md` | 案例分析模板 |

---

## 三、评测目录详细结构

```
evaluation/
│
├── 📊 测试集文件
│   ├── evaluation_gold_final.jsonl      # 原始测试集（有循环问题）
│   ├── evaluation_gold_schema.json      # 测试集格式定义
│   └── evaluation_prediction_schema.json # 预测结果格式定义
│
├── 🔬 实验脚本
│   ├── run_batch_eval_template.py       # 批量评测模板
│   ├── run_all_experiments.py           # 运行全部实验
│   ├── compute_metrics.py               # 计算评测指标
│   ├── plot_results.py                  # 绘制结果图表
│   ├── extract_from_tool_calls.py       # 从工具调用提取结果
│   ├── prepare_prediction_template.py   # 准备预测模板
│   └── analysis_by_coverage.py          # 按覆盖率分层分析
│
├── 📁 results/ (实验结果)
│   ├── exp0_full.jsonl                  # Exp-0 结果
│   ├── exp0_full_raw.jsonl              # Exp-0 原始输出
│   ├── exp1_llm_only.jsonl              # Exp-1 结果
│   ├── exp1_llm_only_raw.jsonl          # Exp-1 原始输出
│   ├── results_summary.json             # 结果汇总
│   ├── e2e_metrics.png                  # 端到端指标图
│   └── retrieval_metrics.png            # 检索指标图
│
├── 📁 scripts/ (工具脚本)
│   └── build_aligned_testset.py         # 构建 PrimeKG-aligned 测试集
│
└── 📁 independent_testset/ (独立测试集)
    ├── README.md                        # 独立测试集构建说明
    ├── scripts/                         # 数据获取脚本
    │   ├── fetch_opentargets.py         #   从 Open Targets 获取
    │   ├── fetch_reactome.py            #   从 Reactome 获取
    │   ├── generate_testset.py          #   生成测试集
    │   ├── validate_primekg_coverage.py #   验证 PrimeKG 覆盖率
    │   └── create_filtered_testset.py   #   创建过滤后测试集
    ├── raw_data/                        # 原始数据
    │   ├── opentargets_*.json           #   Open Targets 数据
    │   └── reactome_*.json              #   Reactome 数据
    ├── processed/                       # 处理后数据
    │   └── coverage_analysis*.json      #   覆盖率分析
    └── output/                          # 最终输出
        ├── independent_gold_final.jsonl #   独立测试集 (53 题)
        ├── testset_high_quality.jsonl   #   高质量子集 (30 题)
        └── testset_summary*.json        #   测试集统计
```

---

## 四、核心文件用途速查

### 4.1 给老师看的

| 优先级 | 文件 | 说明 |
|:------:|------|------|
| ⭐⭐⭐ | `docs/REPORT_TO_ADVISOR.md` | **精简汇报总结**（3-5 分钟快速了解） |
| ⭐⭐ | `EXPERIMENT_PROPOSAL.md` | **完整实验方案**（详细内容） |
| ⭐ | `README.md` | 项目总体说明 |

### 4.2 自己开发用的

| 文件 | 说明 |
|------|------|
| `PRD.md` | 需求定义 |
| `PROGRESS_REPORT.md` | 进度记录 |
| `evaluation/README.md` | 评测模块说明 |

### 4.3 运行实验用的

| 文件 | 说明 |
|------|------|
| `evaluation/run_batch_eval_template.py` | 运行单个实验 |
| `evaluation/run_all_experiments.py` | 运行全部实验 |
| `evaluation/analysis_by_coverage.py` | 分层分析 |

---

## 五、文档阅读顺序建议

### 老师/评审人
```
1. docs/REPORT_TO_ADVISOR.md    (5 分钟速览)
2. EXPERIMENT_PROPOSAL.md       (详细方案)
3. evaluation/EXPERIMENT_REPORT.md (实验结果)
```

### 开发者
```
1. README.md                    (快速入门)
2. PRD.md                       (需求理解)
3. evaluation/README.md         (评测模块)
```

### 自己回顾
```
1. PROGRESS_REPORT.md           (进度状态)
2. docs/PROJECT_STRUCTURE.md    (项目结构)
```

---

## 六、待清理/迁移的文件

以下文件可以考虑整理：

| 当前位置 | 建议操作 |
|----------|----------|
| 根目录的多个 .md 文件 | 保留或迁移到 docs/ |
| evaluation/ 下的临时文件 | 确认后删除 |
| `__pycache__/` | git ignore |

---

**保持文档整洁，便于后续维护！**
