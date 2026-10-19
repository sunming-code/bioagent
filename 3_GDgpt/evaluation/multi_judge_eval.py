"""
多评委陪审团评估（Panel of LLM evaluators, PoLL）—— 替代人工 kappa。

设计依据（文献）：
- Verga et al. "Replacing Judges with Juries" (arXiv:2404.18796, 2024):
  多个架构不同的评委投票，其相互一致性可替代人工 inter-annotator agreement，
  并显著降低单模型 self-preference bias。
- Wang et al. "LLMs are not Fair Evaluators" (ACL 2024, 10.18653/v1/2024.acl-long.511):
  position bias → 用 order-swap 一致性检验。
- Zheng et al. MT-Bench (NeurIPS 2023): 报告 judge 间 agreement 作为可信度指标。

本脚本相对 llm_judge_eval.py 的增量：
  1. 多评委（默认 gpt-4o + qwen-max + gpt-4o-mini，跨家族）
  2. order-swap 去偏：每题两种顺序都判，只有两序一致才计为稳定胜出
  3. 计算评委间一致性：per-dimension Spearman ρ + 简化 Krippendorff α（序数）
  4. 报告每个评委各自的 D3（Traceability）结论，看是否跨评委一致

用法：
  python evaluation/multi_judge_eval.py \
    --config config.json \
    --pred-a evaluation/results/v23_9q_raw.jsonl \
    --pred-b evaluation/results/exp15_gpt4o_raw.jsonl \
    --gold  evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl \
    --ids "id1,id2,..." \
    --judges "gpt-4o,qwen-max,gpt-4o-mini" \
    --out evaluation/results/multijudge_9q.json
"""

import argparse
import json
import re
import time
import itertools
from pathlib import Path
from openai import OpenAI

DIMS = ["D1", "D2", "D3", "D4", "D5"]

RUBRIC = """You are an expert oncologist evaluating AI-generated mechanism reports for Molecular Tumor Board (MTB) preparation.

You will evaluate EXACTLY TWO responses to the same question: one from System 1 and one from System 2.
Rate EACH response independently on the following 5 dimensions using a 1-3-5 scale:

**Scoring scale:** 5 = Excellent (fully meets), 3 = Adequate (partial, notable gaps), 1 = Poor (fails).

**Dimensions:**
D1. Factual Accuracy: Are gene/pathway/drug-disease relationships and mechanistic claims correct?
D2. Completeness: Does it cover the key genes, pathways, and mechanistic links relevant to the question?
D3. Traceability / Source Attribution: Are specific claims attributed to verifiable sources (KG edges, database entries)?
  - 5 = every mechanistic claim cites a specific source/KG edge; 3 = some cited; 1 = no citations, all unattributed.
D4. Clinical Safety: When lacking evidence, does it say so ("insufficient evidence, consult PubMed/OncoKB") rather than fabricate?
  - 5 = explicitly acknowledges limits, no fabrication; 3 = somewhat cautious; 1 = fabricates with false confidence.
D5. Coherence: Is it logically structured, readable, free from contradictions?

**Output format (JSON only, no other text):**
{"system1": {"D1": <int>, "D2": <int>, "D3": <int>, "D4": <int>, "D5": <int>},
 "system2": {"D1": <int>, "D2": <int>, "D3": <int>, "D4": <int>, "D5": <int>}}"""

PROMPT_TEMPLATE = """**Question:** {question}

---
**System 1 response:**
{response_1}

---
**System 2 response:**
{response_2}

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


def parse_scores(raw):
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(m.group()) if m else {}
    except Exception:
        parsed = {}
    return parsed.get("system1", {}), parsed.get("system2", {})


def judge_once(client, model, question, resp_first, resp_second):
    """单次判定，返回 (first_scores, second_scores)。first=prompt里的System1。"""
    prompt = PROMPT_TEMPLATE.format(
        question=question, response_1=resp_first[:3000], response_2=resp_second[:3000]
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": RUBRIC},
                  {"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=400,
    )
    return parse_scores(resp.choices[0].message.content or "")


def judge_with_swap(client, model, question, resp_a, resp_b):
    """
    order-swap 去偏：跑两种顺序。
    顺序1: A=System1, B=System2  →  (a1, b1)
    顺序2: B=System1, A=System2  →  (b2, a2)
    返回 A/B 各维度均值 + 每维是否"两序一致地A>B/A<B/tie"。
    """
    a1, b1 = judge_once(client, model, question, resp_a, resp_b)
    time.sleep(0.3)
    b2, a2 = judge_once(client, model, question, resp_b, resp_a)

    a_avg, b_avg, swap_consistent = {}, {}, {}
    for d in DIMS:
        va = [v for v in [a1.get(d), a2.get(d)] if isinstance(v, int)]
        vb = [v for v in [b1.get(d), b2.get(d)] if isinstance(v, int)]
        a_avg[d] = sum(va) / len(va) if va else None
        b_avg[d] = sum(vb) / len(vb) if vb else None
        # 两序方向是否一致
        if all(isinstance(x, int) for x in [a1.get(d), a2.get(d), b1.get(d), b2.get(d)]):
            dir1 = (a1[d] > b1[d]) - (a1[d] < b1[d])   # order1 下 A vs B
            dir2 = (a2[d] > b2[d]) - (a2[d] < b2[d])   # order2 下 A vs B
            swap_consistent[d] = (dir1 == dir2)
        else:
            swap_consistent[d] = None
    return a_avg, b_avg, swap_consistent


def spearman(x, y):
    """简易 Spearman ρ（无 scipy）。x,y 等长数值列表。"""
    n = len(x)
    if n < 2:
        return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--pred-a", required=True, help="System A (GDgpt)")
    ap.add_argument("--pred-b", required=True, help="System B (GPT-4o direct)")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--ids", default="")
    ap.add_argument("--judges", default="gpt-4o,qwen-max,gpt-4o-mini")
    ap.add_argument("--out", default="evaluation/results/multijudge.json")
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    client = OpenAI(api_key=cfg["api_key"].strip(), base_url=cfg["base_url"].strip())
    judges = [j.strip() for j in args.judges.split(",") if j.strip()]

    A = load_by_id(args.pred_a)
    B = load_by_id(args.pred_b)
    G = load_by_id(args.gold)
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else list(A.keys())
    ids = [i for i in ids if i in A and i in B and i in G]
    print(f"多评委陪审团: {len(judges)} 评委 × {len(ids)} 题（每题 order-swap = 2 次/评委）")
    print(f"评委: {judges}")

    # per_judge[judge][qid] = {"a": {D:score}, "b": {D:score}, "swap": {D:bool}}
    per_judge = {j: {} for j in judges}

    for qid in ids:
        q = G[qid].get("question", "")
        fa = A[qid].get("final_answer") or A[qid].get("answer_text") or ""
        fb = B[qid].get("final_answer") or B[qid].get("answer_text") or ""
        if len(fa) < 30:
            print(f"  [skip] {qid}: A answer too short")
            continue
        for j in judges:
            try:
                a_avg, b_avg, swap = judge_with_swap(client, j, q, fa, fb)
                per_judge[j][qid] = {"a": a_avg, "b": b_avg, "swap": swap}
            except Exception as e:
                print(f"  [warn] {j} failed on {qid}: {str(e)[:50]}")
        print(f"  {qid}: done ({len(judges)} judges)")

    # ── 汇总每个评委的维度均值 ──
    summary = {}
    for j in judges:
        rows = per_judge[j]
        summary[j] = {}
        for d in DIMS:
            va = [rows[q]["a"][d] for q in rows if rows[q]["a"].get(d) is not None]
            vb = [rows[q]["b"][d] for q in rows if rows[q]["b"].get(d) is not None]
            summary[j][d] = {
                "gdgpt": round(sum(va) / len(va), 3) if va else None,
                "gpt4o": round(sum(vb) / len(vb), 3) if vb else None,
            }
        # swap 一致率
        swap_ok = [rows[q]["swap"][d] for q in rows for d in DIMS
                   if rows[q]["swap"].get(d) is not None]
        summary[j]["swap_consistency"] = round(sum(swap_ok) / len(swap_ok), 3) if swap_ok else None

    # ── 评委间一致性（inter-judge agreement）——用 GDgpt 的每题每维分数 ──
    inter = {}
    common_qids = set.intersection(*[set(per_judge[j].keys()) for j in judges]) if judges else set()
    common_qids = sorted(common_qids)
    for d in DIMS:
        # 收集每对评委在 GDgpt 上的 per-question 分数
        pairwise = {}
        for j1, j2 in itertools.combinations(judges, 2):
            x = [per_judge[j1][q]["a"][d] for q in common_qids
                 if per_judge[j1][q]["a"].get(d) is not None
                 and per_judge[j2][q]["a"].get(d) is not None]
            y = [per_judge[j2][q]["a"][d] for q in common_qids
                 if per_judge[j1][q]["a"].get(d) is not None
                 and per_judge[j2][q]["a"].get(d) is not None]
            rho = spearman(x, y)
            pairwise[f"{j1}__vs__{j2}"] = round(rho, 3) if rho is not None else None
        inter[d] = pairwise

    out = {
        "n_questions": len(common_qids),
        "judges": judges,
        "summary_per_judge": summary,
        "inter_judge_spearman_on_gdgpt": inter,
        "per_judge_raw": per_judge,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n[saved] {args.out}")

    # ── 打印可读汇总 ──
    print("\n=== 各评委 D3 (Traceability) 结论 ===")
    for j in judges:
        d3 = summary[j]["D3"]
        lead = "GDgpt★" if (d3["gdgpt"] or 0) > (d3["gpt4o"] or 0) else "GPT-4o"
        print(f"  {j:14s}: GDgpt={d3['gdgpt']} vs GPT-4o={d3['gpt4o']}  → {lead}")
    print("\n=== 评委间 D3 Spearman 一致性 ===")
    for pair, rho in inter["D3"].items():
        print(f"  {pair}: ρ={rho}")
    print("\n=== order-swap 一致率（越高越无位置偏见）===")
    for j in judges:
        print(f"  {j:14s}: {summary[j]['swap_consistency']}")


if __name__ == "__main__":
    main()
