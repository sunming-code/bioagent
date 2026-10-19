# 输入 VCF 后运行 PopGen

当前支持 GRCh38 单样本 VCF。参考频率覆盖 chr1–chr22；其它 contig 保留在患者 VCF 和频率表中，无法查询的 AF 留空，具体范围见 `af_coverage.json`。空值表示未知，不能解释为频率为零。

运行环境已安装在当前工作区：

- `.runtime/envs/popgen`
- `.runtime/envs/popgen_analysis`
- `.runtime/envs/popgen_gnn`

GNN 使用 CPU，可直接推理，无需 GPU。系统基础环境保持原样。环境查找优先使用 `.runtime/envs/`，也支持 `POPGEN_PREFIX`、`POPGEN_ANALYSIS_PREFIX`、`POPGEN_GNN_PREFIX` 覆盖路径。

## 命令行

在 `1_popgen` 目录运行：

```bash
python scripts/check_runtime.py
python orchestrator.py --vcf /绝对路径/你的样本.vcf.gz --outdir results/你的新任务 --threads 8
```

输入可以是 `.vcf` 或 `.vcf.gz`，不要求事先建立索引。程序检查单样本和 GT，转换 `1` 为 `chr1`，拆分多等位记录、排序、bgzip 压缩并建立 tabix 索引。不执行 GRCh37→GRCh38 liftover；输入必须已经采用 GRCh38，程序会拒绝已知错误的参考版本标记或染色体长度。

目前要求至少 10,000 条拆分后的记录、至少 200 个参考底库 SNP，以及至少 200 个有效 GNN 训练位点。少量候选变异列表不适用于此祖先分析。

每次指定新的输出目录；不指定 `--outdir` 时自动创建 `results/runs/<任务ID>`。已有任务目录会拒绝覆盖。

默认包含 PCA、监督 ADMIXTURE K=5、无监督 CV 和最佳 K 结果、频率查询、GNN、交付包。CV 对多个 K 做迭代，是主要耗时阶段；日志中的 `ADMIXTURE --cv K=…` 表示仍在计算。

步骤 2 默认并行运行独立的 ADMIXTURE CV K 值，并按染色体并行查询 1000G 频率；结果仍按原 K 顺序和输入变异顺序合并。默认 CV 并行度为 2、频率查询并行度为 4，可通过 `POPGEN_CV_WORKERS`、`POPGEN_AF_WORKERS` 调整。每个 CV 任务默认保留 `POPGEN_THREADS` 线程；节点资源有限时可设置 `POPGEN_CV_JOB_THREADS`，但 ADMIXTURE 的 CV 小数末位可能出现轻微浮点差异，最佳 K 和祖源判断不变。

如只需要祖先、频率、GNN 和证据包，可显式添加 `--skip-cv`，此时包内对应的无监督文件引用为 null，不会引用历史结果。

## 网页

```bash
bash scripts/run_ui.sh
```

默认地址 `http://127.0.0.1:8008`。需要从其它机器访问时：

```bash
HOST=0.0.0.0 PORT=8008 bash scripts/run_ui.sh
```

上传 VCF 后会创建独立任务。页面轮询排队、运行、成功或失败状态，运行日志可见；成功后展示和下载同一任务的结果。历史任务保存在 `results/jobs/<任务ID>/`，结果位于其 `output/`。服务使用单 worker，每次运行一个分析，后续任务排队。重启时尚未完成的任务会标记失败，需重新提交，不会假装完成。

API：

- `POST /api/upload-vcf`：multipart 字段 `file`；返回 HTTP 202 和 `job_id`。
- `GET /api/jobs/{job_id}`：状态和日志末尾。
- `GET /api/dashboard?job_id=...`：已完成任务结果。
- `GET /api/download-zip?job_id=...`：完整交付 ZIP。

## 输出与交付

`delivery/evidence_pack.json` 引用患者 VCF、VCF 索引、频率表、PCA、ADMIXTURE、GNN 和输入元数据。文件引用与 JSON schema 均会校验；下载的 ZIP 保留相同目录结构，可解压后直接读取相对路径。

- `patient.vcf.gz`、`patient.vcf.gz.tbi`
- `input_metadata.json`
- `ancestry_pca.tsv`
- `admixture_results_K5.tsv`
- `admixture_cv.tsv`、`admixture_unsupervised_K<实际K>.tsv`（启用 CV 时）
- `allele_freq.tsv`、`af_coverage.json`
- `partial_evidence.json`、`gnn_decision.json`
- `delivery/evidence_pack.json`、`delivery/INTERFACE.md`、`delivery/allele_freq.tsv`

样本 ID 来自 VCF，不再默认填写 HG002。患者 VCF 不会在此步骤做 snpEff、VQSR 或 ACMG 致病性分级；ACMG 分级由下游 e-Gene 完成。

## 安装与复核

重建三套隔离环境：`bash scripts/setup_runtime.sh`，默认安装到项目 `.runtime/envs/`，无需共享目录写权限；脚本会同时安装 FASTQ 预处理所需的 `popgen` 环境。原始 GRCh38 FASTA、FASTQ 和 GIAB truth 不属于从 VCF 开始运行的必要依赖。

真实参考样本执行验证：

```bash
python scripts/validate_pipeline.py --outdir results/新的验证目录
```

从参考库导出 NA18526 的 10,000 个均匀分布 SNP，运行时从分析底库和 GNN 参考图移除此样本。此检查验证执行链、剂量一致性和已知样本结果；模型原本见过参考样本，不构成独立临床性能验证。
