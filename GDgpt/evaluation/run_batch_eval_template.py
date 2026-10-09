"""
批量运行 MDTeamGPT + Task KG 评测问题集。

支持 --experiment 参数切换实验配置：
- full: 完整系统（Neo4j + FAISS + Bridge + KG Prefetch + 多角色），默认
- llm_only: 关闭 Neo4j 和 FAISS，纯 LLM 回答
- gpt4o_direct: 直接 LLM 医学专家回答，不走 workflow / KG / 多 Agent
- single_agent: 单一 HypothesisIntegrator + KG
- rag_only: 7 角色 + 单跳 KG，禁用 Bridge intents

运行前请确保 config.json 已配置 api_key。LLM only 时无需 Neo4j 连接。
"""

import argparse
import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

# 确保项目根目录在 sys.path 中（从 evaluation/ 子目录运行时需要）
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents import MDTAgents
from workflow import create_workflow
from utils import load_config


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class EvalCollector:
    def __init__(self):
        self.tool_calls = []

    def on_token(self, role, token):
        # 批量评测时不需要保存流式 token。
        return None

    def on_tool_output(self, role, query, result):
        parsed_result = None
        try:
            parsed_result = json.loads(result)
        except Exception:
            parsed_result = result
        self.tool_calls.append(
            {
                "role": role,
                "query": query,
                "result": parsed_result
            }
        )


def run_one_question(app, agents, question: str, max_rounds: int):
    collector = EvalCollector()
    agents.set_stream_callback(collector.on_token)
    agents.set_tool_callback(collector.on_tool_output)

    state = {
        "case_info": question,
        "ground_truth": "",
        "selected_roles": [],
        "triage_reason": "",
        "current_round": 1,
        "max_rounds": max_rounds,
        "context_bullets": [],
        "final_answer": "",
        "is_converged": False,
        "kb_context_text": "",
        "kb_context_docs": [],
        "kg_prefetch_text": "",
        "kg_prefetch_runs": [],
        "kg_prefetch_plan": {},
        # v2.1: coverage fields (filled in by node_kg_prefetch)
        "kg_coverage_level": "disabled",
        "kg_coverage_ratio": 0.0,
        "kg_reranked_genes": [],
    }

    final_answer = ""
    selected_roles = []
    triage_reason = ""
    context_bullets = []
    kg_coverage_level = "disabled"
    kg_coverage_ratio = 0.0
    kg_reranked_genes: list = []

    for event in app.stream(state):
        if "triage" in event:
            data = event["triage"]
            selected_roles = data.get("selected_roles", [])
            triage_reason = data.get("triage_reason", "")
        if "kg_prefetch" in event:
            data = event["kg_prefetch"]
            kg_coverage_level = data.get("kg_coverage_level", kg_coverage_level)
            kg_coverage_ratio = data.get("kg_coverage_ratio", kg_coverage_ratio)
            kg_reranked_genes = data.get("kg_reranked_genes", kg_reranked_genes)
        if "consultation_layer" in event:
            data = event["consultation_layer"]
            context_bullets = data.get("context_bullets", context_bullets)
        if "safety_layer" in event:
            data = event["safety_layer"]
            if data.get("final_answer"):
                final_answer = data["final_answer"]

    return {
        "answer_text": final_answer,
        "triage_reason": triage_reason,
        "selected_roles": selected_roles,
        "context_bullets": context_bullets,
        "tool_calls": collector.tool_calls,
        # v2.1: coverage info surfaced into each prediction row
        "kg_coverage_level": kg_coverage_level,
        "kg_coverage_ratio": kg_coverage_ratio,
        # gene_reranker: LLM-prioritised gene list (empty if disabled)
        "kg_reranked_genes": kg_reranked_genes,
    }


def run_direct_question(agents, question: str):
    """Direct LLM baseline: no workflow, no KG, no multi-agent consultation."""
    messages = [
        SystemMessage(
            content=(
                "You are a medical oncology expert preparing a concise Molecular Tumor Board "
                "pre-meeting mechanism note. Answer the user's question directly. If evidence "
                "would require external databases or literature, say so explicitly."
            )
        ),
        HumanMessage(content=question),
    ]
    res = agents.llm.invoke(messages)
    return {
        "answer_text": res.content,
        "triage_reason": "Direct LLM baseline; no triage/workflow.",
        "selected_roles": ["DirectLLM"],
        "context_bullets": [],
        "tool_calls": [],
        "kg_coverage_level": "disabled",
        "kg_coverage_ratio": 0.0,
    }


def load_existing_ids(path: Path) -> set:
    """加载已有输出文件中已完成的 id 集合（断点续跑）。"""
    ids = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        ids.add(json.loads(line)["id"])
                    except Exception:
                        pass
    return ids


def _run_with_timeout(func, args=(), kwargs=None, timeout=600):
    """在子线程中运行 func，超时则抛出 TimeoutError。"""
    import threading
    kwargs = kwargs or {}
    result_holder = [None]
    error_holder = [None]

    def target():
        try:
            result_holder[0] = func(*args, **kwargs)
        except Exception as e:
            error_holder[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"单题运行超时 ({timeout}s)")
    if error_holder[0]:
        raise error_holder[0]
    return result_holder[0]


def run_one_question_with_retry(app, agents, question: str, max_rounds: int,
                                 max_retries: int = 3, retry_delay: float = 10.0,
                                 per_question_timeout: int = 1200):
    """带重试 + 超时的单题运行，应对 API 网络不稳定和挂起。"""
    import time
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return _run_with_timeout(
                run_one_question,
                args=(app, agents, question, max_rounds),
                timeout=per_question_timeout,
            )
        except Exception as e:
            last_error = e
            print(f"    [WARN] 第 {attempt}/{max_retries} 次尝试失败: {type(e).__name__}: {e}")
            if attempt < max_retries:
                print(f"    等待 {retry_delay}s 后重试...")
                time.sleep(retry_delay)
    # 全部重试失败，返回空结果而非崩溃
    print(f"    [ERROR] 重试耗尽，跳过本题 (error: {last_error})")
    return {
        "answer_text": f"[ERROR] {last_error}",
        "triage_reason": "",
        "selected_roles": [],
        "context_bullets": [],
        "tool_calls": [],
        "kg_coverage_level": "disabled",
        "kg_coverage_ratio": 0.0,
    }


def run_direct_question_with_retry(agents, question: str, max_retries: int = 3,
                                   retry_delay: float = 10.0,
                                   per_question_timeout: int = 600):
    """Retry wrapper for the direct LLM baseline."""
    import time
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return _run_with_timeout(
                run_direct_question,
                args=(agents, question),
                timeout=per_question_timeout,
            )
        except Exception as e:
            last_error = e
            print(f"    [WARN] direct baseline 第 {attempt}/{max_retries} 次尝试失败: {type(e).__name__}: {e}")
            if attempt < max_retries:
                print(f"    等待 {retry_delay}s 后重试...")
                time.sleep(retry_delay)
    print(f"    [ERROR] direct baseline 重试耗尽，跳过本题 (error: {last_error})")
    return {
        "answer_text": f"[ERROR] {last_error}",
        "triage_reason": "Direct LLM baseline failed.",
        "selected_roles": ["DirectLLM"],
        "context_bullets": [],
        "tool_calls": [],
        "kg_coverage_level": "disabled",
        "kg_coverage_ratio": 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="批量运行 MDTeamGPT + Task KG 评测问题集。")
    parser.add_argument("--gold", required=True, help="gold JSONL 路径")
    parser.add_argument("--out", required=True, help="输出 prediction JSONL 路径")
    parser.add_argument("--max-rounds", type=int, default=6, help="每题最大讨论轮数（PRD 建议 6）")
    parser.add_argument("--limit", type=int, default=None, help="仅运行前 N 题，用于 smoke/dev 调试")
    parser.add_argument("--ids", default=None, help="仅运行指定题目 id，多个 id 用逗号分隔；优先级高于 --limit")
    parser.add_argument("--max-retries", type=int, default=3, help="每题失败后的最大重试次数")
    parser.add_argument("--retry-delay", type=float, default=10.0, help="重试间隔秒数")
    parser.add_argument("--per-question-timeout", type=int, default=1200, help="单题超时时间（秒）")
    parser.add_argument(
        "--experiment",
        choices=["full", "llm_only", "gpt4o_direct", "single_agent", "rag_only"],
        default="full",
        help=(
            "实验配置：full=完整系统，llm_only=关闭 Neo4j 和 FAISS，"
            "gpt4o_direct=直接 LLM，single_agent=单 Agent+KG，rag_only=禁用 Bridge"
        ),
    )
    parser.add_argument("--resume", action="store_true", help="断点续跑：跳过已有输出中已完成的题目")
    parser.add_argument("--adaptive", action="store_true", help="破局①：开启自适应复杂度路由(简单题少角色少轮)")
    parser.add_argument("--gene-reranker", action="store_true", dest="gene_reranker",
                        help="破局②：开启LLM基因重排（解决KG字母序问题，提升基因召回）")
    parser.add_argument("--model", default=None, help="覆盖 config.json 的 text_model（如 gpt-4o-mini）")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("config.json 中缺少 api_key，无法批量运行评测。")
    if getattr(args, "model", None):
        cfg["text_model"] = args.model
        print(f"[--model 覆盖] text_model = {args.model}")

    forced_roles = None
    disabled_intents = []

    # 根据 experiment 覆盖配置。
    # full/single_agent/rag_only 使用 Neo4j；llm_only/gpt4o_direct 不使用工具。
    if args.experiment in {"llm_only", "gpt4o_direct"}:
        enable_tools = False
        neo4j_conf = {"uri": "", "user": "", "password": "", "database": ""}
        if args.experiment == "llm_only":
            print("实验模式: LLM only（多 Agent workflow，已关闭 Neo4j 与工具）")
        else:
            print("实验模式: GPT-4o/direct LLM baseline（不走 workflow / KG / 多 Agent）")
    else:
        enable_tools = cfg.get("enable_tools", True)
        neo4j_conf = {
            "uri": cfg.get("neo4j_uri", ""),
            "user": cfg.get("neo4j_user", ""),
            "password": cfg.get("neo4j_password", ""),
            "database": cfg.get("neo4j_database", ""),
        }
        if args.experiment == "single_agent":
            forced_roles = ["HypothesisIntegrator"]
            print("实验模式: Single Agent + KG（强制 HypothesisIntegrator）")
        elif args.experiment == "rag_only":
            disabled_intents = [
                "DiseaseGenePathwayBridge",
                "GenePhenotypeBridge",
                "DrugTargetDiseaseBridge",
            ]
            print("实验模式: RAG only / no Bridge（禁用 3 个 Bridge intents）")
        else:
            print("实验模式: Full Task KG")

    agents = MDTAgents(
        cfg["api_key"],
        cfg["base_url"],
        cfg["text_model"],
        enable_tools,
        neo4j_conf=neo4j_conf,
        forced_roles=forced_roles,
        disabled_intents=disabled_intents,
        adaptive_routing=getattr(args, "adaptive", False),
    )
    if getattr(args, "adaptive", False):
        print("自适应路由: 开启（破局①,按复杂度裁剪角色/轮数）")
    if getattr(args, "gene_reranker", False):
        agents.gene_reranker = True
        print("基因重排: 开启（破局②,LLM重排KG候选基因,解决字母序问题）")
    app = None if args.experiment == "gpt4o_direct" else create_workflow(agents)

    gold_rows = load_jsonl(Path(args.gold))
    if args.ids:
        requested_ids = [x.strip() for x in args.ids.split(",") if x.strip()]
        requested_set = set(requested_ids)
        gold_rows = [row for row in gold_rows if row.get("id") in requested_set]
        found_ids = {row.get("id") for row in gold_rows}
        missing_ids = [rid for rid in requested_ids if rid not in found_ids]
        if missing_ids:
            print(f"[WARN] requested ids not found in gold: {missing_ids}")
    elif args.limit is not None:
        gold_rows = gold_rows[: max(args.limit, 0)]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 断点续跑：加载已完成的 id
    done_ids = set()
    if args.resume:
        done_ids = load_existing_ids(out_path)
        if done_ids:
            print(f"断点续跑: 已完成 {len(done_ids)} 题，跳过: {done_ids}")

    # 使用 append 模式（续跑）或 write 模式（全新）
    open_mode = "a" if args.resume and done_ids else "w"
    total = len(gold_rows)

    with out_path.open(open_mode, encoding="utf-8") as f:
        for idx, row in enumerate(gold_rows, 1):
            if row["id"] in done_ids:
                print(f"  [{idx}/{total}] id={row['id']} 已完成，跳过")
                continue

            print(f"  [{idx}/{total}] 正在处理 id={row['id']} ...")
            if args.experiment == "gpt4o_direct":
                result = run_direct_question_with_retry(
                    agents,
                    row["question"],
                    max_retries=args.max_retries,
                    retry_delay=args.retry_delay,
                    per_question_timeout=args.per_question_timeout,
                )
            else:
                result = run_one_question_with_retry(
                    app,
                    agents,
                    row["question"],
                    args.max_rounds,
                    max_retries=args.max_retries,
                    retry_delay=args.retry_delay,
                    per_question_timeout=args.per_question_timeout,
                )
            pred = {
                "id": row["id"],
                "answer_text": result["answer_text"],
                "final_answer": result["answer_text"],  # alias for v2.1 metrics
                "predicted_genes": [],
                "predicted_pathways": [],
                "predicted_phenotypes": [],
                "predicted_drugs": [],
                "predicted_relations": [],
                "bridge_found": False,
                "mechanism_completeness": None,
                "graph_faithfulness": None,
                "utility_score": None,
                "tool_calls": result["tool_calls"],
                # v2.1: KG coverage for stratified metrics
                "kg_coverage_level": result.get("kg_coverage_level", "disabled"),
                "kg_coverage_ratio": result.get("kg_coverage_ratio", 0.0),
                # gene_reranker: LLM-prioritised gene order (empty list if disabled)
                "kg_reranked_genes": result.get("kg_reranked_genes", []),
                "cited_edges": [],          # to be populated by extractor
                "asserted_claims": [],      # to be populated by LLM-judge (optional)
                "notes": f"experiment={args.experiment}; max_rounds={args.max_rounds}; selected_roles={result['selected_roles']}",
            }
            f.write(json.dumps(pred, ensure_ascii=False) + "\n")
            f.flush()  # 立即刷盘，防止崩溃丢数据
            print(f"  [{idx}/{total}] id={row['id']} done")

            # 题间间隔，避免 API 限速
            if idx < total:
                import time as _t
                _t.sleep(5)

    print(f"批量评测输出已生成: {out_path}")
    print("说明：当前脚本只自动收集 answer_text 和 tool_calls。")
    print("predicted_genes / pathways / phenotypes / drugs 等字段建议后续人工填写，或再接一个抽取器。")


if __name__ == "__main__":
    main()
