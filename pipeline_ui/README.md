# BioAgent Research Studio · 研究工作台

**启动 / Start**：在 BioAgent 仓库根目录运行 `./start.command`，在浏览器打开 `http://127.0.0.1:8765`。macOS 也可双击 `start.command`。需要 Python 3.11+；首次启动会在项目 `.venv` 安装网页与 manifest 校验依赖。`PORT=8766 ./start.command` 可更换端口。中文 / EN 可以在任意页面切换；保留当前模块、查询、未提交输入及任务，记住界面语言。原始报告、日志、数据库字段和来源名称保留原文。

The UI and queries run locally. Start in the repository root; use the language switch in the header. The interface distinguishes reference data, synthetic examples and sample-derived evidence. Do not expose the service through a public tunnel or reverse proxy: it reads local file paths and can launch scientific processes. No external analytics, hosted fonts, or model calls are used for reference queries.

## 三个独立查询入口 / Module queries

| 模块 | 不需要样本任务 | 需要已有任务 |
|---|---|---|
| PopGen | `CHB`、`EUR`、`HG00096` 查 1000G 面板标签；`chr1:10397:C:A` 精确匹配 GRCh38 REF/ALT，可切换五个大群对照 AF | 查看 PopGen 交付的 `allele_freq.tsv` |
| e-Gene | `心肌病`、`Ataxia`、`HP:0001250` 查词典；`BRCA1` 或 `OMIM:212050` 查锁定的 HPO 基因－疾病关联 | 查真实 `acmg_results.tsv` 和 `disease_candidates.tsv`；空表和文件未生成分别显示 |
| GDgpt | `BRCA1` 或 `Gene:2153` 查项目任务图谱节点；点击进入有方向、关系、来源的边表。无需 Neo4j 或模型密钥 | 打开 `report.html`、`report_plain.html`、`report_graph.html`，也可查看单独标记的合成样例 |

人群标签取自 `data_sources/popgen_panel/sample_superpop.tsv`；知识图谱来自 `3_GDgpt/kg_build/task_kg_output`。17 个 HPO 条目是项目别名表的覆盖范围，并非整个本体。基因－疾病表的安装命令为 `.venv/bin/python -m pipeline_ui.install_reference`；通过 `2_egene/config/disease_sources.lock.json` 的大小和 SHA-256 双校验。该数据在本机 `2_egene/data/disease/`，不随源代码分发。请遵循锁文件中的来源与许可。

`pipeline_ui/references/igsr_frequency.tsv` 是 [IGSR 20220422 高覆盖发布](https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/) 的 358 个 chr1 等位基因摘录，只含位点及人群汇总，不含个体基因型。来源 URL、读取区间和哈希在同目录 `igsr_frequency.source.json`。可对该 URL 获取记录的 byte range，再运行 `python -m pipeline_ui.extract_reference <prefix.bgz>` 重建。完整面板查询需要原始 chr1–22 索引 VCF 和 `tabix`；默认查找原仓库目录，也支持 `POPGEN_1000G_VCF_DIR`。离线摘录未覆盖、完整面板无匹配、字段缺失和真实 AF=0 是不同状态。

## 分析与交付 / Analysis and delivery

**公网静态演示**：在仓库根目录运行 `python3 -m pipeline_ui.build_public_demo BioAgent-Public-Demo.zip`。在 Cloudflare Pages 的 Direct Upload 界面拖入 ZIP；其根目录包含 `index.html`，无需构建命令或服务端。仅导出参考面板的亚群汇总、公开频率摘录、HPO 别名、项目图谱中的部分 NCBI 关系和已核对的合成报告。网页支持离线查询、参考计算、中英界面与报告浏览，不包含样本任务入口，也不会上传输入。不要把工作目录、`runs/` 或本机启动包当作静态站上传。

报告的纸白、陶土和灰梅配色由 `egene_pipeline/report_theme.css` 定义，生成时内嵌，解压后可离线查看。GDgpt 专业版先展示摘要，再给出任务指标、逐基因证据和分析边界；易读版和交互图谱可通过相对链接切换。历史 ZIP、导入的上游报告以及带原始色标的科研图保留原件。

- **参考分析**：真实统计人群构成、批量归一化中英文 HPO 术语、计算一阶图谱邻居和关系计数。在 `runs/reference-notebooks.sqlite` 持久化，可在任务记录重开或导出含输入、来源和代码基线的 JSON。邻域统计不是因果推断。
- **样本流水线**：从 PopGen（VCF/FASTQ）、e-Gene（`evidence_pack.json`）、GDgpt（`report_manifest.json`）或 AtheroMap（`gdgpt_manifest.json`）开始。网页默认以 AtheroMap 为终点，GDgpt 完成后自动继续。网页调用仓库的 `run_pipeline.py`，通过 SSE 更新阶段状态，支持停止任务、查看原始日志及产物。终点选 GDgpt/AtheroMap 时同时打包，较早终点提供阶段交付。运行目录为 `runs/ui_*/output`。
- **可立即运行的端到端样例**：「分析 → 样本流水线 → 运行内置无候选样例」。使用合成 e-Gene manifest，实际执行适配、GDgpt 空候选分支、HTML 与 ZIP 打包，不运行基因组比对或调用模型。`pipeline_ui/examples/no_candidates` 与 GDgpt 报告预览均来自上游测试结构；不是患者数据。
- **真实样本环境**：网页环境不会安装参考基因组、ANNOVAR/InterVar、模块计算环境、Neo4j 或模型凭据。按仓库根 `README.md` 和 `DATASETS.md` 在分析机完成配置。涉及真实样本或模型供应商时，请先核对访问权限、数据用途和费用。

从 PopGen 开始时可设置匹配祖源的 ALT 频率上限（百分比，默认 1）、最低 DP、最低 GQ 及有质量下限时的缺失值策略。任务会将符合条件的携带等位基因写入 `01_popgen/delivery/review_shortlist.tsv.gz`，并在 `evidence_pack.json` 的 `review_policy` 中记录阈值和条数。频率未知的记录保留在全量表中。e-Gene 按自己的输入和判级策略读取完整证据。无监督 ADMIXTURE 的最大 K 可设为 2–10，实际搜索范围及误差记录在 `admixture_cv.tsv`。

任务失败后，任务页和历史详情提供「打开运行错误报告」。运行目录下的 `error_report.html` 列出停止阶段、可取得的子步骤、原因、已完成阶段，并链接已有的阶段日志。启动前被拒绝的表单直接在页面提示原因。

## 复现 / Verification

上游基线：`sunming-code/bioagent` 的 `2844be81dfe297f24287902b1433c095a5499043`。浏览器入口：`pipeline_ui/static/studio.html`。查询实现：`pipeline_ui/catalog.py`。参考分析 API：`pipeline_ui/studio.py`。原有流水线 API 仍保留在 `pipeline_ui/app.py`。

运行回归：`.venv/bin/python -m pip install httpx`，然后 `TMPDIR=/private/tmp .venv/bin/python -m unittest discover -s tests`（Linux 可用 `/tmp`）。测试包含独立查询、真实零与未覆盖的区分、持久化、限制本地请求、合成流水线和三份报告。
