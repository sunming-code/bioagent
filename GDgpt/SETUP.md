# GDgpt Setup

How to get GDgpt running from a fresh clone of this repo. Verified on macOS with
Python 3.9.6.

## 1. Important: run everything from inside `GDgpt/`

`utils.py` reads `config.json` by **relative path from the current working
directory**, not from the script's location. Every command below assumes:

```bash
cd GDgpt
```

If you run `python GDgpt/app.py` from the repo root, config loading silently
falls back to defaults with an empty API key and no Neo4j URI.

## 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The knowledge-graph import script (`kg_build/import_magis_to_neo4j.py`) needs
one extra dependency that is not in `requirements.txt`, because `kg_build` is a
separate project with its own `pyproject.toml`:

```bash
pip install 'py2neo>=2021.2.3'
```

## 3. Start Neo4j

```bash
docker run -d --name primekg-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -v neo4j-data:/data \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:ubi9
```

## 4. Load the knowledge graph

The graph is **pre-built and committed** at `kg_build/task_kg_output/`, so you do
not have to regenerate it:

| File | Size | Contents |
|---|---|---|
| `task_kg_nodes.csv` | 836 KB | 10,133 nodes (Gene 3,582 · Drug 4,730 · Pathway 1,725 · Disease 20 · Phenotype 76) |
| `task_kg_edges.csv` | 12 MB | 87,838 edges |
| `selected_seed_diseases.csv` | 858 B | the 20 cancer types |
| `task_kg_summary.json` | 542 B | build summary |

Import it:

```bash
python kg_build/import_magis_to_neo4j.py \
  --input-dir kg_build/task_kg_output \
  --uri bolt://localhost:7687 --user neo4j --password password
```

For Neo4j Aura instead of local Docker, use the HTTP importer — Aura blocks the
Bolt port 7687 on some corporate networks, so this one talks to the Query API on
port 443:

```bash
python evaluation/import_kg_to_aura_http.py \
  --kg-dir kg_build/task_kg_output
```

### Regenerating the graph from scratch (optional)

Only needed if you want to change the graph. Two source CSVs are **not in this
repo** because they exceed GitHub's 100 MB per-file limit:

- `kg_build/kg.csv` — PrimeKG raw export, 936 MB
- `kg_build/magis_kg_edges.csv` — full MAGIS edge list, 312 MB

Ask Wenqian for them, then:

```bash
python kg_build/create3.py --input kg_build/kg.csv
```

`kg_build/magis_demo_100_edges.csv` (17 KB, 100 edges) *is* included if you just
want to smoke-test the import path.

## 5. Configure credentials

```bash
cp config.example.json config.json
```

Fill in `config.json`:

| Key | What it is |
|---|---|
| `api_key`, `base_url`, `text_model` | any OpenAI-compatible endpoint; results in this repo used `gpt-4o-mini` |
| `neo4j_uri` | `bolt://localhost:7687` for Docker, or `neo4j+s://<id>.databases.neo4j.io` for Aura |
| `neo4j_user`, `neo4j_password`, `neo4j_database` | for Aura, all three are the instance ID |

`config.json` is gitignored — it holds API keys, so do not commit it.

## 6. Run

```bash
streamlit run app.py
```

## 7. Verify without API keys or Neo4j

Both of these run offline against committed data and should pass:

```bash
# placeholder guard: 28 positive + 102 negative cases
python evaluation/scripts/check_placeholder_guard.py

# metric extension self-check: 7 checks
python evaluation/tests/check_metrics_ext.py \
  --pred evaluation/results/adapt15_guardrank_raw.jsonl \
  --kg-nodes kg_build/task_kg_output/task_kg_nodes.csv
```

Expected: `RESULT: PASS (28 positive + 102 negative cases)` and
`7/7 checks passed, 0 skipped, 0 failed`.

## 8. Evaluation pipeline

```
run_batch_eval_template.py    run questions through the system -> *_raw.jsonl
  -> extract_from_tool_calls.py   pull genes/pathways out of the KG tool calls
  -> compute_metrics.py           F1 and recall
  -> compute_system_metrics.py    latency, rounds, coverage
  -> compute_paired_stats.py      Wilcoxon + bootstrap CI
  -> llm_judge_eval.py            single judge
     multi_judge_eval.py          3-judge panel
```

All outputs live in `evaluation/results/`. See `README.md` for what the numbers
mean and `AGENT_HANDOFF.md` for current project status.

## Known open issues

Three knowledge-graph retrieval defects are diagnosed but **not yet fixed** —
details in `docs/weakness-research/DIAGNOSIS_LOG.md`:

1. `DiseaseToPathway` never returns anything; the disease–pathway edge it queries
   does not exist in the graph. Pathway results come entirely from the Bridge
   multi-hop queries.
2. Every edge weight in the graph is an empty string, so the `ORDER BY weight
   DESC` in all single-hop queries is a no-op.
3. Edges are stored in both directions, so an undirected single-hop query counts
   each edge twice — the effective `k` is half what you asked for.
