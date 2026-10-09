"""Checks for the evaluation/metrics_*_ext.py extension scripts.

This is a CHECKER, not a pytest module, which is why it is named
check_metrics_ext.py: its checks are functions called from main() and they need
a --pred argument. Named test_metrics_ext.py it looked collectable, and
`pytest evaluation/tests/` found 0 tests in it and reported success -- a suite
that is invisible rather than failing loudly.

Run from the repository root:

    python evaluation/tests/check_metrics_ext.py --pred <predictions.jsonl> \
        [--kg-nodes <task_kg_nodes.csv>]

Check R1 is the correctness anchor required by the task: the Recall@5 that
metrics_ranking_ext.py reports for genes MUST equal the
retrieval.gene_recall@5 that the pre-existing evaluation/compute_metrics.py
reports on the same (gold, pred) pair. If the two ever diverge, the new
ranking script has changed the metric definition rather than extended it.

Check R6 is the second anchor: recall@all_plain_lowercase MUST equal the value
compute_paired_stats.per_item_metric computes for --metric gene_recall, since
that is the provenance claim the module docstring makes about the archived
0.0467.

R1 and R6 are RELATIVE anchors: they pin the two implementations to each other
and would both stay green if both moved together. R1 in particular compares the
new script to a function it literally calls. R7 is therefore the ABSOLUTE
anchor: it pins the two archive-quoted constants, 0.0100 and 0.046667, to a
named (gold, pred) pair, so editing evaluation/gene_alias_map.json or
evaluation/extract_from_tool_calls.py turns the suite red instead of silently
moving the paper's numbers. R7 skips when that exact pair is not on disk.

The KG node CSV lives outside the repository (it is produced by kg_build), so
R5 takes its path from --kg-nodes or the GDGPT_KG_NODES_CSV environment
variable and is SKIPPED, not failed, when neither resolves to a file. A missing
machine-local input must not turn the whole suite red and mask a real
regression.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl"
PCQA_RAW = REPO / "evaluation/results/pcqa100_gdgpt_raw.jsonl"

TOL = 1e-9

SKIP = "SKIP"


def _run(cmd):
    proc = subprocess.run(
        [sys.executable, *cmd], cwd=REPO, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_r1_recall5_reproduction(pred):
    """metrics_ranking_ext.py gene Recall@5 == compute_metrics.py gene_recall@5."""
    rc_a, out_a, err_a = _run(
        ["evaluation/compute_metrics.py", "--gold", str(GOLD), "--pred", str(pred), "--k", "5"]
    )
    if rc_a != 0:
        return False, "compute_metrics.py exited %d: %s" % (rc_a, err_a.strip()[:400])
    baseline = json.loads(out_a)["retrieval"]["gene_recall@5"]

    rc_b, out_b, err_b = _run(
        ["evaluation/metrics_ranking_ext.py", "--gold", str(GOLD), "--pred", str(pred)]
    )
    if rc_b != 0:
        return False, "metrics_ranking_ext.py exited %d: %s" % (rc_b, err_b.strip()[:400])
    mine = json.loads(out_b)["genes"]["recall@5"]

    # metrics_ranking_ext reports None when no question was scorable, where
    # compute_metrics.py reports 0.0. Say so instead of dying in the subtraction.
    if mine is None:
        return False, ("metrics_ranking_ext scored no questions (recall@5 is null) "
                       "while compute_metrics reported %r; the gold/pred ids probably "
                       "do not intersect" % baseline)
    if abs(mine - baseline) > TOL:
        return False, "Recall@5 mismatch: ext=%r vs compute_metrics=%r" % (mine, baseline)
    return True, "Recall@5 reproduced: %r == compute_metrics %r" % (mine, baseline)


def check_r2_ceiling(pred):
    """|gold|=20 must give a per-question Recall@5 ceiling of exactly 0.25."""
    rc, out, err = _run(
        ["evaluation/metrics_ranking_ext.py", "--gold", str(GOLD), "--pred", str(pred)]
    )
    if rc != 0:
        return False, "metrics_ranking_ext.py exited %d: %s" % (rc, err.strip()[:400])
    per_q = json.loads(out)["genes"]["per_question"]
    bad = [
        q for q in per_q
        if q["n_gold"] == 20 and abs(q["ceiling_recall@5"] - 0.25) > TOL
    ]
    if bad:
        return False, "%d question(s) with |gold|=20 have ceiling != 0.25" % len(bad)
    n20 = sum(1 for q in per_q if q["n_gold"] == 20)
    if n20 == 0:
        return False, "no question with |gold|=20 in this gold/pred intersection"
    return True, "%d question(s) with |gold|=20 all have ceiling@5 == 0.25" % n20


def check_r3_citation_normalisation(pred):
    """Citation edge normalisation must be direction- and case-insensitive."""
    rc, out, err = _run(
        ["evaluation/metrics_citation_ext.py", "--gold", str(GOLD), "--pred", str(pred)]
    )
    if rc != 0:
        return False, "metrics_citation_ext.py exited %d: %s" % (rc, err.strip()[:400])
    probe = json.loads(out).get("normalisation_selftest", {})
    if not probe:
        return False, "no normalisation_selftest block in output"
    failed = [k for k, v in probe.items() if v is not True]
    if failed:
        return False, "normalisation self-test failed: %s" % failed
    return True, "normalisation self-test passed (%d cases)" % len(probe)


def check_r4_aurc_bounds(pred):
    """AURC must lie in [0,1] and the risk-coverage curve must end at coverage 1.0."""
    rc, out, err = _run(
        [
            "evaluation/metrics_abstention_ext.py",
            "--pred", str(pred),
            "--gold", str(GOLD),
            "--correctness", "gene-hit",
        ]
    )
    if rc != 0:
        return False, "metrics_abstention_ext.py exited %d: %s" % (rc, err.strip()[:400])
    res = json.loads(out)
    aurc = res["aurc"]
    if aurc is None:
        return False, "aurc is null: no question carried a correctness label"
    if not (0.0 - TOL <= aurc <= 1.0 + TOL):
        return False, "AURC out of [0,1]: %r" % aurc
    curve = res["risk_coverage_curve"]
    if not curve:
        return False, "empty risk_coverage_curve"
    if abs(curve[-1]["coverage"] - 1.0) > TOL:
        return False, "curve does not reach coverage 1.0 (last=%r)" % curve[-1]["coverage"]
    return True, "AURC=%r in [0,1], curve reaches coverage 1.0" % aurc


def check_r5_drug_coverage_total(pred_unused, kg_nodes=None):
    """Query counts must partition into in-KG + off-KG + no-disease-argument.

    The third bucket matters: GeneToDrug and DrugToDisease runs mostly carry no
    disease argument at all, and folding those into off-KG would report a
    coverage gap that was never tested.
    """
    nodes = Path(kg_nodes) if kg_nodes else None
    if nodes is None or not nodes.is_file():
        return SKIP, ("KG node CSV not available (%s); pass --kg-nodes or set "
                      "GDGPT_KG_NODES_CSV to run this check" % (nodes or "unset"))
    rc, out, err = _run(
        [
            "evaluation/metrics_drug_by_coverage_ext.py",
            "--pred", str(PCQA_RAW),
            "--kg-nodes", str(nodes),
        ]
    )
    if rc != 0:
        return False, "metrics_drug_by_coverage_ext.py exited %d: %s" % (rc, err.strip()[:400])
    res = json.loads(out)
    if res["kg_disease_nodes"]["n"] != 20:
        return False, "expected 20 Disease nodes, got %d" % res["kg_disease_nodes"]["n"]
    for intent, block in res["by_intent"].items():
        tot = (block["in_kg"]["n_queries"] + block["off_kg"]["n_queries"]
               + block["no_disease_arg"]["n_queries"])
        if tot != block["n_queries"] or not block["buckets_sum_to_total"]:
            return False, "%s buckets sum to %d != total %d" % (intent, tot, block["n_queries"])
    d2d = res["by_intent"].get("DiseaseToDrug")
    if d2d is None:
        return False, "no DiseaseToDrug block"
    if d2d["no_disease_arg"]["n_queries"] != 0:
        return False, ("DiseaseToDrug has %d runs with no disease argument; the "
                       "coverage split for this intent is not interpretable"
                       % d2d["no_disease_arg"]["n_queries"])
    return True, ("20 Disease nodes; DiseaseToDrug n=%d partitions as in_kg=%d off_kg=%d "
                  "no_disease_arg=%d" % (d2d["n_queries"], d2d["in_kg"]["n_queries"],
                                         d2d["off_kg"]["n_queries"],
                                         d2d["no_disease_arg"]["n_queries"]))


def check_r6_plain_recall_matches_paired_stats(pred):
    """recall@all_plain_lowercase == compute_paired_stats gene_recall.

    This is the provenance anchor for the archived 0.0467: the docstring claims
    that number is unbounded-k gene recall under PLAIN lowercase normalisation,
    and this check proves it by calling compute_paired_stats itself.
    """
    sys.path.insert(0, str(REPO / "evaluation"))
    try:
        from compute_paired_stats import per_item_metric  # type: ignore
    except ImportError as exc:
        return SKIP, "compute_paired_stats not importable (%s); numpy may be absent" % exc

    gold_by_id = {}
    with GOLD.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                gold_by_id[str(row["id"])] = row

    # metrics_ranking_ext builds its prediction index as a dict keyed by id, so a
    # duplicated id collapses to its LAST occurrence. Averaging over raw lines
    # here would disagree with it whenever a result file has duplicate rows,
    # which is a documented hazard in this project, and R6 would fail spuriously.
    pred_by_id = {}
    with Path(pred).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                pred_by_id[str(row.get("id"))] = row

    vals = []
    for pid, p in pred_by_id.items():
        g = gold_by_id.get(pid)
        if g is None:
            continue
        v = per_item_metric(p, g, "gene_recall")
        if v == v:  # skip NaN
            vals.append(v)
    if not vals:
        return False, "no scorable questions in the gold/pred intersection"
    baseline = sum(vals) / len(vals)

    rc, out, err = _run(
        ["evaluation/metrics_ranking_ext.py", "--gold", str(GOLD), "--pred", str(pred)]
    )
    if rc != 0:
        return False, "metrics_ranking_ext.py exited %d: %s" % (rc, err.strip()[:400])
    mine = json.loads(out)["genes"]["recall@all_plain_lowercase"]
    if mine is None or abs(mine - baseline) > 1e-9:
        return False, ("recall@all_plain_lowercase=%r != compute_paired_stats "
                       "gene_recall=%r" % (mine, baseline))
    return True, ("recall@all_plain_lowercase %.6f == compute_paired_stats "
                  "gene_recall %.6f over N=%d" % (mine, baseline, len(vals)))


#: The two constants the paper and the archived paired-stats file quote, pinned to
#: the exact (gold, pred) pair they come from. R7 asserts these VALUES, not just
#: that two implementations agree with each other.
ARCHIVE_ANCHORS = {
    "pred": "evaluation/results/adapt15_full_ext.jsonl",
    "gold": "evaluation/independent_testset/output/"
            "testset_kg_optimized_enriched_with_edges.jsonl",
    "recall@5": 0.01,
    "recall@all_plain_lowercase": 0.0466666666666666,
    "n_scored": 15,
    "source": "paper Gene Recall@5 0.047 / "
              "evaluation/results/paired_stats_gene_recall.txt 0.0467",
}

#: The 38-question ablation run, pinned for the SAME reason and because two
#: reviewers reported different Recall@5 values for it: 0.0033 from a
#: from-scratch implementation and 0.0043 from compute_metrics.recall_at_k. The
#: difference is _canonicalize_gene stripping " gene"/" protein"/" receptor"
#: suffixes, which collapses two gold sets (30 -> 29, 23 -> 22) and finds a
#: fourth hit. 0.0043 is what this repository's code returns; see
#: evidence/reconcile_recall5.log. Pinning it keeps that reconciliation from
#: silently drifting.
ABLATION_ANCHOR = {
    "pred": "evaluation/results/kg_opt_exp0_extracted.jsonl",
    "recall@5": 0.004296595721278117,
    "recall@all_plain_lowercase": 0.41517925247902365,
    "n_scored": 38,
}


def check_r7_archive_constants(pred_unused, pred_override=None):
    """Pin 0.0100 and 0.046667 to the named (gold, pred) pair, by value.

    An absolute anchor: unlike R1 and R6 this fails if the alias map or the
    extractor changes what those files mean, even when every implementation
    still agrees with every other.
    """
    gold = REPO / ARCHIVE_ANCHORS["gold"]
    cand = [Path(pred_override)] if pred_override else []
    cand.append(REPO / ARCHIVE_ANCHORS["pred"])
    pred = next((c for c in cand if c.is_file()), None)
    if pred is None or not gold.is_file():
        # The adapt15 half needs a file that is untracked in this checkout, but the
        # ablation half is tracked, so still run it rather than skipping both.
        return _check_ablation_anchor(
            gold,
            prefix="adapt15 anchor skipped (%s is untracked here; pass "
                   "--archive-pred to include it)" % ARCHIVE_ANCHORS["pred"],
            skip_if_absent=True,
        )

    rc, out, err = _run(
        ["evaluation/metrics_ranking_ext.py", "--gold", str(gold), "--pred", str(pred)]
    )
    if rc != 0:
        return False, "metrics_ranking_ext.py exited %d: %s" % (rc, err.strip()[:400])
    g = json.loads(out)["genes"]

    problems = []
    if g["n_scored"] != ARCHIVE_ANCHORS["n_scored"]:
        problems.append("n_scored %s != %s" % (g["n_scored"], ARCHIVE_ANCHORS["n_scored"]))
    for key in ("recall@5", "recall@all_plain_lowercase"):
        got, want = g[key], ARCHIVE_ANCHORS[key]
        if got is None or abs(got - want) > 1e-6:
            problems.append("%s %r != %r" % (key, got, want))
    if problems:
        return False, ("archive constants moved (%s). If this is intended, the paper "
                       "and %s must be updated together with ARCHIVE_ANCHORS."
                       % ("; ".join(problems), ARCHIVE_ANCHORS["source"]))
    msg = ("archive constants pinned by value: recall@5 %.6f and "
           "recall@all_plain_lowercase %.6f over N=%d on %s"
           % (g["recall@5"], g["recall@all_plain_lowercase"], g["n_scored"], pred.name))
    return _check_ablation_anchor(gold, prefix=msg)


def _check_ablation_anchor(gold, prefix, skip_if_absent=False):
    """Pin the 38-question ablation run, where two reviewers reported 0.0033 vs 0.0043.

    Tracked in the repository, so it runs even when the adapt15 anchor file is not
    on disk.
    """
    abl = REPO / ABLATION_ANCHOR["pred"]
    if not abl.is_file():
        return (SKIP if skip_if_absent else True), (
            prefix + "; ablation anchor also absent (%s)" % ABLATION_ANCHOR["pred"])
    rc2, out2, err2 = _run(
        ["evaluation/metrics_ranking_ext.py", "--gold", str(gold), "--pred", str(abl)]
    )
    if rc2 != 0:
        return False, "metrics_ranking_ext.py on the ablation anchor exited %d: %s" % (
            rc2, err2.strip()[:300])
    a = json.loads(out2)["genes"]
    bad = []
    if a["n_scored"] != ABLATION_ANCHOR["n_scored"]:
        bad.append("n_scored %s != %s" % (a["n_scored"], ABLATION_ANCHOR["n_scored"]))
    for key in ("recall@5", "recall@all_plain_lowercase"):
        got, want = a[key], ABLATION_ANCHOR[key]
        if got is None or abs(got - want) > 1e-9:
            bad.append("%s %r != %r" % (key, got, want))
    if bad:
        return False, ("ablation anchor moved (%s). 0.0043 is what "
                       "compute_metrics.recall_at_k returns here; a from-scratch "
                       "implementation without its suffix stripping gives 0.0033. See "
                       "evidence/reconcile_recall5.log." % "; ".join(bad))
    return True, (prefix + "; ablation anchor pinned: recall@5 %.6f over N=%d on %s"
                  % (a["recall@5"], a["n_scored"], abl.name))


CHECKS = [
    ("R1 Recall@5 reproduces compute_metrics.py", check_r1_recall5_reproduction),
    ("R2 ceiling Recall@5 == 0.25 when |gold|=20", check_r2_ceiling),
    ("R3 citation edge normalisation self-test", check_r3_citation_normalisation),
    ("R4 AURC in [0,1] and curve reaches coverage 1.0", check_r4_aurc_bounds),
    ("R5 drug-path counts partition into in-KG/off-KG/no-disease-arg", check_r5_drug_coverage_total),
    ("R6 plain-lowercase recall@all reproduces compute_paired_stats",
     check_r6_plain_recall_matches_paired_stats),
    ("R7 archive constants 0.0100 / 0.046667 pinned by value", check_r7_archive_constants),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--kg-nodes", default=os.environ.get("GDGPT_KG_NODES_CSV"),
                    help="task_kg_nodes.csv from kg_build; R5 is skipped without it.")
    ap.add_argument("--archive-pred", default=os.environ.get("GDGPT_ARCHIVE_PRED"),
                    help="the adapt15_full_ext.jsonl the archive constants come from; "
                         "R7 is skipped without it when the tracked path is absent.")
    args = ap.parse_args()
    pred = Path(args.pred).resolve()

    print("repo       : %s" % REPO)
    print("gold       : %s" % GOLD)
    print("pred       : %s" % pred)
    print("pred exists: %s" % pred.exists())
    print("kg nodes   : %s" % (args.kg_nodes or "<not provided; R5 will skip>"))
    print("archive    : %s" % (args.archive_pred or ARCHIVE_ANCHORS["pred"]))
    print()

    failures = 0
    skipped = 0
    for name, fn in CHECKS:
        try:
            if fn is check_r5_drug_coverage_total:
                ok, msg = fn(pred, kg_nodes=args.kg_nodes)
            elif fn is check_r7_archive_constants:
                ok, msg = fn(pred, pred_override=args.archive_pred)
            else:
                ok, msg = fn(pred)
        except Exception as exc:  # a crash is a red check, not a harness crash
            ok, msg = False, "%s: %s" % (type(exc).__name__, exc)
        label = SKIP if ok is SKIP else ("PASS" if ok else "FAIL")
        print("[%s] %s\n       %s" % (label, name, msg))
        if ok is SKIP:
            skipped += 1
        elif not ok:
            failures += 1

    print()
    print("%d/%d checks passed, %d skipped, %d failed"
          % (len(CHECKS) - failures - skipped, len(CHECKS), skipped, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
