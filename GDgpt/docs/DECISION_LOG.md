# 📒 GDgpt 决策日志 (Decision Log)

> 记录项目从 2026-03 到 2026-04 的关键决策、踩过的坑、未完成事项。
> 供未来 AI Agent 与学生自己快速复盘使用，避免重复决策。
>
> 版本：v1.0  ·  创建：2026-04-26

---

## 📋 Changelog

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | 2026-04-26 | 初版：提炼 `.codebuddy/memory/2026-03-*.md` 5 份日记 + 新增 2026-04 重大决策章节 |

---

## 目录

1. [2026-04 重大决策（导师反馈驱动）](#1-2026-04-重大决策导师反馈驱动)
2. [2026-03 阶段决策三栏表](#2-2026-03-阶段决策三栏表基于-codebuddymemory-提炼)
3. [已踩过的坑（Lessons Learned）](#3-已踩过的坑lessons-learned)
4. [未完成事项（Open Items）](#4-未完成事项open-items截至-2026-04-26)

---

## 1. 2026-04 重大决策（导师反馈驱动）

| 决策 ID | 日期 | 决策内容 | 背景 / 理由 | 影响范围 |
| --- | --- | --- | --- | --- |
| **D-2026-04-17-01** | 2026-04-17 | **项目场景从"通用 KGQA"重定位为"精准肿瘤学 MTB 辅助"** | 导师反馈"应用场景不明显，故事讲不好，不足以毕业"。KG 的 20 种疾病恰好以癌症为主，天然契合 MTB 场景 | 全部顶层文档、论文叙事、评测设计 |
| **D-2026-04-17-02** | 2026-04-17 | **评测维度从"P/R/F1"升级为"Traceability / Hallucination / Clinical Utility"** | 导师反馈"测的是系统不是性能，F1=0.05 体现不出系统价值" | PRD / EXPERIMENT_PROPOSAL 评测章节 |
| **D-2026-04-17-03** | 2026-04-17 | **Baseline 从"LLM only 1 档"扩展为"GPT-4o / 单 Agent+KG / RAG only / OncoKB 手动"4 档** | 导师反馈"不能只跟 LLM only 全零比，要跟医生真正会用的替代方案比" | EXPERIMENT_PROPOSAL §4；代码需实现多档开关 |
| **D-2026-04-17-04** | 2026-04-17 | **测试集升级为"双轨策略"** | 保留 38 题做消融；新建 20 题 MTB 场景集（OncoKB 2024-2025 + CIViC + 真实 MTB 案例）做主实验；15 题时间分割集做泛化 | 评测目录新增 3 个测试集文件；Week 1-2 行动计划 |
| **D-2026-04-20-01** | 2026-04-20 | **7 角色 Agent 明确映射到 MTB 真实席位** | RareAgents (AAAI-26) 对标，给论文"为什么是 7 个角色"一个讲得通的答案 | PRD §0.5；论文 Method 章节 |
| **D-2026-04-20-02** | 2026-04-20 | **不重建 KG**，20 种癌症子图对 MTB 足够 | Knowledge Connector (Nature Commun 2026) 也只用 OncoKB / CIViC 子集；20 种疾病几乎全是主流癌症 | 节省工程成本；KG 构建脚本冻结 |
| **D-2026-04-21-01** | 2026-04-21 | 确定两周执行计划（Week 1 测试集+脚本；Week 2 主实验+案例） | 对导师的正式汇报 | `docs/导师汇报文档.md` §7 |
| **D-2026-04-26-01** | 2026-04-26 | **建立 AGENT_HANDOFF + 多 agent 兼容入口体系** | 学生即将迁移到其他代码 agent，需要"记忆外部化"到 Markdown | 新建 AGENT_HANDOFF.md / CLAUDE.md / AGENTS.md / .cursorrules / .windsurfrules / .clinerules / .github/copilot-instructions.md |
| **D-2026-04-26-02** | 2026-04-26 | **PRD / EXPERIMENT_PROPOSAL 采用 v2.0 + 附录存档 v1.x 策略** | 保留演进痕迹方便导师看发展 | 文档体积增加但可追溯 |
| **D-2026-04-26-03** | 2026-04-26 | **Benchmark 调研重大发现**：锁定 **MTBBench**（arXiv 2511.20490, 2025-11, ETH+EPFL+HUG）和 **PrimeKGQA**（Zenodo 13829395, 2024-10, Hamburg）两个外部权威 benchmark | 研究效率第一铁律：有现成不要自造。调研发现 MTBBench 场景完美对口 MTB + PrimeKGQA 直接基于 PrimeKG | 论文 Experimental Setup 可直接引用；可规避"作者自造有偏"质疑 |
| **D-2026-04-26-04** | 2026-04-26 | **测试集从"自造 20 题"升级为"混搭 70 题"**：B1 PrimeKGQA 癌症子集 40 题 + B2 MTBBench 纵向子集 20 题 + B3 自制 MTB 补充集 10 题 | MTBBench 多模态吃不下（含 H&E/IHC 图像），取其纵向文本子集；PrimeKGQA 数据量足够筛癌症相关；自制部分只保留最能展示 Bridge+多角色特色的 10 题 | Week 1 计划调整；evaluation/external_benchmarks/ 新建；自制 10 题对医生验证的压力大幅降低 |
| **D-2026-04-26-05** | 2026-04-26 | **新建《导师汇报文档_v2_20260426.md》**，补齐技术概念详解（KG/Bridge/互盲/Prefetch/KB/FAISS 共 6 个详例） | 回应导师"故事讲不好"反馈需要不只换场景，还要把技术细节讲得工程师+医生都能看懂 | docs/导师汇报文档_v2_20260426.md（本次新增文档） |

---

## 2. 2026-03 阶段决策三栏表（基于 `.codebuddy/memory/` 提炼）

### 2026-03-18（Exp-1 LLM only 全量跑完 + 超时机制）

| 关键决策 | 踩坑与教训 | 待办 / 未完成 |
| --- | --- | --- |
| 从 eval-013 断点续跑 Exp-1 到 eval-030 | eval-028 / 030 API 三次超时写入 `[ERROR]` 标记，影响整体指标 | 未来批量实验需提前规划 retry 策略 |
| 为 `run_batch_eval_template.py` 加 **单题 10 分钟超时机制**（基于 threading 的 `_run_with_timeout`） | 两个重复进程导致 eval-013~021 各有 2 条重复记录，去重后才准确 | 批量脚本需内建"幂等性 + 进程锁" |
| 全量指标：Exp-0 bridge_hit_rate=1.0, coverage=0.86；Exp-1 检索层全 0 | Phenotype F1：LLM (0.633) 反超 Full (0.438)，因 KG 表型稀疏 | 表型是 KG 弱项，v2.0 不再强调 |

### 2026-03-19（项目清理 + 首版汇报文档）

| 关键决策 | 踩坑与教训 | 待办 / 未完成 |
| --- | --- | --- |
| **删除 14 个多余文件**（样本文件、临时脚本、PS1、.bak） | 评测目录堆积中间产物，必须持续清理 | 建立"评测产物统一放 `results/`"约定 |
| **新建 `.gitignore` + `config.example.json`** | 之前 `config.json` 险些提交 | `config.json` 永远别提交 |
| **README.md** 从 MDTeamGPT 原版重写为 GDgpt | 之前 README 沿用上游项目，误导严重 | — |
| 新建 `evaluation/EXPERIMENT_REPORT.md` + `PROGRESS_REPORT.md` | 汇报文档要早建早维护 | — |

### 2026-03-23（汇报文档完善：场景 + 技术原理 + 案例）

| 关键决策 | 踩坑与教训 | 待办 / 未完成 |
| --- | --- | --- |
| PROGRESS_REPORT 新增「典型用户交互场景」（输入疾病 / 基因 / 药物三种） | 早期交互场景还是"泛泛医生"，未锚定 MTB | 2026-04 导师反馈后才重定位 |
| 补充 **Bridge Query 原理图 + Cypher 实现**（以 DiseaseGenePathwayBridge 为例） | — | — |
| 补充 **KG Prefetch 机制 + 多角色同轮互盲跨轮可见**的代码说明 | 互盲机制是关键创新点，一定要在论文中讲清 | 在论文 Method 中单独一节 |
| 完整案例：eval-001 breast carcinoma（28 基因 + 8 通路 + 4 药物 + bridge_found=true） | 案例真实可信是关键 | v2.0 需补 MTB 场景下 2-3 个临床化案例 |
| 补充**指标计算原理详解**（P/R/F1 用假设数据演示） | — | — |

### 2026-03-30（独立测试集构建 + Neo4j 重启）

| 关键决策 | 踩坑与教训 | 待办 / 未完成 |
| --- | --- | --- |
| 发现**循环评测问题**：Gold 从 PrimeKG 生成，系统知识源也是 PrimeKG → Bridge Hit Rate = 100% 不可信 | 测试集设计必须考虑 Gold 的**独立来源** | v2.0 双轨策略直接解决 |
| 构建 `evaluation/independent_testset/` —— 从 Open Targets / Reactome 独立源获取 | ⚠️ 要求的是"Gold 来源独立"而非"内容不在 KG" | v2.0 主实验切到 MTB 测试集后，此集降级为历史参考 |
| Neo4j 从 Docker Volume 恢复：`neo4j-data` 保留了之前的数据 | **默认密码：neo4j / password**，URL：`http://localhost:7474` | 密码管理：已放 `config.json`，别提交 |
| PrimeKG 统计：Drug 4730 / Gene 3582 / Pathway 1725 / Phenotype 76 / **Disease 仅 20** ⚠️ | 20 种疾病是硬约束，重建不现实 | v2.0 将"限制"重新诠释为"精准肿瘤学场景契合" |
| 覆盖率 v2（模糊匹配）：Gene 56.6%、Disease 44.4%、Pathway 100%、可用性得分 72.6% USABLE | 模糊匹配必须写，否则分数太难看 | — |
| 筛选 3 级测试集：High (30) / Medium (13) / Low (10)，合计 53 | 分层策略来自此处 | — |

### 2026-03-31（测试集 Quick/Full 版本 + 分层策略）

| 关键决策 | 踩坑与教训 | 待办 / 未完成 |
| --- | --- | --- |
| 生成两版测试集：Quick 30 题（83.3% 覆盖）+ Full 80 题（86.2% 覆盖） | — | v2.0 后 80 题集降级为历史参考 |
| **分层报告策略**：按任务类型（pathway / gene / disease）分层报告，不追求整体 F1 | `pathway-centered 100% 覆盖` vs `disease-centered 39-50% 覆盖`，后者 KG 无法支持 | v2.0 分层策略仍有效，用于轨道 A 消融分析 |
| **论文叙事 v1.0**："KG coverage is the critical factor" | 2026-04 导师反馈后叙事被整个替换 | v2.0 叙事聚焦 MTB 可追溯性 / 幻觉率 |
| 更新 `EXPERIMENT_PROPOSAL.md` 与 `docs/REPORT_TO_ADVISOR.md` | — | 2026-04-26 两者均升级到 v2.0 |

---

## 3. 已踩过的坑（Lessons Learned）

### 3.1 工程坑

| 坑 | 发生日期 | 教训 | 避免方法 |
| --- | --- | --- | --- |
| 批量评测两个进程并发运行导致重复记录 | 2026-03-18 | 脚本无幂等性 | 运行前检查已有结果文件；进程锁 |
| LLM API 调用无限挂起 | 2026-03-18 | 缺超时机制 | `run_batch_eval_template.py` 已加 10 分钟超时 |
| `config.json` 含 API Key 险些提交 | 2026-03-19 | 默认 git add . 的坏习惯 | `.gitignore` 必建；用 `config.example.json` 模板 |
| 评测目录堆积中间产物（sample / raw / extracted 十几个文件） | 2026-03-19 | 没有产物命名约定 | "评测产物统一放 `results/`"，中间态加 `_raw` / `_extracted` 后缀 |

### 3.2 研究方向坑

| 坑 | 发生日期 | 教训 | 避免方法 |
| --- | --- | --- | --- |
| **循环评测**：Gold 从 PrimeKG 生成 → Bridge Hit Rate 100% 不可信 | 2026-03-30 | 测试集 Gold 的来源必须独立于 KG 构建数据源 | 双轨策略 + MTB 场景集来自 OncoKB / CIViC / 临床案例 |
| **场景太泛**："生物医学问答"不是场景，"MTB 辅助"才是场景 | 2026-04-17 | 讲故事要"用户 + 使用时刻 + 替代方案" | 导师反馈驱动的 v2.0 重定位 |
| **只跟 LLM only 全零比**，对比无信息量 | 2026-04-17 | Baseline 要跟医生真正会用的替代方案比 | 4 档 Baseline（GPT-4o / 单 Agent+KG / RAG only / OncoKB 手动） |
| **只测性能不测系统**：F1=0.05 不能让人看懂系统价值 | 2026-04-17 | 系统级指标（可追溯/幻觉/效用）比 F1 更重要 | 新增 Traceability / Hallucination / Clinical Utility |

### 3.3 文档 / 协作坑

| 坑 | 发生日期 | 教训 | 避免方法 |
| --- | --- | --- | --- |
| PRD / EXPERIMENT_PROPOSAL 版本脱节（2026-03 定稿，2026-04 定位已变，但文档未更新） | 2026-04-26 发现 | 顶层文档要按季度复核；重大方向调整必须同步更新顶层文档 | v2.0 已采用 "Changelog + 版本号 + 更新日期"三件套 |
| `.codebuddy/memory/` 只有 CodeBuddy 能读，其他 agent 接手时会丢记忆 | 2026-04-26 | 关键决策必须落到 git 跟踪的 Markdown | AGENT_HANDOFF + DECISION_LOG 体系 |
| README 项目结构图长期未更新，新 docs 文件不可见 | 2026-04-26 | README 结构图要每次大改文档时同步 | 已在 2026-04-26 v2.0 更新 |

---

## 4. 未完成事项（Open Items，截至 2026-04-26）

### 4.1 P0 —— 本周必做（Week 1: 2026-04-27 ~ 05-03）

- [ ] **构建 20 题 MTB 场景测试集** `evaluation/mtb_testset_v1.jsonl`
  - 数据来源：OncoKB 2024-2025 Level 1-2 + CIViC 2024+ + ClinVar 2023.07+ + 真实 MTB 案例
  - 5 种癌症 × 4 种任务 = 20 题
  - 由 1-2 位合作医生验证
- [ ] **实现 Traceability / Hallucination 计算脚本** `evaluation/compute_system_metrics.py`
- [ ] **实现 GPT-4o / 单 Agent+KG / RAG only 三档 Baseline**（代码开关 + 批量脚本）

### 4.2 P0 —— 下周必做（Week 2: 2026-05-04 ~ 05-10）

- [ ] 在 MTB 测试集上跑完 Exp-0 / 5 / 7 / 8 全部实验
- [ ] 完成 2-3 个案例分析（1 成功 + 1 失败 + 1 典型 MTB 病例）
- [ ] 整理数据、画图，写论文实验章节 v0.1
- [ ] 准备导师汇报 PPT

### 4.3 P1 —— 等导师确认后启动

- [ ] **联系合作医生做 Utility Score 打分**（1-2 位肿瘤科医生）
- [ ] 构建 15 题时间分割泛化集 `evaluation/timesplit_testset.jsonl`
- [ ] 医生打分表 `evaluation/utility_scoring_form.md`

### 4.4 P2 —— 可选高 ROI 改进

- [ ] KG 查询改证据加权排序（预估 Gene Recall 0.05 → 0.20）—— 1 天
- [ ] 提高 `DiseaseToGene` 的 k 从 8 → 20 —— 0.5 天
- [ ] 补充 `kg_gene_count` 元数据以便评测更准确 —— 0.5 天

### 4.5 待导师确认的 5 个事项

1. MTB 作为主场景是否认可？
2. 测试集策略是否可行？（38 消融 + 20 MTB + 15 泛化）
3. 新增系统级指标是否符合预期？（尤其 Utility Score 需合作医生）
4. Gene Recall = 5.5% 是否需要重点解决？
5. 论文投稿目标？（先满足毕设答辩 vs 同步瞄准期刊）

---

## 5. 决策原则汇总（供未来参考）

1. **权威源优先**：MTB 定位以 `docs/SCENARIO_AND_RESEARCH_PROPOSAL.md` 为准；导师反馈以 `docs/ADVISOR_FEEDBACK_ANALYSIS.md` 为准
2. **历史可追溯**：所有重大版本升级保留旧内容至"附录" / "Part II"，不删除
3. **测试集双轨**：消融用 KG 优化集，主实验用场景集，不混淆
4. **评测区分三档可信度**：图谱事实 / 文献支持 / LLM 推测
5. **Baseline 必须跟"真实替代方案"比**：GPT-4o / OncoKB 手动查 > LLM only 全零
6. **敏感信息**：`config.json` 永不提交；任何文档用 `<PLACEHOLDER>` 占位

---

*本文档由 2026-04-26 初建；后续重大决策请以"D-YYYY-MM-DD-NN"编号追加到 §1。*
