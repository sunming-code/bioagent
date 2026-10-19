"""
计算 LLM-judge vs 人工评分的 Cohen's kappa（验证 LLM-judge 可靠性）。
人工评分从 human_rating_form.md 里解析（须先手动填写）。

用法：
  python evaluation/compute_kappa.py \
    --llm  evaluation/results/llm_judge_results.json \
    --human evaluation/results/human_rating_filled.json
（human_rating_filled.json 格式见脚本末尾示例）
"""

import argparse, json, math
from collections import Counter

DIMS = ["D1", "D2", "D3", "D4", "D5"]
LEVELS = [1, 3, 5]

def cohen_kappa(ratings1, ratings2):
    """Cohen's kappa for ordinal ratings (1/3/5 → mapped to 0/1/2 for computation)."""
    assert len(ratings1) == len(ratings2) and len(ratings1) > 0
    # map to 0/1/2
    def m(v): return LEVELS.index(int(v)) if int(v) in LEVELS else round((v-1)/2)
    r1 = [m(v) for v in ratings1]
    r2 = [m(v) for v in ratings2]
    n = len(r1)
    k = len(LEVELS)
    # observed agreement
    po = sum(1 for a, b in zip(r1, r2) if a == b) / n
    # expected agreement
    c1 = Counter(r1); c2 = Counter(r2)
    pe = sum((c1.get(cat, 0)/n) * (c2.get(cat, 0)/n) for cat in range(k))
    if pe >= 1.0: return 1.0
    return (po - pe) / (1 - pe)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", required=True)
    ap.add_argument("--human", required=True)
    args = ap.parse_args()

    llm_data = json.load(open(args.llm))
    human_data = json.load(open(args.human))   # {qid: {system: {D1:.., D2:..}}}

    print(f"=== Cohen's kappa: LLM-judge vs Human (N={llm_data['n']}) ===")
    for system in ["system_a", "system_b"]:
        print(f"\n  System: {'A (GDgpt)' if system=='system_a' else 'B (GPT-4o)'}")
        for dim in DIMS:
            llm_scores = []
            human_scores = []
            for r in llm_data["per_question"]:
                qid = r["id"]
                lv = r[system].get(dim)
                hv = human_data.get(qid, {}).get(system, {}).get(dim)
                if lv and hv:
                    llm_scores.append(lv)
                    human_scores.append(hv)
            if len(llm_scores) < 2:
                print(f"    {dim}: insufficient data"); continue
            k = cohen_kappa(llm_scores, human_scores)
            interp = "excellent" if k>0.8 else "good" if k>0.6 else "moderate" if k>0.4 else "fair"
            print(f"    {dim}: κ = {k:.3f}  ({interp})")

    print("""
Note: κ > 0.6 is generally considered 'good' agreement, supporting LLM-judge validity.
      Per HeaLing 2026, report κ explicitly and call the judge a 'validated proxy'.
""")

if __name__ == "__main__":
    main()

# ---------- human_rating_filled.json 格式示例 ----------
# {
#   "ind_dc_87845f398756": {
#     "system_a": {"D1": 5, "D2": 3, "D3": 5, "D4": 5, "D5": 5},
#     "system_b": {"D1": 3, "D2": 3, "D3": 1, "D4": 1, "D5": 5}
#   },
#   ...
# }
