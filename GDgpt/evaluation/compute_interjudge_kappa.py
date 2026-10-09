"""
Inter-judge Cohen's kappa from multijudge panel data.
Computes kappa between every pair of judges for each dimension.
Supplements Spearman rho already reported in multijudge_9q.json.

Usage:
  python evaluation/compute_interjudge_kappa.py \
    --multijudge evaluation/results/multijudge_9q.json

Output: per-dimension inter-judge kappa for system_a and system_b.
"""

import argparse, json
from collections import Counter

DIMS = ["D1", "D2", "D3", "D4", "D5"]
LEVELS = [1, 3, 5]


def map_score(v):
    iv = int(v)
    if iv in LEVELS:
        return LEVELS.index(iv)
    return round((v - 1) / 2)


def cohen_kappa(r1, r2):
    assert len(r1) == len(r2) and len(r1) >= 2
    n = len(r1)
    k = len(LEVELS)
    po = sum(1 for a, b in zip(r1, r2) if a == b) / n
    c1, c2 = Counter(r1), Counter(r2)
    pe = sum((c1.get(cat, 0) / n) * (c2.get(cat, 0) / n) for cat in range(k))
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def interp(k):
    if k > 0.8: return "excellent"
    if k > 0.6: return "good"
    if k > 0.4: return "moderate"
    if k > 0.2: return "fair"
    if k >= 0.0: return "slight"
    return "negative"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--multijudge", required=True)
    args = ap.parse_args()

    data = json.load(open(args.multijudge))
    judges = data["judges"]
    raw = data["per_judge_raw"]

    # Build per-judge, per-system, per-dim score lists (aligned by question order)
    qids = list(raw[judges[0]].keys())

    print("=== Inter-judge Cohen's kappa (N={}) ===\n".format(len(qids)))

    for system_key, system_label in [("a", "System A (GDgpt)"), ("b", "System B (GPT-4o)")]:
        print(f"  {system_label}")
        for dim in DIMS:
            scores = {}
            for j in judges:
                scores[j] = [map_score(raw[j][qid][system_key][dim]) for qid in qids]

            pairs = [(judges[i], judges[j])
                     for i in range(len(judges)) for j in range(i + 1, len(judges))]

            kappas = []
            for ja, jb in pairs:
                k = cohen_kappa(scores[ja], scores[jb])
                kappas.append((ja, jb, k))

            mean_k = sum(k for _, _, k in kappas) / len(kappas)
            parts = ", ".join(f"{a.split('-')[0]}vs{b.split('-')[0]}={k:.3f}" for a, b, k in kappas)
            print(f"    {dim}: mean κ = {mean_k:.3f} ({interp(mean_k)})  [{parts}]")
        print()

    print("Note: inter-judge kappa measures rubric clarity / agreement between LLM evaluators.")
    print("      This is NOT equivalent to human expert validation.")
    print("      Use to support 'evaluator-agnostic rubric' claims, NOT 'human-validated judge' claims.")


if __name__ == "__main__":
    main()
