# 诊断输出全记录 (read-only)

日期 2026-10-08 · 只读调查，未改任何项目文件，未跑任何 batch eval，未改 KG
环境：Neo4j **未运行**（localhost:7687 / 7474 均 CLOSED，docker daemon 未启动）；
      config.json 指向 Aura (`neo4j+s://`, tools.py:39-44 HTTP 模式)，本次未读 config.json、未连 Aura。
      因此 `CALL gds.list()` / `SHOW PROCEDURES` / 任何 live Cypher **本次无法执行（NOT RUN）**。
      替代证据链：`evaluation/build_expected_kg_edges.py:9-11` 的 docstring 说明
      `expected_kg_edges` 中每条边都已逐条连 Aura 核实存在，故该文件可当作 KG 的离线真值快照；
      KG 导入源 CSV `kg_build /task_kg_output/task_kg_edges.csv` 亦为离线真值。

关键代码位置
- `tools.py:212-222`  DiseaseToGene：`ORDER BY weight DESC, gene ASC LIMIT $k`
- `tools.py:116`      `_relation_text()`；weight 由 `coalesce(r.weight, 0.0)` 产生
- `tools.py:262-271`  DiseaseToDrug：`MATCH (d:Disease)-[r:TREATS|CONTRAINDICATED_FOR|OFF_LABEL_FOR]-(drug:Drug)`
- `workflow.py:216-230` v2.2 占位符兜底（本次发现其 guard 失效）
- `evaluation/run_batch_eval_template.py:278,284-286` `--model` 覆盖 cfg["text_model"]
- `evaluation/run_batch_eval_template.py:259` `--max-rounds` default=6
- `evaluation/run_batch_eval_template.py:386-400` 每条输出 pred dict —— **不含 text_model / max_rounds / 任何 run config**
- `evaluation/import_kg_to_aura_http.py:30,34-35` 导入脚本白名单包含 Drug + TREATS/CONTRAINDICATED_FOR/OFF_LABEL_FOR（**未过滤掉药物边**）

---

=== Falsifier: are gold genes present in the KG as ASSOCIATED_WITH neighbours of the disease? ===
source gold file: evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl
expected_kg_edges were each verified against the live KG by evaluation/build_expected_kg_edges.py (docstring lines 9-11)

disease_focus                                gold KGverified  ceilR@5 kg_gene_count
-----------------------------------------------------------------------------------
hereditary breast ovarian cancer syndrome      20         20    0.250          1156
hereditary breast carcinoma                    20         20    0.250          1085
breast neoplasm                                20         19    0.250          1074
squamous cell carcinoma of the corpus uteri    20         20    0.250          1074
undifferentiated carcinoma of the corpus ute   20         20    0.250          1074
schizophrenia                                  20         20    0.250           890
colorectal cancer                              20         20    0.250           819
familial prostate carcinoma                    20         19    0.250           662
prostate cancer                                20         19    0.250           616
hepatocellular carcinoma                       20         13    0.250           614
liver cancer                                   20         20    0.250           612
lung cancer                                    20         20    0.250           556
adenocarcinoma of liver and intrahepatic bil   20         20    0.250           521
undifferentiated carcinoma of liver and intr   20         20    0.250           521
squamous cell carcinoma of liver and intrahe   20         20    0.250           521
-----------------------------------------------------------------------------------
TOTAL gold genes=300  KG-verified=290 (96.7%)
MEAN ceiling Recall@5 if ranker were perfect over full neighbour set = 0.250
PAPER reported Gene Recall@5 = 0.047
=== Drug-Disease edges in the imported KG export (LIVE read of the CSV actually imported) ===
source: /Users/yeawenqi/hkust/kg_build /task_kg_output/task_kg_edges.csv

Drug<->Disease edge rows (both directions stored) = 574  => 287 undirected edges
    282 rows (141 edges)  TREATS
    248 rows (124 edges)  CONTRAINDICATED_FOR
     44 rows (22 edges)  OFF_LABEL_FOR

weight values on Drug<->Disease rows: {'': 574}

Disease nodes in KG: 20; of these 18 have >=1 Drug edge

-- per-disease Drug edge counts (undirected) --
     3  adenocarcinoma of liver and intrahepatic biliary tract   {'TREATS': 3}
     2  breast cancer   {'TREATS': 2}
     9  breast carcinoma   {'TREATS': 7, 'OFF_LABEL_FOR': 2}
    11  breast neoplasm   {'TREATS': 9, 'OFF_LABEL_FOR': 2}
     7  colorectal cancer   {'TREATS': 5, 'OFF_LABEL_FOR': 1, 'CONTRAINDICATED_FOR': 1}
     0  colorectal carcinoma   <-- NO drug edges
     0  colorectal neoplasm   <-- NO drug edges
     4  familial prostate carcinoma   {'TREATS': 4}
    26  hepatocellular carcinoma   {'TREATS': 4, 'CONTRAINDICATED_FOR': 21, 'OFF_LABEL_FOR': 1}
     2  hereditary breast carcinoma   {'TREATS': 2}
    51  hereditary breast ovarian cancer syndrome   {'CONTRAINDICATED_FOR': 26, 'TREATS': 17, 'OFF_LABEL_FOR': 8}
    26  liver cancer   {'TREATS': 4, 'CONTRAINDICATED_FOR': 21, 'OFF_LABEL_FOR': 1}
    34  lung cancer   {'OFF_LABEL_FOR': 7, 'TREATS': 27}
    25  prostate cancer   {'CONTRAINDICATED_FOR': 19, 'TREATS': 6}
    25  prostate carcinoma   {'CONTRAINDICATED_FOR': 19, 'TREATS': 6}
    52  schizophrenia   {'TREATS': 35, 'CONTRAINDICATED_FOR': 17}
     3  squamous cell carcinoma of liver and intrahepatic biliary tract   {'TREATS': 3}
     2  squamous cell carcinoma of the corpus uteri   {'TREATS': 2}
     3  undifferentiated carcinoma of liver and intrahepatic biliary tract   {'TREATS': 3}
     2  undifferentiated carcinoma of the corpus uteri   {'TREATS': 2}
=== Why the Drug path is empty: out-of-KG disease scope, NOT missing Drug-Disease edges ===
file: evaluation/results/pcqa100_gdgpt_raw.jsonl (LIVE read, 99 records)
granularity: individual query objects inside each tool_call bundle, each paired with its own result block

DiseaseToDrug queries issued = 34
  returned 'No matches'      = 30
  returned drug rows         = 4

distinct disease strings asked = 15; of these in the KG's 20 Disease nodes = 1

disease asked                                 calls  nomatch  inKG  hasDrugEdgesInKG
  prostate cancer                                4        0  YES   YES
  renal cell carcinoma                           3        3  no    n/a
  gastric cancer                                 3        3  no    n/a
  ovarian carcinoma                              3        3  no    n/a
  cancers with egfr mutations                    3        3  no    n/a
  non-squamous non-small cell lung cancer        3        3  no    n/a
  esophageal squamous cell carcinoma             3        3  no    n/a
  fallopian tube carcinoma                       2        2  no    n/a
  cancers with ar mutation                       2        2  no    n/a
  cancers with tnks mutations                    2        2  no    n/a
  bladder urothelial carcinoma                   2        2  no    n/a
  cancers with cd3e mutations                    1        1  no    n/a
  cancers with gpnmb mutations                   1        1  no    n/a
  cancers with mgmt mutations                    1        1  no    n/a
  cancers with idh1 mutation                     1        1  no    n/a

queries that returned rows, by disease: {'prostate cancer': 4}

KG ground truth (from task_kg_edges.csv): 287 undirected Drug-Disease edges exist
  TREATS 141 / CONTRAINDICATED_FOR 124 / OFF_LABEL_FOR 22; 18 of 20 Disease nodes carry >=1
  e.g. lung cancer 34, schizophrenia 52, hereditary breast ovarian cancer syndrome 51
=== Length confound: answer word counts, GDgpt vs GPT-4o direct (LIVE read of raw files) ===
set                arm         N  median    mean   min    max
internal N=15      GDgpt      15      26      56     3    486
internal N=15      GPT-4o     15     375     375   287    424
                   ratio GPT-4o/GDgpt (median) = 14.42x

internal N=9 v2.3  GDgpt       9     217     211   147    243
internal N=9 v2.3  GPT-4o     15     375     375   287    424
                   ratio GPT-4o/GDgpt (median) = 1.73x

PcQA N=99/100      GDgpt      99      30      86     6    257
PcQA N=99/100      GPT-4o    100     147     163    51    362
                   ratio GPT-4o/GDgpt (median) = 4.90x

=== GDgpt final answers on the MAIN N=15 set are near-empty (LIVE read) ===
file: evaluation/results/adapt15_full_raw.jsonl

[  3w] ind_dc_894be162ddbb: Continuing discussion ```
[  3w] ind_dc_22d4a0eb6658: Continuing discussion   ```
[  3w] ind_dc_2000b5e3f24d: Continuing discussion ```
[  3w] ind_dc_d746db37c9cf: Continuing discussion ```
[  3w] ind_dc_c36faf6ef60d: Continuing discussion   ```
[  3w] ind_dc_dbb1afa7f685: Continuing discussion ```
[ 22w] ind_dc_9c33ed784d74: A2M facilitates tumor invasion and metastasis in colorectal cancer by enabling extracellular matrix remodeling through the "Degradation of the extracellular matrix" pathway.
[ 26w] ind_dc_6847df815fd5: Oncogenic signaling drives tumorigenesis (PI3K/AKT, RAF/MAP), inflammatory pathways remodel the tumor microenvironment, and DNA repair deficiencies (BRCA2) contribute to hereditary risk in familial pr
[ 36w] ind_dc_182a1e726ac1: Schizophrenia involves genetic variants (e.g., GRIN1, ABCA13, ABCB1) disrupting synaptic signaling (RAF/MAP kinase cascade, GPCR signaling), lipid transport (ABCA genes), and neuroimmune pathways (Neu
[ 36w] ind_dc_8df2021cf75b: Chromosomal instability (via chromatid cohesion and spindle checkpoint pathways), cytoskeletal remodeling (via RHO GTPases Activate Formins), and tumor-associated inflammation (via Neutrophil degranul
[ 48w] ind_dc_3bb0a1cdbe69: Hepatocellular carcinoma involves genes such as A2M, AADAT, ABCB1, and ABCB4, which are linked to pathways including Neutrophil degranulation, Resolution/Separation of Sister Chromatids, Interleukin-4
[ 52w] ind_dc_d130a7eb1f15: Adenocarcinoma of the liver and intrahepatic biliary tract involves key genes (A2M, ABCB1, CDK1, AURKB) and pathways (e.g., Resolution and Separation of Sister Chromatids, RHO GTPases Activate Formins
[ 53w] ind_dc_87845f398756: The mechanism for breast neoplasm involves hormone-driven cell proliferation and survival (e.g., Estrogen-dependent signaling via ESR1, BCL2), oncogenic signaling through PI3K/AKT and RAF/MAPK pathway
[ 68w] ind_dc_f30ad13c7079: Squamous cell carcinoma of the liver is driven by genomic instability from mitotic dysregulation (via CDK1, AURKB, BIRC5, PLK1, CENPE, KIF2C). Cytoskeletal remodeling (RHO GTPases Activate Formins pat
[486w] ind_dc_efd557a940d1: {   "Consistency": {     "Disease_Gene_Associations": [       {"gene": "ABCA3", "disease": "undifferentiated carcinoma of the corpus uteri", "sources": ["NCBI", "MONDO"]},       {"gene": "ABCA4", "dis

=== same question ids under the v2.3 prompt (v23_9q_raw.jsonl) ===
[243w] ind_dc_87845f398756: ** Breast neoplasm is associated with dysregulation of key pathways and genes, as confirmed by the knowledge graph. The **Estrogen-dependent gene expression pat
[227w] ind_dc_efd557a940d1: **   The knowledge graph confirms that **undifferentiated carcinoma of the corpus uteri** is ASSOCIATED_WITH the **ABCA** and **ABCB** gene families, including 
[185w] ind_dc_182a1e726ac1: Schizophrenia is ASSOCIATED_WITH multiple genes, including **A1BG**, **ABCA1**, **ABCA13**, and **ABCB1**, as confirmed by the knowledge graph. These genes are 
[147w] ind_dc_9c33ed784d74: Colorectal cancer is ASSOCIATED_WITH several genes, including **A2M**, **ABCA1**, **ABCA10**, and **ABCA12**, per the knowledge graph. Among these, **A2M** is I
[197w] ind_dc_6847df815fd5: Familial prostate carcinoma is ASSOCIATED_WITH several genes, including **AAAS**, **ABCC4**, **ABCG5**, and **ABO**, as confirmed by the knowledge graph. It is 
[216w] ind_dc_3bb0a1cdbe69: Hepatocellular carcinoma (HCC) is ASSOCIATED_WITH the genes **A2M**, **AADAT**, **ABCB1**, and **ABCB4**, as confirmed by the knowledge graph, although their sp
[235w] ind_dc_d130a7eb1f15: Adenocarcinoma of the liver and intrahepatic biliary tract is driven by multiple mechanisms supported by the knowledge graph. The gene **A2M** is ASSOCIATED_WIT
[229w] ind_dc_8df2021cf75b: The undifferentiated carcinoma of the liver and intrahepatic biliary tract is ASSOCIATED_WITH multiple genes, including **A2M**, **AADAT**, **ABCB1**, and **ABC
[217w] ind_dc_f30ad13c7079: Squamous cell carcinoma of the liver and intrahepatic biliary tract is ASSOCIATED_WITH the genes **A2M**, **AADAT**, **ABCB1**, and **ABCB4** per the knowledge 


=== 'Continuing discussion' empty-answer failures across all raw result files (LIVE) ===
file                                recs  empty<=5w  ContDisc
adapt15_full_raw.jsonl                15          6         6
adapt3_raw.jsonl                       3          2         2
adapt6_retry_raw.jsonl                 6          0         1
compare_full_5q_raw.jsonl              4          1         1
dev_full_limit1_raw.jsonl              1          1         0
dev_full_limit2_raw_v2.jsonl           2          2         0
dev_single_agent_raw.jsonl             3          2         2
dev_single_agent_raw_v2.jsonl          5          1         1
exp1_llm_only_raw.jsonl               30         22        20
kg_opt_exp1_llm_only_v2_raw.jsonl     38         31         0
pc1_full_raw.jsonl                     1          1         1
adapt15_full_ext.jsonl                15          6         6
adapt3_ext.jsonl                       3          2         2
=== workflow.py placeholder guard misses the fenced variant ===
guard: workflow.py:221-223  final_ans.strip().lower() in ('continuing discussion', ...)
       workflow.py:228      final_ans.strip().lower() == 'continuing discussion'

  id=ind_dc_894be162ddbb
    answer_text repr      = 'Continuing discussion\n```'
    .strip().lower()      = 'continuing discussion\n```'
    == 'continuing discussion' ? False   <-- guard fails, placeholder survives

so the v2.2 fallback (substitute the Lead's last_bullet) never fires for these records.
