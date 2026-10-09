# GDgpt — Auditable MTB Assistance via KG-Grounded Multi-Agent Reasoning

> **KG-grounded multi-agent system for Molecular Tumor Board (MTB) preparation**
>
> Ye Wenqian · HKUST · 2026  ·  Target venue: ML4H 2026 (NeurIPS Workshop)
>
> Paper draft: [`docs/paper_draft_en.md`](./docs/paper_draft_en.md)

---

## What it does

Preparing a Molecular Tumor Board case requires a clinician to manually query OncoKB, CIViC, and PubMed, taking **1–2 hours per case**. GDgpt automates this by generating *auditable* gene–disease–pathway–drug mechanism reports that cite specific knowledge graph edges — so every claim is verifiable.

**Core differentiators vs. GPT-4o direct answer:**

| Property | GDgpt | GPT-4o direct |
|---|:---:|:---:|
| KG-edge citations in output | ✅ Always | ✗ Never |
| Explicit abstention on unknown diseases | ✅ 8/8 = 100% | ✗ 0/8 = 0% |
| Pathway F1 (N=15, Wilcoxon p≈0.0007) | **0.596** | 0.000 |
| D3 Traceability (PcQA N=99) | **4.19 / 5** | 2.98 / 5 |

---

## Key Results

### Main experiment (N=15 disease-centered questions)

| Metric | GDgpt | GPT-4o | p-value | 95% CI |
|---|:---:|:---:|:---:|:---:|
| **Pathway F1** | **0.596** | 0.000 | **0.0007** | [0.575, 0.619] |
| **Bridge Hit Rate** | **1.000** | 0.000 | **0.0007** | [1.000, 1.000] |
| Gene Recall (no rank cut) | 0.047 | 0.000 | 0.068 | [0.013, 0.093] |
| Gene Recall@5 (rank cut at 5) | 0.010 | 0.000 | — | — |

### Coverage-aware abstention (N=8 KG-absent real diseases)

| System | Abstention rate |
|---|:---:|
| **GDgpt** | **8/8 = 100%** |
| GPT-4o | 0/8 = 0% |

Diseases tested: glioblastoma, melanoma, AML, cystic fibrosis, Huntington disease, nasopharyngeal carcinoma, Marfan syndrome, gastric cancer.

### External benchmark: PcQA (N=99, independent KG)

| Dimension | GDgpt | GPT-4o | Winner |
|---|:---:|:---:|:---:|
| **D3 Traceability** | **4.19** | **2.98** | **GDgpt ★** |
| D4 Clinical Safety | 4.33 | 4.21 | GDgpt |
| D1 Factual Accuracy | 3.24 | 4.84 | GPT-4o |
| D2 Completeness | 1.89 | 4.62 | GPT-4o |
| D5 Coherence | 2.96 | 5.00 | GPT-4o |

GDgpt leads on D3 (traceability) consistently across all datasets and all three judges, including the cross-family Alibaba qwen-max judge.

### Component ablation (N=3)

| Configuration | Pathway F1 | Bridge Hit |
|---|:---:|:---:|
| Full system | 0.667 | 1.0 |
| **− Bridge queries (rag_only)** | **0.084 (−87%)** | **0.0** |
| − Multi-role (single_agent) | 0.653 | 1.0 |

Bridge multi-hop Cypher queries are the architectural core.

---

## Architecture

```
User query
    ↓
[Triage]      — complexity classification + role selection
    ↓
[KG Prefetch] — 2-3 Cypher queries → KG coverage ratio (LOW/PARTIAL/HIGH)
    ↓
[Consultation]— 7 specialist roles, same-round mutual blindness
    ↓
[Safety Review]— checks KG grounding; triggers another round if needed
    ↓
Final MTB report with cited_edges + [KG-supported] / [LLM-inferred] tags
```

**Knowledge graph**: PrimeKG-derived Neo4j subgraph — 10,133 nodes (Gene: 3,582 · Drug: 4,730 · Pathway: 1,725 · Disease: 20 · Phenotype: 76), 87,838 edges, 20 cancer types.

**11 query intents**: 8 single-hop + 3 Bridge multi-hop (DiseaseGenePathwayBridge, GenePhenotypeBridge, DrugTargetDiseaseBridge).

**Adaptive routing**: 1-role/1-round for simple queries (~37 sec) → 5-role/3-round for complex (~5 min). 3–5× speedup, Bridge Hit Rate preserved at 1.0.

---

## Quick Start

### Requirements

- Python 3.9+
- Neo4j (Docker recommended; see below)
- OpenAI-compatible LLM API

### Install

```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json: api_key, base_url, text_model, neo4j_uri/user/password
```

### Neo4j (Docker)

```bash
docker run -d --name primekg-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -v neo4j-data:/data \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:ubi9
```

Then load the PrimeKG subgraph dump into the container (see `kg_build/`).

### Run

```bash
streamlit run app.py
```

---

## Evaluation

```bash
# Re-run inter-judge kappa on existing results
python evaluation/compute_interjudge_kappa.py \
  --multijudge evaluation/results/multijudge_9q.json

# Compute human vs LLM-judge kappa (fill human_rating_form_v23.md first)
python evaluation/compute_kappa.py \
  --llm evaluation/results/llm_judge_v23_results.json \
  --human evaluation/results/human_rating_filled.json
```

All evaluation results are in `evaluation/results/`. Key files:

| File | Contents |
|---|---|
| `pcqa99_judge_results.json` | PcQA full N=99 per-dimension scores |
| `multijudge_9q.json` | 3-judge panel, N=9 internal, with swap consistency |
| `llm_judge_v23_results.json` | 3-vote GPT-4o judge, N=9 internal |
| `paired_stats_pathway_f1.txt` | Wilcoxon + bootstrap CI for Pathway F1 |
| `lowcov_full_raw.jsonl` | N=8 abstention experiment outputs |

---

## Limitations

- **Gene Recall (unbounded) = 0.047**: PrimeKG associates 1000+ genes per cancer type with no edge weights, so `DiseaseToGene` falls back to alphabetical order and returns an arbitrary slice of a 521-1,156-gene neighbourhood. Live KG verification (2026-10-08) found 290 of 300 gold genes *are* `ASSOCIATED_WITH` neighbours of their disease, so this is a retrieval-truncation defect we can fix, not an inherent KG data constraint. The metric applies no rank cut (ceiling 1.0); the rank-cut figure on the same input is Recall@5 = 0.010 (ceiling 0.25). Labelling 0.047 as "Gene Recall@5" was an error. See `docs/paper_draft_en.md` 4.1 and 5.5.
- **D1/D2/D5 lower than GPT-4o**: GDgpt is constrained to KG-grounded content; GPT-4o draws on parametric knowledge. The tradeoff is traceability and abstention.
- **No clinical expert evaluation**: We use a 3-judge LLM panel with inter-judge Cohen's κ (D3 mean κ=0.353) as a proxy. Human expert validation is future work.
- **Pilot study scale**: N=15 (main), N=8 (abstention), N=3 (ablation), N=99 (external PcQA).

---

## Citation

```bibtex
@article{ye2026gdgpt,
  title={GDgpt: Auditable Molecular Tumor Board Assistance via KG-Grounded
         Multi-Agent Reasoning with Coverage-Aware Abstention},
  author={Ye, Wenqian},
  year={2026},
  note={Preprint. Target: ML4H 2026 (NeurIPS Workshop)}
}
```

---

## For AI Agents

See [`AGENT_HANDOFF.md`](./AGENT_HANDOFF.md) — project SSOT with current status, constraints, and quick-start for new agents. The file is mirrored to `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.clinerules`, and `.github/copilot-instructions.md`.
