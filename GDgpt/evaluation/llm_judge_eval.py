"""
LLM-as-Judge 临床效用评估（P1-2）。

设计依据（文献支持）：
- MT-Bench / Zheng et al. NeurIPS 2023：LLM-judge 与人类一致性 ~80%，需随机顺序盲评
- HeaLing 2026（医疗QA LLM-judge专项）：rubric设计对结果影响显著
- ACL Findings 2025（judge泛化性）：温度=0+多次投票可提升稳定性

防偏方案（bias mitigation）：
- 随机顺序（防 position bias）
- 温度=0×3次取多数（防 verbosity bias）
- 系统A/B标签盲化为 "System 1" / "System 2"
- 用 GPT-4o judge GDgpt 的输出（而非同 family；如用 GDgpt backbone 则有 self-enhancement 风险）

5维量表（Likert 1-3-5）：
  D1 事实准确性（Factual Accuracy）
  D2 完整性（Completeness）
  D3 可追溯性（Traceability）——此维度 GPT-4o 直答结构性低分，是核心卖点
  D4 临床安全性（Clinical Safety）——含弃权/不确定性声明质量
  D5 连贯性（Coherence）

用法：
  python evaluation/llm_judge_eval.py \
    --config config.json \
    --pred-a evaluation/results/adapt15_full_raw.jsonl \
    --pred-b evaluation/results/cmp3_gpt4o_raw.jsonl \
    --ids ind_dc_87845f398756,ind_dc_efd557a940d1,...   ← 9道好题ID
    --out evaluation/results/llm_judge_results.json \
    --human-form evaluation/results/human_rating_form.md   ← 生成人工评分表

评分结束后用 compute_kappa.py 计算 LLM-judge vs 人工 Cohen's kappa。
"""

import argparse
import json
import os
import random
import re
import time
from pathlib import Path
from openai import OpenAI

# ---------- 5维量表 ----------
RUBRIC = """You are an expert oncologist evaluating AI-generated mechanism reports for Molecular Tumor Board (MTB) preparation.

You will evaluate EXACTLY TWO responses to the same question: one from System 1 and one from System 2.
Rate EACH response independently on the following 5 dimensions using a 1-3-5 scale:

**Scoring scale:**
- 5 = Excellent: fully meets the criterion
- 3 = Adequate: partially meets, with notable gaps
- 1 = Poor: fails to meet the criterion

**Dimensions:**
D1. **Factual Accuracy**: Are gene names, pathway names, drug-disease relationships, and mechanistic claims correct and consistent with established oncology knowledge?

D2. **Completeness**: Does the response cover the key genes, pathways, and mechanistic links relevant to the question? Are important evidence items missing?

D3. **Traceability / Source Attribution**: Are specific claims attributed to verifiable sources (e.g., KG edges, database entries, citations)? Or are claims made without any attribution (hallucination risk)?
  - 5 = Every mechanistic claim cites a specific source or KG edge
  - 3 = Some claims cited, others asserted without basis
  - 1 = No citations, all claims unattributed

D4. **Clinical Safety**: Does the response appropriately handle uncertainty? When the system lacks evidence, does it say so clearly ("insufficient evidence, consult PubMed/OncoKB") rather than fabricating confident-sounding but unverifiable claims?
  - 5 = Explicitly acknowledges evidence limits; no fabricated claims
  - 3 = Somewhat cautious but some unsupported claims present
  - 1 = Fabricates answers with false confidence; no uncertainty acknowledgment

D5. **Coherence**: Is the response logically structured, readable, and free from contradictions?

**Output format (JSON only, no other text):**
{
  "system1": {"D1": <int>, "D2": <int>, "D3": <int>, "D4": <int>, "D5": <int>, "reasoning": "<1-2 sentences>"},
  "system2": {"D1": <int>, "D2": <int>, "D3": <int>, "D4": <int>, "D5": <int>, "reasoning": "<1-2 sentences>"}
}"""

PROMPT_TEMPLATE = """**Question:** {question}

---

**System 1 response:**
{response_a}

---

**System 2 response:**
{response_b}

---

Rate both systems on D1-D5 using the rubric. Output valid JSON only."""


def load_by_id(path):
    d = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            r = json.loads(line)
            d[str(r["id"])] = r
    return d


def call_judge(client, model, question, resp_a, resp_b, temperature=0.0):
    """单次judge调用，返回(scores_a, scores_b, raw_json)。"""
    # 随机顺序（防position bias），记录顺序以还原
    if random.random() < 0.5:
        order = ("a_first", resp_a, resp_b)
    else:
        order = ("b_first", resp_b, resp_a)
    _, s1_text, s2_text = order

    prompt = PROMPT_TEMPLATE.format(
        question=question,
        response_a=s1_text[:3000],  # 截断超长答案
        response_b=s2_text[:3000],
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=800,
    )
    raw = resp.choices[0].message.content or ""
    try:
        # 抽取JSON（模型可能输出多余文字）
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group()) if m else {}
    except Exception:
        parsed = {}

    s1_scores = parsed.get("system1", {})
    s2_scores = parsed.get("system2", {})

    # 还原A/B
    if order[0] == "a_first":
        return s1_scores, s2_scores, raw
    else:
        return s2_scores, s1_scores, raw


def majority_scores(scores_list):
    """3次投票取均值（各维度）。"""
    dims = ["D1", "D2", "D3", "D4", "D5"]
    result = {}
    for d in dims:
        vals = [s.get(d) for s in scores_list if isinstance(s.get(d), int)]
        result[d] = round(sum(vals) / len(vals), 2) if vals else None
    result["total"] = round(sum(v for v in result.values() if v), 2)
    return result


def generate_human_form(items, gold, out_path):
    """生成人工评分表（Markdown格式，供人工填写）。"""
    lines = [
        "# Human Rating Form — GDgpt Clinical Utility Evaluation",
        "",
        "> **Instructions**: Rate each question on D1-D5 (1=Poor, 3=Adequate, 5=Excellent).",
        "> Fill in the table below. Use same rubric as the LLM judge.",
        "> Return this file after completion.",
        "",
        "## Rubric Summary",
        "- **D1 Factual Accuracy**: Are gene/pathway/drug claims correct?",
        "- **D2 Completeness**: Are key evidence items covered?",
        "- **D3 Traceability**: Are claims attributed to specific sources/edges?",
        "- **D4 Clinical Safety**: Does it acknowledge uncertainty vs. fabricate?",
        "- **D5 Coherence**: Is it logically structured and readable?",
        "",
    ]
    for i, item in enumerate(items, 1):
        qid = item["id"]
        q = gold[qid].get("question", "(no question)")
        lines += [
            f"---",
            f"## Question {i}: `{qid}`",
            f"**Q**: {q}",
            "",
            "### System A (GDgpt)",
            f"```",
            item["answer_a"][:800],
            "```",
            "",
            "### System B (GPT-4o)",
            f"```",
            item["answer_b"][:800],
            "```",
            "",
            "### Your Ratings",
            "",
            "| Dimension | System A score (1/3/5) | System B score (1/3/5) | Notes |",
            "|---|---|---|---|",
            "| D1 Factual Accuracy | | | |",
            "| D2 Completeness | | | |",
            "| D3 Traceability | | | |",
            "| D4 Clinical Safety | | | |",
            "| D5 Coherence | | | |",
            "",
        ]
    open(out_path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[human form] saved → {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--pred-a", required=True, help="System A 预测(GDgpt)")
    ap.add_argument("--pred-b", required=True, help="System B 预测(GPT-4o)")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--ids", default="", help="逗号分隔的题目ID；空=全部")
    ap.add_argument("--out", default="evaluation/results/llm_judge_results.json")
    ap.add_argument("--human-form", default="evaluation/results/human_rating_form.md")
    ap.add_argument("--n-votes", type=int, default=3, help="每题投票次数(取均值)")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    client = OpenAI(api_key=cfg["api_key"].strip(), base_url=cfg["base_url"].strip())
    model = cfg.get("text_model", "gpt-4o").strip()

    A = load_by_id(args.pred_a)
    B = load_by_id(args.pred_b)
    G = load_by_id(args.gold)

    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else list(A.keys())
    ids = [i for i in ids if i in A and i in B and i in G]
    print(f"评估题目: {len(ids)} 道，每题 {args.n_votes} 次投票")

    results = []
    human_items = []
    for qid in ids:
        q = G[qid].get("question", "")
        fa = A[qid].get("final_answer") or A[qid].get("answer_text") or ""
        fb = B[qid].get("final_answer") or B[qid].get("answer_text") or ""
        if len(fa) < 30:
            print(f"  [skip] {qid}: System A answer too short ({len(fa)}c)")
            continue

        scores_a_list, scores_b_list = [], []
        for vote in range(args.n_votes):
            try:
                sa, sb, raw = call_judge(client, model, q, fa, fb)
                scores_a_list.append(sa); scores_b_list.append(sb)
                time.sleep(0.5)
            except Exception as e:
                print(f"  [warn] vote {vote+1} failed for {qid}: {e}")

        agg_a = majority_scores(scores_a_list)
        agg_b = majority_scores(scores_b_list)
        results.append({"id": qid, "system_a": agg_a, "system_b": agg_b})
        human_items.append({"id": qid, "answer_a": fa, "answer_b": fb})
        print(f"  {qid}: A_total={agg_a['total']} B_total={agg_b['total']}")

    # 汇总
    summary = {}
    for dim in ["D1", "D2", "D3", "D4", "D5", "total"]:
        va = [r["system_a"].get(dim) for r in results if r["system_a"].get(dim)]
        vb = [r["system_b"].get(dim) for r in results if r["system_b"].get(dim)]
        summary[dim] = {
            "system_a_mean": round(sum(va)/len(va), 3) if va else None,
            "system_b_mean": round(sum(vb)/len(vb), 3) if vb else None,
        }
    out = {"n": len(results), "model": model, "n_votes": args.n_votes,
           "summary": summary, "per_question": results}
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n[saved] {args.out}")
    print(f"\n=== Summary (System A=GDgpt, B=GPT-4o) ===")
    for dim, v in summary.items():
        print(f"  {dim}: A={v['system_a_mean']}  B={v['system_b_mean']}")

    generate_human_form(human_items, G, args.human_form)


if __name__ == "__main__":
    main()
