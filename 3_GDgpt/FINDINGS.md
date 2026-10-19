# FINDINGS - guard fix and gene ranking

2026-10-08. Worktree `/Users/yeawenqi/hkust/wt-guard-gene`, branch
`fix/guard-and-gene-ranking`, based on `grad` (f3dda3a). `text_model = gpt-4o`,
`max_rounds = 6`, temperature 0.7 gen / 0.0 critic, `--adaptive`, gene-reranker off.
KG: live Aura 08da4c21, read-only over the HTTP Query API (443).

## Outcome

Both fixes work. Guard: placeholders 6 of 15 -> 0, median answer length 26 -> 219 words.
Ranking: uncut Gene Recall 0.0467 -> 0.0900 (p vs GPT-4o 0.068 -> 0.018, now significant),
traceability 0.029 -> 0.060, and on the 6 questions with trustworthy gold uncut recall
more than doubles to 0.2083. Judge total 8.92 -> 13.13 -> 15.89, D3 now beats GPT-4o
(3.80 vs 3.22); GPT-4o still leads overall (~23.1).

Three qualifications, all measured, none smoothed over: Pathway F1 regressed 0.596 ->
0.554, trading a published strength for a published weakness; on 9 of 15 questions the gold
is a near-arbitrary neighbour sample so the gene metric is blind there and the whole gain
comes from the other 6; and the winning signal is a popularity prior returning nearly the
same genes for every disease. Separately, the published Gene Recall@5 of 0.047 is
un-truncated recall, not recall@5.

## Step-by-step table

All baseline numbers are RECOMPUTED this run from `adapt15_full_raw.jsonl` through the
documented pipeline, not copied from the paper, so every column is measured the same way.

| Metric | Baseline | Step 3 (guard) | Step 4 (+ranking) | PcQA N=99 final |
|---|---|---|---|---|
| gene_recall@5 (k=5 truncated) | 0.0100 | 0.0100 | **0.0167** | PENDING |
| gene_recall@20 | 0.0433 | 0.0433 | **0.0600** | PENDING |
| gene_recall (no cutoff) | 0.0467 | 0.0467 | **0.0900** | PENDING |
| gene_recall p vs GPT-4o | - | 0.068 | **0.018** | PENDING |
| gene_f1 | 0.0423 | 0.0423 | **0.0765** | PENDING |
| pathway_f1 | 0.5961 | 0.5813 | *0.5545* | PENDING |
| pathway_precision@5 | 0.600 | 0.520 | *0.373* | PENDING |
| bridge_hit_rate | 1.0 | 1.0 | 1.0 | PENDING |
| coverage | 0.500 | 0.500 | 0.517 | PENDING |
| traceability | 0.029 | 0.029 | **0.060** | PENDING |
| answer length median words | 26 | **219** | **218** | PENDING |
| placeholder answers | 6 of 15 | **0** | **0** | PENDING |
| judge D1 / D2 / D3 / D4 / D5 | 1.74 / 1.67 / 1.15 / 1.96 / 2.41 | 2.20 / 2.20 / 3.00 / 2.74 / 3.00 | **2.91 / 2.87 / 3.80 / 3.31 / 3.00** | PENDING |
| judge total | 8.92 | 13.13 | **15.89** | PENDING |

Bold improved, *italic* regressed. GPT-4o arm (`exp15_gpt4o_raw.jsonl`, reused not rerun):
judge total ~23.1 (D3 3.22), gene_recall 0.0000, pathway_f1 0.0000, bridge_hit 0.0, median
375 words. Paired stats step 4: pathway_f1 p=0.0007, bridge_hit p=0.0007.

### Stratified gene recall - both ways, nothing dropped (human's decision)

| Stratum | n | R@5 base -> s4 | R@20 base -> s4 | R nocut base -> s4 |
|---|---|---|---|---|
| ALL questions | 15 | 0.0100 -> **0.0167** | 0.0433 -> **0.0600** | 0.0467 -> **0.0900** |
| OT cross-validated gold | 6 | 0.0250 -> **0.0417** | 0.1000 -> **0.1417** | 0.1000 -> **0.2083** |
| PrimeKG, no OT match | 9 | 0.0000 -> 0.0000 | 0.0056 -> 0.0056 | 0.0111 -> 0.0111 |

The 9 cannot reward better retrieval: their gold is a near-arbitrary sample of the disease's
neighbours, not a curated gene list. Colorectal cancer gold carries MIR1273C, KRTAP10-8,
LINC00673, TMEM238L but neither APC, KRAS, TP53 nor BRAF, so a ranking surfacing real
drivers scores 0 by construction. End to end those 9 are exactly flat, not worse.
Reproduce: `evaluation/scripts/stratified_gene_recall.py`.

### Retrieval-side signal choice (full neighbour set, not comparable to the rows above)

| Signal | R@5 all15 | R@20 all15 | R@5 OT-6 | R@20 OT-6 |
|---|---|---|---|---|
| alphabetical (before) | 0.0033 | 0.0167 | 0.0000 | 0.0000 |
| **bio_degree (shipped)** | **0.0400** | **0.0933** | **0.1000** | **0.1833** |
| assoc_degree,cohesion | 0.0367 | 0.0967 | 0.0917 | 0.2417 |
| cohesion (disease-specific) | 0.0233 | 0.0733 | 0.0583 | 0.1750 |
| total degree | 0.0033 | 0.0600 | - | - |

R@5 ceiling 0.250 (|gold|=20, k=5). Latency max 0.5s on 1074-1156 neighbours. All
candidates including losers: `gene_ranking_probe.log`.

## Findings that change how the numbers should be read

1. **Pathway F1 regressed and it was not predicted.** The ranking changes which genes
   DiseaseToGene returns, so downstream GeneToPathway queries run on different genes and
   reach different pathways; hub genes' pathways do not match the gold pathway lists. Step 4
   trades Pathway F1 0.596 (a best-in-paper number) for Gene Recall. A research judgement -
   see Open questions. Reversing it means dropping the bio_degree ORDER BY; nothing else
   depends on it.
2. **The guard cannot move retrieval metrics, by construction.** `compute_metrics` derives
   predictions from `tool_calls`; the guard only rewrites `final_answer`. Flat gene/bridge
   rows in the step 3 column are expected; the pathway drift there is planner variation.
3. **The published 0.047 is not recall@5.** Recomputing reproduces pathway_f1 and bridge_hit
   exactly but gives gene_recall@5 = 0.0100. `compute_metrics` truncates predictions to k;
   `compute_paired_stats` uses all predictions and returns 0.0467. So "Recall@5 = 0.047" is
   un-truncated recall mislabelled - which accounts for the 4.7x discrepancy an earlier
   investigation recorded but could not explain. Both definitions are carried above.
4. **The gain is a popularity prior.** Mean pairwise top-8 overlap across the 15 diseases is
   0.577, 24 distinct genes across all 15 lists, TP53 and PIK3CA in 15/15. Every
   disease-specific signal tried scored lower.
5. **Judge noise bound.** The identical GPT-4o file scored 23.40 and 24.26 in two runs, so
   ~0.9 of noise sits on these totals at 3 votes. Step 3's D3 and step 4's D1/D3/D4 clear
   it; D5 does not.
6. **Two planned signals are dead here**, measured not assumed: "distinct sources" is
   constant at 2 per neighbour (both directions stored), and "pathways shared with the
   disease" is always 0 - there are **no Disease-Pathway edges**.

## Defects found outside the approved scope (reported, not fixed)

1. `DiseaseToPathway` matches Disease-Pathway edges, of which the KG has 0, so the intent
   can never return a row. Pathway results come only from the bridge intent.
2. `ORDER BY weight DESC` is a no-op in all 10 single-hop intents: `weight` is `''` on every
   relationship type. See `CALL_SITES.md`.
3. The both-directions duplication halves the effective `k` of every undirected single-hop
   intent, as it did for DiseaseToGene (top-8 gave 4 distinct genes).

## Confidence and falsifier

**Confidence: HIGH.** Every claim is from the live KG or a repo file named by path,
re-verified this session rather than inherited - the previous investigation's HIGH was
downgraded for resting on an offline snapshot.

**Correction to a starting fact.** The brief says all 30854 ASSOCIATED_WITH weights are 0.
Live, `weight` is the empty STRING, so `coalesce(r.weight, 0.0)` returns `''`. The
alphabetical conclusion holds, the mechanism differs, and a "rank by weight" fix would have
been a silent no-op.

**Falsifier: RAN, three of them, and they changed the work.** (a) "Ranking by graph signals
will raise Gene Recall@5 across all 15" - partly FALSIFIED: it raises the 6 trustworthy
questions and leaves 9 flat. (b) "The probe and the shipped Cypher measure the same thing" -
initially FALSE, one term counted relationships giving 2x; fixed, now identical on 15/15.
(c) "The guard fix is complete" - FALSE: review found the diverged-panel phrase missing, 11
of 99 PcQA rows still unflagged; fixed before step 5.

## Open questions

- **Is the pathway regression an acceptable price for the gene gain?** 0.596 -> 0.554 and
  precision@5 0.600 -> 0.373, against uncut Gene Recall 0.0467 -> 0.0900 and traceability
  0.029 -> 0.060. Default taken: ship and report both directions.
- Is a popularity-prior ranking acceptable when the system sells disease specificity?
  Default: ship `bio_degree`. Measured alternative `assoc_degree,cohesion` trades R@5
  0.1000 -> 0.0917 for R@20 0.1833 -> 0.2417 and better specificity.
- ~~Report gene recall aggregate or on the trustworthy subset?~~ **Decided by the human:
  both, nothing dropped, no gold recurated.** Done in the tables above.
- Did the original N=15 use `max_rounds` 3 (paper) or 6 (script default and CLAUDE.md
  convention)? Unrecorded. This run uses 6. Reproducibility gap.

## Decisions to evaluate

`DECISIONS.md` D1-D7, each with rationale and the consequence of overruling it.

## Evidence

Red/green pairs: `guard_check_red|green.log`, `ranking_check_red|green.log`. KG and signal
choice: `kg_schema_recon.log`, `gene_ranking_probe.log`. Runs and metrics:
`smoke2_guardfix.log`, `step3d_n15.log`, `step3d_postproc.log`, `step3d_sysmetrics.log`,
`step3d_judge.log`, `step4d_postproc.log`, `step4d_judge.log`,
`stratified_gene_recall.log`. Docs: `CALL_SITES.md`, `code-review.md`, `DECISIONS.md`.
Process note: `singleton_check.log`.

## Residuals

- PcQA N=99 on the final config is RUNNING (~4 min/question, about 6.6 hours), with its
  post-processing and judge (n_votes 1, matching `pcqa99_judge_results.json`) to follow.
  That column reads PENDING.
- No KG writes or reimport; all access read-only. Main checkout untouched. No dependency
  changes: the existing virtualenv supplied libraries only, against this worktree's code.
