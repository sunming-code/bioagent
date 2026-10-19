# Adversarial code review - guard fix and gene ranking

Scope: `git diff origin/grad...HEAD`, the commits unique to
`fix/guard-and-gene-ranking` - `13584e3` (placeholder guard) and `d8fa1be`
(DiseaseToGene bio_degree ranking). Files: `tools.py`, `workflow.py`, three new scripts
under `evaluation/scripts/`, one results jsonl.

Rounds: 1. Review run at high effort against the committed diff, with findings verified
by executing the changed functions against the committed raw result files rather than by
reading alone.

No CRUX code review was cut and AutoSDE was not run. This repo is a personal GitHub
repo, not a Brazil or CRUX package: there is no `Config` or `packageInfo` and the remote
is `github.com:vinoricaye2003-jpg/GDgpt`. Running `cr` or `autosde` here would upload
private academic work to an unrelated internal review system, and the task brief
forbids push, PR and merge in any case. This file is the review record.

## Findings and dispositions

10 findings. 7 fixed, 3 accepted with reasons.

### 1. Guard missed the second placeholder phrase - FIXED (was the most serious)

`PLACEHOLDER_PHRASES` carried only the "Continuing discussion" family, but
`agents.py:501` instructs the reviewer to emit
`"Continuing analysis - further rounds needed."` on DIVERGED. Verified by executing the
new guard over `evaluation/results/pcqa100_gdgpt_raw.jsonl`: **11 of 99 rows were still
classified as substantive** - the exact defect this change exists to fix, surviving in
the other prompt variant. The original check could not see it because it read only the
pre-v2.3 `adapt15_full_raw.jsonl`.

This is the class-of-fix point: fixing the reported string alone would have left step 5
(PcQA N=99) still broken. Fixed by splitting the phrase list into
`PLACEHOLDER_EXACT` (matched whole-string only) and `PLACEHOLDER_PREFIXES` (matched with
a word boundary and a total-length bound), adding the analysis variants, and making the
check read both result files. Now 28 positive and 102 negative cases pass.

### 2. Same defect left in 9 sibling intents - ACCEPTED, reported not fixed

`ORDER BY weight DESC` is a no-op in every single-hop intent, and the undirected-match
duplication halves every intent's effective k. Correct and confirmed. Not fixed because
the approved scope named DiseaseToGene, and changing the others moves the published
pathway, phenotype and drug metrics, which needs its own approval. Every affected line
is enumerated in `CALL_SITES.md` so the class is visible rather than implied.

### 3. Code comment overstated the measured gain - FIXED

The comment cited R@20 0.1000 and 6-question R@20 0.2250, which were pre-correction
numbers from the earlier 2x-counting version of the probe, and it omitted the measured
regression. Corrected to R@20 0.0933 and 0.1833, and the comment now states both costs
explicitly, including that R@5 goes 0.0056 -> 0.0000 on the 9 questions with arbitrary
gold. An inaccurate evidence citation in a comment is how a known regression quietly
disappears.

### 4. DiseaseToPathway can never return a row - ACCEPTED, reported not fixed

Confirmed by this change's own probe: the live KG has 0 Disease-Pathway edges of any
type, yet the intent remains selectable by the planner. A real defect, outside the
approved scope. Recorded in `FINDINGS.md` and `CALL_SITES.md`.

### 5. A single-line fenced answer normalised to empty - FIXED

`_normalise_final_answer` dropped any line beginning with a fence wholesale, so
```` ```BRCA1 loss drives repair deficiency``` ```` collapsed to `""` and was treated as
a placeholder, discarding a real answer. Verified. Fixed with `_strip_fences`, which
removes fence markers and any language tag but keeps content on the same line. Pinned by
the `single-line-fenced` and `fenced-json` negative cases.

### 6. Prefix match had no word boundary - FIXED

`startswith("none")` classified `"Nonetheless, consider olaparib."` as a placeholder.
Verified. Fixed two ways: `none` and `n/a` now match whole-string only, and the prefix
family requires the next character to be non-alphanumeric. Pinned by the
`none-prefix-word` and `legit-none-sentence` negative cases - the latter covers
`"None of the eight candidate genes are clinically actionable."`, a legitimate short
answer the earlier version would have thrown away.

### 7. Provenance dedup was substring-based - FIXED

`acc CONTAINS s` dropped `MONDO` when `MONDO_grouped` was already accumulated, making
the emitted source depend on relationship ordering. Fixed to accumulate a list and test
`src IN acc`, so dedup is by whole element. Spot-checked live:
schizophrenia yields `MONDO_grouped|NCBI` and colorectal cancer `MONDO|NCBI`, both
intact.

### 8. Check hardcoded the HTTP transport - FIXED

Both new scripts called `_http_run` directly, so they crashed on the local
`bolt://localhost:7687` setup the README documents. Fixed with a small helper in each
that asks `kg._use_http()` and falls back to a Bolt session, mirroring what `tools.py`
does internally.

### 9. Ranking check covers only the diseases the change improves - ACCEPTED, by design

Correct observation. The check is deliberately scoped to the 3 diseases whose gold is
Open Targets cross-validated, and it pins that provenance so it fails loudly if the
testset changes. The 9 regressed questions are intentionally not asserted on, because
their gold is a near-arbitrary neighbour sample - colorectal cancer gold holds MIR1273C
and KRTAP10-8 but neither APC nor TP53 - so asserting on them would force the ranking to
fit an arbitrary list. The regression is not hidden: it is measured and reported in
`FINDINGS.md`, in the `tools.py` comment, and in the probe log stratified by provenance.
Reasoning recorded in the check's own header so a later reader cannot mistake it for
laziness.

### 10. Cited evidence files were untracked or gitignored - FIXED

The `tools.py` comment pointed at `logs/gene_ranking_probe.log`, which `*.log` ignores,
and at a then-untracked root `FINDINGS.md`. Fixed by pointing the comment at the
reproducing script, which is committed, and by committing `FINDINGS.md`,
`DECISIONS.md`, `CALL_SITES.md` and this file. Logs stay out of the diff on purpose -
they are run output, captured as evidence rather than versioned.

## Residual risk

- The step-3 N=15 rerun was launched before finding 1 was fixed, so that process is
  running the narrower guard. Its output will be re-checked with the shipped guard on
  completion; if any answer is still a placeholder the run is redone rather than
  reported. Verifying equivalence rather than assuming it.
- The ranking's disease-specificity cost (top-8 overlap 0.577, 24 distinct genes across
  15 lists) is a measured property of the chosen signal, not a defect in the code, and
  is with the human as an open question.
