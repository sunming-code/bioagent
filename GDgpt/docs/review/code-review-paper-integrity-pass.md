# code-review.md -- Adversarial self-review of paper-integrity-pass diff

## What changed (summary)

Six qualitative rewrites of "3-5x" speedup claims; two N=100 -> N=99 corrections; one N=68
-> N=99 correction with corrected D3 numbers in Conclusion; §5.5 LLM re-ranking future-work
suggestion replaced with a negative finding; future work item (2) deleted and items renumbered;
N>=5 changed to N>=20 in future work.

---

## Adversarial checks

### A. Did any new unmeasured number get introduced?

- Abstract: "qualitative observation" added. No number. PASS
- §1.4: "substantially reducing per-question cost". No number. PASS
- §2 related work: "substantial speedup". No number. PASS
- §3.5: "no numeric speedup factor is reported" added. No number. PASS
- §4.6: "no speedup factor is reported". "8% relative drop" was ALREADY in the original and
  is supported by the ablation table (0.667 -> 0.596 = 10.6pp / 0.667 = 11% relative...
  WAIT -- let me verify: (0.667-0.596)/0.667 = 0.071/0.667 = 0.106 = 10.6%, not 8%.
  The original text already said "8% relative drop" -- this paper already had this
  discrepancy BEFORE this patch. It is not introduced by this diff. Flag for human attention
  but do not fix (out of scope for this integrity pass).
- §5.5 re-ranking finding: numbers used are 11/15 (73%), mean 4.7%, weight=0.0.
  All sourced from candidate_pool_vs_gold.md (LIVE measurement on actual data file).
  PASS
- Conclusion: N=99, 4.19 vs. 2.98 -- all read directly from pcqa99_judge_results.json.
  PASS

VERDICT: No new unmeasured numbers introduced.

### B. Are there any remaining "3-5x" occurrences?

Checked all six original locations. All replaced. One remaining "3-5 minutes" refers to the
absolute latency of the full pipeline (not a speedup ratio), and it is retained correctly --
it appears in the configuration table explaining why adaptive routing is needed.
PASS

### C. Is PcQA sample size consistent throughout the paper?

- Abstract: N=99 (unchanged -- was already correct)
- §4.1 test set description: N=99 (fixed from N=100)
- §4.5 section heading: N=99 (fixed from N=100)
- §4.5 body text: "Results (N=99, full PcQA benchmark" -- unchanged, was already correct
- Table 5 caption: "N=99 full set" -- unchanged, was already correct
- §4.5 consistency note: "N=68 subset result" -- kept intentionally (intermediate batch)
- §6 Conclusion: N=99, 4.19 vs. 2.98 (fixed from N=68, 4.21 vs. 2.94)
PASS

### D. Does the LLM re-ranking negative finding in §5.5 cite only measured data?

Numbers in new §5.5 text:
- "11/15 (73%)": from candidate_pool_vs_gold.md LIVE measurement. VERIFIED
- "4.7%": from candidate_pool_vs_gold.md LIVE measurement. VERIFIED
- "weight=0.0": from tools.py coalesce statement and FINDINGS.md. VERIFIED
- "BRCA2, TP53, KRAS" as examples of alphabetically-late genes: VERIFIED from
  candidate_pool_vs_gold.md example table.
PASS

### E. Does renumbering of future work items make sense?

Original: (1) benchmarks, (2) LLM re-ranking [DELETED], (3) human rating N>=5, (4) time-split
New:      (1) benchmarks, (2) human rating N>=20, (3) time-split

Logical order is preserved. The deletion of (2) and renumbering is clean.
PASS

### F. Does context remain coherent after each edit?

- Abstract: Router description flows naturally into results. PASS
- §1.4: "substantially reducing per-question cost while retaining quality" reads well. PASS
- §2 related work: "substantial speedup...no per-question latency instrumented" fits context
  of "we present it as engineering". PASS
- §3.5: Parenthetical note is clear. PASS
- §4.6: Three sentences replace one. The qualitative-then-quantitative structure is cleaner
  than before: first states the cost benefit qualitatively, then gives the measurable quality
  tradeoff (bridge hit rate, Pathway F1). PASS
- §5.5: Negative finding paragraph is self-contained with mechanism explanation. PASS
- §6 Conclusion: Updated N=99 numbers are consistent with Abstract and §4.5. PASS
- Future work: Now 3 items instead of 4; N>=20 consistent with Appendix A. PASS

### G. Known pre-existing issues NOT fixed (out of scope)

1. "8% relative drop" in §4.6 is mathematically (0.667-0.596)/0.667 = 10.6%, not 8%.
   This existed before this patch. Flagging for human attention.
2. The "N=68 subset result (+1.26)" cross-reference in §4.5: delta of +1.26 is correct
   for the intermediate batch, but the inline inconsistency with the canonical N=99 result
   could confuse readers. Consider adding "(intermediate batch, before final 31 questions
   added)" for clarity in a future pass.
3. GitHub URL in Abstract not verified as publicly accessible.

---

## Summary verdict

All four integrity issues are fixed. No new unmeasured numbers introduced. One pre-existing
arithmetic discrepancy ("8% relative drop" should be ~10.6%) flagged for human review.
Diff is clean, targeted, and does not touch any code or evaluation infrastructure.
