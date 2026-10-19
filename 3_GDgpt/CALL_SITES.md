# Call sites for the shared components touched

Two shared components changed: `tools.py` (`Neo4jKGTool._build_query`, the KG query
builder used by every agent) and `workflow.py` (the LangGraph node that produces
`final_answer`). Both are repo-root modules imported across the system, so each fix is
a class of fix. Every site is enumerated below, including the ones deliberately left
alone and why.

## workflow.py - placeholder guard

The guard was inline and duplicated. It is now one module-level helper,
`is_placeholder_final_answer`, and BOTH sites call it.

| Site | Before | After |
|---|---|---|
| `workflow.py` `node_safety_check`, placeholder fallback | inline `strip().lower() in (...)` exact match | calls the helper |
| `workflow.py` `node_safety_check`, max-rounds branch | inline `== "continuing discussion"` only, narrower than the first site | calls the same helper |

The max-rounds branch was the second half of the same defect: it tested one bare
string, so it would have missed every fence-wrapped value too. Fixing only the
reported site would have left it live. No other module referenced the placeholder
strings (`grep` for `continuing discussion` across `*.py` returns only these).

Consumers of `final_answer` are unaffected in shape: it was already a string and still
is. `evaluation/run_batch_eval_template.py` writes it to the `final_answer` field; the
only behavioural change is that it now carries content where it previously carried a
placeholder, which is the intent.

## tools.py - DiseaseToGene ranking

Changed: the `DiseaseToGene` branch of `_build_query` only.

Callers of the `DiseaseToGene` intent, all verified against the unchanged output
column contract `[disease, gene, relation, source, weight]`:

| Call site | What it does | Affected? |
|---|---|---|
| `agents.py:199` | default KG prefetch plan, `k=8` | Yes, gets better-ranked genes. k unchanged. |
| `agents.py:245` | query-plan prompt example shown to the LLM | No code change needed; still `k=8`. |
| `agents.py:337` | fallback query when planning fails, `k=8` | Yes, same improvement. |
| `agents.py:32` | intent allow-list membership | No change; intent name unchanged. |
| `evaluation/extract_from_tool_calls.py:94` | builds `predicted_genes` for the Gene Recall metric | Reads `disease`, `gene`, `relation` only. All three still emitted, so no change needed. Verified by reading `_collect_edges_from_record`. |
| `evaluation/scripts/check_disease_to_gene_ranking.py` | the new red-first check | Added by this change. |
| `evaluation/scripts/probe_gene_ranking_signals.py` | the signal probe | Added by this change. |
| `app.py` | Streamlit UI, routes through the same `run_structured` | Yes, inherits the ranking. No UI code change. |

`source` and `weight` are still emitted but are read by no caller outside `tools.py`
(`grep` for the column names across the repo finds no consumer). `weight` is
deliberately left as a passthrough rather than being overwritten with `bio_degree`, so
the column keeps one meaning across all intents.

## Same class of defect, present and NOT fixed here

These are the same two root causes in sibling intents. They are outside the approved
scope (which named DiseaseToGene), so they are reported rather than changed. Listed so
the class is visible and nobody concludes the fix was complete.

`ORDER BY weight DESC` is a no-op in every one of these, because `weight` is the empty
string on all 87838 relationships in the KG, not only on ASSOCIATED_WITH:

| Line | Intent | Secondary key that therefore decides the order |
|---|---|---|
| `tools.py:195` | GeneToDisease | `disease ASC` |
| `tools.py:207` | GeneToPathway | `pathway ASC` |
| `tools.py:264` | DiseaseToPathway | `pathway ASC` |
| `tools.py:276` | DiseaseToPhenotype | `phenotype ASC` |
| `tools.py:288` | DrugToDisease | `disease ASC` |
| `tools.py:300` | DiseaseToDrug | `drug ASC` |
| `tools.py:312` | GeneToDrug | `drug ASC` |

The undirected-match duplication is also present in all of the above, so each one's
effective `k` is halved exactly as DiseaseToGene's was (top-8 yielding 4 distinct
values). Worth fixing as one batch; it needs its own approval because it changes what
every other intent returns and so would move the pathway, phenotype and drug metrics
too.

Separately, `tools.py:260` `DiseaseToPathway` matches
`(d:Disease)-[:ASSOCIATED_WITH|INVOLVED_IN]-(p:Pathway)` and the live KG has **0**
Disease-Pathway edges of any type, so that intent can never return a row at all. That
is a correctness defect independent of ordering.


## 2026-10-16 并行执行调用点

- `workflow.py` 通过 `parallel_execution.consult_specialists` 调用同轮专家；共享上下文不变，汇总输入保留角色顺序。分诊与经验检索并行。
- `agents.MDTAgents` 的模型调用增加计时，构造参数追加可选并发上限；所有既有位置参数保持兼容。
- `tools.MedicalTools.execute_plan` 仅将独立的全 Neo4j 查询计划并行，输出顺序及查询内容不变；`run_tools` 和专家/共享 KG 预取均继承。
- `app.py` 使用按角色隔离的缓冲，UI 回调在工作流调用线程分发；各轮完成后清理游标。
- `evaluation/run_batch_eval_template.py` 在每轮结束后恢复稳定角色顺序，增加计时字段；`run_all_experiments.py` 和部署检查通过同一入口继承。
- `knowledge_base.DualKnowledgeBase` 的公共读写方法及初始化加锁，适用于 Web 多会话和分诊线程。
- `scripts/local_runtime.py` 的 `smoke` 使用同一工作流；`restart-web` 重载页面模块；历史串行检查产物不覆盖。
