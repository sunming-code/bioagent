# 📚 GDgpt 文档地图 (Documentation Index)

> 一张图看懂所有文档的分类、优先级与阅读顺序。
>
> 版本：v2.0  ·  最后更新：**2026-04-26**

---

## 🎯 TL;DR（30 秒速读）

GDgpt 是一个**精准肿瘤学 MTB（分子肿瘤委员会）机制解释辅助系统**，基于 Task KG + 7 角色 LLM Agent 构建。

- **当前主场景**：肿瘤科医生 MTB 会前准备，对比 GPT-4o 的核心价值是"可追溯 + 低幻觉"
- **当前阶段**：2026-04 完成场景重定位，Week 1-2 构建 20 题 MTB 场景测试集 + 跑 4 档 Baseline
- **卡点**：等导师确认 5 个方向性问题（见 `docs/导师汇报文档.md` §八）

---

## 🧭 角色化入口（按你是谁选入口）

### 🤖 我是一个刚接手项目的 AI Agent

按顺序读：

1. [`../AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) —— **Agent 迁移交接总入口**（必读）
2. [`SCENARIO_AND_RESEARCH_PROPOSAL.md`](./SCENARIO_AND_RESEARCH_PROPOSAL.md) —— MTB 场景定位权威源
3. [`导师汇报文档.md`](./导师汇报文档.md) —— 最新项目快照
4. [`../PRD.md`](../PRD.md) —— v2.0 需求规格（含 MTB 章节）
5. [`DECISION_LOG.md`](./DECISION_LOG.md) —— 历史决策与踩坑

### 👨‍🏫 我是老师 / 论文评审

按顺序读：

1. [`导师汇报文档.md`](./导师汇报文档.md) —— 给导师的正式汇报（2026-04-21）
2. [`SCENARIO_AND_RESEARCH_PROPOSAL.md`](./SCENARIO_AND_RESEARCH_PROPOSAL.md) —— MTB 场景定位详细论证
3. [`ADVISOR_FEEDBACK_ANALYSIS.md`](./ADVISOR_FEEDBACK_ANALYSIS.md) —— 对您反馈的深度应对
4. [`../EXPERIMENT_PROPOSAL.md`](../EXPERIMENT_PROPOSAL.md) Part I —— v2.0 场景导向评测方案

### 👩‍💻 我是新加入的开发者

按顺序读：

1. [`../README.md`](../README.md) —— 项目总览与快速启动
2. [`../PRD.md`](../PRD.md) —— 需求规格（第 0-7 章）
3. [`PROJECT_STRUCTURE.md`](./PROJECT_STRUCTURE.md) —— 目录与文件职责
4. [`../evaluation/README.md`](../evaluation/README.md) —— 评测框架
5. [`DECISION_LOG.md`](./DECISION_LOG.md) §3 —— 已踩过的坑

### 🧑‍🎓 我是学生自己（复习 / 续写）

按顺序读：

1. [`DECISION_LOG.md`](./DECISION_LOG.md) —— 快速回忆所有重大决策
2. [`../PROGRESS_REPORT.md`](../PROGRESS_REPORT.md) 末尾 2026-04 章节 —— 最近进度
3. [`../AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) —— 下次换 agent 直接用

---

## 📋 文档分类

### 1️⃣ Agent 迁移入口（2026-04 新建）

| 文档 | 用途 | 最后更新 |
| --- | --- | --- |
| [`../AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) ⭐ | **SSOT**：Agent 迁移交接总入口 | 2026-04-26 |
| [`../CLAUDE.md`](../CLAUDE.md) | Claude Code 专用入口（同步自 HANDOFF） | 2026-04-26 |
| [`../AGENTS.md`](../AGENTS.md) | Codex CLI / Cursor 新标准入口（同步自 HANDOFF） | 2026-04-26 |
| `../.cursorrules` | Cursor 老格式规则（精简版） | 2026-04-26 |
| `../.windsurfrules` | Windsurf 规则（精简版） | 2026-04-26 |
| `../.clinerules` | Cline / Roo 规则（精简版） | 2026-04-26 |
| `../.github/copilot-instructions.md` | GitHub Copilot 规则（精简版） | 2026-04-26 |

### 2️⃣ 需求与规格（Specs）

| 文档 | 版本 | 用途 | 最后更新 |
| --- | :---: | --- | --- |
| [`../README.md`](../README.md) | v2.0 | 项目总览 + 快速启动 | 2026-04-26 |
| [`../PRD.md`](../PRD.md) ⭐ | **v2.0** | 产品需求文档（MTB 定位 + 附录 A 存档 v1.3） | 2026-04-26 |
| [`PROJECT_STRUCTURE.md`](./PROJECT_STRUCTURE.md) | — | 项目文件结构说明 | 2026-03 |

### 3️⃣ 研究方案（Research Proposals）

| 文档 | 用途 | 最后更新 |
| --- | --- | --- |
| [`SCENARIO_AND_RESEARCH_PROPOSAL.md`](./SCENARIO_AND_RESEARCH_PROPOSAL.md) ⭐ | **MTB 场景定位权威源**（含 8 篇对标论文详解） | 2026-04-20 |
| [`ADVISOR_FEEDBACK_ANALYSIS.md`](./ADVISOR_FEEDBACK_ANALYSIS.md) | 导师 2026-04-17 反馈深度分析与应对策略 | 2026-04-17 |

### 4️⃣ 实验与评测（Experiments）

| 文档 | 版本 | 用途 | 最后更新 |
| --- | :---: | --- | --- |
| [`../EXPERIMENT_PROPOSAL.md`](../EXPERIMENT_PROPOSAL.md) ⭐ | **v2.0** | 实验方案（Part I v2.0 主方案 + Part II v1.0 存档） | 2026-04-26 |
| [`../evaluation/README.md`](../evaluation/README.md) | — | 评测框架使用说明 | 2026-03 |
| [`../evaluation/EXPERIMENT_REPORT.md`](../evaluation/EXPERIMENT_REPORT.md) | — | 实验结果报告 | 2026-03 |
| [`../evaluation/independent_testset/README.md`](../evaluation/independent_testset/README.md) | — | 独立测试集（轨道 C 降级版） | 2026-03-31 |

### 5️⃣ 进度与汇报（Progress & Reports）

| 文档 | 用途 | 最后更新 |
| --- | --- | --- |
| [`../PROGRESS_REPORT.md`](../PROGRESS_REPORT.md) ⭐ | 开发进度（累积 + 2026-04 重定位章节） | 2026-04-26 |
| [`导师汇报文档.md`](./导师汇报文档.md) ⭐ | 对导师正式汇报（2026-04-21） | 2026-04-21 |
| [`REPORT_TO_ADVISOR.md`](./REPORT_TO_ADVISOR.md) | 早期给老师的汇报总结 | 2026-03 |
| [`ADVISOR_BRIEFING_20260410.md`](./ADVISOR_BRIEFING_20260410.md) | 2026-04-10 汇报材料 | 2026-04-10 |
| [`TWO_DAY_ACTION_PLAN.md`](./TWO_DAY_ACTION_PLAN.md) | 两日行动计划 | 2026-04 |

### 6️⃣ 决策与记忆（Decisions & Memory）

| 文档 | 用途 | 最后更新 |
| --- | --- | --- |
| [`DECISION_LOG.md`](./DECISION_LOG.md) ⭐ | **决策日志**（2026-04 重大决策 + 2026-03 三栏表 + 踩坑 + 未完成事项） | 2026-04-26 |
| [`../.codebuddy/memory/`](../.codebuddy/memory/) | 5 份 2026-03 CodeBuddy 工作日记（其他 agent 不会主动读，精华已提炼到 DECISION_LOG） | 2026-03 |

---

## 📊 当前项目状态（2026-04-26）

| 项 | 状态 |
| --- | :---: |
| 系统开发 | ✅ 完成 |
| 轨道 A：38 题 KG 优化集 | ✅ 完成 |
| 主实验 Exp-0（38 题） | ✅ 完成 |
| Baseline Exp-1 LLM only（38 题） | ✅ 完成 |
| 分层分析（按覆盖率） | ✅ 完成 |
| **场景重定位到 MTB** | ✅ **完成（2026-04-17）** |
| **PRD / EXPERIMENT v2.0 升级** | ✅ **完成（2026-04-26）** |
| **AGENT_HANDOFF 多 agent 兼容体系** | ✅ **完成（2026-04-26）** |
| 轨道 B：20 题 MTB 场景测试集 | 🔄 Week 1 构建 |
| Traceability / Hallucination 脚本 | 🔄 Week 1 实现 |
| GPT-4o / 单 Agent+KG / RAG only 三档 Baseline | 🔄 Week 1 实现 |
| MTB 主实验（Exp-0/5/7/8） | ⏳ Week 2 跑 |
| 医生 Utility Score 打分 | ⏳ 等合作医生资源 |
| 轨道 C：15 题时间分割泛化集 | ⏳ 可选 |
| 论文撰写 v0.1 | ⏳ Week 2 末 |

---

## 🔗 关键路径速查

```bash
# 给导师汇报（最新）
docs/导师汇报文档.md
docs/SCENARIO_AND_RESEARCH_PROPOSAL.md

# 给新 agent 交接
AGENT_HANDOFF.md
docs/DECISION_LOG.md

# 运行实验
python evaluation/run_all_experiments.py
python evaluation/run_batch_eval_template.py \
  --gold evaluation/evaluation_gold_final.jsonl \
  --out evaluation/results/exp0_full_raw.jsonl \
  --max-rounds 6 --experiment full

# 当前测试集（v2.0 双轨）
evaluation/evaluation_gold_final.jsonl            # 轨道 A 消融
evaluation/mtb_testset_v1.jsonl                   # 轨道 B 主实验（待建）
evaluation/timesplit_testset.jsonl                # 轨道 C 泛化（待建）

# Neo4j 快速启动
docker run -d --name primekg-neo4j -p 7474:7474 -p 7687:7687 \
  -v neo4j-data:/data -e NEO4J_AUTH=neo4j/password neo4j:ubi9
```

---

## 📝 版本与维护

- 本 INDEX.md 每次新增 / 升级顶层文档时必须同步更新
- 顶层文档（README / PRD / EXPERIMENT_PROPOSAL）均采用"Changelog + 版本号 + 更新日期"三件套
- 2026-04-17 及之后的决策请追加到 `DECISION_LOG.md` §1，使用 `D-YYYY-MM-DD-NN` 编号

---

*本文档由 2026-04-26 v2.0 重写；上一版本为 2026-03-31 v1.0（仅列 6 个文档）。*
