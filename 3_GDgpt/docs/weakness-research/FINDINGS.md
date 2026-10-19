# 论文弱点突破：诊断与方法排序

## Outcome

论文对弱点的归因有两处错了，且都错在"低估可修复性"一侧——这是好消息（以下均 LIVE）。
(1) 基因召回低**不是**"gold 基因不在 KG 里"：300 个 gold 基因里 **290 个（96.7%）确实是该疾病的
ASSOCIATED_WITH 邻居**，含全部 11 道"零重叠"题；真因是 `k=8` + 边权并列把 521–1156 个邻居按字母序截断。
(2) 药物路径空**不是** KG 缺边：KG 有 **287 条 Drug–Disease 边**，20 个疾病节点中 18 个至少有 1 条；
真因是被问疾病名 14/15 落在 20 疾病范围外。
(3) D1/D2/D5 落后有相当一部分是**系统 bug 造成的答案长度差**，不只是评委偏好：主实验 N=15 里
6 条答案是占位符，中位 26 词 vs GPT-4o 375 词。

## Cause

| 弱点 | file:line | 机制 |
|---|---|---|
| 基因召回 0.047 | `tools.py:212-222` | `ORDER BY weight DESC, gene ASC LIMIT $k`，weight 恒 0 → 纯字母序；k=8×3 query 只取到 ~20-26 个候选。**完美排序下 Recall@5 上限 = 0.250**（受 \|gold\|=20 限制），现值仅为上限的 19%（LIVE） |
| LLM-judge 落后 | `workflow.py:221-228` | v2.2 占位符兜底用 `strip().lower()` 精确比对，实际输出却是 `'Continuing discussion\n``` '`（带 markdown 栅栏），guard 不命中 → 兜底不触发，Lead 的实质内容被丢掉。v2.3 prompt 的 N=9 中位 217 词无此问题（LIVE） |
| 药物路径空 | `tools.py:262-271` | Cypher 与导入白名单都正确（`import_kg_to_aura_http.py:30,34-35`）。30 次 No matches **全部**是 KG 外疾病名；唯一在 KG 内的 "prostate cancer" 4/4 返回了边（LIVE） |
| 公平性假设 | `run_batch_eval_template.py:386-400` | **未证实且不可证实**：输出记录不含 text_model / max_rounds / 任何 run config。论文 L122 声明两臂都用 GPT-4o（INFERRED，采信）；`--model`（L278）是 cfg 全局覆盖，单次调用内两臂一致，但两臂是两次独立调用 |

计数更正：按"单 query 对象 + 其结果块"的粒度，DiseaseToDrug 是 **34 次 / 30 次 No matches**；任务描述的 68/60 恰为 2 倍。

## Confidence and falsifier

**Confidence: HIGH** —— 三条主结论均来自离线真值文件的直接读取（KG 导入源 CSV + 逐条连 Aura 核实过的
`expected_kg_edges`），不依赖推断；唯一封顶因素是 live KG 本次不可达，故结论验证于**离线快照**。

**Falsifier: RAN。** 检验命题 =「gold 基因根本不在候选集里，所以重排是无用功」（论文与
`evaluation/investigation_2026/candidate_pool_vs_gold.md` 的现有结论）。做法：用
`testset_kg_optimized_enriched_with_edges.jsonl` 的 `expected_kg_edges`（每条边均已逐条连 Aura 核实存在，
见 `build_expected_kg_edges.py:9-11`）统计 15 题 300 个 gold 基因中有多少是该疾病的 ASSOCIATED_WITH 邻居。
**结果 290/300 = 96.7%，11 道"零重叠"题全部 20/20 命中 → 原命题被推翻。**

**NOT RUN：** GDS 可用性（`CALL gds.list()` / `SHOW PROCEDURES`）与任何 live Cypher 计数——
localhost:7687 / 7474 均 CLOSED、docker daemon 未启动，按约束未启动也未改动任何服务。
故"PPR 是否需要 GDS"未验证；但 degree / 共享邻居计数用纯 Cypher 即可。

## Recommendation

完整 9 项排序表（含预期收益、风险）见 `METHODS_RANKED.md`。前四项：

| # | 方法 | 弱点 | 工作量 | 需人批准？ |
|---|---|---|---|---|
| 1 | 修 `workflow.py` 占位符 guard，重跑主 N=15 + PcQA N=99 | 2,3 | 1d + 2-3d | ✅ 要 |
| 2 | DiseaseToGene 查询时按图信号（degree/共享通路/source 数）排全邻居集，**不改 KG** | 1 | 3-5d | ✅ 要 |
| 3 | 并列补报 Recall@20 / Hit@5 / nDCG@10（Recall@5 原值照留） | 1,5 | 1d | ❌ 否 |
| 5 | Traceability 换成 citation precision / recall（两字段都已存在） | 2,5 | 2-3d | ❌ 否 |

**两周计划** D1-2 修 guard（一行）+ 3 题冒烟 + #7 run config 落盘 → D3-5 实现 #2，先离线用
`expected_kg_edges` 调参再测 Recall@5 与延迟 → D6-9 带 #1+#2 重跑主 N=15 与 PcQA N=99（需人先批准）
→ D10-12 做 #3、#5 → D13-14 改写论文 §4.3/§5.5/§6：基因召回归因改为"k=8 字母序截断"，
药物路径归因改为"疾病覆盖只有 20 个"。**这两处更正即使不跑新实验也必须做。**

## Decisions to evaluate

- 是否批准修 `workflow.py` guard 并重跑主 N=15 + PcQA N=99？默认：批准——6/15 空答案使主表当前不可辩护。
- 是否接受"只增不换"补报 Recall@20/Hit@5/nDCG@10？默认按此执行。
- 是否做 Open Targets 证据分数排序（#9）？默认**不做**：15 题中 4 题 gold 来源含 Open Targets，存在信息泄漏；先做 #2。
- 扩 N 走 PrimeKGQA 还是 MTBBench？默认 PrimeKGQA（同源 KG，gold 天然在图内）。

## Open questions

- GDS 是否可用、1156 邻居上 Cypher 聚合延迟多少？无法测。默认不依赖 GDS。
- 主 N=15 实际 `max_rounds` 是 3（论文 L122）还是 6（脚本 default）？产物无记录。默认按论文的 3 报告，并列为可复现性缺口。
- 两臂 backbone 是否真都是 GPT-4o？产物无记录。默认采信论文，建议重跑时落盘。
- PcQA N=99 中多少题的疾病落在 20 疾病范围内？本次只统计了发出 DiseaseToDrug 的 15 个疾病串。默认分层报告前先补此统计。

## Evidence

- `DIAGNOSIS_LOG.md` —— 诊断命令与原始输出：falsifier 逐题表、Drug–Disease 边分布、答案长度对比、占位符 bug repr、环境说明。
- `LITERATURE_NOTES.md` —— 每条引用的验证结果，含 3 条**已拒绝**候选及理由。
- `METHODS_RANKED.md` —— 9 项方法排序全表。

## Residuals

- 所有"预期"收益均未实测；#1 与 #2 重跑后数字仍可能落后于 GPT-4o，届时须如实报告而非回退方法。
- 纯只读调查：未改项目文件、未动 KG、未跑 batch eval、未读 config.json。
- live KG 不可达；Neo4j 可用时建议用 live Cypher 复核邻居集大小与 Drug–Disease 计数。
