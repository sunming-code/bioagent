from typing import List, Dict, Any, Callable, Optional
import json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from tools import MedicalTools

# Gene-Disease-Pathway (GDP) oriented role pool.
SPECIALIST_POOL = [
    "GeneCurator",
    "DiseaseMechanismAnalyst",
    "PathwayBiologist",
    "PhenotypeMapper",
    "DrugMechanismAnalyst",
    "EvidenceReviewer",
    "HypothesisIntegrator"
]

ROLE_FOCUS = {
    "GeneCurator": "normalize genes, aliases, and gene-level evidence quality",
    "DiseaseMechanismAnalyst": "explain disease-gene mechanisms and prioritize causal hypotheses",
    "PathwayBiologist": "trace pathway-level bridge evidence and mechanistic cascades",
    "PhenotypeMapper": "map disease and gene evidence to phenotypes and observable traits",
    "DrugMechanismAnalyst": "analyze treatment, target, contraindication, and drug-gene-disease links",
    "EvidenceReviewer": "separate graph-supported facts from weak or speculative claims",
    "HypothesisIntegrator": "combine multi-hop evidence into a coherent mechanism chain"
}

QUERY_INTENTS = [
    "GeneToDisease",
    "GeneToPathway",
    "DiseaseToGene",
    "DiseaseToPathway",
    "DiseaseToPhenotype",
    "DrugToDisease",
    "DiseaseToDrug",
    "GeneToDrug",
    "DiseaseGenePathwayBridge",
    "GenePhenotypeBridge",
    "DrugTargetDiseaseBridge"
]


def _strip_code_fences(text: str) -> str:
    content = (text or "").strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _safe_json_load(text: str):
    try:
        return json.loads(_strip_code_fences(text))
    except Exception:
        return None


def _norm_complexity(text: str) -> str:
    """从LLM输出里抽 low/moderate/high，兜底 high（不牺牲质量）。"""
    t = (text or "").strip().lower()
    if "low" in t:
        return "low"
    if "moderate" in t or "medium" in t:
        return "moderate"
    return "high"


# 复杂度 → (角色数, max_rounds) 路由表（破局①）
COMPLEXITY_ROUTE = {
    "low": {"n_roles": 1, "max_rounds": 1},
    "moderate": {"n_roles": 3, "max_rounds": 1},
    "high": {"n_roles": 5, "max_rounds": 3},
}


class MDTAgents:
    def __init__(
        self,
        api_key,
        base_url,
        text_model,
        enable_tools=True,
        neo4j_conf: Optional[Dict[str, Any]] = None,
        forced_roles: Optional[List[str]] = None,
        disabled_intents: Optional[List[str]] = None,
        adaptive_routing: bool = False,
        gene_reranker: bool = False,
    ):
        # 主生成模型，温度 0.7，负责生成/汇总。
        self.llm = ChatOpenAI(
            model=text_model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.7,
            streaming=True
        )
        # 低温 0.0，负责“判断类任务”（关键词提取、安全评审、CoT评审）。
        self.critic_llm = ChatOpenAI(
            model=text_model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            streaming=False
        )

        self.tools = MedicalTools(enable=enable_tools, neo4j_conf=neo4j_conf)
        self.forced_roles = [r for r in (forced_roles or []) if r in SPECIALIST_POOL]
        self.disabled_intents = set(disabled_intents or [])
        self.adaptive_routing = adaptive_routing  # 破局①:自适应复杂度路由开关(默认关,向后兼容)
        self.gene_reranker = gene_reranker  # 基因重排:默认关,向后兼容;可由构造函数或外部设置
        # Callbacks
        self.stream_callback = None
        self.tool_callback = None

    def set_stream_callback(self, callback: Callable[[str, str], None]):
        self.stream_callback = callback

    def set_tool_callback(self, callback: Callable[[str, str, str], None]):
        self.tool_callback = callback

    # 1. Primary Care (Triage)
    def assess_complexity(self, case_info: str) -> str:
        """自适应路由(破局①,对标MDAgents)：轻量分类问题复杂度 low/moderate/high。
        用 critic_llm(temp=0)确定性分类。single-fact/单实体查询→low；
        多实体或需机制解释→moderate；需多跳推理/矛盾整合/罕见复杂病例→high。
        1次轻量调用，据此决定投入几个角色/几轮，简单题省下全7角色开销。"""
        prompt = ChatPromptTemplate.from_template(
            """Classify the COMPLEXITY of this biomedical mechanism question for routing.

Question: {case}

Rules:
- "low": single entity / single-fact lookup (e.g. "what genes are associated with X").
- "moderate": multiple entities OR needs a mechanism explanation across gene-pathway.
- "high": needs multi-hop reasoning, reconciling conflicting evidence, or a complex/rare case.

Output ONLY one word: low, moderate, or high."""
        )
        try:
            res = (prompt | self.critic_llm).invoke({"case": case_info[:600]})
            level = _norm_complexity(res.content)
            return level
        except Exception:
            return "high"  # 出错兜底用最全配置，不牺牲质量

    def primary_care_doctor(self, case_info: str) -> Dict[str, Any]:
        if self.forced_roles:
            return {
                "reasoning": "Experiment override: forced single-role or fixed-role baseline.",
                "selected_roles": self.forced_roles
            }

        prompt = ChatPromptTemplate.from_template(
            """You are a Triage Coordinator for a Task KG biomedical mechanism analysis team.
            Analyze the user problem/question and select the most appropriate roles.

            Available Roles:
            {pool}

            Role Focus:
            {role_focus}

            Problem / Question: {case}

            TASK:
            1. Explain your reasoning.
            2. Select AT LEAST 3 roles.
            3. Prefer roles that together can cover genes, pathways, phenotypes, drugs, and evidence quality when relevant.

            OUTPUT JSON FORMAT:
            {{
                "reasoning": "...",
                "selected_roles": ["Role A", "Role B", "Role C"]
            }}
            """
        )
        chain = prompt | self.llm
        role_focus = "\n".join([f"- {role}: {focus}" for role, focus in ROLE_FOCUS.items()])
        result = chain.invoke({"pool": ", ".join(SPECIALIST_POOL), "role_focus": role_focus, "case": case_info})

        data = _safe_json_load(result.content)
        if data:
            selected = [s for s in data.get("selected_roles", []) if s in SPECIALIST_POOL]
            remaining = [s for s in SPECIALIST_POOL if s not in selected]
            while len(selected) < 3 and remaining:
                selected.append(remaining.pop(0))
            data["selected_roles"] = selected
            return data
        return {
            "reasoning": "Fallback selection for mechanism analysis.",
            "selected_roles": ["GeneCurator", "DiseaseMechanismAnalyst", "PathwayBiologist"]
        }

    @staticmethod
    def _extract_disease_hint(case_info: str) -> str:
        """从 case_info 提取疾病名作为 KG 查询 fallback 参数。
        支持常见格式：'associated with X', 'about X', 'for X?'；无法提取时返回空串。"""
        import re
        patterns = [
            r"associated with (.+?)(?:\?|$)",
            r"about (.+?)(?:\?|$)",
            r"for (.+?)(?:\?|$)",
            r"in (.+?)(?:\?|$)",
        ]
        text = case_info.strip()[:400]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                hint = m.group(1).strip(" .?")
                if len(hint) > 3:
                    return hint
        return ""

    def _default_query_plan(self, role: str, case_info: str = "") -> Dict[str, Any]:
        disease_hint = self._extract_disease_hint(case_info) if case_info else ""
        base_queries = [
            {"tool": "Neo4j_KG", "intent": "DiseaseToGene", "disease": disease_hint, "k": 8},
            {"tool": "Neo4j_KG", "intent": "DiseaseGenePathwayBridge", "disease": disease_hint, "k": 5}
        ]
        if role == "PhenotypeMapper":
            base_queries.append({"tool": "Neo4j_KG", "intent": "DiseaseToPhenotype", "disease": disease_hint, "k": 5})
        if role == "DrugMechanismAnalyst":
            base_queries.append({"tool": "Neo4j_KG", "intent": "DiseaseToDrug", "disease": disease_hint, "k": 5})
        return self._filter_query_plan({"queries": base_queries})

    def _available_intents(self) -> List[str]:
        return [intent for intent in QUERY_INTENTS if intent not in self.disabled_intents]

    def _filter_query_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        if not self.disabled_intents:
            return plan
        queries = []
        for query in (plan.get("queries", []) if isinstance(plan, dict) else []):
            if query.get("intent") not in self.disabled_intents:
                queries.append(query)
        return {"queries": queries}

    def plan_kg_queries(self, case_info: str, role: str, residual_context: str = "", shared: bool = False) -> Dict[str, Any]:
        planner_prompt = ChatPromptTemplate.from_template(
            """You are planning Task KG queries for a biomedical mechanism analysis system.

Role: {role}
Role Focus: {role_focus}
Problem: {case}
Residual Context: {context}

Available intents:
{intents}

Rules:
1. Return ONLY valid JSON.
2. Return 2-3 queries in execution order.
3. {bridge_rule}
4. Use exact fields required by each intent. Include "tool": "Neo4j_KG" in every query.
5. Keep k between 3 and 10.
6. If the problem is disease-centric, start with DiseaseToGene or DiseaseGenePathwayBridge.
7. If the role is DrugMechanismAnalyst, include a drug-related query when relevant.
8. If the role is PhenotypeMapper, include DiseaseToPhenotype or GenePhenotypeBridge when relevant.

Output schema:
{{
  "queries": [
    {{"tool": "Neo4j_KG", "intent": "DiseaseToGene", "disease": "...", "k": 8}},
    {{"tool": "Neo4j_KG", "intent": "DiseaseGenePathwayBridge", "disease": "...", "k": 5}}
  ]
}}
"""
        )
        available_intents = self._available_intents()
        intents_text = "\n".join([f"- {intent}" for intent in available_intents])
        bridge_rule = (
            "Prefer bridge queries when mechanism/pathway explanation is needed."
            if not self.disabled_intents
            else "Bridge intents are disabled for this experiment; use single-hop intents only."
        )
        chain = planner_prompt | self.critic_llm
        res = chain.invoke({
            "role": "SharedKGPlanner" if shared else role,
            "role_focus": "shared prefetch for common evidence" if shared else ROLE_FOCUS.get(role, "general mechanism analysis"),
            "case": case_info[:600],
            "context": residual_context[:800],
            "intents": intents_text,
            "bridge_rule": bridge_rule
        })
        plan = _safe_json_load(res.content)
        if isinstance(plan, dict) and isinstance(plan.get("queries"), list) and plan["queries"]:
            filtered = self._filter_query_plan(plan)
            if filtered.get("queries"):
                return filtered
        return self._default_query_plan(role, case_info)

    def run_kg_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return self.tools.execute_plan(json.dumps(plan, ensure_ascii=False))

    def rerank_genes(self, case_info: str, gene_candidates: List[str], k: int = 20) -> List[str]:
        """用 critic_llm(temp=0)从 KG 候选基因里筛出最相关的 k 个。
        解决"KG无边权重→字母序ABCA3排第一"问题(过度宽泛KG的已知局限)。
        仅在 gene_reranker=True 时调用，默认关闭以保持向后兼容。"""
        if not gene_candidates:
            return gene_candidates
        # 最多提交 200 个候选，超出截断（防 token 爆炸）
        candidates_str = ", ".join(gene_candidates[:200])
        prompt = ChatPromptTemplate.from_template(
            """You are a precision oncology gene expert.

Question: {case}

The knowledge graph returned these gene candidates (alphabetically ordered, no clinical relevance ranking):
{candidates}

Task: Select the {k} most clinically relevant genes for the specific disease/question above.
Use your biomedical knowledge to prioritize well-known causal/driver genes over alphabetically-early unrelated genes.

Return ONLY a JSON array of gene symbols, most relevant first.
Example: ["BRCA1", "TP53", "PIK3CA", "PTEN"]
Return nothing else."""
        )
        try:
            res = (prompt | self.critic_llm).invoke({
                "case": case_info[:500],
                "candidates": candidates_str,
                "k": k
            })
            ranked = _safe_json_load(res.content)
            if isinstance(ranked, list) and ranked:
                # 只保留原候选集里真实存在的基因（防幻觉）
                valid = [g for g in ranked if g in set(gene_candidates)]
                if valid:
                    return valid[:k]
        except Exception as e:
            print(f"[rerank_genes] 重排失败，回退原序: {e}")
        return gene_candidates[:k]

    def shared_kg_prefetch(self, case_info: str) -> Dict[str, Any]:
        plan = self.plan_kg_queries(case_info, role="GeneCurator", residual_context="", shared=True)
        result = self.run_kg_plan(plan)
        result["plan"] = plan

        # 基因重排：若开启，额外取大候选集(k=50)→LLM重排→注入prefetch文本顶部
        if self.gene_reranker and self.tools.enable:
            try:
                # 从现有 runs 里提取已检索到的基因
                candidate_genes: List[str] = []
                for run in result.get("runs", []):
                    for rec in (run.get("records") or []):
                        g = rec.get("gene") or rec.get("Gene") or rec.get("g.name")
                        if g and isinstance(g, str) and g not in candidate_genes:
                            candidate_genes.append(g)
                # 如果现有结果基因太少（<20），额外跑一次大k查询
                if len(candidate_genes) < 20:
                    disease_hint = self._extract_disease_hint(case_info) or case_info[:120]
                    big_plan = self.run_kg_plan({
                        "queries": [{"tool": "Neo4j_KG", "intent": "DiseaseToGene",
                                     "disease": disease_hint, "k": 50}]
                    })
                    for run in big_plan.get("runs", []):
                        for rec in (run.get("records") or []):
                            g = rec.get("gene") or rec.get("Gene") or rec.get("g.name")
                            if g and isinstance(g, str) and g not in candidate_genes:
                                candidate_genes.append(g)

                if len(candidate_genes) >= 3:
                    reranked = self.rerank_genes(case_info, candidate_genes, k=20)
                    rerank_note = (
                        f"[Gene Re-rank (LLM-prioritised, top-{len(reranked)}): "
                        + ", ".join(reranked)
                        + "]\n"
                    )
                    # 注入到 prefetch text 最前面，让 specialist 优先看到
                    result["text"] = rerank_note + result.get("text", "")
                    result["reranked_genes"] = reranked
            except Exception as e:
                print(f"[shared_kg_prefetch] gene_reranker 步骤失败，继续原流程: {e}")

        return result

    #2. Specialists (Consultation)
    def specialist_consult(self, role: str, case_info: str, residual_context: str, round_num=1):

        #Tool Usage Logic
        tool_context = ""
        if self.tools.enable:
            try:
                query_plan = self.plan_kg_queries(case_info, role, residual_context)
                tool_exec = self.run_kg_plan(query_plan)
                tool_res = tool_exec.get("text", "")
                if tool_res:
                    if self.tool_callback:
                        self.tool_callback(role, json.dumps(query_plan, ensure_ascii=False), json.dumps(tool_exec, ensure_ascii=False))
                    tool_context = f"\n[Structured Graph Evidence]:\n{tool_res}\n"
            except Exception as e:
                print(f"Tool error: {e}")

        # Strict Reasoning Structure (GDP / KG oriented)
        structure_instruction = """
        IMPORTANT INSTRUCTIONS:
        1. **Independence**: You are providing your opinion INDEPENDENTLY. You cannot see the opinions of other specialists in this current round. You can only see the summary of previous rounds (if any).
        2. **Blindness**: You do NOT have access to the ground truth. Distinguish graph-supported facts from your own biological interpretation.
        3. **KG Coverage Awareness (v2.1)**: The residual context may contain a banner of the form `[KG COVERAGE: LOW|PARTIAL|HIGH (ratio)]`. You MUST obey it strictly:
           - If `LOW`: begin your response with "Insufficient KG evidence for this case." Recommend external lookup (PubMed / OncoKB / CIViC). DO NOT fabricate drug names, trial names, or pathway chains. All biological claims must be labeled `[LLM-inferred]`.
           - If `PARTIAL`: every factual claim MUST be tagged either `[KG-supported: <edge>]` or `[LLM-inferred]`. Do NOT mix them in one sentence.
           - If `HIGH`: cite KG edges explicitly (e.g., `(Drug)-[TARGETS]->(Gene)`) for every mechanism claim.
        4. **Structure**: You must structure your response in exactly three sections:

           - **1. Graph Facts**:
             (List the key graph-supported entities and relations: Disease, Gene, Pathway, Phenotype, Drug. Explicitly state which findings came from the KG. If coverage is LOW, write "No graph facts available.")

           - **2. Mechanistic Interpretation**:
             (Build the best current mechanism chain. Prefer Disease→Gene→Pathway bridges. If phenotype/drug evidence exists, use it to support or challenge the chain. Clearly mark weak inferences.)

           - **3. Output**:
             (State your current best mechanism summary, confidence level, and the next validation step. Keep unsupported speculation minimal. If coverage is LOW, set confidence to "low" and next step to "external evidence lookup".)
        """

        system_prompt = (
            f"You are a {role} in a Task KG biomedical mechanism analysis team.\n"
            f"Your specialty focus is: {ROLE_FOCUS.get(role, 'general mechanism analysis')}.\n"
            f"{structure_instruction}"
        )

        user_text = f"Problem / Question: {case_info}\n{tool_context}\n"

        if round_num == 1:
            user_text += "\n[Status]: Round 1. Analyze independently."
            user_text += f"\n*** PRIOR KNOWLEDGE / CONTEXT ***\n{residual_context}\n"
        else:
            user_text += f"\n[Status]: Round {round_num}.\n"
            user_text += f"*** RESIDUAL CONTEXT (Previous Rounds) ***\n{residual_context}\n"
            user_text += "Review the summaries of previous rounds. Support, refute, or synthesize based on that history using KG-grounded evidence when possible."

        messages = [SystemMessage(content=system_prompt)]

        messages.append(HumanMessage(content=user_text))

        try:
            full_res = ""
            for chunk in self.llm.stream(messages):
                token = chunk.content
                full_res += token
                if self.stream_callback: self.stream_callback(role, token)
            return full_res
        except Exception as e:
            return f"Error: {e}"

    #3. Lead Physician
    def lead_physician_synthesis(self, round_dialogues: List[str], round_num: int):
        # Lead Physician DOES see all dialogues from the current round (to synthesize them),
        # but DOES NOT see Ground Truth.
        # v2.3: Prompt redesigned so the synthesis produces an INLINE-CITED clinical report
        # (KG entity names and edge types appear in the answer text, not just in JSON fields).
        # This makes KG evidence visible to downstream evaluators (LLM-judge, human raters)
        # and improves traceability scoring.
        prompt = ChatPromptTemplate.from_template(
            """You are the Lead Integrator (MTB Chair) for a precision oncology mechanism board.
            Synthesize the specialists' discussions from Round {rnd} into a structured clinical report.

            Specialists' Output (Current Round):
            {dialogues}

            TASK: Write a clinical mechanism report in EXACTLY this format:

            ## MTB Mechanism Report

            ### 1. KG-Grounded Facts
            List each CONFIRMED fact from the knowledge graph. For every fact, name the specific
            entity and relation type inline. Use this pattern:
            - "The knowledge graph confirms [Gene X] is [RELATION] [Disease/Pathway Y] (KG: [Gene X]–[RELATION]–[Y])."
            - If coverage is LOW: "No KG evidence available for this entity — external lookup required."

            ### 2. Mechanistic Interpretation
            Build the mechanism chain using the KG facts above. Every gene, pathway, or drug name
            cited here must appear in Section 1 or be explicitly marked [LLM-inferred].
            Preferred chain: Disease → Gene → Pathway → Drug.

            ### 3. Clinical Summary & Confidence
            One paragraph: best current mechanistic explanation, confidence level (HIGH/MEDIUM/LOW
            based on KG coverage), and recommended next verification step (e.g., "verify via OncoKB").

            ### 4. Internal Notes (for next-round agents only)
            JSON: {{"Consistency": ..., "Conflict": ..., "Tools_Usage": ..., "Long_Term_Experience": ...}}

            Write sections 1-3 in clear clinical prose. Section 4 in JSON.
            """
        )
        chain = prompt | self.llm
        res = chain.invoke({
            "rnd": round_num,
            "dialogues": "\n\n".join(round_dialogues)
        })

        content = res.content.strip()
        if content.startswith("```json"): content = content[7:]
        if content.endswith("```"): content = content[:-3]
        return content.strip()

    #4. Safety Reviewer
    def safety_reviewer(self, current_bullet: str, round_num: int):
        # v2.3: FINAL_ANSWER must be a readable clinical report (not JSON),
        # extracting the clinical prose from the MTB Mechanism Report in current_bullet.
        prompt = ChatPromptTemplate.from_template(
            """You are the Mechanism Review and Validation Agent.
            Review the current round's synthesis and determine if it has converged.

            Current Context:
            {bullet}

            TASK:
            1. Decide if the analysis has converged to a defensible, KG-grounded conclusion.
            2. If CONVERGED: extract the clinical answer by combining Sections 1+2+3 from the
               MTB Mechanism Report above into a single readable paragraph. The answer MUST:
               - Name specific genes, pathways, and drugs with their KG relations inline
                 (e.g., "BRCA1 is ASSOCIATED_WITH hereditary breast ovarian cancer and INVOLVED_IN
                 DNA repair pathways per the knowledge graph")
               - State the confidence level
               - End with next verification step
               - If any claims are LLM-inferred (not KG-grounded), label them [LLM-inferred]
            3. If DIVERGED: write "Continuing analysis — further rounds needed."

            OUTPUT FORMAT (Strict):
            STATUS: [CONVERGED / DIVERGED]
            REASON: [1 sentence]
            FINAL_ANSWER: [The complete clinical prose answer as described above]
            """
        )
        chain = prompt | self.critic_llm
        res = chain.invoke({"bullet": current_bullet})
        return res.content

    # 5. CoT Reviewer
    def cot_reviewer(self, case_info, final_answer, ground_truth):
        # Only this agent sees the Ground Truth
        prompt = ChatPromptTemplate.from_template(
            """You are the 'Chain-of-Thought Reviewer'.

            CASE: {case}
            MODEL ANSWER: {answer}
            GROUND TRUTH: {truth}

            TASK:
            Step 1: Determine correctness (letters match for Choice, semantic match for Open).

            Step 2: Generate specific fields based on correctness.

            IF CORRECT:
               - "is_correct": true
               - "summary_s4": A concise summary of the final reasoning (S4_final).

            IF INCORRECT:
               - "is_correct": false
               - "initial_hypothesis": What was the likely first thought?
               - "analysis_process": Step-by-step breakdown of the failure.
               - "final_conclusion": The wrong conclusion reached.
               - "error_reflection": Why it was wrong and how to avoid it.

            OUTPUT JSON ONLY.
            """
        )
        chain = prompt | self.critic_llm
        try:
            res = chain.invoke({
                "case": case_info[:500],
                "answer": final_answer,
                "truth": ground_truth
            })
            content = res.content.strip()
            if content.startswith("```json"): content = content[7:]
            if content.endswith("```"): content = content[:-3]
            return json.loads(content)
        except:
            return {"is_correct": False, "analysis_text": "Parse Error"}
