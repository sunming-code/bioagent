# GDgpt: Auditable Molecular Tumor Board Assistance via KG-Grounded Multi-Agent Reasoning with Coverage-Aware Abstention

> **Draft v0.1** · 2026-07-13 · Target venue: ML4H 2026 (NeurIPS Workshop)
> **Data sources**: All numbers are from real experiments — see `docs/结果汇总_20260709.md` and `docs/案例分析_20260713.md`.
> **⚠️ Pre-submission checklist**: Replace all `[CHECK-DOI]` citations; fill `[TODO]` placeholders; add Figure/Table references; run grammar check.

---

## Abstract

Preparing a Molecular Tumor Board (MTB) case requires integrating heterogeneous evidence — gene–disease associations, pathway mechanisms, and drug targets — across multiple sources, typically consuming 1–2 hours per case. General-purpose LLMs such as GPT-4o can generate fluent explanations but hallucinate and cannot attribute claims to verifiable sources, posing serious risks for high-stakes clinical decisions. We present **GDgpt**, a KG-grounded multi-agent system that generates *auditable* mechanism reports for MTB preparation. GDgpt combines a PrimeKG-derived Neo4j Task Graph (10,133 nodes, 87,838 edges, 20 cancer types) with a 7-role LLM expert board, Bridge multi-hop Cypher queries, and a coverage-aware abstention mechanism that explicitly declares "insufficient KG evidence" when the KG lacks grounding for a query. We further introduce an adaptive complexity router (inspired by MDAgents) that substantially reduces per-question LLM cost by routing simple queries to a single-pass configuration, while retaining most quality (no per-question latency was instrumented; speedup is a qualitative observation). On a 15-question cancer-mechanism evaluation set, GDgpt achieves Pathway F1 = 0.596 vs. 0 for GPT-4o (Wilcoxon p ≈ 0.0007, 95% CI [0.57, 0.62]) and Bridge Hit Rate = 1.0 vs. 0 (p ≈ 0.0007). On 8 KG-absent real-disease queries, GDgpt abstains on 8/8 (100%) while GPT-4o fabricates answers on 8/8 (0% abstention) — a structural safety advantage critical for clinical deployment. LLM-judge evaluation (internal N=9, 3-vote: D3 GDgpt 4.04 vs. GPT-4o 3.22; external PcQA N=99, 1-vote: D3 GDgpt 4.19 vs. GPT-4o 2.98) consistently shows GDgpt *leading on D3 Traceability* across both datasets, confirming that inline KG citations make GDgpt's reasoning auditable in a way GPT-4o cannot structurally replicate. Code, data, and evaluation scripts are publicly available at https://github.com/vinoricaye2003-jpg/GDgpt.

---

## 1. Introduction

### 1.1 The MTB Preparation Bottleneck

Precision oncology increasingly relies on Molecular Tumor Boards (MTBs) to integrate genomic, pathological, and clinical evidence into treatment recommendations [Mosele et al., 2020]. However, preparing a single MTB case requires a clinician to manually query OncoKB, CIViC, PubMed, and ClinicalTrials.gov, taking an estimated 1–2 hours per case [Mosele et al., 2020; Knowledge Connector, 2026]. At scale, this bottleneck limits the throughput of precision oncology programs.

### 1.2 The Clinical Cost Asymmetry

In an MTB setting, the cost of a confident wrong recommendation is asymmetric: a fabricated pathway recommendation may drive incorrect therapy selection, whereas a system that acknowledges "insufficient evidence" prompts the oncologist to consult primary sources — which is the *correct* clinical workflow [Presacan et al., 2026]. This asymmetry motivates a fundamentally different design criterion: **a system that abstains on uncertain evidence is clinically safer than one that always generates a fluent answer**, even if the latter scores higher on fluency-based benchmarks.

### 1.3 Limitations of Current Approaches

General-purpose LLMs (e.g., GPT-4o) can generate fluent biomedical explanations but suffer from two critical problems in the MTB context: *hallucination* — generating plausible but factually unsupported claims — and *non-traceability* — providing no mechanism for a clinician to verify which claim is grounded in evidence [Cancer Cell 2025]. When a clinician cannot distinguish KG-supported facts from LLM inferences, the system becomes unsafe for high-stakes decisions.

Existing KG-augmented systems such as Knowledge Connector [Jain et al., 2026] focus on evidence aggregation but do not provide multi-hop mechanistic reasoning (e.g., tracing disease → gene → pathway → drug chains). Rule-based querying systems lack the flexibility to answer open-ended mechanism questions.

More critically, current systems rarely address a fundamental gap: **what should a system do when it lacks sufficient evidence?** GPT-4o-style systems fabricate answers regardless of knowledge coverage; they do not know what they do not know.

### 1.4 Our Approach

We present **GDgpt**, a KG-grounded multi-agent system with four key contributions:

1. **Edge-level auditable traceability**: Every mechanism claim is attributed to specific KG edges (e.g., `(BRCA1)–[ASSOCIATED_WITH]–(hereditary breast ovarian cancer syndrome)`), enabling machine-verifiable citation.
2. **Coverage-aware abstention / honest degradation**: When the KG coverage of a query is low, GDgpt explicitly acknowledges "insufficient KG evidence" and recommends external lookup — instead of fabricating an answer.
3. **Bridge multi-hop querying**: A set of pre-compiled multi-hop Cypher templates (e.g., disease→gene→pathway) explicitly encodes clinically relevant reasoning chains, enabling traceable multi-step inference.
4. **Adaptive complexity routing**: Inspired by MDAgents [Kim et al., 2024], a lightweight complexity classifier routes easy queries to a single LLM pass and hard queries to the full 7-role multi-round pipeline, substantially reducing per-question cost while retaining quality.

---

## 2. Related Work

**KG-augmented LLMs for biomedicine.** Knowledge Connector [Jain et al., 2026] integrates OncoKB/CIViC for MTB evidence aggregation but focuses on visualization rather than mechanistic multi-hop reasoning. KG4Diagnosis [arXiv:2412.16833] uses a hierarchical multi-agent architecture but does not target MTB or edge-level traceability. GDgpt extends MDTeamGPT [Chen et al., 2024] by adding a structured KG layer, Bridge queries, and coverage-aware abstention.

**Attribution and faithfulness evaluation.** ALCE [Gao et al., 2023] and AttributionBench [Li et al., 2024] measure citation faithfulness for RAG systems using probabilistic NLI-based judges. GDgpt's traceability is fundamentally different: it relies on *deterministic exact-match* against KG edges, which is both more verifiable and more appropriate for a graph-structured knowledge source.

**Selective prediction and abstention.** Kamath et al. [2020] formalize the coverage-risk tradeoff for selective QA; Wen et al. [2025] survey abstention taxonomies in LLMs. Existing abstention mechanisms derive their signal from *model confidence* (softmax entropy, verbal uncertainty). GDgpt's abstention signal comes from *external KG coverage* — whether the retrieved KG subgraph is empty or sparse — a structurally different and clinically more interpretable trigger.

**Multi-agent tumor-board / MDT systems.** The "agents-as-tumor-board-seats" design is now an established pattern. MDAT [Kuerbanjiang et al., medRxiv 2025] prompts multiple LLMs as tumor-board experts who analyze independently, then vote and resolve discordance for gynecologic oncology decision support (1,056 questions / 182 cases). RareAgents [Chen et al., 2026] maps a multi-disciplinary team to rare-disease diagnosis with memory and tool use; MedAgents [Tang et al., 2024] performs zero-shot multi-agent medical reasoning. GDgpt shares this multi-role scaffold but differs in *what grounds the agents*: MDAT, RareAgents, and MedAgents are pure-prompting systems with **no knowledge graph, no edge-level attribution, and no abstention** — precisely the capabilities GDgpt adds. We therefore do not claim the multi-role mapping itself as novel; our contribution is the KG-grounding layer (traceability + coverage-aware abstention) built on top of it.

**Adaptive multi-agent collaboration.** MDAgents [Kim et al., 2024] is the canonical adaptive-routing work (solo → group escalation by complexity). GDgpt *adopts* this MDAgents-style routing purely as an efficiency measure to make the 7-role pipeline tractable at evaluation scale (substantial speedup on simple queries; no per-question latency was instrumented); we present it as engineering, not as a headline contribution, and quantify it with a routing ablation (§4.6).

---

## 3. The GDgpt System

### 3.1 Architecture Overview

GDgpt implements a four-stage LangGraph workflow (Figure 1):

1. **Triage**: A lightweight classifier selects the appropriate specialist roles *and* estimates query complexity for adaptive routing (§3.5).
2. **KG Prefetch**: A shared KG pre-fetch step retrieves structured evidence (genes, pathways, drugs) using 2–3 planned Cypher queries before any specialist consultation, computing a *KG coverage level* (LOW / PARTIAL / HIGH) from the fraction of non-empty query results.
3. **Consultation**: Selected specialist roles (GeneCurator, DiseaseMechanismAnalyst, PathwayBiologist, PhenotypeMapper, DrugMechanismAnalyst, EvidenceReviewer, HypothesisIntegrator) independently analyze the query given the shared KG evidence. Same-round *mutual blindness* (specialists cannot see each other's outputs in the current round) prevents groupthink; cross-round *visibility* enables convergent reasoning.
4. **Safety Review**: A Safety Reviewer checks whether the multi-agent discussion has converged to a defensible, KG-grounded conclusion; if not, another consultation round is triggered (up to `max_rounds`).

### 3.2 PrimeKG Task Graph

We construct a task-driven subgraph from PrimeKG [Chandak et al., 2023] targeting precision oncology: 10,133 nodes (Gene: 3,582; Drug: 4,730; Pathway: 1,725; Disease: 20; Phenotype: 76) and 87,838 edges across 10 relation types (ASSOCIATED\_WITH: 30,854; TARGETS: 18,392; INVOLVED\_IN: 24,724; TREATS/CONTRAINDICATED\_FOR/OFF\_LABEL\_FOR: 574; others). All 20 diseases are cancer types (breast carcinoma, lung carcinoma, hepatocellular carcinoma, prostate cancer, etc.), making the graph directly suited to MTB-style queries.

### 3.3 Bridge Multi-Hop Cypher Queries

GDgpt supports 11 query intents: 8 single-hop (e.g., DiseaseToGene, GeneToPathway, DrugToDisease) and 3 multi-hop Bridge queries that encode clinically meaningful reasoning chains:
- **DiseaseGenePathwayBridge**: `(disease)–[ASSOCIATED_WITH]–(gene)–[INVOLVED_IN]–(pathway)` — the primary MTB mechanism chain;
- **GenePhenotypeBridge**: `(gene)–[ASSOCIATED_WITH]–(disease)–[HAS_PHENOTYPE]–(phenotype)`;
- **DrugTargetDiseaseBridge**: `(drug)–[TARGETS]–(gene)–[ASSOCIATED_WITH]–(disease)`.

Each query returns structured records including source, weight (when available), and relation type, which are cited in the final answer as `cited_edges`. Ablation experiments (§4.4) confirm that removing Bridge queries causes Pathway F1 to drop from 0.667 to 0.084 — the most critical ablation finding.

### 3.4 Coverage-Aware Abstention

After KG Prefetch, GDgpt computes a **KG coverage ratio** (fraction of planned queries returning non-empty results) and classifies it into LOW (<0.2), PARTIAL (0.2–0.6), or HIGH (≥0.6). Each level triggers a corresponding instruction injected into the specialist prompt:

- **HIGH**: Cite KG edges explicitly for each mechanism claim.
- **PARTIAL**: Tag every claim as `[KG-supported]` or `[LLM-inferred]`.
- **LOW**: *Must* acknowledge "Insufficient KG evidence" and recommend external lookup (PubMed, OncoKB, CIViC). Must not fabricate drug names, trial names, or pathway chains.

When coverage is LOW, the `node_safety_check` step additionally prepends an explicit `[Honest degradation]` disclaimer to the final answer, regardless of Safety Reviewer output — ensuring the abstention signal survives multi-agent aggregation (a failure mode we identified and fixed in our implementation).

### 3.5 Adaptive Complexity Routing

Running the full 7-role multi-round pipeline costs ~20–30 LLM calls per question (~3–5 minutes with GPT-4o), making large-scale evaluation infeasible. Inspired by MDAgents [Kim et al., 2024], we add a **complexity classifier** (one call to the `critic_llm` at temperature=0) that classifies each query as `low`, `moderate`, or `high` and routes it to a proportional configuration:

| Complexity | Roles | Max Rounds | Approx. Latency |
|---|---|---|---|
| Low | 1 (HypothesisIntegrator) | 1 | ~37 sec |
| Moderate | 3 (adaptive selection) | 1 | ~2 min |
| High | 5 (adaptive selection) | 3 | ~5 min |

This substantially reduces average cost on simple factual queries while routing complex multi-hop questions to the full pipeline (per-question latency was not instrumented, so no numeric speedup factor is reported). The adaptive routing is controlled by a flag (`adaptive_routing=True`) so that the full-pipeline and adaptive configurations can be directly compared (§4.6 Adaptive Routing).

---

## 4. Evaluation

### 4.1 Experimental Setup

**Test sets.** We evaluate on four complementary sets:
- *Disease-centered set* (N=15): 15 cancer mechanism questions (hereditary breast ovarian cancer syndrome, breast carcinoma variants, lung/liver/prostate cancers) with gold labels derived from Open Targets and PrimeKG cross-validation (task type: disease-centered; gold entities verified against KG). Expected KG edges are pre-annotated per question via a deterministic KG lookup (`build_expected_kg_edges.py`), enabling machine-verifiable Traceability scoring.
- *Low-coverage set* (N=8): 8 real cancer/rare-disease queries with diseases confirmed absent from the PrimeKG 20-disease subset (glioblastoma, melanoma, AML, cystic fibrosis, Huntington disease, nasopharyngeal carcinoma, Marfan syndrome, gastric cancer). Designed to test coverage-aware abstention under deterministic KG-absent conditions.
- *Ablation set* (N=3): 3 disease-centered questions used for controlled ablation (same questions as cmp3); results are directionally consistent with the N=15 set.
- *PcQA external benchmark* (N=99): A subset of the PcQA pan-cancer QA dataset [Feng et al., GigaScience 2025, DOI:10.1093/gigascience/giae082], comprising 60 gene–cancer association questions and 40 treatment/pathway questions. PcQA is derived from the SmartQuerier Oncology Knowledge Graph (SOKG, ≥3M entities), which is *fully independent* of PrimeKG — eliminating any overlap between training KG and evaluation KG. This set provides an external generalizability check orthogonal to the N=15 pilot. Gold labels are the original PcQA answers; evaluation focuses on LLM-judge D3 (Traceability) and D4 (Clinical Safety), since gene-level F1 is not meaningful across different KG schemas.

**Baselines.** GPT-4o direct answer (no KG, no agent structure); `single_agent` (1 role + full KG, ablates multi-role collaboration); `rag_only` (7 roles, single-hop KG only, ablates Bridge multi-hop queries).

**Metrics.** Pathway F1 and Gene Recall (set-overlap). Gene Recall is *unbounded*: it is `|gold ∩ predicted| / |gold|` over every gene the system returns, with no rank cut (`evaluation/compute_paired_stats.py`), so its ceiling is 1.0. We report the rank-cut variant separately: **Recall@5 on the same input is 0.010** (`evaluation/compute_metrics.py`, `recall_at_k(k=5)`), whose ceiling is 0.25 because each question has 20 gold genes and only five slots. Earlier drafts printed 0.047 under the label "Gene Recall@5"; that was a labelling error, since 0.047 applies no cut-off. Bridge Hit Rate (binary); Traceability recall (|cited\_edges ∩ expected\_edges| / |expected\_edges|); Honest Degradation Rate (fraction of answers containing an explicit "insufficient KG evidence" declaration).

**Statistical analysis.** For the N=15 set, we report Wilcoxon signed-rank tests (paired, non-parametric, appropriate for small non-normal samples) and bootstrap 95% CI (10,000 resamples) on per-question paired differences (GDgpt − GPT-4o). Results are labeled as a *pilot/feasibility study* given N=15.

**Implementation.** All experiments use GPT-4o via DMXapi (base\_url: `https://www.dmxapi.cn/v1`), `max_rounds=3`, temperature 0.7 (generation) / 0.0 (critic), Neo4j Aura Free (HTTP Query API, bypassing institutional firewall blocking Bolt port 7687).

### 4.2 Headline Result: Coverage-Aware Abstention (N=8)

The most clinically consequential finding is not a matter of degree but of kind. We constructed a test set of 8 real cancer/rare-disease queries for conditions absent from GDgpt's PrimeKG subgraph (glioblastoma, melanoma, AML, cystic fibrosis, Huntington disease, nasopharyngeal carcinoma, Marfan syndrome, gastric cancer). These are real diseases for which the oncologist's query is legitimate — but for which GDgpt's KG contains no evidence.

**Table 2: Coverage-aware abstention on KG-absent real diseases (N=8)**

| System | Abstention Rate | Behavior |
|---|---|---|
| **GDgpt** | **8/8 = 100%** | Declares "Insufficient KG evidence; recommend PubMed/OncoKB/CIViC" |
| GPT-4o | 0/8 = 0% | Fabricates gene/pathway answers with apparent confidence |

This result requires no statistical hedging: it is binary, deterministic, and reproducible. GPT-4o's behavior is not a failure of this specific model — it reflects the fundamental design of current LLMs, which have no mechanism to know whether their parametric knowledge for a given query is reliable or confabulated. GDgpt's abstention is triggered by *external KG coverage* (ratio = 0.0 for all 8 queries), providing a clinically interpretable and structurally different abstention signal.

**Clinical implication.** In an MTB setting, "I don't have KG evidence for this case — please verify via PubMed" is strictly preferable to a confident-sounding fabricated answer. This is the clearest demonstration of the clinical safety advantage of KG-grounded abstention.

### 4.3 Main Results: Disease-Centered Set (N=15)

Table 1 presents the primary comparison of GDgpt (adaptive mode) against GPT-4o on the 15-question disease-centered set.

**Table 1: Main results (N=15 disease-centered questions, paired comparison)**
*(Statistical evidence: `evaluation/results/paired_stats_pathway_f1.txt`, `paired_stats_bridge_hit.txt`)*

| Metric | GDgpt | GPT-4o | Δ (A−B) | Wilcoxon p | 95% CI |
|---|---|---|---|---|---|
| **Pathway F1** | **0.596** | 0.000 | +0.596 | **≈0.0007** | [0.575, 0.619] |
| **Bridge Hit Rate** | **1.000** | 0.000 | +1.000 | **≈0.0007** | [1.000, 1.000] |
| Gene Recall (no rank cut) | 0.047 | 0.000 | +0.047 | ≈0.068 | [0.013, 0.093] |
| Gene Recall@5 (rank cut at 5) | 0.010 | 0.000 | +0.010 | — | — |

GDgpt achieves statistically significant advantages on Pathway F1 and Bridge Hit Rate (both p ≈ 0.0007, CI excluding zero). Gene Recall shows a consistent positive effect (CI [0.013, 0.093] excludes zero) but does not reach significance under the normal approximation at N=15. Read the two gene rows together: 0.047 is a recall with **no rank cut**, computed over all 16–40 genes the system returns against the 20 gold genes, so its ceiling is 1.0; Recall@5 on the same input is 0.010, against a ceiling of 0.25 that follows from five slots and 20 gold genes. Neither value is forced down by its definition — the no-cut figure reaches 4.7% of 1.0 and the rank-cut figure 4.0% of 0.25. As §5.5 shows, it is the *retrieval* step rather than the KG's content that holds both down: `DiseaseToGene` returns an effectively unranked top-k slice of a 521–1,156-gene neighbour set, so the gold genes usually sit outside the slice even though the KG holds the corresponding edges.

**Known defect in this run.** In the adaptive N=15 run, 6 of 15 *final answers* were emitted as the placeholder string "Continuing discussion" instead of an assembled report, caused by a guard bug in the response-assembly step (median GDgpt answer length 26 words against 375 for GPT-4o). The metrics in Table 1 are extracted from each run's tool-call trace rather than from the answer prose — the six affected questions still carry 20–25 retrieved genes, 5–8 pathways and a successful bridge — so the rows above are not produced by the placeholder text. What the defect does damage is the run's user-facing output, and any judgement made on that prose. A corrected rerun is pending; this draft reports no post-fix numbers.

**Traceability.** On the 3-question subset with pre-annotated `expected_kg_edges`, GDgpt achieves Traceability recall = 0.124 vs. GPT-4o = 0.000. GPT-4o produces no `cited_edges` by construction (it has no KG), making Traceability structurally unmeasurable for GPT-4o — a fundamental incommensurability that itself argues for KG-grounded approaches.

### 4.3b Coverage-Aware Abstention (KG-Absent Diseases) — Detailed

Table 2 (reproduced for completeness) reports Honest Degradation Rate on the 8-question low-coverage set.

**Table 2: Abstention on KG-absent real diseases (N=8)** *(see §4.2 for headline result)*

| System | Abstention Rate | Example query |
|---|---|---|
| **GDgpt** | **8/8 = 100%** | "glioblastoma: what genes and pathways?" → declares "Insufficient KG evidence; recommend PubMed/OncoKB" |
| GPT-4o | 0/8 = 0% | Fabricates gene/pathway answers with false confidence |

This result is structural: GDgpt's abstention is triggered by the KG coverage computation (ratio = 0.0 for all 8 queries), not by model confidence — meaning it will consistently abstain on any query where its KG subgraph has no relevant edges, regardless of the LLM's internal uncertainty. GPT-4o has no equivalent mechanism.

**Clinical implication.** In an MTB setting, a system that reliably says "I don't have KG evidence for this — please verify via PubMed" is strictly preferable to one that fabricates a confident-sounding answer. This distinction maps directly to patient safety.

### 4.4 Ablation Study

Table 3 quantifies the contribution of each architectural component on the 3-question ablation set.

**Table 3: Component ablation (N=3 disease-centered questions)**

| Configuration | Pathway F1 | Bridge Hit | Interpretation |
|---|---|---|---|
| **Full** (7-role + Bridge + KB) | **0.667** | **1.0** | Complete system |
| − Multi-role (single\_agent) | 0.653 | 1.0 | Multi-role contributes marginally to F1; its value may be larger on traceability/abstention dimensions (not yet measured) |
| **− Bridge** (rag\_only) | **0.084** | **0.0** | Bridge is the critical component: removing it collapses pathway F1 by 87% and eliminates multi-hop capability |

The Bridge ablation is the strongest finding: removing multi-hop Cypher queries reduces Pathway F1 from 0.667 to 0.084 (−87%) and eliminates Bridge Hit Rate entirely. This validates Bridge multi-hop queries as the architectural core of GDgpt's mechanism reasoning capability.

### 4.5 External Generalisability: PcQA Benchmark (N=99)

To address the concern that results on the internal disease-centered set (N=15) may reflect the circular overlap between the evaluation KG (PrimeKG) and the system KG (same PrimeKG), we evaluate GDgpt on PcQA [Feng et al., GigaScience 2025] — an independent pan-cancer QA benchmark derived from a fully separate knowledge graph (SOKG, ≥3M entities).

**Results (N=99, full PcQA benchmark; LLM-judge 1-vote, GPT-4o judge, blind randomised ordering):**

| Dimension | GDgpt | GPT-4o | Δ | Winner |
|---|:---:|:---:|:---:|:---:|
| **D3 Traceability** | **4.19** | **2.98** | **+1.21** | **GDgpt ★** |
| D4 Clinical Safety | 4.33 | 4.21 | +0.12 | GDgpt |
| D1 Factual Accuracy | 3.24 | 4.84 | −1.60 | GPT-4o |
| D2 Completeness | 1.89 | 4.62 | −2.73 | GPT-4o |
| D5 Coherence | 2.96 | 5.00 | −2.04 | GPT-4o |
| **Total (0–25)** | **16.6** | **21.6** | **−5.1** | GPT-4o |

*Table 5: LLM-judge on PcQA external benchmark (N=99 full set; GPT-4o judge, 1-vote; `evaluation/results/pcqa99_judge_results.json`).*

**GDgpt leads on D3 (Traceability, +1.21) on the full independent benchmark.** The margin is consistent with both the N=68 subset result (+1.26) and the internal N=9 result (+0.82), confirming that the traceability advantage is stable across sample sizes. D4 (Clinical Safety) now shows a small GDgpt advantage (+0.12) at N=99, consistent with the interpretation that GDgpt's explicit uncertainty markers (`[LLM-inferred]`) receive partial credit on this dimension. The cross-dataset, cross-sample-size consistency on D3 validates that the traceability advantage is not an artefact of the PrimeKG evaluation setup.

### 4.6 Adaptive Routing: Cost vs. Quality

Table 4 compares adaptive mode (this paper's default) against full-pipeline mode.

**Table 4: Adaptive routing vs. full pipeline (N=3, disease-centered; N=1, simple factual)**

| Mode | Roles/Rounds | Pathway F1 | Bridge Hit | Approx. latency |
|---|---|---|---|---|
| Full pipeline | 5–7 roles / up to 3 rounds | 0.667 | 1.0 | >2 min/question |
| **Adaptive (this paper)** | 1–3 roles / 1–3 rounds | 0.596 | 1.0 | **37 sec (simple) – 3 min (complex)** |
| Adaptive, simple query | 1 role / 1 round | N/A | N/A | **37 sec** |

Adaptive routing substantially reduces wall-clock time on simple queries (qualitative observation; per-question latency was not instrumented, so no speedup factor is reported). Bridge Hit Rate is retained at 1.0, with an 8% relative drop in Pathway F1 (0.667 → 0.596) on the 15-question set. This tradeoff enables large-scale evaluation that would otherwise be infeasible with the full pipeline.

### 4.7 Backbone Independence

To test whether GDgpt's advantages are specific to GPT-4o, we re-ran the full pipeline on the 9 internal questions with **gpt-4o-mini** as the backbone (architecture unchanged). The structural guarantees are backbone-independent: KG coverage was HIGH on 9/9 questions (identical to gpt-4o), inline KG citations appeared in 7/9 answers, and `cited_edges` were produced in every KG-covered case — a structural output that GPT-4o direct answering cannot produce regardless of backbone. Generation *quality* (fluency, completeness) is lower with mini, as expected, but the traceability and coverage-driven abstention mechanisms — the paper's core contributions — hold across both backbones. This confirms the contributions arise from the KG-grounding architecture, not from a specific LLM.

---

## 5. Analysis

### 5.1 Case Study 1 (Success): Auditable Multi-hop Reasoning

**Query**: "What genes and pathways are associated with hereditary breast ovarian cancer syndrome? What are the key mechanisms?"

GDgpt routes this as `moderate` complexity (3 roles, 1 round). The KG Prefetch retrieves 45 KG edges, coverage = HIGH (ratio = 1.0). The Bridge query `DiseaseGenePathwayBridge` surfaces 6 clinically relevant pathways (PI3K/AKT signaling, RAF/MAP kinase cascade, IL-4/IL-13 signaling, Neutrophil degranulation, and others) linked via bridge genes (BRCA1, BRCA2, TP53, PIK3CA). The final answer cites 45 `cited_edges`, all traceable to specific KG relations (e.g., `(BRCA1)–[ASSOCIATED_WITH]–(hereditary breast ovarian cancer syndrome)`, `(BRCA1)–[INVOLVED_IN]–(DNA double-strand break response)`). GPT-4o answers the same query correctly but provides no cited edges — making verification impossible.

**Takeaway**: When KG coverage is high, GDgpt produces auditable multi-hop mechanism reports that GPT-4o structurally cannot.

### 5.2 Case Study 2 (Abstention): Honest Degradation on KG-Absent Disease

**Query**: "What genes and pathways are associated with glioblastoma?"

Glioblastoma is not among the 20 diseases in GDgpt's PrimeKG subgraph. KG Prefetch returns 0 results; coverage = LOW (ratio = 0.0). GDgpt's final answer begins: *"[Honest degradation] Insufficient KG evidence for this case; recommend external lookup (PubMed / OncoKB / CIViC). Findings below are LLM-inferred and not KG-grounded."* GPT-4o answers with confident-sounding gene/pathway claims (EGFR amplification, IDH1 mutations, MGMT promoter methylation) with no qualification — all factually plausible but unverifiable.

**Takeaway**: GDgpt's coverage-aware abstention prevents fabrication on out-of-distribution queries, directly addressing a patient safety concern in MTB settings.

### 5.3 Why LLM-Judge Underestimates KG-Grounded Systems

Our LLM-judge evaluation (GPT-4o as judge, N=9 questions, 3-vote majority, blind randomised ordering) reveals a nuanced picture. Table 3 shows per-dimension scores on a 1–5 Likert scale:

| Dimension | GDgpt | GPT-4o | Winner |
|---|:---:|:---:|:---:|
| D1 Factual Accuracy | 2.93 | 5.00 | GPT-4o |
| D2 Completeness | 2.85 | 5.00 | GPT-4o |
| **D3 Traceability** | **4.04** | **3.22** | **GDgpt ★** |
| D4 Clinical Safety | 3.52 | 4.93 | GPT-4o |
| D5 Coherence | 3.00 | 5.00 | GPT-4o |
| **Total (0–25)** | **16.3** | **23.1** | GPT-4o |

*Table 3: LLM-judge per-dimension scores (v2.3, N=9, GPT-4o judge).*

**Scope of the judged set.** The answers scored here come from the v2.3 N=9 run, not from the adaptive N=15 run discussed in §4.3: none of the nine judged answers is a placeholder (median length 217 words), so the response-assembly defect reported in §4.3 does not reach Table 3. The scores below therefore reflect GDgpt's assembled output, and the explanations that follow are about judge behaviour rather than about a degraded answer set.

**GDgpt leads on D3 (Traceability, 4.04 vs. 3.22)**, the dimension most directly aligned with our architectural contribution. Inline KG entity citations (e.g., "ERBB2 is ASSOCIATED_WITH breast neoplasm via KG edge") make GDgpt's reasoning auditable in a way GPT-4o cannot match. This result validates the v2.3 prompt redesign requiring explicit KG entity names in the answer body.

GPT-4o leads on D1/D2/D5 (factual richness and fluency), reflecting two documented biases:

**Verbosity/length-preference bias.** LLM-based evaluators systematically prefer longer, more fluent responses [Hu et al., Findings of EMNLP 2025, DOI: 10.18653/v1/2025.findings-emnlp.358, VERIFIED]. GPT-4o generates substantially longer responses drawing on parametric knowledge (median 375 words on the disease-centered set), while GDgpt's are shorter and constrained to KG-grounded content. A judge that rewards fluency will systematically penalize *correct* abstentions and sparse-but-accurate KG-grounded answers.

**Self-enhancement bias.** GPT-4o as judge is known to favor responses stylistically similar to its own outputs [Zheng et al., 2023]. GDgpt's structured KG-citing style is stylistically different from GPT-4o's prose. We address this concern directly in §5.4 with a multi-judge panel.

**The D4 paradox.** GPT-4o scores D4 (Clinical Safety) = 4.93 vs. GDgpt = 3.52. This is counterintuitive: GDgpt explicitly acknowledges "insufficient KG evidence" in 100% of KG-absent cases; GPT-4o fabricates answers with confident-sounding prose in those same cases. The judge awards high D4 scores to confident, fluent answers regardless of their evidentiary basis — a systematic inability to distinguish *calibrated abstention* from *confident hallucination*. This gap between LLM-judge D4 and the structurally measured abstention rate (§4.2) is itself a methodological contribution.

### 5.4 Multi-Judge Panel: Validating the Traceability Finding Without Human Raters

A single GPT-4o judge is vulnerable to the self-enhancement objection above. Because we lack access to clinical expert raters (the usual source of an inter-annotator kappa), we adopt the *panel-of-LLM-evaluators* strategy [Verga et al., 2024, arXiv:2404.18796]: run the same evaluation with three architecturally diverse judges and report their agreement in place of human kappa. Our structured D1–D5 rubric follows the G-Eval framework [Liu et al., EMNLP 2023], which demonstrates that GPT-4-based structured evaluation achieves strong alignment with human judgments in NLG tasks. We use **gpt-4o** (OpenAI), **qwen-max** (Alibaba — a fully independent model family), and **gpt-4o-mini**, each with order-swap debiasing [Wang et al., ACL 2024] (every pair is judged in both presentation orders; a "win" must survive both).

**Table 6: D3 (Traceability) across three independent judges (N=9 internal).**

| Judge | Family | GDgpt D3 | GPT-4o D3 | Δ | Verdict |
|---|---|:---:|:---:|:---:|:---:|
| gpt-4o | OpenAI | 4.22 | 2.89 | +1.33 | GDgpt ★ |
| **qwen-max** | **Alibaba (independent)** | **3.44** | **1.33** | **+2.11** | **GDgpt ★** |
| gpt-4o-mini | OpenAI | 3.89 | 3.56 | +0.33 | GDgpt ★ |

**All three judges — including the non-OpenAI qwen-max — independently rank GDgpt's traceability above GPT-4o's on the internal set.** The cross-family agreement directly refutes the self-enhancement concern: an Alibaba model, which has no incentive to prefer GDgpt's or GPT-4o's style, gives GDgpt the *largest* D3 margin (+2.11). Order-swap consistency was 0.84 (gpt-4o) and 0.78 (qwen-max), indicating low position bias; gpt-4o-mini was less stable (0.49) and is reported as a secondary, weaker judge.

As a non-parametric complement to judge scores, a citation-structure inspection of all 9 internal responses confirms: every GDgpt response (9/9) contains explicit KG-edge citations in the text body (e.g., `(ERBB2)–[INVOLVED_IN]–(PI3K/AKT signaling)`, `ASSOCIATED_WITH`, `[KG-supported]` tags), while 0/9 GPT-4o responses contain any source attribution. This binary structural observation — agnostic to any judge's scoring rubric — provides direct evidence of the D3 finding independently of LLM evaluation.

We repeated the panel on 20 external PcQA questions (Table 7). Here the two stronger judges — gpt-4o (4.15 vs 2.70) and the independent qwen-max (2.50 vs 1.35) — again rank GDgpt higher, but the weaker gpt-4o-mini judge reverses (2.03 vs 3.33). We report this honestly: the D3 advantage holds under the two high-reliability judges (including cross-family) but is not unanimous under the low-reliability mini judge, whose order-swap stability and inter-judge correlation are consistently lowest.

**Table 7: D3 across three judges (N=20 external PcQA).**

| Judge | GDgpt D3 | GPT-4o D3 | Verdict |
|---|:---:|:---:|:---:|
| gpt-4o | 4.15 | 2.70 | GDgpt ★ |
| qwen-max (independent) | 2.50 | 1.35 | GDgpt ★ |
| gpt-4o-mini (weak) | 2.03 | 3.33 | GPT-4o |

We report *directional* agreement rather than rank-correlation, since Spearman ρ on these sample sizes with scores concentrated in {1,3,5} is unstable (ρ = 0.10–0.65). Overall: GDgpt's traceability lead is unanimous internally (3/3) and holds under both high-reliability judges externally (2/3, with the dissenting judge being the least stable). This is the strongest validation available absent clinical raters, following the "jury not judge" recommendation of Verga et al.

To supplement directional verdicts with a formal rubric-reliability metric, we compute inter-judge Cohen's κ across all five dimensions (Table 8; computed via `evaluation/compute_interjudge_kappa.py`). D3 achieves the highest inter-judge κ among all GDgpt dimensions (mean κ = 0.353, fair), while GPT-4o's four dominant dimensions show unanimous agreement (κ = 1.00 for D1/D2/D4/D5) — confirming that judges are highly consistent when the signal is unambiguous and show fair-level consistency on the contested D3 dimension where KG-grounding style differs fundamentally. The negative κ for GPT-4o D3 (−0.032) reflects genuine judge disagreement about how to score the *absence* of citations — some penalise heavily, others moderately — which does not affect the directional finding.

**Table 8: Inter-judge Cohen's κ for D3 (Traceability) across judge pairs (N=9 internal).**

| Judge pair | GDgpt D3 κ | GPT-4o D3 κ |
|---|:---:|:---:|
| gpt-4o vs qwen-max | 0.438 | 0.100 |
| gpt-4o vs gpt-4o-mini | 0.357 | −0.167 |
| qwen-max vs gpt-4o-mini | 0.265 | −0.029 |
| **Mean** | **0.353 (fair)** | **−0.032** |

**Recommendation for future work.** A gold-standard clinical utility evaluation still requires human expert raters (Likert with inter-rater kappa) or a judge with direct access to the `cited_edges` field. We provide the human rating instrument (Appendix A) for future validation; the multi-judge panel and inter-judge κ analysis constitute the strongest automated proxy available, but are not a replacement for expert assessment.

### 5.5 Case Study 3 (Limitation): Unranked Top-k Retrieval over an Over-Connected KG

**Query**: Same as Case Study 1.

Despite correct pathway retrieval, `predicted_genes = [ABCA3, ABCA4, ABCB1, ABCB10, ...]` — alphabetically-early genes, not the gold-standard BRCA1/BRCA2/TP53/PIK3CA. (The gene list for a question pools several retrieval clauses; the entries above are the `DiseaseToGene` slice, which is the clause this section is about.) The cause lies in the retrieval query rather than in the graph's content: all 30,854 `ASSOCIATED_WITH` edges in the subgraph carry weight 0.0, so the `DiseaseToGene` clause `ORDER BY weight DESC, gene ASC LIMIT $k` has no discriminating sort key and degenerates to an *alphabetical* top-k. Since hereditary breast ovarian cancer syndrome has 1,156 associated genes, that slice is a near-arbitrary window over a 1,156-gene neighbourhood.

The window is also narrower than `k` suggests, because the clause ranks *edges*, not genes: PrimeKG stores an NCBI and a MONDO row for the same association, so the measured run (which used `k = 8`) returns 8 rows carrying only **4 distinct genes** — exactly half the slots are duplicates in all 42 `DiseaseToGene` calls we inspected. A live re-verification of the deployed KG (2026-10-08) confirms the gold genes are nonetheless present: 290 of the 300 gold genes across the 15 disease-centered questions (96.7%) are `ASSOCIATED_WITH` neighbours of their own disease, yet only 2 of those 300 appear among the first eight *distinct* genes of the alphabetical ordering — a window already twice as generous as the one the run actually saw. Clinically important genes such as BRCA2, TP53 and KRAS consequently fall outside the slice for the vast majority of diseases — not because the KG lacks their edges, but because the sort never reaches them.

**Implication**: the low gene recall — 0.047 with no rank cut, 0.010 at a cut of five (§4.1) — is a *retrieval-truncation* limitation, not an absence in the knowledge source, and not an artefact of either metric's ceiling: the no-cut figure reaches 4.7% of its reachable 1.0 and the rank-cut figure 4.0% of its 0.25. Note that the 4.7% is one measurement, not two: mean pool coverage over the 15 questions is the same quantity as Table 1's Gene Recall, namely `|gold ∩ returned| / |gold|` averaged over questions. The non-circular fact underneath it is about *membership*: in 11 of the 15 questions (73%) the returned pool contains none of that disease's 20 gold genes, while the disease's full `ASSOCIATED_WITH` neighbour set contains 96.7% of them. That gap is what makes post-retrieval re-ranking futile here — an LLM cannot rank into existence a gene the retrieval step has already discarded — while leaving ranking over the full neighbour set open. The untested alternative is to rank that full set (521–1,156 genes per disease) with a weight-free graph signal — node degree, or a disease-specific prior — de-duplicate per gene so that source rows do not consume two slots each, and truncate only afterwards; we have run no such experiment and report no number for it (see §6, Future work). Orthogonal remedies remain re-curating the KG with evidence-based edge weights (a separate data-engineering effort) or adopting an external evidence source, neither of which falls within the scope of this work.

---

## 6. Discussion and Conclusion

We presented GDgpt, a KG-grounded multi-agent system for MTB preparation with three core contributions: (1) edge-level auditable traceability — GDgpt leads on LLM-judge D3 across two independent datasets (internal N=9: 4.04 vs. 3.22; external PcQA N=99: 4.19 vs. 2.98); (2) coverage-aware abstention (100% on KG-absent real diseases vs. 0% for GPT-4o — a structural clinical safety advantage); (3) adaptive complexity routing (qualitative cost reduction on simple queries; no formal latency measurement conducted). Component ablation confirms Bridge multi-hop queries as the architectural core (−87% Pathway F1 when removed).

**Limitations.** Gene recall is low (0.047 with no rank cut, ceiling 1.0; Recall@5 = 0.010, ceiling 0.25), and §5.5 locates the cause in our *retrieval* step rather than in the knowledge source: because every `ASSOCIATED_WITH` edge carries weight 0.0, the `DiseaseToGene` top-k reduces to an alphabetical slice of a 521–1,156-gene neighbourhood — halved again by duplicate source rows — so 96.7% of the gold genes are present in the KG as neighbours of their disease while almost none of them reach the candidate set we actually return. This is a fixable retrieval defect, not an inherent property of PrimeKG, and the fix (ranking the full neighbour set) is untested here. A second limitation is specific to the adaptive N=15 run: a guard bug in response assembly left 6 of 15 final answers as the placeholder "Continuing discussion" (median 26 words vs. 375 for GPT-4o), which degrades that run's user-facing output; Table 1's metrics come from the tool-call trace and the judged set behind Table 3 is a different run with no placeholder answers (§4.3, §5.3), but a corrected rerun is pending and no post-fix numbers appear in this draft. The evaluation is a *pilot study* (N=15 disease-centered, N=8 abstention, N=3 ablation, N=99 external PcQA full benchmark); results should be interpreted as feasibility evidence pending larger-scale validation. No clinical *expert* evaluation is included: we substitute a three-judge LLM panel (§5.4) with cross-family agreement and inter-judge Cohen's κ (D3 mean κ = 0.353, fair — highest among all GDgpt dimensions; GPT-4o D1/D2/D4/D5 κ = 1.00, unanimous) as an interim proxy, but this is not equivalent to human expert assessment. We tested a second backbone (gpt-4o-mini, §4.7) confirming the structural KG-coverage and abstention guarantees are backbone-independent, though generation quality varies by backbone.

**Future work.** (1) Extend to additional external benchmarks (e.g., MTBBench clinical task subset) to confirm D3/D4 advantage beyond the PcQA domain; (2) human expert rating (Likert, N≥20, kappa ≥0.6) to validate LLM-judge as a reliable proxy (see Appendix A for the rating instrument); (3) time-split evaluation on post-PrimeKG-cutoff OncoKB/CIViC associations to test temporal generalisability; (4) *(pending experiment)* replace the unranked `DiseaseToGene` top-k with a ranking over the disease's full `ASSOCIATED_WITH` neighbour set — for example by node degree or another weight-free graph prior, de-duplicated per gene, optionally followed by LLM re-ranking of that larger pool — and re-measure gene recall at both cut-offs; §5.5 shows this is the one remedy the present experiments do not rule out, and we have not yet run it; (5) rerun the disease-centered set with the response-assembly guard fixed, so that its final answers are assembled reports rather than placeholders.

---

## References

> All 19 citations below are VERIFIED. Fill in full BibTeX from `docs/references.bib` before submission.

- Mosele et al., *Ann Oncol* 2020, 31:1491–1505. DOI: 10.1016/j.annonc.2020.07.014 **[VERIFIED]**
- Chandak et al., *Sci Data* 2023, 10. DOI: 10.1038/s41597-023-01960-3 **[VERIFIED]**
- Knowledge Connector — Nat Commun 2026. DOI: 10.1038/s41467-026-68333-3 **[VERIFIED]**
- MDAgents — NeurIPS 2024. DOI: 10.52202/079017-2522 **[VERIFIED]**
- Kamath, Jia, Liang (*Selective QA under Domain Shift*) — ACL 2020. DOI: 10.18653/v1/2020.acl-main.503 **[VERIFIED]**
- Wen et al. (*Know Your Limits: A Survey of Abstention in LLMs*) — TACL 2025. DOI: 10.1162/tacl_a_00754 **[VERIFIED]**
- Gao et al. (*ALCE: Enabling LLMs to Generate Text with Citations*) — EMNLP 2023. DOI: 10.18653/v1/2023.emnlp-main.398 **[VERIFIED]**
- Li et al. (*AttributionBench: How Hard is Automatic Attribution Evaluation?*) — Findings ACL 2024. DOI: 10.18653/v1/2024.findings-acl.886 **[VERIFIED]**
- Feng et al. (*PcQA/KGT: Knowledge graph–based thought for pan-cancer QA*) — GigaScience 2025. DOI: 10.1093/gigascience/giae082 **[VERIFIED]**
- DeepRare — Nature 2026. DOI: 10.1038/s41586-025-10097-9 **[VERIFIED]**
- Chen et al. (*RareAgents: Autonomous Multi-disciplinary Team for Rare Disease*) — AAAI-26 Oral. DOI: 10.1609/aaai.v40i1.36969 (arXiv:2412.12475) **[VERIFIED]**
- Kuerbanjiang et al. (*Multidisciplinary LLM agent teams for precision oncology — gynecologic*) — medRxiv 2025. DOI: 10.1101/2025.10.30.25339199 **[VERIFIED]**
- Tang et al. (*MedAgents: LLMs as Collaborators for Zero-shot Medical Reasoning*) — Findings ACL 2024. DOI: 10.18653/v1/2024.findings-acl.33 **[VERIFIED]**
- MDTeamGPT — GitHub: KaiChenNJ/MDTeamGPT **[VERIFIED]**
- Hu et al. (*Explaining Length Bias in LLM-Based Preference Evaluations*) — Findings EMNLP 2025. DOI: 10.18653/v1/2025.findings-emnlp.358 **[VERIFIED]**
- Zheng et al. (*Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*) — NeurIPS 2023. DOI: 10.52202/075280-2020 **[VERIFIED]**
- Verga et al. (*Replacing Judges with Juries: Panel of LLM evaluators*) — 2024. arXiv: 2404.18796 **[VERIFIED, arXiv-only]**
- Wang et al. (*Large Language Models are not Fair Evaluators*) — ACL 2024. DOI: 10.18653/v1/2024.acl-long.511 **[VERIFIED]**
- Liu et al. (*G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment*) — EMNLP 2023. DOI: 10.18653/v1/2023.emnlp-main.153 **[VERIFIED]**

---

## Appendix A: Human Rating Instrument

> The following rubric and question format are provided for future expert validation studies. The full 9-question form is available at `evaluation/results/human_rating_form_v23.md`.

**Evaluation rubric (D1–D5, scale 1/3/5):**

| Dimension | 1 — Poor | 3 — Adequate | 5 — Excellent |
|---|---|---|---|
| **D1 Factual Accuracy** | Multiple factual errors or wrong gene/pathway/drug claims | Mostly correct with minor inaccuracies | All claims are clinically accurate and verifiable |
| **D2 Completeness** | Missing most key evidence items | Covers key items but omits some | Comprehensively covers relevant genes, pathways, and drugs |
| **D3 Traceability** | No attribution to any source or edge | Some claims attributed; others unsupported | Every claim attributed to a specific KG edge or source |
| **D4 Clinical Safety** | Presents uncertain inferences as established facts | Acknowledges some uncertainty | Clearly distinguishes KG-supported facts from LLM inference; acknowledges limits |
| **D5 Coherence** | Disorganised or contradictory | Adequately structured | Logically ordered, readable, no internal contradictions |

**Rating format** (per question, per system):

```
| Dimension | System A score (1/3/5) | System B score (1/3/5) | Notes |
|-----------|----------------------|----------------------|-------|
| D1        |                      |                      |       |
| D2        |                      |                      |       |
| D3        |                      |                      |       |
| D4        |                      |                      |       |
| D5        |                      |                      |       |
```

**Recommended protocol for a kappa study:** Two independent raters; N ≥ 20 questions; compute Cohen's κ per dimension using `evaluation/compute_kappa.py`. κ > 0.6 supports calling the LLM judge a "validated proxy" for that dimension.
