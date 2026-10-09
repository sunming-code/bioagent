# DECISIONS - guard fix and gene ranking

## Outcome

Placeholder guard fixed and verified: 6 of 15 answers were bare placeholders; a former
placeholder now returns 195 words instead of 3. Gene ranking fixed, lifting
retrieval-side Recall@5 from 0.0033 to 0.0400 (0.0000 to 0.1000 where the answer key is
trustworthy). Two honest caveats: the winning signal is a popularity prior returning
similar genes across diseases, and on 9 of 15 questions the answer key is too arbitrary
to score against. End-to-end reruns still running at ~14 min per question.

## Decisions to evaluate

- D1 Bound the placeholder match to at most 3 leftover words. Why: an unbounded prefix
  match would discard a real synthesis that merely opens with "Continuing discussion".
  If overruled: drop the bound and accept that risk.
- D2 Rank DiseaseToGene by biological degree (distinct disease + distinct pathway
  neighbours). Why: best measured Recall@5; plain total degree ranks drug-metabolism
  hubs, since 1942 of CYP3A4's 1970 edges go to drugs. If overruled: use assoc_degree
  with pathway cohesion, trading Recall@5 0.1000 for 0.0917 and Recall@20 0.1833 for
  0.2417, with better disease specificity.
- D3 Count distinct neighbours, not relationships, in that score. Why: the source data
  stores both edge directions, so relationship counts double. Supersedes: counting
  relationships, because the shipped query then did not match the probe that chose the
  signal.
- D4 Keep k at 8. Why: de-duplicating already doubled the distinct genes at the same k.
  If overruled: a larger k raises recall mechanically and muddies the baseline
  comparison.
- D5 Leave the weight output column a passthrough rather than writing the new score
  into it. Why: the column would otherwise mean different things per intent. If
  overruled: expose the score and audit every consumer.
- D6 Report the gene score overall AND split by answer-key provenance, changing no
  denominator, and state plainly why the 9 weak answer keys cannot reward better
  retrieval. Why: the overall number understates the fix, but dropping 9 questions looks
  like discarding data. Confirmed by the human, who also ruled out recurating the 9.
- D7 Run the reruns at max_rounds 6. Why: the paper says 3, the script default and
  project convention say 6, and the artefacts record neither. If overruled: rerun at 3,
  which changes every number.

## Open questions

- ~~How to report the gene score when 9 of 15 answer keys are unreliable?~~ Answered by
  the human: report both, drop nothing, do not recurate. Reflected in FINDINGS.md.
- Is a popularity-prior ranking acceptable for a system selling disease specificity?
  Top-8 overlap across diseases is 0.577, 24 distinct genes across 15 lists. Default:
  ship it and report the cost.
- Was the original N=15 at max_rounds 3 or 6? Unrecorded. Default: 6.
- Three sibling defects are reported, not fixed: seven other intents share the dead
  sort key and the duplicate-halved k, and DiseaseToPathway can never return a row (the
  KG has no Disease-Pathway edges). Default: report only, since fixing them moves other
  published metrics.

## Gate facts

- Publishing: nothing pushed, no PR, no merge, no review published. This is a personal
  GitHub repo, not a Brazil/CRUX package (no Config or packageInfo; remote is github),
  so the CRUX review flow and AutoSDE do not apply - running them would upload private
  academic work to an unrelated internal system. The adversarial review is in
  code-review.md.
- Call sites: no `packages/*` here. Shared modules touched are `tools.py` and
  `workflow.py`; all call sites are enumerated in CALL_SITES.md, including the seven
  sibling intents left unchanged.
- Lanes and verdicts: guard check FAIL exit 1 then PASS exit 0
  (`guard_check_red.log`, `guard_check_green.log`); ranking check FAIL exit 1 then PASS
  exit 0 (`ranking_check_red.log`, `ranking_check_green.log`); 2-question smoke PASS
  exit 0 (`smoke2_guardfix.log`); signal probe PASS exit 0 (`gene_ranking_probe.log`);
  KG schema recon PASS (`kg_schema_recon.log`); the three end-to-end reruns RUNNING.
- Adversarial review rounds: 1.

## Evidence

`FINDINGS.md` number table and diagnosis; `CALL_SITES.md` call sites of both shared
modules; `code-review.md` self-review and dispositions; `kg_schema_recon.log` live KG
shape, weight empty everywhere; `guard_check_red/green.log` and
`ranking_check_red/green.log` the two red-first pairs; `gene_ranking_probe.log` every
candidate signal stratified by answer-key source; `smoke2_guardfix.log` answer length
before and after.

## Residuals

- The three end-to-end reruns and their metric, paired-stats and judge post-processing
  are incomplete; those table rows read PENDING.
- No KG writes or reimport; all KG access read-only. Main checkout untouched. No
  dependency changes: the existing virtualenv supplied libraries only, against this
  worktree's code.
- Backend/evaluation change with no user-visible surface, so no screenshot; verified by
  the red/green and smoke logs.
