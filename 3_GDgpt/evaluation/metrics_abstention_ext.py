"""Risk-coverage curve and AURC for KG-coverage-gated abstention.

Selective prediction framing: the system may decline to answer. The confidence
score it gates on is `kg_coverage_ratio` (how much of the question the Task KG
could cover). Sorting questions by that score and accepting the most confident
prefix gives a risk-coverage curve; the area under it (AURC) summarises how
well the score separates answers the system gets right from ones it gets wrong.
Lower AURC is better.

Definitions used here
---------------------
  coverage c  = (# accepted questions) / N
  risk(c)     = (# wrong among accepted) / (# accepted), where an ABSTENTION
                COUNTS AS WRONG. This is enforced in _risk_coverage: an item
                with abstained=True is counted wrong no matter what the
                correctness rule said about it, and `per_question` records that
                decision per row as `counted_correct_in_risk`.
  AURC        = trapezoidal integral of risk over coverage, divided by the
                coverage span, i.e. a coverage-weighted mean risk.

WHICH ERROR RATE AURC IS BOUNDED BY. Because `risk` counts abstentions as
wrong, the no-information baseline for `aurc` is NOT `overall_error_rate` (the
pure correctness error rate). It is
`error_rate_counting_abstention_as_wrong`, which is exactly risk at coverage
1.0. Both are reported, and `aurc_bound_ok` records that the bound holds. An
earlier version of this module documented the abstention-as-wrong rule but did
not implement it; under --correctness judge, where the judge scores every
abstention correct, that made risk FALL as coverage rose and pushed aurc above
the error rate it was supposed to be bounded by.

Three area numbers are reported and they are not interchangeable:
  aurc                       -- over `risk`; abstentions count as errors, so
                                declining to answer is penalised exactly as
                                hard as answering wrongly. Bounded above by
                                error_rate_counting_abstention_as_wrong.
  aurc_excluding_abstentions -- over `risk_excluding_abstentions`; abstentions
                                are removed from numerator and denominator, so
                                this is the risk of the answers actually given,
                                and it is bounded by
                                `operating_point.risk`. Read this one when the
                                claim under test is that abstaining on
                                uncovered questions is correct behaviour; it is
                                also the right headline for any arm whose
                                abstained set coincides with a confidence tie
                                group (see `abstention.
                                coincides_with_confidence_tie_group`), because
                                there the drop in `aurc` is largely mechanical.
                                SUPPRESSED under --correctness abstain-ok with
                                --abstention honest, where it is 1.0 by
                                construction.
  aurc_mean_of_tie_groups    -- unweighted mean over tie groups, which weights
                                a 2-question group the same as a 34-question
                                one. NOT comparable across arms with different
                                tie-group counts. Kept only because some papers
                                mean this by AURC.

TIES ARE NOT BROKEN ARBITRARILY. Many questions share a confidence value (on
the PcQA GDgpt run, `kg_coverage_ratio = 0.0` covers 52 of the 99 raw rows and
34 of the 66 rows that gene-hit can score). Accepting "half of the zeros" is
not an operating point the system can reach, so curve points are emitted only
at tie-group boundaries and the group sizes are reported. Confidences are
grouped on a value rounded to CONF_ROUNDING decimal places, recorded in the
output as `confidence_rounding`, so a producer that computes the ratio in
floating point cannot split one conceptual group into several.

DEGENERATE CONFIDENCE. A confidence field that is absent, or present but
CONSTANT across every scored row, carries no ranking information: the curve is
a single point and an "area" over a zero-wide span is just that point's value.
Both cases set `confidence_field_warning` and force `aurc` (and the other two
areas) to None rather than printing a number that invites a cross-arm
comparison. The GPT-4o PcQA arm is the constant case: all 100 rows carry 0.0.

ABSTENTION. `--abstention honest` marks a question abstained when its
final_answer contains an explicit insufficient-evidence statement, using the
SAME patterns as evaluation/compute_system_metrics.py (imported, not copied).
The system's own operating point is then coverage = 1 - abstention_rate, and
`operating_point` reports the risk there over the answers actually given.

CORRECTNESS. Chosen with --correctness:
  gene-hit  : loose text match -- correct if any gold gene or gold drug string
              occurs in final_answer. Requires --gold. Questions whose gold has
              no genes AND no drugs are unscorable this way and are skipped,
              not counted wrong.
              This rule INTENTIONALLY DIFFERS from
              compute_system_metrics.loose_accuracy, which reads
              `gold_actionable_genes` -- a field absent from every gold file any
              reported experiment uses, present only in mtb_testset_dev_5.jsonl
              and track_b_mini_v1.jsonl. Reading `gold_genes` instead changes
              the measurement: on adapt15_full_ext x indep38 gold the existing
              function returns 0/15 and this rule returns 3/15. The difference
              is a bug in the existing script, tracked as its own item in
              FINDINGS, not an equivalence to rely on.
  abstain-ok: correct iff the system abstained. This is the right rule for the
              8-question low-coverage set, whose gold is EMPTY BY DESIGN (every
              row is a KG-absent disease, so "insufficient KG evidence" is the
              only correct answer and any confident answer is a hallucination).
              gene-hit would skip all 8 of those questions. NOTE: combined with
              --abstention honest this makes correct == abstained, so fields
              over the answered subset are 1.0 by construction and are
              suppressed; read abstention_rate instead. With --abstention none
              nothing is marked abstained, the identity does not hold, and
              nothing is suppressed.
  judge     : --judge <path> --judge-arm {system_a,system_b}; correct if that
              arm's `total` >= --judge-threshold.
  field     : correct if the boolean prediction field --correctness-field is true.

SMALL N. Any set with N < 30 gets `small_n_caveat` set in the output; an AURC
over 8 questions is an anecdote, not an estimate, and the field says so. The
answer-length-bias diagnostic needs at least LENGTH_BIAS_MIN_SUBGROUP answers
on each side before it will raise a warning, so a one-answer subgroup is
reported as `underpowered` instead of being presented as a finding.

NOTHING SCORABLE. If no row carries a correctness label, the result is a valid
report with `n_scored: 0` and `no_scorable_rows_reason` explaining which rule
skipped everything -- not a crash. `--correctness gene-hit` on the
low-coverage set is exactly that case and used to raise KeyError.

Usage
-----
  python evaluation/metrics_abstention_ext.py \
      --pred evaluation/results/pcqa100_gdgpt_raw.jsonl \
      --gold evaluation/external_benchmarks/pcqa_100.jsonl \
      --correctness gene-hit \
      [--out evaluation/results/metrics_ext_abstention_<tag>.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compute_system_metrics import HONEST_RE  # noqa: E402  (shared patterns)

SMALL_N = 30

# Answers at or above this length are "long" for the length-bias diagnostic.
LENGTH_BIAS_SPLIT = 500

# The length-bias warning needs this many answers on BOTH sides of the split
# before it fires. Without it the warning triggers off a single short answer,
# which is what happened on the GPT-4o PcQA arm (n_short = 1).
LENGTH_BIAS_MIN_SUBGROUP = 10

# Confidences are grouped into tie groups on a value rounded to this many
# decimal places, so a producer computing the ratio in floating point cannot
# split one conceptual operating point into several.
CONF_ROUNDING = 6


def _load_jsonl(path: Path) -> List[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _answer_text(row: dict) -> str:
    return str(row.get("final_answer") or row.get("answer_text") or "")


def _gold_strings(gold: dict) -> List[str]:
    out = []
    for g in gold.get("gold_genes") or []:
        s = str(g).strip()
        if s:
            out.append(s)
    for d in gold.get("gold_drugs") or []:
        name = d.get("name") if isinstance(d, dict) else d
        s = str(name or "").strip()
        if s:
            out.append(s)
    return out


def _correct_gene_hit(pred: dict, gold: Optional[dict]) -> Optional[bool]:
    if gold is None:
        return None
    needles = _gold_strings(gold)
    if not needles:
        return None  # nothing to be right or wrong about
    hay = _answer_text(pred).lower()
    return any(n.lower() in hay for n in needles)


def _correct_judge(pid: str, judge: dict, arm: str, threshold: float) -> Optional[bool]:
    for q in judge.get("per_question") or []:
        if str(q.get("id")) == pid:
            block = q.get(arm) or {}
            total = block.get("total")
            if total is None:
                return None
            return float(total) >= threshold
    return None


def _risk_coverage(items: List[dict]) -> List[dict]:
    """Curve over tie-groups of confidence, descending.

    Two risks are reported at every point, because they answer different
    questions and the choice changes the conclusion:

      risk                      -- an abstention counts as WRONG, which is what
                                   the module docstring promises. This asks "if
                                   we were forced to accept this prefix, how
                                   often would we be wrong?", so declining to
                                   answer is penalised the same as answering
                                   wrongly. The abstained flag overrides the
                                   correctness label here: without that
                                   override, a correctness rule that scores
                                   abstentions correct (the LLM judge does, and
                                   gene-hit does for 5 of 34 GDgpt abstentions
                                   whose insufficient-evidence text happens to
                                   contain a gold gene string) makes risk FALL
                                   as coverage rises.
      risk_excluding_abstentions -- abstentions are removed from BOTH the
                                   numerator and the denominator, so the risk
                                   is over the answers actually given. This is
                                   the number to read when the point of the
                                   system is that abstaining is the right
                                   behaviour on uncovered questions. It is None
                                   for a prefix where everything was abstained.

    Each item is annotated in place with `counted_correct_in_risk`, so the
    override is auditable per question rather than implicit.
    """
    ordered = sorted(items, key=lambda x: -x["conf_key"])
    n = len(ordered)
    curve: List[dict] = []
    i = 0
    wrong = 0
    answered = 0
    answered_wrong = 0
    while i < n:
        conf_key = ordered[i]["conf_key"]
        j = i
        while j < n and ordered[j]["conf_key"] == conf_key:
            it = ordered[j]
            # An abstention is wrong for `risk` regardless of the correctness
            # rule's verdict on it. This is the documented definition.
            counted_correct = it["correct"] and not it["abstained"]
            it["counted_correct_in_risk"] = counted_correct
            if not counted_correct:
                wrong += 1
            if not it["abstained"]:
                answered += 1
                if not it["correct"]:
                    answered_wrong += 1
            j += 1
        accepted = j
        curve.append({
            "threshold_conf": conf_key,
            "n_accepted": accepted,
            "coverage": accepted / n,
            "risk": wrong / accepted,
            "n_answered": answered,
            "risk_excluding_abstentions": (answered_wrong / answered) if answered else None,
            "group_size": j - i,
        })
        i = j
    return curve


def _area(curve: List[dict], key: str):
    """Coverage-weighted mean of curve[key] over the region where it is DEFINED.

    Returns (value, coverage_span_used, coverage_start).

    Points where the key is None are not merely skipped: integrating from
    coverage 0 by back-extrapolating the first defined value would credit the
    undefined region with that value and divide by the full span. On a
    4-item case that understated the result by 2x, and the bias grew the more
    of the top prefix was abstained, so abstaining more improved the score.
    The integral therefore starts at the FIRST defined coverage and is divided
    by the span it actually covers, and that span is reported so a reader can
    see how much of the curve the number speaks for.
    """
    pts = [(p["coverage"], p[key]) for p in curve if p.get(key) is not None]
    if not pts:
        return None, 0.0, None
    if len(pts) == 1:
        return pts[0][1], 0.0, pts[0][0]
    area = 0.0
    for k in range(1, len(pts)):
        x0, y0 = pts[k - 1]
        x1, y1 = pts[k]
        area += (x1 - x0) * (y1 + y0) / 2.0
    span = pts[-1][0] - pts[0][0]
    return (area / span if span else pts[-1][1]), span, pts[0][0]


#: Every key _aurc returns, so the empty-curve branch cannot omit one. compute()
#: reads these unconditionally; a missing key used to raise KeyError on any input
#: with nothing scorable.
AURC_KEYS = (
    "aurc",
    "aurc_coverage_span",
    "aurc_excluding_abstentions",
    "aurc_excluding_abstentions_coverage_span",
    "aurc_excluding_abstentions_coverage_start",
    "aurc_mean_of_tie_groups",
)


def _aurc(curve: List[dict]) -> Dict[str, Optional[float]]:
    if not curve:
        return {k: None for k in AURC_KEYS}
    a, a_span, _ = _area(curve, "risk")
    b, b_span, b_start = _area(curve, "risk_excluding_abstentions")
    return {
        "aurc": a,
        # The integral runs from the LOWEST ACHIEVABLE coverage to 1.0, not from
        # coverage 0: with tie groups, coverages below the first group are not
        # operating points this system can reach, and assuming a risk for them
        # would be inventing data.
        "aurc_coverage_span": a_span,
        "aurc_excluding_abstentions": b,
        "aurc_excluding_abstentions_coverage_span": b_span,
        "aurc_excluding_abstentions_coverage_start": b_start,
        # Unweighted mean over TIE GROUPS, not over questions: a 12-item group
        # and a 34-item group count equally, and an arm with one tie group
        # collapses to its overall error rate. Kept because some papers mean
        # this by AURC, but it is NOT comparable across arms with different
        # numbers of tie groups. Prefer `aurc`.
        "aurc_mean_of_tie_groups": mean(p["risk"] for p in curve),
    }


def compute(pred_rows, gold_by_id, judge, args) -> dict:
    items: List[dict] = []
    skipped: List[str] = []
    n_abstained = 0
    n_missing_conf = 0

    for p in pred_rows:
        pid = str(p.get("id"))
        abstained_now = bool(HONEST_RE.search(_answer_text(p)))
        if args.correctness == "gene-hit":
            ok = _correct_gene_hit(p, gold_by_id.get(pid))
        elif args.correctness == "abstain-ok":
            ok = abstained_now
        elif args.correctness == "judge":
            ok = _correct_judge(pid, judge or {}, args.judge_arm, args.judge_threshold)
        else:
            raw = p.get(args.correctness_field)
            ok = None if raw is None else bool(raw)
        if ok is None:
            skipped.append(pid)
            continue

        raw_conf = p.get("kg_coverage_ratio")
        if raw_conf is None:
            # Treating a missing confidence as 0.0 would silently produce a
            # degenerate single-point curve if the field were ever renamed.
            n_missing_conf += 1
        conf = 0.0 if raw_conf is None else float(raw_conf)
        abstained = abstained_now if args.abstention == "honest" else False
        if abstained:
            n_abstained += 1

        items.append({"id": pid, "conf": conf,
                      "conf_key": round(conf, CONF_ROUNDING),
                      "correct": bool(ok), "abstained": abstained,
                      "answer_chars": len(_answer_text(p)),
                      "coverage_level": p.get("kg_coverage_level")})

    n = len(items)
    if n == 0:
        # Nothing carried a correctness label. Report that, with the reason, as a
        # valid result; crashing here told the user nothing about their input.
        reason = {
            "gene-hit": "every gold row has empty gold_genes AND empty gold_drugs, so "
                        "the loose text rule has nothing to match. Try "
                        "--correctness abstain-ok on a set whose gold is empty by "
                        "design, or --correctness judge with a judge file.",
            "abstain-ok": "no prediction row produced an answer to inspect.",
            "judge": "no prediction id appears in the judge file with a numeric total "
                     "for the selected --judge-arm.",
            "field": "no prediction row carries the field %r." % args.correctness_field,
        }.get(args.correctness, "no row carried a correctness label.")
        return {
            "n_scored": 0,
            "n_skipped_no_correctness_label": len(skipped),
            "skipped_ids": skipped,
            "correctness_source": args.correctness,
            "no_scorable_rows_reason": (
                "All %d prediction rows were skipped: %s No curve, risk or AURC can be "
                "computed and every metric below is null." % (len(skipped), reason)
            ),
            "confidence_field": "kg_coverage_ratio",
            "confidence_rounding": CONF_ROUNDING,
            "distinct_confidence_values": [],
            "n_confidence_tie_groups": 0,
            "n_rows_missing_confidence_field": n_missing_conf,
            "confidence_field_warning": None,
            "overall_error_rate": None,
            "error_rate_counting_abstention_as_wrong": None,
            "aurc_bound_ok": None,
            "abstention": {"mode": args.abstention, "n_abstained": 0,
                           "abstention_rate": None,
                           "coincides_with_confidence_tie_group": None},
            "operating_point": {"coverage": None, "risk": None,
                                "note": "no scorable rows"},
            "correctness_length_bias": None,
            "risk_coverage_curve": [],
            "small_n_caveat": None,
            "per_question": [],
            **{k: None for k in AURC_KEYS},
            "tautology_warning": None,
        }

    curve = _risk_coverage(items)
    areas = _aurc(curve)

    answered = [x for x in items if not x["abstained"]]
    op_coverage = (len(answered) / n) if n else None
    op_risk = (
        sum(1 for x in answered if not x["correct"]) / len(answered) if answered else None
    )
    # Under abstain-ok, correct == abstained, so the answered set is exactly the
    # incorrect set and op_risk is tautologically 1.0. That identity only holds
    # when something can actually be marked abstained: with --abstention none
    # nothing is, and these fields are informative, so do not blank them.
    op_tautological = args.correctness == "abstain-ok" and args.abstention != "none"

    conf_values = sorted({x["conf_key"] for x in items}, reverse=True)

    # A confidence field that is present but CONSTANT ranks nothing: one tie
    # group, a single-point "curve", and an area over a zero-wide span that is
    # just that point's value. Printing it as `aurc` invites exactly the
    # cross-arm comparison it cannot support, so suppress the areas and warn
    # with the same prominence as the missing-field case.
    degenerate_conf = len(conf_values) < 2
    conf_warning = None
    if n_missing_conf:
        conf_warning = (
            "%d of %d scored rows had no kg_coverage_ratio and were treated as 0.0; "
            "the curve below is correspondingly degenerate." % (n_missing_conf, n)
        )
    if degenerate_conf:
        detail = (
            "kg_coverage_ratio is CONSTANT at %s across all %d scored rows, so it "
            "carries no ranking information: the curve is a single point and the "
            "coverage span is 0. aurc, aurc_excluding_abstentions and "
            "aurc_mean_of_tie_groups are reported as null rather than as a number "
            "that could be compared against an arm which does have a confidence "
            "signal. Read overall_error_rate instead."
            % (conf_values[0] if conf_values else "n/a", n)
        )
        conf_warning = (conf_warning + " " + detail) if conf_warning else detail

    # Does the abstained set coincide with one or more whole confidence tie
    # groups? If so the AURC gain is largely circular (see the abstention block
    # in the result). Compared as id sets, not counts.
    abstained_ids = {x["id"] for x in items if x["abstained"]}
    abstained_conf_values = sorted({x["conf_key"] for x in items if x["abstained"]})
    ids_at_those_confs = {x["id"] for x in items if x["conf_key"] in abstained_conf_values}
    abstained_is_tie_group = bool(abstained_ids) and abstained_ids == ids_at_those_confs

    # A loose substring correctness rule rewards verbosity: a longer answer has
    # more chances to contain a gold string. If accuracy on long answers is far
    # above accuracy on short ones, the rule is partly measuring length, and
    # cross-arm risk comparisons are confounded whenever the arms differ in
    # answer length. Reported from the data so the caveat cannot be forgotten.
    short = [x for x in items if x["answer_chars"] < LENGTH_BIAS_SPLIT]
    long_ = [x for x in items if x["answer_chars"] >= LENGTH_BIAS_SPLIT]
    acc_short = (sum(1 for x in short if x["correct"]) / len(short)) if short else None
    acc_long = (sum(1 for x in long_ if x["correct"]) / len(long_)) if long_ else None
    hazard = {
        "split_chars": LENGTH_BIAS_SPLIT,
        "n_short": len(short),
        "n_long": len(long_),
        "accuracy_short_answers": acc_short,
        "accuracy_long_answers": acc_long,
        "accuracy_gap_long_minus_short": (
            acc_long - acc_short if (acc_long is not None and acc_short is not None) else None
        ),
        "min_subgroup_required": LENGTH_BIAS_MIN_SUBGROUP,
        "underpowered": min(len(short), len(long_)) < LENGTH_BIAS_MIN_SUBGROUP,
        "warning": None,
    }
    gap = hazard["accuracy_gap_long_minus_short"]
    if hazard["underpowered"]:
        # A gap measured off one or two answers is not evidence. Say that
        # instead of raising a finding the sample cannot support.
        hazard["note"] = (
            "NOT ASSESSED: the smaller subgroup has %d answer(s), below the %d required. "
            "The gap of %s is reported for completeness only and must not be quoted as a "
            "length confound for this arm."
            % (min(len(short), len(long_)), LENGTH_BIAS_MIN_SUBGROUP,
               "n/a" if gap is None else round(gap, 4))
        )
    elif gap is not None and gap > 0.5:
        hazard["warning"] = (
            "Correctness tracks ANSWER LENGTH more than content under this rule "
            "(long-answer accuracy %.4f over n=%d exceeds short-answer accuracy %.4f "
            "over n=%d by %.4f). Risk and AURC remain valid WITHIN this arm as a "
            "ranking of its own confidence score, but do NOT compare absolute risk "
            "across arms whose answer lengths differ."
            % (acc_long, len(long_), acc_short, len(short), gap)
        )

    return {
        "n_scored": n,
        "n_skipped_no_correctness_label": len(skipped),
        "skipped_ids": skipped,
        "correctness_source": args.correctness,
        "confidence_field": "kg_coverage_ratio",
        "distinct_confidence_values": conf_values,
        "n_confidence_tie_groups": len(conf_values),
        "confidence_rounding": CONF_ROUNDING,
        "n_rows_missing_confidence_field": n_missing_conf,
        "confidence_is_constant": degenerate_conf,
        "confidence_field_warning": conf_warning,
        "overall_error_rate": (
            sum(1 for x in items if not x["correct"]) / n if n else None
        ),
        # risk counts abstentions as wrong, so THIS is the no-information
        # baseline aurc is bounded by, not overall_error_rate above. It equals
        # risk at coverage 1.0 by construction.
        "error_rate_counting_abstention_as_wrong": (
            sum(1 for x in items if not (x["correct"] and not x["abstained"])) / n
        ),
        "aurc_bound_ok": (
            None if (degenerate_conf or areas["aurc"] is None) else
            areas["aurc"] <= (
                sum(1 for x in items if not (x["correct"] and not x["abstained"])) / n
            ) + 1e-12
        ),
        "aurc": None if degenerate_conf else areas["aurc"],
        "aurc_coverage_span": None if degenerate_conf else areas["aurc_coverage_span"],
        # Every risk_excluding_abstentions point is 1.0 by construction under
        # abstain-ok WITH --abstention honest (correct == abstained, so every
        # answered item is wrong), so the area carries no information and is
        # suppressed rather than printed as a score somebody might quote.
        "aurc_excluding_abstentions": (
            None if (op_tautological or degenerate_conf)
            else areas["aurc_excluding_abstentions"]
        ),
        "aurc_excluding_abstentions_coverage_span": (
            None if (op_tautological or degenerate_conf)
            else areas["aurc_excluding_abstentions_coverage_span"]
        ),
        "aurc_excluding_abstentions_coverage_start": (
            None if (op_tautological or degenerate_conf)
            else areas["aurc_excluding_abstentions_coverage_start"]
        ),
        "aurc_mean_of_tie_groups": (
            None if degenerate_conf else areas["aurc_mean_of_tie_groups"]
        ),
        "tautology_warning": (
            "--correctness abstain-ok with --abstention honest defines "
            "correct == abstained. Fields over the ANSWERED subset are therefore 1.0 "
            "by construction and are suppressed (operating_point.risk, "
            "aurc_excluding_abstentions). overall_error_rate and aurc are informative "
            "but are just restatements of the abstention rate: read "
            "abstention.abstention_rate as the result."
        ) if op_tautological else None,
        "abstention": {
            "mode": args.abstention,
            "n_abstained": n_abstained,
            "abstention_rate": (n_abstained / n) if n else None,
            # When the abstained set IS a confidence tie group, the final curve
            # step moves risk by near-arithmetic necessity: the confidence
            # score, the abstention decision and (under gene-hit) the
            # correctness label on those rows are the same variable. Any drop
            # of aurc below the error rate is then largely mechanical, and
            # aurc_excluding_abstentions is the honest headline.
            "coincides_with_confidence_tie_group": abstained_is_tie_group,
            "coincidence_note": (
                "The %d abstained rows are exactly the rows at confidence %s. The fall "
                "in aurc relative to error_rate_counting_abstention_as_wrong is "
                "therefore largely CIRCULAR and must not be quoted as the size of the "
                "abstention signal. Quote aurc_excluding_abstentions, and the interior "
                "of the curve, instead." % (n_abstained, abstained_conf_values)
            ) if abstained_is_tie_group else None,
        },
        "operating_point": {
            "coverage": op_coverage,
            "risk": None if op_tautological else op_risk,
            "note": (
                "suppressed: under --correctness abstain-ok, correct == abstained, "
                "so the answered set is exactly the incorrect set and this risk "
                "would be 1.0 by construction, carrying no information. Read "
                "abstention.abstention_rate instead."
                if op_tautological else
                "coverage 1.0 means the arm abstained on nothing, so this risk is "
                "the overall error rate. It does NOT imply a single-point curve: "
                "the curve has one point per confidence tie group (%d here) "
                "regardless of abstention." % len(conf_values)
            ),
        },
        "correctness_length_bias": hazard,
        "risk_coverage_curve": curve,
        "small_n_caveat": (
            "N=%d < %d: AURC is a descriptive summary of this run, not an estimate "
            "with a usable confidence interval. Do not report it as a headline "
            "number." % (n, SMALL_N)
        ) if n < SMALL_N else None,
        "per_question": items,
    }


def json_safe(obj):
    """Replace NaN/Infinity with None so the output is valid RFC 8259 JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Risk-coverage curve and AURC from kg_coverage_ratio.")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", default=None, help="Required for --correctness gene-hit.")
    ap.add_argument(
        "--correctness",
        choices=["gene-hit", "abstain-ok", "judge", "field"],
        default="gene-hit",
    )
    ap.add_argument("--correctness-field", default="correct")
    ap.add_argument("--judge", default=None)
    ap.add_argument("--judge-arm", choices=["system_a", "system_b"], default="system_a")
    ap.add_argument("--judge-threshold", type=float, default=15.0)
    ap.add_argument("--abstention", choices=["honest", "none"], default="honest")
    ap.add_argument("--out", default=None, help="Optional NEW json file to write.")
    args = ap.parse_args()

    pred_rows = _load_jsonl(Path(args.pred))
    gold_by_id: Dict[str, dict] = {}
    if args.gold:
        gold_by_id = {str(r["id"]): r for r in _load_jsonl(Path(args.gold))}
    if args.correctness == "gene-hit" and not gold_by_id:
        raise SystemExit("--correctness gene-hit requires --gold")
    judge = json.loads(Path(args.judge).read_text(encoding="utf-8")) if args.judge else None
    if args.correctness == "judge" and judge is None:
        raise SystemExit("--correctness judge requires --judge")

    result = compute(pred_rows, gold_by_id, judge, args)
    result["inputs"] = {"pred": args.pred, "gold": args.gold, "judge": args.judge}

    text = json.dumps(json_safe(result), indent=2, ensure_ascii=False, allow_nan=False)
    print(text)
    if args.out:
        out = Path(args.out)
        if out.exists():
            raise SystemExit("refusing to overwrite existing file: %s" % out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
