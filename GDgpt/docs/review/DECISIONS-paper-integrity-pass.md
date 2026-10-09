# DECISIONS.md -- paper-integrity-pass

## Fix 1: Remove "3-5x" speedup/cost claims (6 locations)

**Decision**: Replace all six occurrences of "3-5x" (or "3-5 times") with qualitative language.
Add explicit note that per-question latency was not instrumented.

**Locations changed**:
- Abstract (line ~11): "reduces per-question LLM cost by 3-5x" -> qualitative
- §1.4 contributions (line ~40): "reducing cost by 3-5x" -> qualitative
- §2 related work (line ~54): "3-5x speedup on simple queries" -> qualitative
- §3.5 (line ~102): "reduces average cost by 3-5x on simple factual queries" -> qualitative + note
- §4.6 result sentence (line ~216): "reduces average latency by 3-5x on simple queries" -> qualitative + note
- §6 Conclusion (line ~320): "adaptive complexity routing (3-5x speedup, quality retention)" -> qualitative

**Rationale**: No timing fields (latency, elapsed_sec, wall_time, duration_sec) exist in any of
the 69 JSONL result files under evaluation/results/. Verified by exhaustive field inspection of
all JSONL files. The approximate latency values in Table 4 (37 sec, 2 min, 5 min) are qualitative
estimates from the system configuration (roles/rounds count), not measured wall-clock times.
Keeping an unmeasured "3-5x" number in a results section or conclusion would be fabrication.

**Why rewrite rather than measure**: Adding per-question timing requires instrumenting the
evaluation pipeline and re-running the full comparison -- a new experiment. That is out of scope
for this integrity pass. The qualitative claim is honest and still communicates the engineering
motivation. When timing is properly measured, the numeric factor can be restored.

**No new numbers introduced**: The rewritten text contains no numeric speedup factor.

---

## Fix 2: Unify PcQA sample size to N=99

**Decision**: Change all "N=100" occurrences to N=99. Change Conclusion's "N=68: 4.21 vs. 2.94"
to "N=99: 4.19 vs. 2.98".

**Locations changed**:
- §4.1 test set description: "PcQA external benchmark (N=100)" -> N=99
- §4.5 section heading: "PcQA Benchmark (N=100)" -> N=99
- §6 Conclusion: "external PcQA N=68: 4.21 vs. 2.94" -> "external PcQA N=99: 4.19 vs. 2.98"

**Verification**: Read pcqa99_judge_results.json directly.
  - n field: 99
  - D3 summary: system_a_mean = 4.192 (rounds to 4.19), system_b_mean = 2.98
  - pcqa100_gdgpt_raw.jsonl actual row count: 99 (file is misnamed; only 99 were evaluated)
  The N=99 and D3=4.19 vs. 2.98 are the authoritative measurements.

**N=68 note**: N=68 (= 49+19) was an intermediate result before the final batch of 31 questions
was evaluated. It remains valid as a consistency cross-reference in §4.5 body text and is kept
there unchanged. Its use as the canonical number in the Conclusion was incorrect; fixed.

**No new numbers introduced**: The corrected numbers (N=99, 4.19, 2.98) are read directly from
pcqa99_judge_results.json with no arithmetic or estimation.

---

## Fix 3: Remove "LLM re-ranking" from future work -- proven ineffective

> **Partly superseded 2026-10-08** (branch fix/paper-attribution). Live KG verification found
> 290 of 300 gold genes ARE ASSOCIATED_WITH neighbours of their disease, so "re-ranking is
> structurally ineffective" is too strong. What holds: re-ranking the TRUNCATED top-k pool
> cannot help (the 11/15 and 4.7% figures below stand). What does not hold: the conclusion that
> ranking is hopeless -- ranking the FULL neighbour set is untested and is now future work.
> The paper drafts carry the corrected wording; see docs/paper_draft_en.md 5.5.

**Decision**: Delete future work item (2) "LLM re-ranking of retrieved candidates to improve gene
recall". Replace the suggestion in §5.5 Case Study 3 with a negative finding grounded in
measured data. Renumber remaining future work items.

**Evidence for the negative finding** (from evaluation/results/adapt15_full_raw.jsonl cross-
referenced against evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl,
computed in the prior research-boost-retrieval investigation):
- 11/15 (73%) disease-centered questions: 0% overlap between KG candidate pool and gold genes
- Mean pool coverage across all 15 questions: 4.7%
- Root cause: PrimeKG edge weights are uniformly 0.0 (confirmed in tools.py via
  coalesce(r.weight, 0.0) + ORDER BY weight DESC, gene ASC), so retrieval degrades to
  alphabetical gene ordering; BRCA2, TP53, KRAS fall outside the returned top-k
- Re-ranking cannot produce gold genes absent from the candidate pool

**Why this matters**: Suggesting an approach that has been shown to be structurally ineffective
as "future work" is misleading. Reporting it as a negative finding is scientifically stronger:
it documents why the obvious remedy fails, which is useful for readers and reviewers.

**New text in §5.5**: States the negative finding with numbers, explains the mechanism,
and correctly scopes the actual fix (re-curating KG weights, not post-retrieval ranking).
All numbers cited in the new text are sourced from the measured investigation.

---

## Fix 4: Unify N>=5 -> N>=20 in future work item on human expert rating

**Decision**: Change "Likert, N>=5, kappa >=0.6" to "Likert, N>=20, kappa >=0.6" in the
future work paragraph.

**Rationale**: Appendix A already specifies "N >= 20 questions" as the recommended protocol
for a kappa study. N>=5 is too small to produce stable Cohen's kappa estimates and was
inconsistent with the project's own Appendix. N=20 is the correct threshold from the
established rubric in Appendix A.

---

## Open questions (for human review)

1. The abstract still shows the GitHub URL (https://github.com/vinoricaye2003-jpg/GDgpt).
   This has not been verified to be public/correct -- it is outside the scope of this pass.

2. The "N=68 subset result (+1.26)" cross-reference in §4.5 body text (around line 202) is
   kept as a historical consistency note. Its delta (+1.26) is mathematically correct per the
   intermediate batch files. If the intermediate batches should not be cited, that is a
   separate editorial decision.
