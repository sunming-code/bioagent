## 评测资源说明

这个目录提供了一套 `MDTeamGPT + Task KG` 项目的起步评测资源，目标是支持一套
**小而精、适合毕业设计和论文写作**的评测流程，重点衡量：

- KG 检索质量
- 端到端回答质量
- 案例级别的可解释性

### 新增脚本（实验流程）

- `extract_from_tool_calls.py`
  - 从 prediction 的 `tool_calls` 中抽取 `predicted_genes`、`predicted_pathways`、`predicted_phenotypes`、`predicted_drugs`、`bridge_found`
  - 用法：`python extract_from_tool_calls.py --pred predictions_raw.jsonl --out predictions.jsonl`
- `run_experiments.ps1`
  - 一键运行 Exp-0、Exp-1、抽取、指标计算
  - 用法：在 `Lib\MDTeamGPT` 目录下执行 `.\evaluation\run_experiments.ps1`
- **`run_all_experiments.py`**（实验自动化）
  - 按 `experiment_config.yaml` 配置依次运行多种实验（Full KG、LLM only 等），在 30 题 gold 集上批量评测，抽取实体、计算指标，并生成对比图表
  - 用法：在 `Lib\MDTeamGPT` 下执行 `python evaluation/run_all_experiments.py`（全量）或 `python evaluation/run_all_experiments.py --quick`（3 题快速验证）
  - 输出：`evaluation/results/` 下的 predictions、`results_summary.json`、`retrieval_metrics.png`、`e2e_metrics.png`
- **`plot_results.py`**（可视化）
  - 根据 `results_summary.json` 生成 retrieval 与 end-to-end 指标柱状图
  - 用法：`python evaluation/plot_results.py --input evaluation/results/results_summary.json`

### 文件说明

- `experiment_config.yaml`
  - 实验自动化配置：gold 路径、output_dir、metrics_k、实验列表。修改此文件即可调整参数，无需改代码。
- `evaluation_gold_schema.json`
  - 人工精标 gold 数据的字段规范。
- `evaluation_gold_seed.jsonl`
  - 首版 30 题 starter 数据集，覆盖 disease / gene / pathway / drug / phenotype
    五类任务。这里的内容已经尽量与当前 Task KG 对齐，但仍需要人工复核。
- `evaluation_prediction_schema.json`
  - 预测结果文件的字段规范。
- `evaluation_predictions_sample.jsonl`
  - 一个预测结果示例，帮助你理解 `evaluation_predictions.jsonl` 应该怎么写。
- `prepare_prediction_template.py`
  - 根据 gold 文件自动生成一份“待填写”的 prediction 模板。
- `run_batch_eval_template.py`
  - 批量运行当前系统的评测脚手架，自动收集 `answer_text` 和 `tool_calls`。
- `compute_metrics.py`
  - 从 gold 文件和 prediction 文件中计算检索层与端到端层指标。
- `baselines_and_ablation.md`
  - 推荐的 baseline 与 ablation 方案。
- `case_study_template.md`
  - 成功案例 / 失败案例的分析模板。
- `breast_carcinoma_case_study.md`
  - 用 `breast carcinoma` 样例整理的一份案例分析示范。

### 推荐使用流程

1. 从 `evaluation_gold_seed.jsonl` 开始。
2. 人工核对每条样本，把 `gold_*` 字段补充/修正完整。
3. 将修订后的版本另存为 `evaluation_gold_final.jsonl`。
4. 先用 `prepare_prediction_template.py` 生成一份 prediction 模板。
5. 运行系统，将每题预测结果填入 `evaluation_predictions.jsonl`。
6. 用 `compute_metrics.py` 计算评测结果。

### 参考命令

#### 1. 生成 prediction 模板

```bash
.\\Scripts\\python.exe Lib\\MDTeamGPT\\evaluation\\prepare_prediction_template.py ^
  --gold Lib\\MDTeamGPT\\evaluation\\evaluation_gold_final.jsonl ^
  --out Lib\\MDTeamGPT\\evaluation\\evaluation_predictions.jsonl
```

#### 2. 计算指标

```bash
.\\Scripts\\python.exe Lib\\MDTeamGPT\\evaluation\\compute_metrics.py ^
  --gold Lib\\MDTeamGPT\\evaluation\\evaluation_gold_final.jsonl ^
  --pred Lib\\MDTeamGPT\\evaluation\\evaluation_predictions.jsonl
```

#### 3. 批量跑问题集（脚手架）

```powershell
# 在 Lib\MDTeamGPT 目录下执行（需先 scripts\activate）
python evaluation\run_batch_eval_template.py ^
  --gold evaluation\evaluation_gold_final.jsonl ^
  --out evaluation\predictions_exp0_raw.jsonl ^
  --max-rounds 6 ^
  --experiment full
```

Exp-1 (LLM only)：
```powershell
python evaluation\run_batch_eval_template.py ^
  --gold evaluation\evaluation_gold_final.jsonl ^
  --out evaluation\predictions_exp1_llm_only.jsonl ^
  --max-rounds 6 ^
  --experiment llm_only
```

#### 4. 从 tool_calls 抽取实体

```powershell
python evaluation\extract_from_tool_calls.py ^
  --pred evaluation\predictions_exp0_raw.jsonl ^
  --out evaluation\predictions_exp0.jsonl
```

#### 5. 实验自动化（推荐）

```powershell
# 在 Lib\MDTeamGPT 下执行（需先 scripts\activate）
# 快速验证（3 题）
python evaluation/run_all_experiments.py --quick

# 全量 30 题
python evaluation/run_all_experiments.py

# 指定配置
python evaluation/run_all_experiments.py --config evaluation/experiment_config.yaml

# 仅画图（已有 results_summary.json 时）
python evaluation/plot_results.py --input evaluation/results/results_summary.json
```

配置 `experiment_config.yaml` 可修改 gold 路径、output_dir、metrics_k，以及实验列表（新增实验只需追加一项）。

依赖：`run_all_experiments.py` 需要 `pyyaml`；`plot_results.py` 需要 `matplotlib`。若缺失可运行 `pip install pyyaml matplotlib`。

说明：
- 这个脚本会直接调用当前的 `workflow + agents` 跑问题集。
- 它会自动收集：
  - `answer_text`
  - `tool_calls`
  - 角色选择信息
- 但不会自动高质量抽取 `predicted_genes / pathways / phenotypes / drugs`。
- 因此更推荐的做法是：
  1. 先用它批量生成 raw predictions
  2. 再人工或用后处理脚本补全结构化字段
  3. 最后再跑 `compute_metrics.py`

### 预测结果至少应包含

每条 prediction 记录建议至少包含：

- `id`
- `answer_text`
- `predicted_genes`
- `predicted_pathways`
- `predicted_phenotypes`
- `predicted_drugs`
- `predicted_relations`
- `bridge_found`
- `mechanism_completeness`
- `graph_faithfulness`
- `utility_score`

### 重要说明

`evaluation_gold_seed.jsonl` 只是一个**图谱对齐的 starter 数据集**，并不是最终可直接发论文的
严谨 benchmark。所有标记为 `seed_from_graph_needs_manual_review` 的样本都建议你结合：

- 当前 Task KG 查询结果
- PrimeKG 原始数据
- Reactome / KEGG / WikiPathways
- HPO / MONDO / DisGeNET
- 必要时的 PubMed 摘要

进行人工复核后，再作为正式 gold 使用。
