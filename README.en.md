# Bioagent: From genomic data to traceable mechanism reports

[简体中文](README.md) | **English**

Version **1.2.2** · Updated **2026-10-19**

This project connects population genetics, variant annotation and ACMG classification, gene–disease mechanism analysis, and single-cell/spatial reference analysis in a resumable pipeline. It accepts a **GRCh38 single-sample VCF** or paired-end FASTQ files, and can also continue from a completed stage manifest. Outputs include structured evidence, HTML reports, and a ZIP package for offline viewing.

## Features and layout

| Module | Main functions | Main outputs |
|---|---|---|
| `1_popgen/` | FASTQ alignment and variant calling; PCA, ADMIXTURE, and frozen GNN ancestry analysis; matched 1000G allele frequencies | VCF, ancestry and frequency tables, `evidence_pack.json` |
| `2_egene/` | Input validation, ANNOVAR annotation, InterVar ACMG2015 classification, HPO-based disease association ranking, and reporting | `report_manifest.json`, variant/disease evidence tables, HTML |
| `3_GDgpt/` | Seven expert roles use a Neo4j task knowledge graph to produce mechanism explanations with tool-query records | Gene/disease/pathway analysis, cited edges, per-task reports |
| `4_atheromap/` | GSE159677 scDRS reference-context analysis and integration of GSE241346 gsMap spatial results | Single-cell/spatial reference results and figures |
| `egene_pipeline/`, `contracts/` | Cross-stage file contracts, verification, failure recovery, and unified delivery | Status manifests, complete reports, and ZIP packages |
| `pipeline_ui/` | A local web interface for selecting start/end stages and viewing logs and stage outputs as they become available | Browser interface and SSE progress updates |

The default workflow is `PopGen → e-Gene → GDgpt`. Add `--with-atheromap` to include the fourth stage. Each module uses an isolated environment. Stages exchange file manifests containing sizes, SHA-256 checksums, and sample identifiers.

## Get the code

```bash
git clone https://github.com/sunming-code/bioagent.git
cd bioagent
```

The repository contains approximately **50 MiB** of files: source code, documentation, a GNN model of about 6.3 MiB, task-graph CSV files of about 12.5 MiB, and small research records. **Raw sequencing data, reference databases, Conda/venv environments, large run outputs, and the ANNOVAR installation package are excluded from Git.** Prepare the inputs needed for your workflow using the instructions below.

## Installation and configuration

Run the following commands from the repository root. Environment validation primarily targets **Linux x86_64**. The main controller and GDgpt use Python 3.11; PopGen and AtheroMap versions are defined by their environment files. You need Git, curl, tar, Perl, and Python venv support. FASTQ preprocessing requires Java, and the fourth-stage installer requires Conda. GNN inference can run on a CPU.

Data sources and preparation steps are included with each module's setup instructions. See [DATASETS.md (Chinese)](DATASETS.md) for complete download commands, layouts, versions, and known gaps, and [provenance.json](data_sources/provenance.json) for sources and checksums. Reserve additional space for data, intermediate files, and software environments according to the selected entry point and stages.

### 1. Install the PopGen environments

```bash
bash 1_popgen/scripts/setup_runtime.sh
```

The script creates `1_popgen/.runtime/envs/{popgen,popgen_analysis,popgen_gnn}` and checks the software. Run the complete data check after preparing the references. Use `POPGEN_PREFIX`, `POPGEN_ANALYSIS_PREFIX`, and `POPGEN_GNN_PREFIX` to override environment locations.

### 2. Prepare the PopGen references

PopGen frequency queries use the **1000G high-coverage GRCh38 VCF panel of 3,202 individuals**. Download the chr1–22 VCF files and their `.tbi` indexes from the [official IGSR release directory](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/) into `1_popgen/data/1000GP/20220422_3202_phased_SNV_INDEL_SV/`. Batch download commands are provided in DATASETS.md. PCA, ADMIXTURE, and GNN also require the `ref_1000g_pruned.*` panel built from these VCFs. Generate the required `samples.info` from the label and individual tables included in the repository:

```bash
python3 - <<'PYDATA'
import csv
from pathlib import Path
base = Path('data_sources/popgen_panel')
sex = {row[1]: row[4] for row in (line.split() for line in (base / 'ref_1000g_pruned.fam').read_text().splitlines())}
out = Path('1_popgen/data/1000GP/samples.info')
out.parent.mkdir(parents=True, exist_ok=True)
with (base / 'sample_superpop.tsv').open() as source, out.open('w', newline='') as target:
    writer = csv.writer(target, delimiter='\t', lineterminator='\n')
    for row in csv.DictReader(source, delimiter='\t'):
        writer.writerow([row['IID'], row['SUBPOP'], sex.get(row['IID'], '0')])
PYDATA
bash 1_popgen/scripts/build_1000g_panel.sh 1-22
1_popgen/.runtime/envs/popgen_gnn/bin/python 1_popgen/scripts/check_runtime.py
```

Default data paths are relative to the repository. Set `POPGEN_1000G_VCF_DIR`, `POPGEN_SAMPLES_INFO`, and `PANEL_TMP` to use existing data or a larger temporary directory. The pruned panel's checksums, individual order, and training sites must match the frozen model. Verify a rebuilt panel against the provenance records; retraining a model does not reproduce the existing frozen checkpoint.

For FASTQ input, also download the [Broad GRCh38 FASTA](https://storage.googleapis.com/gcp-public-data--broad-references/hg38/v0/Homo_sapiens_assembly38.fasta), save it as `1_popgen/data/reference/GRCh38.fa`, verify it, and prepare the BWA indexes, FAI, and sequence dictionary. Commands are provided in DATASETS.md. Public example FASTQs are optional when starting from an existing VCF.

For a public paired-end sequencing example, use the Novogene HG002 WES [R1](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124639/HG002_novogene_wes_18g_rep1_R1.fq.gz) and [R2](https://hweu-ld.oss-eu-west-1.aliyuncs.com/demo/20190605124722/HG002_novogene_wes_18g_rep1_R2.fq.gz) files. Download them into `1_popgen/data/fastq/`; exact filenames, MD5 checksums, and resumable download commands are in DATASETS.md.

### 3. Install e-Gene and its reference and disease databases

Each user must obtain ANNOVAR from the [official registration page](https://www.openbioinformatics.org/annovar/annovar_download_form.php); the program cannot be redistributed with this repository. The hg38 annotation and classification databases come from the [official ANNOVAR database distribution](https://annovar.openbioinformatics.org/en/latest/user-guide/download/). The installer follows the protocols, URLs, and versions pinned in `2_egene/config/dependencies.lock.json`. Obtain dbNSFP and other databases under their respective terms.

`prepare_reference.py` downloads the hg38 FASTA from [UCSC](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz) and creates its FAI for input and REF checks. `setup_disease_data.py` downloads the HPO/HGNC versions pinned in `2_egene/config/disease_sources.lock.json` and builds the phenotype/disease association database. Replace the ANNOVAR archive path below with your own authorized package:

```bash
python3 2_egene/scripts/setup_dependencies.py \
  --annovar-archive /absolute/path/annovar.latest.tar.gz --workers 4
python3 2_egene/scripts/setup_input_runtime.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/prepare_reference.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/setup_disease_data.py
2_egene/.runtime/venv/bin/python 2_egene/scripts/check_dependencies.py
```

Installation creates `2_egene/.runtime/venv/`, configuration files, and database manifests. **The live OMIM `mim2gene.txt` has changed since the pinned local snapshot. Resolve access to the historical snapshot or explicitly choose a new version first**, or the downloader's ETag/size checks may stop installation. Historical source locks have not been silently changed to make installation pass. See [2_egene/README.md](2_egene/README.md) for detailed installation instructions.

### 4. Install GDgpt and configure the model and Neo4j

```bash
python3 -m venv 3_GDgpt/.venv
3_GDgpt/.venv/bin/python -m pip install -r 3_GDgpt/requirements.lock.txt
cp 3_GDgpt/config.example.json 3_GDgpt/config.json
```

Set your model and database configuration in `3_GDgpt/config.local.json`, which is ignored by Git. Example:

```json
{
  "api_key": "YOUR_MODEL_API_KEY",
  "base_url": "https://your-model-service/v1",
  "text_model": "YOUR_MODEL_NAME",
  "neo4j_uri": "bolt://127.0.0.1:7687",
  "neo4j_user": "neo4j",
  "neo4j_password": "YOUR_DATABASE_PASSWORD",
  "neo4j_database": "neo4j"
}
```

You can also override configuration with `GDGPT_API_KEY`, `GDGPT_BASE_URL`, `GDGPT_TEXT_MODEL`, and `GDGPT_NEO4J_*` environment variables. The default local embedding model downloads its model files on first use; prepare its cache in advance for offline operation.

Use a dedicated Neo4j instance. The following example uses the official Docker Community image; replace the password placeholder with the same password used in your configuration:

```bash
docker run -d --name bioagent-neo4j \
  -p 127.0.0.1:7474:7474 -p 127.0.0.1:7687:7687 \
  -v bioagent-neo4j-data:/data \
  -e NEO4J_AUTH=neo4j/REPLACE_WITH_YOUR_PASSWORD \
  neo4j:5.26-community
# Wait for the database to become ready, then import the included task graph.
3_GDgpt/.venv/bin/python 3_GDgpt/scripts/import_local_kg.py
```

The importer reads the database settings from `config.local.json`, verifies **10,133 nodes and 87,838 edges**, and refuses to mix in unrelated graph content. See the [official Neo4j Docker guide](https://neo4j.com/docs/operations-manual/current/docker/introduction/) for Docker configuration. `3_GDgpt/scripts/run_local.sh` manages the original server's local Neo4j/Java installation; it does not install the excluded `.runtime/` directory in a fresh clone. Docker users do not need that launcher.

### 5. Set up the fourth stage when needed

```bash
bash 4_atheromap/tools/setup_environments.sh
cp 4_atheromap/config/paths.example.env 4_atheromap/config/paths.local.env
```

Edit the local paths, configure working directories using the [AtheroMap environment guide](4_atheromap/docs/ENVIRONMENTS.md), and prepare inputs for both branches.

For scDRS, the original GSE159677 aggregate matrix is available from [NCBI GEO](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE159677). It cannot directly replace the project's manually annotated H5AD files, scores, and weights; a public distribution URL for those processed files has not yet been confirmed. Reference files must match `4_atheromap/config/GSE159677_scdrs.reference.json`; newly processed data must be registered again. See the [scDRS interface guide](4_atheromap/docs/SCDRS_INTEGRATION.md) for the workflow and contracts.

gsMap uses GSE241346 spatial data, GCST007435 GWAS statistics, and the official gsMap reference resources. Download URLs, file layouts, and SHA-256 checksums are recorded in the [download manifest](4_atheromap_data/GSE241346_gsMap/download_manifest.json). Conversion and preparation steps are described in the [gsMap input guide](4_atheromap/docs/GSMAP_INPUTS.md). The official resource URL returned HTTP 403 during the audit on this host; confirm an accessible download source first.

The root entry point also consumes an **already validated gsMap output directory**. Complete the analysis and checks described in the [gsMap validation guide](4_atheromap/docs/GSMAP_VALIDATION_20261018.md) before enabling it. A complete four-stage run requires these processed data and validation outputs; see [DATASETS.md, section 4 (Chinese)](DATASETS.md#4-不能仅用公开下载替代的内容) for the remaining gaps.

## Usage

After preparing the environments and data for your selected stages, run commands from the repository root. Input must use GRCh38; the pipeline does not perform automatic GRCh37 liftover. VCF ancestry analysis requires sufficient genome-wide sites, so a short list of candidate variants cannot replace a full sample VCF.

```bash
# Run the default three-stage workflow from a single-sample VCF.
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /absolute/path/sample.vcf.gz --outdir runs/sample_analysis

# Start from paired-end FASTQs. First prepare the Broad FASTA, BWA/FAI indexes,
# and sequence dictionary as described in DATASETS.md.
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --fastq-dir /absolute/path/fastq_directory \
  --reference "$PWD/1_popgen/data/reference/GRCh38.fa" \
  --outdir runs/sample_from_fastq

# Continue mechanism analysis from an existing e-Gene report.
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --egene-report /absolute/path/delivery/report_manifest.json \
  --outdir runs/sample_mechanism

# Add --case when clinical phenotypes are available; the template contains no real case data.
# --case /absolute/path/case.json

# Stop after e-Gene without calling the GDgpt model.
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /absolute/path/sample.vcf.gz --end-stage egene --outdir runs/sample_egene

# Enable the fourth stage after preparing its data and validated gsMap results.
2_egene/.runtime/venv/bin/python run_pipeline.py \
  --vcf /absolute/path/sample.vcf.gz --with-atheromap --outdir runs/sample_four_stage
```

Use [case.template.json](2_egene/examples/case.template.json) for the case format. The sample ID must match the VCF. Missing age, phenotypes, family information, and medical history remain unknown. REF mismatches are rejected by default. `--ref-mismatch exclude` explicitly excludes mismatches and records them; it is not a universal default.

Use a new output directory for each run. After completion, open `runs/<task>/delivery/index.html`, or download and extract `delivery.zip` for offline viewing. The task directory retains intermediate results, execution parameters, hashes, failure status, and reuse records. Model requests require your own service account and quota. No model is called when there are no eligible candidates.

### Local web interface

```bash
1_popgen/.runtime/envs/popgen_gnn/bin/python -m uvicorn \
  pipeline_ui.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, select the start/end stages and input paths accessible on the server, and view stage status, logs, and completed outputs while the run progresses. For a remote server, use SSH or VS Code port forwarding. See [pipeline_ui/README.md](pipeline_ui/README.md) for details. The web interface uses the same CLI and database configuration.

### Installation checks and command help

```bash
2_egene/.runtime/venv/bin/python run_pipeline.py --help
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v
1_popgen/.runtime/envs/popgen_gnn/bin/python 1_popgen/scripts/check_runtime.py
```

Synthetic regression tests do not require paid model calls. They verify file contracts, argument propagation, recovery/failure semantics, and report delivery. Historical real-data validation is recorded for [2026-10-16](PIPELINE_VALIDATION_20261016.md) and [2026-10-18](PIPELINE_VALIDATION_20261018.md); those records do not establish reproducibility on a new machine before its data are prepared.

## Advanced entry points and resuming runs

The five e-Gene stage entry points remain available, together with report, GDgpt-input, and unified-pipeline resume entry points. Select exactly one input option:

| Entry point | Subsequent execution |
|---|---|
| `--vcf` | PopGen ancestry/frequency/GNN → all e-Gene stages → GDgpt → unified delivery |
| `--fastq-dir` | PopGen FASTQ preprocessing, then the workflow above; use `--reference` for the reference FASTA |
| `--popgen-pack` | Start from an existing PopGen `delivery/evidence_pack.json` |
| `--prepared-manifest` | Continue annotation from prepared e-Gene input |
| `--annotation-manifest` | Continue ACMG classification from annotation results |
| `--acmg-manifest` | Continue disease analysis from classification results; real case information can be added |
| `--disease-manifest` | Generate the e-Gene report, then run GDgpt |
| `--egene-report` | Adapt an e-Gene `delivery/report_manifest.json` and run GDgpt |
| `--gdgpt-input` | Run GDgpt from an adapted `input_manifest.json`; unified delivery still requires the original e-Gene report |
| `--resume-from` | Verify and reuse successful stages from a previous `pipeline_manifest.json`; continue failed stages in a new directory |

For example, continue from an existing PopGen delivery on the original server:

```bash
python run_pipeline.py \
  --popgen-pack 1_popgen/results/validation_current/delivery/evidence_pack.json \
  --ref-mismatch exclude \
  --outdir runs/NA18526_from_popgen
```

Here, `--ref-mismatch exclude` preserves the exclusion strategy already documented for the NA18526 validation data. New samples reject mismatches by default; do not treat this option as a general quality-control default. Sample provenance, missing quality fields, and reference-allele limitations are described in the [PopGen validation record](1_popgen/VALIDATION_20261016.md).

## GDgpt task selection

By default, the pipeline creates a mechanism-analysis task for **every disease candidate retained by e-Gene**. Use `--max-candidates N` to set an explicit limit; the report records the number left unanalyzed rather than silently truncating them. With zero candidates, it returns `no_eligible_candidates` and the upstream conclusion, **without calling a model, promoting background VUS, or generating a disease diagnosis**.

For explicit exploration of a gene, use `--gene`; the option can be repeated:

```bash
python run_pipeline.py \
  --egene-report 2_egene/results/NA18526_complete/delivery/report_manifest.json \
  --gene RNF34 \
  --outdir runs/NA18526_RNF34
```

The gene must connect unambiguously to an existing patient variant context that overlaps an annotated gene feature. A nearby gene from an intergenic/upstream/downstream annotation cannot be used directly as the variant's target gene. These tasks are marked `explicit_gene_exploration`; they preserve the original VUS/benign classification and background routing without changing disease candidates. RNF34 is a VUS in this example and is used for exploratory mechanism analysis.

Each model task starts its query with the gene and disease hypothesis to accommodate the existing GDgpt query planner's first-600-character window. Complete structured evidence is stored in `gdgpt_input.json`, including positive/negative phenotypes, original GT, quality fields, ACMG evidence items, frequency-use permissions, and exclusion reasons. By default, 20 variant contexts per task are shown to the model, with the remaining count explicitly recorded. Increase this with `--prompt-variants`. Complete evidence remains in the delivery, and omitted contexts are not represented as individually reviewed by the model.

GDgpt allows up to **6 rounds** by default and accepts `--max-rounds 1..6`; actual convergence follows its existing workflow. Each task has a default hard timeout of **3,600 seconds**, configurable with `--task-timeout`. Tasks run in separate subprocesses. A timeout or failure stops the current pipeline run, while completed tasks are retained for resuming. A failed task is not retried in the same background thread.

Model settings come from `3_GDgpt/config.json` or existing `GDGPT_*` environment variables. API keys are not written into unified configuration or reports. Neo4j must be running: new machines can use the Docker configuration above, while the original server's local installation is managed with `bash 3_GDgpt/scripts/run_local.sh start`. Empty-candidate delivery does not need a model service.

## Connect the fourth-stage scDRS analysis

The pipeline provides a verifiable `3_GDgpt → 4_atheromap` interface, connected on the original server to the reviewed reference files under `4_atheromap_data/GSE159677_scDRS`. After preparing the fourth-stage assets described above, add `--with-atheromap` to run all four stages:

```bash
python run_pipeline.py \
  --egene-report 2_egene/results/NA18526_complete/delivery/report_manifest.json \
  --gene RNF34 --with-atheromap \
  --outdir runs/NA18526_four_stage
```

This produces interface manifests, scDRS delivery, and validated gsMap results under `05_atheromap/`, with the fourth-stage report under `delivery/atheromap/`. You can also use `--resume-from .../pipeline_manifest.json --with-atheromap` on an existing three-stage run to execute only the fourth stage. The standalone continuation commands remain available:

```bash
2_egene/.runtime/venv/bin/python -m egene_pipeline.atheromap_adapter \
  --gdgpt-manifest runs/NA18526_RNF34_pipeline/delivery/gdgpt/gdgpt_manifest.json \
  --scope reference-context \
  --outdir runs/new_task_atheromap_input

bash 4_atheromap/tools/run_scdrs.sh \
  --input-manifest runs/new_task_atheromap_input/input_manifest.json \
  --mode reuse --plots all \
  --outdir runs/new_task_atheromap_scdrs
```

The interface preserves original variant classifications, case information, frequency permissions, and GDgpt tasks. scDRS cells belong to an external reference cohort. The actual GWAS source of the current `z_score` has not been confirmed, so results are restricted to reference context. Use `--mode recompute` to recalculate reference scores and synchronize subtype exports. Input contracts, data registration, commands, and outputs are described in the [scDRS interface guide](4_atheromap/docs/SCDRS_INTEGRATION.md). See `run_pipeline.py --help` for unified four-stage options.

## Outputs and recovery

```text
runs/task/
├── 01_popgen/                 Created when starting from raw input
├── 02_egene/                  Annotation, classification, disease analysis, original e-Gene report
├── 03_gdgpt_input/            gdgpt_input.json, input_manifest.json
├── 04_gdgpt/                  Per-task queries, raw results, tool records, timings, and reports
├── 05_atheromap/              scDRS, validated gsMap outputs, and fourth-stage report (when enabled)
├── delivery/
│   ├── index.html             Unified report home page
│   ├── pipeline_report.json   Ancestry/frequency summaries, task selection, and provenance
│   ├── delivery_manifest.json
│   ├── egene/                 Complete offline e-Gene delivery
│   └── gdgpt/                 Complete mechanism-analysis delivery
├── delivery.zip               Extract and open delivery/index.html
├── logs/                      Per-stage logs
├── pipeline_manifest.json     Parameters, commands, stage-manifest hashes, and execution records
└── status.json
```

Reused stages stay in their original run directories; large bioinformatics intermediates are not copied. The final offline package copies the required reports and complete TSV files. Original paths in `delivery/provenance` and `*.source.json` are provenance records, not executable entry points after relocation. Ancestry and frequency results are carried into the e-Gene report; the original PopGen VCF, intermediates, and model outputs stay in `01_popgen/` or their original task directories.

To resume a failed run, specify a new output directory:

```bash
python run_pipeline.py \
  --resume-from runs/failed_task/pipeline_manifest.json \
  --outdir runs/resumed_task
```

Resuming verifies successful stage manifests and file hashes and checks that they refer to the same sample. After an e-Gene failure, it locates the last completed e-Gene stage. For an incomplete GDgpt stage, completed tasks can be reused only when their inputs, model, graph CSV snapshots, code, and task parameters match. Entirely successful stages retain their original configuration and results. You may adjust `--threads`, `--task-timeout`, and interpreter paths for recovery, but cannot change clinical information or analysis policy through resume. To change case information, filtering policy, or gene selection, start from the corresponding upstream manifest.

Existing run directories are not overwritten, and failed runs do not publish a success ZIP. Data-file references and local links in the final package are relative; SHA-256 checksums can be verified against `delivery_manifest.json`. See [PIPELINE_VALIDATION_20261018.md](PIPELINE_VALIDATION_20261018.md) for the real-data four-stage continuation record.

## Parameters and environments

`python run_pipeline.py --help` lists all options. PopGen's `--skip-cv` and `--skip-gnn`, together with e-Gene quality/frequency/disease-policy arguments, are explicitly forwarded to the original entry points. These stages are not skipped by default. Their original restrictions on changing policies for reused stages still apply.

The PopGen controller uses the e-Gene interpreter by default, while bioinformatics computation is dispatched to its isolated environments through `runtime.py`. e-Gene uses `2_egene/.runtime/venv/bin/python`, and GDgpt uses `3_GDgpt/.venv/bin/python`. Override interpreters with `--popgen-python`, `--egene-python`, and `--gdgpt-python`; environments do not need to be merged.

## Validation and interpretation limits

```bash
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v
```

Synthetic tests are explicitly labeled. They cover complete-table reading, preservation of classification/frequency permissions, rejection of nearby-gene targeting, candidate and empty-candidate handling, mixed samples, tampering, task reuse, hard timeouts, stopping after failures, and portable ZIP delivery. Real server runs are documented in the [validation record](PIPELINE_VALIDATION_20261016.md).

The GDgpt graph contains five node types—genes, diseases, pathways, phenotypes, and drugs—and has no variant nodes. Its mechanism explanations do not establish allele pathogenicity, tumor driver status, drug sensitivity, or an individual's disease probability. Upstream observations and graph-query records are retained separately; model text requires review. e-Gene's Mendelian disease candidates are not automatically treated as cancer-treatment evidence.
