from typing import TypedDict, List, Annotated, Any
import operator
from langgraph.graph import StateGraph, END
from knowledge_base import kb_system


# safety_reviewer 的状态串，只在"整句就是它"时才算占位符。
# 这些词也可能是实质答案的开头（"None of the 8 genes are actionable."），
# 所以只做全等比对，不做前缀比对。
PLACEHOLDER_EXACT = (
    "n/a",
    "na",
    "none",
    "null",
    "-",
    "tbd",
)

# safety_reviewer 的"还没收敛"状态串。它们**只会**作为状态出现，不会是
# 真实答案的开头，所以允许带一小截尾巴（markdown 栅栏、"— further rounds
# needed." 之类）。两个来源都在 agents.py 里写死：
#   CONVERGED 之外的兜底 -> "Continuing discussion"
#   agents.py:501 DIVERGED -> "Continuing analysis — further rounds needed."
# 只修第一个会在 PcQA N=99 上漏掉 11/99 条（实测），所以两类一起收。
PLACEHOLDER_PREFIXES = (
    "continuing discussion",
    "continuing the discussion",
    "continuing analysis",
    "continuing the analysis",
    "discussion continues",
)

# 命中前缀后，整句的总词数上限。实测占位符最长是 6 词
# （"continuing analysis further rounds needed"），留到 10 词吸收改写，
# 又远低于真实答案的长度（产物里最短的实质答案 22 词）。
_PLACEHOLDER_MAX_WORDS = 10

_FENCE_PREFIXES = ("```", "~~~")


def _strip_fences(line: str) -> str:
    """去掉行首/行尾的 markdown 栅栏，但**保留**同一行上的正文。

    不能整行丢掉：单行就是 ```BRCA1 drives repair deficiency``` 的实质答案
    会被归一化成空串，进而被误判为占位符。
    """
    out = line.strip()
    for fence in _FENCE_PREFIXES:
        if out.startswith(fence):
            out = out[len(fence):]
            # ```json / ```cypher 这类语言标注，紧贴栅栏时才算标注
            head, sep, tail = out.partition(" ")
            if head and head.isalnum() and sep:
                out = tail
            elif head and head.isalnum() and not sep:
                out = ""
        if out.endswith(fence):
            out = out[: -len(fence)]
    return out.strip()


def _normalise_final_answer(text: Any) -> str:
    """去掉 markdown 栅栏与空白，返回小写正文，用于占位符判定。

    safety_reviewer 的实际输出形如 'Continuing discussion\\n```'，v2.2 的
    `strip().lower()` 精确比对因此不命中，Lead 综合的实质内容被丢掉。
    """
    if not text:
        return ""
    parts = [_strip_fences(line) for line in str(text).splitlines()]
    return " ".join(" ".join(parts).split()).strip().lower()


def is_placeholder_final_answer(text: Any) -> bool:
    """safety_reviewer 的 FINAL_ANSWER 是否只是占位符（无实质内容）。"""
    norm = _normalise_final_answer(text)
    if not norm:
        return True
    if norm in PLACEHOLDER_EXACT:
        return True
    if len(norm.split()) > _PLACEHOLDER_MAX_WORDS:
        return False
    for phrase in PLACEHOLDER_PREFIXES:
        if norm == phrase:
            return True
        # 必须卡词边界，否则 "Nonetheless, consider olaparib." 会被
        # "none" 前缀命中而当成占位符丢掉。
        if norm.startswith(phrase) and not norm[len(phrase):len(phrase) + 1].isalnum():
            return True
    return False


class MDTState(TypedDict):
    case_info: str
    ground_truth: str

    selected_roles: List[str]
    triage_reason: str

    current_round: int
    max_rounds: int

    context_bullets: Annotated[List[str], operator.add]
    final_answer: str
    is_converged: bool

    kb_context_text: str
    kb_context_docs: Any
    kg_prefetch_text: str
    kg_prefetch_runs: Any
    kg_prefetch_plan: Any
    # v2.1: KG coverage awareness for honest degradation
    kg_coverage_level: str     # "high" | "partial" | "low" | "disabled"
    kg_coverage_ratio: float   # 0.0 ~ 1.0, fraction of non-empty KG queries
    kg_reranked_genes: Any      # LLM-reranked gene list from gene_reranker (empty list if disabled)


def _compute_kg_coverage(runs: list) -> tuple:
    """Compute KG coverage level from prefetch runs.

    Rules (v2.1):
      - coverage_ratio = (# queries with non-empty results) / (# total queries)
      - low     : ratio < 0.2
      - partial : 0.2 <= ratio < 0.6
      - high    : ratio >= 0.6
    If no queries were executed, fall back to "low" so downstream agents
    know they must degrade honestly.
    """
    if not runs:
        return "low", 0.0
    total = len(runs)
    non_empty = 0
    for r in runs:
        if not isinstance(r, dict):
            continue
        # Neo4j tool runs expose structured rows as `records`.
        if "records" in r:
            records = r.get("records") or []
            if isinstance(records, list) and records:
                non_empty += 1
            continue
        # Fallback for other tool shapes.
        results = r.get("results")
        if isinstance(results, (list, dict)) and len(results) > 0:
            non_empty += 1
            continue
        text = str(r.get("text") or "").strip().lower()
        if text and "no matches" not in text and "no results" not in text:
            non_empty += 1
    ratio = non_empty / max(total, 1)
    if ratio < 0.2:
        level = "low"
    elif ratio < 0.6:
        level = "partial"
    else:
        level = "high"
    return level, round(ratio, 3)


def create_workflow(agents_instance):
    def node_triage(state: MDTState):
        kb_system.init_embeddings(
            api_key=agents_instance.llm.openai_api_key,
            base_url=agents_instance.llm.openai_api_base
        )

        retrieval_result = kb_system.retrieve_context_details(state["case_info"])
        triage_result = agents_instance.primary_care_doctor(state["case_info"])
        roles = triage_result["selected_roles"]
        reason = triage_result["reasoning"]

        # 自适应路由（破局①,对标MDAgents）：按复杂度裁剪角色数+轮数,简单题省全7角色开销。
        # 仅在 adaptive_routing 开启且非 forced_roles(baseline实验)时生效。
        out_max_rounds = state.get("max_rounds")
        if getattr(agents_instance, "adaptive_routing", False) and not agents_instance.forced_roles:
            from agents import COMPLEXITY_ROUTE
            level = agents_instance.assess_complexity(state["case_info"])
            route = COMPLEXITY_ROUTE.get(level, COMPLEXITY_ROUTE["high"])
            # 裁剪角色数（保留triage选出的前n个,不足则用原选择）
            n = route["n_roles"]
            if len(roles) > n:
                roles = roles[:n]
            out_max_rounds = min(state.get("max_rounds", 3), route["max_rounds"])
            reason = f"[adaptive:{level}→{n}roles/{route['max_rounds']}r] " + reason

        result = {
            "selected_roles": roles,
            "triage_reason": reason,
            "current_round": 1,
            "kb_context_text": retrieval_result["text"],
            "kb_context_docs": retrieval_result["docs"],
            "context_bullets": []
        }
        if out_max_rounds is not None:
            result["max_rounds"] = out_max_rounds
        return result

    def node_kg_prefetch(state: MDTState):
        if not agents_instance.tools.enable:
            return {
                "kg_prefetch_text": "Task KG prefetch disabled.",
                "kg_prefetch_runs": [],
                "kg_prefetch_plan": {},
                "kg_coverage_level": "disabled",
                "kg_coverage_ratio": 0.0
            }

        prefetch = agents_instance.shared_kg_prefetch(state["case_info"])
        runs = prefetch.get("runs", [])
        coverage_level, coverage_ratio = _compute_kg_coverage(runs)
        return {
            "kg_prefetch_text": prefetch.get("text", ""),
            "kg_prefetch_runs": runs,
            "kg_prefetch_plan": prefetch.get("plan", {}),
            "kg_coverage_level": coverage_level,
            "kg_coverage_ratio": coverage_ratio,
            "kg_reranked_genes": prefetch.get("reranked_genes", []),
        }

    def node_consultation_and_synthesis(state: MDTState):
        roles = state["selected_roles"]
        rnd = state["current_round"]
        bullets = state["context_bullets"] #历史轮次

        # v2.1: build a KG coverage banner prepended to residual_context
        cov_level = state.get("kg_coverage_level", "disabled")
        cov_ratio = state.get("kg_coverage_ratio", 0.0)
        if cov_level == "low":
            coverage_banner = (
                f"[KG COVERAGE: LOW ({cov_ratio:.2f})] "
                "The Task KG returned little or no evidence for this case. "
                "You MUST acknowledge 'insufficient KG evidence' and recommend external lookup "
                "(PubMed / OncoKB / CIViC). Do NOT fabricate drug names, trial names, or pathway chains. "
                "Mark any biological interpretation explicitly as [LLM-inferred].\n\n"
            )
        elif cov_level == "partial":
            coverage_banner = (
                f"[KG COVERAGE: PARTIAL ({cov_ratio:.2f})] "
                "The Task KG partially supports this case. For every claim, label it as either "
                "[KG-supported] (with the exact edge) or [LLM-inferred] (not found in KG). "
                "Do NOT mix the two in the same sentence.\n\n"
            )
        elif cov_level == "high":
            coverage_banner = (
                f"[KG COVERAGE: HIGH ({cov_ratio:.2f})] "
                "The Task KG provides solid grounding. Cite KG edges explicitly "
                "(e.g., `(Drug)-[TARGETS]->(Gene)`) for each mechanism claim.\n\n"
            )
        else:  # disabled
            coverage_banner = ""

        #  Logic Check: Residual Context
        # 1. This is calculated BEFORE the agent loop.
        # 2. It only contains info from PREVIOUS rounds (bullets).
        # 3. Therefore, agents in this round CANNOT see each other's current output.
        residual_context = ""
        if rnd == 1:
            residual_context = (
                f"{coverage_banner}"
                f"PRIOR KNOWLEDGE FROM DB:\n{state['kb_context_text']}\n\n"
                f"SHARED TASK KG PREFETCH:\n{state.get('kg_prefetch_text', 'No shared KG evidence.')}"
            )
        else:
            residual_context = (
                f"{coverage_banner}"
                f"SHARED TASK KG PREFETCH:\n{state.get('kg_prefetch_text', 'No shared KG evidence.')}\n\n"
            )
            recent_bullets = bullets[-2:]
            for i, b in enumerate(recent_bullets):
                bullet_rnd = rnd - len(recent_bullets) + i
                residual_context += f"--- Round {bullet_rnd} Summary ---\n{b}\n"

        dialogues = []
        for role in roles:
            # Logic Check: Independence & Blindness
            # 1. 'residual_context' is static for all agents in this loop.
            # 2. 'ground_truth' is NOT passed to the agent.
            res = agents_instance.specialist_consult(role, state["case_info"], residual_context, rnd)
            dialogues.append(f"**{role}**: {res}")

        # Lead Physician synthesizes the accumulated dialogues
        summary_json = agents_instance.lead_physician_synthesis(dialogues, rnd)

        return {
            "context_bullets": [summary_json],
            "current_round": rnd
        }

    def node_safety_check(state: MDTState):
        last_bullet = state["context_bullets"][-1]
        rnd = state["current_round"]

        # Safety Reviewer checks convergence based on the summary
        review = agents_instance.safety_reviewer(last_bullet, rnd)

        is_converged = "STATUS: CONVERGED" in review
        final_ans = ""

        if "FINAL_ANSWER:" in review:
            parts = review.split("FINAL_ANSWER:")
            final_ans = parts[1].strip() if len(parts) > 1 else review

        # v2.2 fix: final_answer 表达环节修复（解决"占位符/丢内容"缺陷）——
        # safety_reviewer 常返回 "Continuing discussion" 等占位符或空，
        # 导致 final_answer 丢掉 Lead 综合的实质内容（连带压低幻觉率/证据留存/弃权率指标）。
        # 兜底策略：占位/空时改用 Lead 综合的 last_bullet（含 Integration/Tools_Usage 等实质内容）。
        if is_placeholder_final_answer(final_ans):
            final_ans = last_bullet or "No convergent conclusion produced."

        if rnd >= state["max_rounds"]:
            is_converged = True
            if is_placeholder_final_answer(final_ans):
                final_ans = last_bullet or "Max rounds reached; see round summaries."

        # v2.2: KG 覆盖度 LOW 时，强制 final_answer 含显式"证据不足"声明（诚实降级/弃权卖点的落地）。
        # coverage 检测在 kg_prefetch 已算好；此处确保它体现在最终输出而非被综合环节丢掉。
        cov_level = state.get("kg_coverage_level", "disabled")
        if cov_level == "low":
            honest_note = ("[Honest degradation] Insufficient KG evidence for this case; "
                           "recommend external lookup (PubMed / OncoKB / CIViC). "
                           "Findings below are LLM-inferred and not KG-grounded.\n\n")
            if "insufficient" not in final_ans.lower():
                final_ans = honest_note + final_ans

        return {
            "is_converged": is_converged,
            "final_answer": final_ans,
            "current_round": rnd + 1
        }

    def router(state: MDTState):
        if state["is_converged"]:
            return "end"
        return "continue"

    workflow = StateGraph(MDTState)

    workflow.add_node("triage", node_triage)
    workflow.add_node("kg_prefetch", node_kg_prefetch)
    workflow.add_node("consultation_layer", node_consultation_and_synthesis)
    workflow.add_node("safety_layer", node_safety_check)

    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "kg_prefetch")
    workflow.add_edge("kg_prefetch", "consultation_layer")
    workflow.add_edge("consultation_layer", "safety_layer")

    workflow.add_conditional_edges("safety_layer", router, {"continue": "consultation_layer", "end": END})

    return workflow.compile()
