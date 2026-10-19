#!/usr/bin/env bash
# Guard against three refuted claims about GDgpt's low gene recall.
#
# 1. "the gold genes are absent from the knowledge source / this is an inherent
#    PrimeKG property / re-ranking is structurally ineffective".
#    Refuted 2026-10-08 on the live KG: 290 of 300 gold genes ARE ASSOCIATED_WITH
#    neighbours of their disease. The candidate pool is truncated by unranked
#    top-k retrieval, not by the knowledge source.
# 2. "Recall@5 is capped at 0.25" - the reported 0.047 is an UNBOUNDED recall
#    (evaluation/compute_paired_stats.py: len(gold & pred) / len(gold), no rank
#    cut), so its ceiling is 1.0. No rank-cut value is reported yet.
# 3. "Table 3 should be read as a lower bound because of the placeholder answers"
#    - the judged run behind Table 3 (v23_9q_raw.jsonl) has 0 placeholder
#    answers; the 6/15 placeholder defect belongs to the adaptive N=15 run.
#
# Exit codes (conventional: non-zero means the guard failed):
#   0 = GREEN, no refuted claim found
#   1 = RED, at least one refuted claim present
#   2 = the check could not run (missing file, bad working directory)

set -u

cd "$(dirname "$0")/.." || { echo "ERROR: cannot reach the repository root"; exit 2; }

FILES=(
  docs/paper_draft_en.md
  docs/paper_draft_zh.md
  README.md
  .claude/skills/research-method/SKILL.md
)

for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: scanned file is missing: $f (renamed? update this script)"
    exit 2
  fi
done

# Each pattern is an extended regex. Whitespace between CJK words is optional so
# that reformatting cannot smuggle a claim past the guard.
#
# Wrong attribution wording. A line that NEGATES one of these is not a finding,
# because the corrected text has to be able to say "not an inherent property of
# PrimeKG" / "不是 PrimeKG 数据的固有属性".
ATTRIBUTION=(
  'limitation of the knowledge source'
  'an inherent data constraint'
  'absent from the candidate pool'
  'structurally ineffective'
  'structurally impossible'
  'KG data constraint, not an architectural flaw'
  'not a failure of GDgpt.s architecture'
  'over-connected KG limitation'
  '固有属性'
  '非设计缺陷'
  '非系统设计缺陷'
)
NEGATED='(不是|不属于|not an inherent|no longer|refuted)'

# Wrong numbers and wrong run attribution. These are never acceptable, not even
# in a negated sentence, so they are matched without the negation filter.
#
# The first pattern is the metric mislabel: 0.047 printed as a Recall@5. Writing
# "Recall@5 = 0.010" is correct and must NOT trip, so the pattern only fires when
# 0.047 sits within a few non-alphanumeric characters of the Recall@5 label
# (table cell, "=", ":", a CJK copula) in either order.
STRICT=(
  'Recall@5[^A-Za-z0-9]{0,8}0\.047'
  '0\.047[^A-Za-z0-9]{0,8}(的[[:space:]]*)?Recall@5'
  'returning five genes'
  'lower bound on GDgpt'
)

found=0
for f in "${FILES[@]}"; do
  for p in "${ATTRIBUTION[@]}"; do
    hits=$(command grep -nE "$p" "$f" | command grep -vE "$NEGATED") || true
    if [ -n "$hits" ]; then
      printf 'FINDING %s :: %s\n%s\n' "$f" "$p" "$hits"
      found=1
    fi
  done
  for p in "${STRICT[@]}"; do
    hits=$(command grep -nE "$p" "$f") || true
    if [ -n "$hits" ]; then
      printf 'FINDING %s :: %s\n%s\n' "$f" "$p" "$hits"
      found=1
    fi
  done
done

if [ "$found" -eq 1 ]; then
  echo "RESULT: RED - at least one refuted claim is still present"
  exit 1
fi
echo "RESULT: GREEN - no refuted claim found in ${#FILES[@]} scanned files"
exit 0
